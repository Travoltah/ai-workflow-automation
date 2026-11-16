"""Intake: decides what a file really is and whether it can be read, before any AI sees it. No AI here.

  type        from the file's bytes (magic numbers), not its name; a .pdf that isn't a PDF is caught
  protection  PDF: restricted (opens, but printing/copying blocked) vs needs a password to open;
              Word/Excel: encrypted Office container. A supplied password is used once, in memory.
  macros      Word files with VBA macros are rejected
  pages       images are turned upright (EXIF), PDFs are rendered page by page; digital text kept
  quality     per page: blur (variance of the Laplacian), darkness, glare, resolution
  metadata    PDF producer, creator and dates, for tamper signals
"""
from __future__ import annotations

import hashlib
import io
import zipfile

import cv2
import filetype
import pymupdf as fitz  # PyMuPDF
import msoffcrypto
import numpy as np
from docx import Document
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()

MAX_PAGES = 4
AI_EDGE = 1568          # longest edge sent to the model
THUMB_EDGE = 900        # longest edge shown to the reviewer
THRESHOLDS = {"blur": 100.0, "dark": 50.0, "glare": 0.25, "min_side": 600}
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/heic", "image/heif"}


class IntakeResult(dict):
    """status: ok | needs_password | poor_quality | unsupported_type | corrupt | rejected_macro"""


def quality(img: Image.Image, glare: bool = True) -> dict:
    """Blur and glare are measured only where the page has content (text, photo, edges), not on blank paper.

    The first version averaged over the whole image, so a sharp scan of a mostly white statement, or a receipt
    on white paper, was rejected: white paper counted as "glare". Now the image is cut into 50 px tiles; tiles
    with almost no contrast (blank paper) are ignored; blur is the 90th percentile of the Laplacian variance of
    the content tiles, and glare is the share of blown-out pixels inside content tiles.
    """
    g = np.array(ImageOps.grayscale(img).resize((1000, max(1, int(1000 * img.height / img.width)))))
    lap = cv2.Laplacian(g, cv2.CV_64F)
    t = 50
    tiles = [(y, x) for y in range(0, g.shape[0] - t + 1, t) for x in range(0, g.shape[1] - t + 1, t) if g[y:y + t, x:x + t].std() > 12]
    sharp = [lap[y:y + t, x:x + t].var() for y, x in tiles]
    blown = [(g[y:y + t, x:x + t] >= 253).mean() for y, x in tiles]
    q = {
        "blur_score": round(float(np.percentile(sharp, 90)), 1) if sharp else 0.0,
        "brightness": round(float(g.mean()), 1),
        "glare_fraction": (round(float(np.mean(blown)), 3) if blown else 0.0) if glare else None,   # scans: not assessed
        "content_tiles": len(tiles),
        "width": img.width, "height": img.height,
    }
    problems = []
    if q["blur_score"] < THRESHOLDS["blur"]:
        problems.append("blurred")
    if q["brightness"] < THRESHOLDS["dark"]:
        problems.append("too dark")
    if glare and q["glare_fraction"] > THRESHOLDS["glare"]:
        problems.append("glare")
    if min(img.width, img.height) < THRESHOLDS["min_side"]:
        problems.append("resolution too low")
    q["problems"] = problems
    return q


def jpeg(img: Image.Image, edge: int, q: int) -> bytes:
    im = img.convert("RGB")
    im.thumbnail((edge, edge), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    return buf.getvalue()


def page_record(img: Image.Image, check_quality: bool, glare: bool = True) -> dict:
    return {"ai_jpeg": jpeg(img, AI_EDGE, 85), "thumb_jpeg": jpeg(img, THUMB_EDGE, 70),
            "quality": quality(img, glare) if check_quality else {"problems": [], "note": "digital page: quality not scored"}}


def pdf_meta(doc: fitz.Document) -> dict:
    m = doc.metadata or {}
    return {k: m.get(k) for k in ("producer", "creator", "creationDate", "modDate", "title")}


def read_pdf(data: bytes, password: str | None) -> IntakeResult:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        return IntakeResult(status="corrupt", reason=f"The PDF could not be opened: {e}")
    encryption = "none"
    if doc.needs_pass:
        encryption = "password"
        if not password:
            return IntakeResult(status="needs_password", encryption="password",
                                reason="The PDF is password-protected. Ask the customer for the password or an unprotected copy.")
        if not doc.authenticate(password):
            return IntakeResult(status="needs_password", encryption="password", wrong_password=True,
                                reason="The password supplied did not open the PDF.")
    elif doc.is_encrypted or (doc.metadata or {}).get("encryption"):
        encryption = "restricted"               # opens without a password; printing or copying may be blocked
    pages, text_parts = [], []
    for i, page in enumerate(doc):
        if i >= MAX_PAGES:
            break
        text = page.get_text().strip()
        text_parts.append(text)
        zoom = min(AI_EDGE / max(page.rect.width, page.rect.height), 4)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        scanned = len(text) < 40                # an image-only page: a scan or a photo inside a PDF
        rec = page_record(img, check_quality=scanned, glare=False)   # glare comes from photographing glossy cards, not from scans
        rec["scanned"] = scanned
        pages.append(rec)
    text = "\n\n".join(text_parts).strip()
    return IntakeResult(status="ok", encryption=encryption, pages=pages, text=text, page_count=doc.page_count,
                        pdf_meta=pdf_meta(doc), scanned=all(p["scanned"] for p in pages))


def read_image(data: bytes) -> IntakeResult:
    try:
        im = Image.open(io.BytesIO(data))
        frames = []
        for i in range(getattr(im, "n_frames", 1)):
            if i >= MAX_PAGES:
                break
            im.seek(i)
            frames.append(ImageOps.exif_transpose(im.copy()).convert("RGB"))   # upright, as the camera meant
    except Exception as e:
        return IntakeResult(status="corrupt", reason=f"The image could not be opened: {e}")
    return IntakeResult(status="ok", encryption="none", pages=[page_record(f, check_quality=True) for f in frames],
                        text="", page_count=len(frames), pdf_meta={}, scanned=True)


def read_docx(data: bytes) -> IntakeResult:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
    except zipfile.BadZipFile:
        return IntakeResult(status="corrupt", reason="The Word file is damaged.")
    if any(n.lower().endswith("vbaproject.bin") for n in names):
        return IntakeResult(status="rejected_macro", reason="The Word file contains macros. Macro-enabled files are not accepted.")
    if "word/document.xml" not in names:
        return IntakeResult(status="unsupported_type", reason="The file is an archive, not a Word document.")
    try:
        d = Document(io.BytesIO(data))
    except Exception as e:
        return IntakeResult(status="corrupt", reason=f"The Word file could not be read: {e}")
    text = "\n".join(p.text for p in d.paragraphs if p.text.strip())
    images = []
    for n in names:
        if n.startswith("word/media/"):
            try:
                images.append(ImageOps.exif_transpose(Image.open(io.BytesIO(z.read(n)))).convert("RGB"))
            except Exception:
                pass
    return IntakeResult(status="ok", encryption="none", pages=[page_record(i, True) for i in images[:MAX_PAGES]],
                        text=text, page_count=len(images), pdf_meta={}, scanned=False)


def read_office_encrypted(data: bytes, password: str | None) -> IntakeResult:
    try:
        office = msoffcrypto.OfficeFile(io.BytesIO(data))
        encrypted = office.is_encrypted()
    except Exception:
        return IntakeResult(status="unsupported_type", reason="Old binary Office files (.doc, .xls) are not accepted. Save as .docx or PDF.")
    if not encrypted:
        return IntakeResult(status="unsupported_type", reason="Old binary Office files (.doc, .xls) are not accepted. Save as .docx or PDF.")
    if not password:
        return IntakeResult(status="needs_password", encryption="password",
                            reason="The Word file is password-protected. Ask the customer for the password or an unprotected copy.")
    out = io.BytesIO()
    try:
        office.load_key(password=password)
        office.decrypt(out)
    except Exception:
        return IntakeResult(status="needs_password", encryption="password", wrong_password=True,
                            reason="The password supplied did not open the Word file.")
    result = read_docx(out.getvalue())
    result["encryption"] = "password"
    return result


def inspect(data: bytes, filename: str, password: str | None = None) -> IntakeResult:
    """Everything known about a file before any AI call."""
    kind = filetype.guess(data)
    mime = kind.mime if kind else None
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":       # OLE container: encrypted Office, or old .doc/.xls
        mime = "application/x-ole-storage"
        result = read_office_encrypted(data, password)
    elif mime == "application/pdf":
        result = read_pdf(data, password)
    elif mime in IMAGE_MIMES:
        result = read_image(data)
    elif mime in ("application/zip", "application/vnd.openxmlformats-officedocument.wordprocessingml.document") and ext in ("docx", "docm"):
        result = read_docx(data)
    else:
        result = IntakeResult(status="unsupported_type",
                              reason=f"The file named {filename!r} is really {mime or 'not a recognised document type'}. Accepted: PDF, JPG, PNG, HEIC, WebP, TIFF, DOCX.")
    if result["status"] == "ok":
        bad = [p for p in result["pages"] if p["quality"]["problems"]]
        if not result["pages"] and not result.get("text"):
            result.update(status="corrupt", reason="No pages or text could be read from the file.")
        elif bad and len(bad) == len(result["pages"]):
            problems = sorted({x for p in bad for x in p["quality"]["problems"]})
            result.update(status="poor_quality", reason=f"The image is {', '.join(problems)}: ask the customer to retake it in good light, flat and in focus.")
    declared_ext_mime = {"pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "heic": "image/heic"}.get(ext)
    result.update(mime=mime, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                  extension_mismatch=bool(declared_ext_mime and mime and declared_ext_mime != mime and not (ext == "heic" and mime == "image/heif")))
    return result
