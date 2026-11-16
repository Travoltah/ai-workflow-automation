"""The KYC checks, in code. Pure functions: no database, no AI, easy to test.

Input: the application form, each document's intake result and the AI extraction.
Output: a list of checks (pass / fail / warn), the application status and what the customer must do.
Nothing is ever approved here: the best outcome is "ready_for_review" for a person.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

from mrz import parse_td3

ID_TYPES = {"passport", "national_id", "drivers_licence"}
POA_TYPES = {"utility_bill", "bank_statement"}
CUSTOMER_FIX = {
    "needs_password": "The file is password-protected: send the password through the secure link, or upload an unprotected copy.",
    "poor_quality": "The photo or scan can't be read reliably: retake it flat, in focus and in good light.",
    "unsupported_type": "The file type isn't accepted: upload a PDF, JPG, PNG, HEIC or DOCX.",
    "corrupt": "The file is damaged: upload it again.",
    "rejected_macro": "Macro-enabled Word files aren't accepted: upload a PDF or a .docx without macros.",
    "password_locked": "Too many wrong passwords: upload an unprotected copy.",
}


def norm_name(s: str | None) -> list[str]:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper()
    s = re.sub(r"\b(MR|MRS|MS|MISS|DR)\b\.?", " ", s)
    return [t for t in re.sub(r"[^A-Z ]", " ", s).split() if t]


def names_match(a: str | None, b: str | None) -> bool:
    """Same surname (last token) and same first given name; middle names may be missing on one side."""
    x, y = norm_name(a), norm_name(b)
    if not x or not y:
        return False
    return x[-1] == y[-1] and x[0] == y[0]


def addr_tokens(s: str | None) -> set[str]:
    return {t for t in re.sub(r"[^A-Z0-9 ]", " ", str(s or "").upper()).split() if len(t) > 1}


def addresses_match(a: str | None, b: str | None) -> bool:
    x, y = addr_tokens(a), addr_tokens(b)
    return bool(x and y) and len(x & y) / min(len(x), len(y)) >= 0.6


def to_date(s) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def val(extraction: dict, field: str):
    f = (extraction.get("fields") or {}).get(field) or {}
    return f.get("value")


def check(code, result, severity, detail, document_id=None, action="reviewer"):
    return {"code": code, "result": result, "severity": severity, "detail": detail, "document_id": document_id,
            "action": action if result in ("fail", "warn") else "none"}


def validate(application: dict, documents: list[dict], config: dict, today: dt.date | None = None) -> dict:
    """documents: [{document_id, filename, declared_type, status, status_reason, pdf_meta, extraction (or None)}]"""
    today = today or dt.date.today()
    form = application.get("applicant") or {}
    checks = []

    # 1. files that never reached the AI: the customer has to act
    for d in documents:
        if d["status"] in CUSTOMER_FIX:
            checks.append(check("FILE_" + d["status"].upper(), "fail", "high", f"{d['filename']}: {d.get('status_reason') or CUSTOMER_FIX[d['status']]}",
                                d["document_id"], action="customer"))

    read = [d for d in documents if d.get("extraction")]
    ids = [d for d in read if d["extraction"].get("doc_type") in ID_TYPES]
    poas = [d for d in read if d["extraction"].get("doc_type") in POA_TYPES]

    # 2. the right documents
    for d in read:
        e = d["extraction"]
        kind = "identity document" if d.get("declared_type") == "identity" else "proof of address" if d.get("declared_type") == "proof_of_address" else None
        ok_types = ID_TYPES if d.get("declared_type") == "identity" else POA_TYPES if d.get("declared_type") == "proof_of_address" else None
        if ok_types and e.get("doc_type") not in ok_types:
            checks.append(check("WRONG_DOCUMENT", "fail", "high",
                                f"{d['filename']} was uploaded as a {kind} but reads as: {e.get('doc_type')} ({e.get('notes') or 'no notes'}).",
                                d["document_id"], action="customer"))
        if e.get("readability") in ("partial", "unreadable"):
            checks.append(check("READABILITY", "warn", "medium", f"{d['filename']}: the model reports the document as {e.get('readability')}.", d["document_id"]))
        low = [k for k, f in (e.get("fields") or {}).items() if f and f.get("value") and f.get("confidence") == "low"]
        if low:
            checks.append(check("LOW_CONFIDENCE_FIELDS", "warn", "medium", f"{d['filename']}: low-confidence fields: {', '.join(sorted(low))}.", d["document_id"]))
        for issue in (e.get("verification") or {}).get("unverified", []):
            checks.append(check("FIELD_NOT_IN_TEXT", "warn", "medium", f"{d['filename']}: {issue}", d["document_id"]))
    pending = [d for d in documents if d["status"] in ("ok", "received") and not d.get("extraction")]
    if not any(d["status"] in CUSTOMER_FIX for d in documents) and not pending:
        if not ids:
            checks.append(check("MISSING_IDENTITY", "fail", "high", "No identity document (passport, national ID or driver's licence) was found.", action="customer"))
        if not poas:
            checks.append(check("MISSING_PROOF_OF_ADDRESS", "fail", "high", "No proof of address (utility bill or bank statement) was found.", action="customer"))

    # 3. identity document checks
    for d in ids:
        e, doc_id, name = d["extraction"], d["document_id"], d["filename"]
        expiry = to_date(val(e, "expiry_date"))
        if expiry is None:
            checks.append(check("ID_EXPIRY_UNKNOWN", "warn", "medium", f"{name}: no expiry date could be read.", doc_id))
        elif expiry < today:
            checks.append(check("ID_EXPIRED", "fail", "high", f"{name}: expired on {expiry.isoformat()}.", doc_id, action="customer"))
        else:
            checks.append(check("ID_EXPIRED", "pass", "high", f"{name}: valid until {expiry.isoformat()}.", doc_id))
        dob = to_date(val(e, "date_of_birth"))
        if dob:
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            ok = age >= int(config.get("min_age", 18))
            checks.append(check("MINIMUM_AGE", "pass" if ok else "fail", "high", f"{name}: applicant is {age}.", doc_id))
        pattern = (config.get("id_formats") or {}).get(f"{(val(e, 'issuing_country') or '').upper()}:{e.get('doc_type')}")
        number = val(e, "document_number")
        if pattern and number:
            ok = re.fullmatch(pattern, str(number)) is not None
            checks.append(check("ID_NUMBER_FORMAT", "pass" if ok else "fail", "high",
                                f"{name}: number {number} {'matches' if ok else 'does not match'} the {val(e, 'issuing_country')} {e.get('doc_type')} format.", doc_id))
        if e.get("doc_type") == "passport":
            l1, l2 = val(e, "mrz_line1"), val(e, "mrz_line2")
            if not (l1 and l2):
                checks.append(check("MRZ_PRESENT", "warn", "medium", f"{name}: the machine-readable zone could not be read.", doc_id))
            else:
                m = parse_td3(l1, l2)
                checks.append(check("MRZ_CHECK_DIGITS", "pass" if m["valid"] else "fail", "high",
                                    f"{name}: " + ("all check digits are correct." if m["valid"] else "; ".join(m["problems"]) +
                                                   ". Possible misread or edited document."), doc_id))
                if m["fields"]:
                    diffs = []
                    for field in ("document_number", "date_of_birth", "expiry_date"):
                        printed = val(e, field)
                        if printed and m["fields"].get(field) and str(printed).replace(" ", "").upper() != str(m["fields"][field]).upper():
                            diffs.append(f"{field}: printed {printed}, MRZ {m['fields'][field]}")
                    if m["fields"].get("surname") and not names_match(val(e, "full_name"), f"{m['fields']['given_names']} {m['fields']['surname']}"):
                        diffs.append(f"name: printed {val(e, 'full_name')}, MRZ {m['fields']['given_names']} {m['fields']['surname']}")
                    checks.append(check("MRZ_MATCHES_PAGE", "fail" if diffs else "pass", "high",
                                        f"{name}: " + ("; ".join(diffs) if diffs else "the printed details match the MRZ."), doc_id))

    # 4. proof of address checks
    max_age = int(config.get("proof_of_address_max_age_days", 90))
    for d in poas:
        e, doc_id, name = d["extraction"], d["document_id"], d["filename"]
        issued = to_date(val(e, "document_date"))
        if issued is None:
            checks.append(check("POA_DATE_UNKNOWN", "warn", "medium", f"{name}: no statement or bill date could be read.", doc_id))
        else:
            days = (today - issued).days
            ok = 0 <= days <= max_age
            checks.append(check("POA_RECENT", "pass" if ok else "fail", "high",
                                f"{name}: dated {issued.isoformat()} ({days} days old; limit {max_age}).", doc_id, action="customer"))

    # 5. consistency across documents and the application form
    if form.get("full_name"):
        for d in ids + poas:
            n = val(d["extraction"], "full_name")
            if n:
                ok = names_match(form["full_name"], n)
                checks.append(check("NAME_MATCHES_APPLICATION", "pass" if ok else "fail", "high",
                                    f"{d['filename']}: {n!r} vs application {form['full_name']!r}.", d["document_id"]))
    if form.get("date_of_birth"):
        for d in ids:
            dob = val(d["extraction"], "date_of_birth")
            if dob:
                ok = to_date(dob) == to_date(form["date_of_birth"])
                checks.append(check("DOB_MATCHES_APPLICATION", "pass" if ok else "fail", "high",
                                    f"{d['filename']}: {dob} vs application {form['date_of_birth']}.", d["document_id"]))
    if form.get("address"):
        for d in poas:
            addr = val(d["extraction"], "address")
            if addr:
                ok = addresses_match(form["address"], addr)
                checks.append(check("ADDRESS_MATCHES_APPLICATION", "pass" if ok else "warn", "medium",
                                    f"{d['filename']}: {addr!r} vs application {form['address']!r}.", d["document_id"]))

    # 6. tamper signals: flagged for the reviewer, never decided here
    suspicious = [s.lower() for s in config.get("suspicious_producers", [])]
    for d in documents:
        meta = d.get("pdf_meta") or {}
        tool = f"{meta.get('producer') or ''} {meta.get('creator') or ''}".lower()
        hits = [s for s in suspicious if s in tool]
        created, modified = (meta.get("creationDate") or "")[2:10], (meta.get("modDate") or "")[2:10]
        later = created.isdigit() and modified.isdigit() and modified > created
        if hits or later:
            reasons = ([f"made or saved with {', '.join(hits)}"] if hits else []) + ([f"modified ({modified}) after it was created ({created})"] if later else [])
            checks.append(check("PDF_EDIT_SIGNALS", "warn", "high", f"{d['filename']}: {'; '.join(reasons)}. Compare with an original from the issuer.", d["document_id"]))

    customer = [c for c in checks if c["result"] == "fail" and c["action"] == "customer"]
    status = "processing" if pending else "action_required" if customer else "ready_for_review"
    return {
        "status": status,
        "checks": checks,
        "summary": {"fail": sum(c["result"] == "fail" for c in checks), "warn": sum(c["result"] == "warn" for c in checks),
                    "pass": sum(c["result"] == "pass" for c in checks)},
        "customer_actions": sorted({c["detail"] for c in customer}),
    }
