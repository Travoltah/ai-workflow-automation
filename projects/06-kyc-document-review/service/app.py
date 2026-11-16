"""KYC intake service: file handling and checks, in code. Called by n8n; the unlock form is called by the reviewer's browser.

    POST /intake                  {application_id, filename, declared_type, data_b64} -> document id and status
    GET  /documents/{id}/ai-input page images (JPEG, base64) and digital text, for the extraction call
    POST /validate/{app_id}       runs every check, stores them, sets the application status
    POST /unlock                  {document_id, password, actor} (form or JSON): opens a protected file ONCE, in memory.
                                  The password is never stored, logged or returned. Then asks n8n to process the document.
    GET  /health
"""
from __future__ import annotations

import asyncio
import base64
import html
import json
import os
import urllib.request

import psycopg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from intake import inspect
from validation import validate

app = FastAPI(title="KYC intake service")
DATABASE_URL = os.environ["DATABASE_URL"]
N8N_PROCESS_URL = os.environ.get("N8N_PROCESS_URL", "")      # e.g. http://n8n:5678/webhook/kyc/process
REVIEW_URL = os.environ.get("REVIEW_URL", "")


def db():
    return psycopg.connect(DATABASE_URL)


def audit(cur, app_id, doc_id, event, actor, detail=None):
    cur.execute("INSERT INTO kyc.audit_log (application_id, document_id, event, actor, detail) VALUES (%s, %s, %s, %s, %s)",
                (app_id, doc_id, event, actor, Jsonb(detail or {})))


def store_pages(cur, doc_id, result):
    cur.execute("DELETE FROM kyc.pages WHERE document_id = %s", (doc_id,))
    for i, p in enumerate(result.get("pages") or [], 1):
        cur.execute("INSERT INTO kyc.pages (document_id, page_no, ai_jpeg, thumb_jpeg, quality) VALUES (%s, %s, %s, %s, %s)",
                    (doc_id, i, p["ai_jpeg"], p["thumb_jpeg"], Jsonb(p["quality"])))


class IntakeRequest(BaseModel):
    application_id: int
    filename: str
    declared_type: str = "other"
    data_b64: str


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/intake")
def intake(req: IntakeRequest):
    try:
        data = base64.b64decode(req.data_b64, validate=True)
    except Exception:
        raise HTTPException(400, "data_b64 is not valid base64")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "File larger than 15 MB")
    r = inspect(data, req.filename)
    with db() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO kyc.documents (application_id, filename, declared_type, mime, size_bytes, sha256, file, status, status_reason,
                         encryption, extension_mismatch, scanned, digital_text, pdf_meta, page_count)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING document_id""",
                    (req.application_id, req.filename, req.declared_type if req.declared_type in ("identity", "proof_of_address") else "other",
                     r.get("mime"), r["size_bytes"], r["sha256"], data, r["status"], r.get("reason"), r.get("encryption"),
                     r.get("extension_mismatch", False), r.get("scanned"), r.get("text"), Jsonb(r.get("pdf_meta") or {}), r.get("page_count")))
        doc_id = cur.fetchone()[0]
        store_pages(cur, doc_id, r)
        audit(cur, req.application_id, doc_id, "document_received", "api",
              {"filename": req.filename, "status": r["status"], "mime": r.get("mime"), "encryption": r.get("encryption"),
               "extension_mismatch": r.get("extension_mismatch")})
    return {"document_id": doc_id, "filename": req.filename, "status": r["status"], "reason": r.get("reason"), "mime": r.get("mime"),
            "encryption": r.get("encryption"), "pages": len(r.get("pages") or []), "scanned": r.get("scanned"),
            "quality": [p["quality"] for p in r.get("pages") or []]}


@app.get("/documents/{doc_id}/ai-input")
def ai_input(doc_id: int):
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT filename, declared_type, status, digital_text FROM kyc.documents WHERE document_id = %s", (doc_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "No such document")
        if row[2] != "ok":
            raise HTTPException(409, f"Document is {row[2]}")
        cur.execute("SELECT page_no, ai_jpeg FROM kyc.pages WHERE document_id = %s ORDER BY page_no", (doc_id,))
        pages = [{"page_no": n, "media_type": "image/jpeg", "data": base64.b64encode(b).decode()} for n, b in cur.fetchall()]
    return {"document_id": doc_id, "filename": row[0], "declared_type": row[1], "text": (row[3] or "")[:8000], "pages": pages}


@app.post("/validate/{app_id}")
def run_checks(app_id: int):
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT applicant FROM kyc.applications WHERE application_id = %s", (app_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "No such application")
        cur.execute("SELECT key, value FROM kyc.settings")
        config = dict(cur.fetchall())
        cur.execute("""SELECT d.document_id, d.filename, d.declared_type, d.status, d.status_reason, d.pdf_meta,
                              CASE WHEN e.document_id IS NULL THEN NULL ELSE jsonb_build_object('doc_type', e.doc_type, 'readability', e.readability,
                                   'fields', e.fields, 'notes', e.notes, 'verification', e.verification) END
                         FROM kyc.documents d LEFT JOIN kyc.extractions e USING (document_id)
                        WHERE d.application_id = %s ORDER BY d.document_id""", (app_id,))
        docs = [dict(zip(("document_id", "filename", "declared_type", "status", "status_reason", "pdf_meta", "extraction"), r)) for r in cur.fetchall()]
        result = validate({"applicant": row[0]}, docs, config)
        cur.execute("DELETE FROM kyc.checks WHERE application_id = %s", (app_id,))
        for c in result["checks"]:
            cur.execute("""INSERT INTO kyc.checks (application_id, document_id, code, result, severity, detail, action)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""", (app_id, c["document_id"], c["code"], c["result"], c["severity"], c["detail"], c["action"]))
        cur.execute("""UPDATE kyc.applications SET status = %s, check_summary = %s, customer_actions = %s, updated_at = now()
                       WHERE application_id = %s AND decision IS NULL""",
                    (result["status"], Jsonb(result["summary"]), Jsonb(result["customer_actions"]), app_id))
        audit(cur, app_id, None, "checks_run", "system", {"status": result["status"], **result["summary"]})
    result["documents"] = [{k: d[k] for k in ("document_id", "filename", "status")} | {"doc_type": (d["extraction"] or {}).get("doc_type")} for d in docs]
    result["application_id"] = app_id
    return result


@app.post("/unlock")
async def unlock(request: Request):
    """Opens a password-protected document with a password supplied by a person. The password is used once, in memory."""
    is_form = "form" in request.headers.get("content-type", "")
    body = dict(await request.form()) if is_form else await request.json()
    doc_id = int(body.get("document_id") or 0)
    actor = str(body.get("actor") or "").strip()[:100] or "unknown"
    password = str(body.get("password") or "")
    body = None                                   # nothing below may echo the request
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT application_id, filename, status, password_attempts, file FROM kyc.documents WHERE document_id = %s FOR UPDATE", (doc_id,))
        row = cur.fetchone()
        if not row:
            return respond(is_form, {"ok": False, "error": "No such document"}, 404)
        app_id, filename, status, attempts, file = row
        cur.execute("SELECT value FROM kyc.settings WHERE key = 'max_password_attempts'")
        limit = int((cur.fetchone() or [3])[0])
        if status != "needs_password":
            return respond(is_form, {"ok": False, "error": f"{filename} is {status}, not waiting for a password"}, 409)
        if not password:
            return respond(is_form, {"ok": False, "error": "Enter the password"}, 400)
        r = inspect(bytes(file), filename, password=password)
        password = None                           # used once; dropped before anything is stored
        if r.get("wrong_password"):
            attempts += 1
            locked = attempts >= limit
            cur.execute("UPDATE kyc.documents SET password_attempts = %s, status = %s, status_reason = %s WHERE document_id = %s",
                        (attempts, "password_locked" if locked else "needs_password",
                         "Too many wrong passwords: ask for an unprotected copy." if locked else r.get("reason"), doc_id))
            audit(cur, app_id, doc_id, "password_attempt_failed", actor, {"attempts": attempts, "locked": locked})
            result = {"ok": False, "error": "That password didn't open the file." + (" The file is now locked: ask for an unprotected copy." if locked else ""),
                      "attempts": attempts, "locked": locked}
            processed = None
        else:
            cur.execute("""UPDATE kyc.documents SET status = %s, status_reason = %s, encryption = 'password', password_attempts = %s,
                             scanned = %s, digital_text = %s, pdf_meta = %s, page_count = %s WHERE document_id = %s""",
                        (r["status"], r.get("reason"), attempts + 1, r.get("scanned"), r.get("text"), Jsonb(r.get("pdf_meta") or {}), r.get("page_count"), doc_id))
            store_pages(cur, doc_id, r)
            audit(cur, app_id, doc_id, "password_supplied", actor, {"result_status": r["status"]})   # never the password itself
            result = {"ok": True, "document_id": doc_id, "status": r["status"], "reason": r.get("reason")}
            processed = app_id
    if processed and N8N_PROCESS_URL:
        # In a worker thread: n8n's processing calls this service back (page images, checks). A blocking call
        # here froze the event loop and deadlocked the two (found in the first evaluation).
        try:
            result["processing"] = await asyncio.to_thread(start_processing, processed)
        except Exception as e:
            result["processing_error"] = f"{type(e).__name__}: could not start processing"
    return respond(is_form, result, 200 if result["ok"] else 400)


def start_processing(app_id: int) -> dict:
    req = urllib.request.Request(N8N_PROCESS_URL, data=json.dumps({"application_id": app_id}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def respond(is_form: bool, result: dict, code: int):
    if not is_form:
        return JSONResponse(result, status_code=code)
    status = result.get("processing", {}).get("status") if result.get("ok") else None
    msg = (f"<h2>File opened</h2><p>The document was unlocked and processed. Application status: <b>{html.escape(str(status or 'processing'))}</b>.</p>"
           if result.get("ok") else f"<h2>Not opened</h2><p>{html.escape(result.get('error', 'Error'))}</p>")
    back = f'<p><a href="{html.escape(REVIEW_URL)}">Back to the review page</a></p>' if REVIEW_URL else ""
    return HTMLResponse(f"<!doctype html><meta charset='utf-8'><title>Unlock</title><body style='font-family:system-ui;max-width:620px;margin:40px auto'>{msg}{back}</body>", status_code=code)
