"""Generates SPECIMEN KYC documents for the demo and the evaluation. Every person, company and document is FICTIONAL.

Identity documents are issued by "Utopia" (code UTO), the fictional specimen state used in ICAO Doc 9303.
Portraits are plain silhouettes. Every document is marked SPECIMEN.

Writes sample-documents/<case>/<file> and sample-documents/cases.json: per application, the form the
customer filled in, the files, the true field values, and the expected outcome. Dates are relative to
today, so regenerate before evaluating if the files are months old.

    docker compose run --rm intake python /scripts/make_specimens.py /specimens
"""
from __future__ import annotations

import datetime as dt
import io
import json
import sys
import zipfile
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from pillow_heif import register_heif_opener

sys.path.insert(0, "/app")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service"))
from mrz import build_td3  # noqa: E402

register_heif_opener()
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "sample-documents")
TODAY = dt.date.today()
FONT_DIR = "/usr/share/fonts/truetype/dejavu/"
INK, MUTED, RED = (25, 35, 60), (95, 105, 125), (190, 30, 45)


def font(size, bold=False, mono=False):
    name = "DejaVuSansMono.ttf" if mono else ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    try:
        return ImageFont.truetype(FONT_DIR + name, size)
    except OSError:
        return ImageFont.load_default(size)


def ddmmmyyyy(d: dt.date) -> str:
    return d.strftime("%d %b %Y").upper()


def silhouette(img, box):
    """A plain silhouette in a framed box: never a real face."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    tile = Image.new("RGB", (w, h), (214, 220, 230))
    d = ImageDraw.Draw(tile)
    d.ellipse([w * 0.3, h * 0.14, w * 0.7, h * 0.5], fill=(150, 160, 178))
    d.ellipse([w * 0.12, h * 0.55, w * 0.88, h * 1.3], fill=(150, 160, 178))   # shoulders, cut off by the frame
    d.rectangle([0, 0, w - 1, h - 1], outline=MUTED, width=2)
    img.paste(tile, (x0, y0))


def specimen_stamp(img, text="SPECIMEN"):
    """A translucent stamp across the portrait, away from the data fields."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x, y = 40, int(img.height * 0.42)
    d.text((x, y), text, font=font(64, True), fill=(200, 30, 45, 90))
    return Image.alpha_composite(img.convert("RGBA"), layer.rotate(20, center=(x + 190, y + 35))).convert("RGB")


def passport(p: dict, mrz_dob_override: dt.date | None = None) -> Image.Image:
    img = Image.new("RGB", (1500, 1040), (236, 241, 236))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1500, 90], fill=(28, 70, 60))
    d.text((40, 22), "UTOPIA · PASSPORT · PASSEPORT", font=font(38, True), fill=(255, 255, 255))
    d.text((1150, 30), "SPECIMEN", font=font(30, True), fill=(255, 220, 120))
    silhouette(img, (50, 140, 420, 620))
    rows = [("Type / Code", f"P   UTO"), ("Passport No.", p["number"]), ("Surname", p["surname"].upper()),
            ("Given names", p["given"].upper()), ("Nationality", "UTOPIAN"), ("Date of birth", ddmmmyyyy(p["dob"])),
            ("Sex", p["sex"]), ("Place of birth", p["pob"].upper()), ("Date of issue", ddmmmyyyy(p["issue"])),
            ("Date of expiry", ddmmmyyyy(p["expiry"])), ("Authority", "UTOPIA PASSPORT OFFICE")]
    for i, (k, v) in enumerate(rows):
        y = 130 + i * 50
        d.text((470, y), k, font=font(20), fill=MUTED)
        d.text((720, y - 4), v, font=font(30, True), fill=INK)
    l1, l2 = build_td3(p["surname"], p["given"], p["number"], "UTO", "UTO", p["dob"], p["sex"], p["expiry"])
    if mrz_dob_override:                       # someone edited the date of birth in the MRZ without recomputing its check digit
        l2 = l2[:13] + mrz_dob_override.strftime("%y%m%d") + l2[19:]
    d.rectangle([0, 860, 1500, 1040], fill=(250, 250, 248))
    d.text((40, 880), l1, font=font(43, mono=True), fill=INK)
    d.text((40, 950), l2, font=font(43, mono=True), fill=INK)
    return specimen_stamp(img)


def national_id(p: dict) -> Image.Image:
    img = Image.new("RGB", (1400, 880), (233, 238, 248))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1400, 100], fill=(30, 58, 110))
    d.text((40, 26), "REPUBLIC OF UTOPIA · NATIONAL IDENTITY CARD", font=font(36, True), fill=(255, 255, 255))
    silhouette(img, (50, 150, 400, 600))
    rows = [("ID number", p["number"]), ("Surname", p["surname"].upper()), ("First names", p["given"].upper()),
            ("Date of birth", p["dob"].strftime("%d/%m/%Y")), ("Place of birth", p["pob"].upper()), ("Sex", p["sex"]),
            ("Date of issue", p["issue"].strftime("%d/%m/%Y")), ("Date of expiry", p["expiry"].strftime("%d/%m/%Y"))]
    for i, (k, v) in enumerate(rows):
        y = 150 + i * 62
        d.text((450, y), k, font=font(22), fill=MUTED)
        d.text((720, y - 5), v, font=font(32, True), fill=INK)
    d.text((40, 800), "Issued by the Registrar-General of Utopia · SPECIMEN · not a real document", font=font(22), fill=MUTED)
    return specimen_stamp(img)


def bill_pdf(p: dict, bill_date: dt.date, name_override: str | None = None) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(0, 0, 595, 70), color=None, fill=(0.95, 0.55, 0.1))
    page.insert_text((36, 44), "Contoso Power (fictional)", fontsize=22, fontname="helv", color=(1, 1, 1))
    page.insert_text((400, 44), "SPECIMEN", fontsize=18, fontname="hebo", color=(1, 1, 1))
    lines = [("Electricity bill", 16), ("", 10), (f"Bill date: {ddmmmyyyy(bill_date).title()}", 12),
             (f"Account number: CP-{p['account']}", 12), ("", 10), ("Customer", 11),
             (name_override or p["full"], 13), (p["address"], 12), ("", 10),
             (f"Supply period: {ddmmmyyyy(bill_date - dt.timedelta(days=31)).title()} to {ddmmmyyyy(bill_date - dt.timedelta(days=1)).title()}", 11),
             ("Units used: 412 kWh", 11), ("Amount due: UTD 58.40", 13),
             (f"Pay by: {ddmmmyyyy(bill_date + dt.timedelta(days=21)).title()}", 11), ("", 10),
             ("This is a fictional specimen document generated for software testing.", 9)]
    y = 110
    for text, size in lines:
        if text:
            page.insert_text((36, y), text, fontsize=size, fontname="helv", color=(0.1, 0.12, 0.2))
        y += size + 12
    doc.set_metadata({"producer": "Contoso Billing System 4.2", "creator": "Contoso Billing", "title": "Electricity bill",
                      "creationDate": fitz.get_pdf_now(), "modDate": fitz.get_pdf_now()})
    return doc


def statement_pdf(p: dict, stmt_date: dt.date) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(0, 0, 595, 70), color=None, fill=(0.1, 0.25, 0.45))
    page.insert_text((36, 44), "Northwind Bank (fictional)", fontsize=22, fontname="helv", color=(1, 1, 1))
    page.insert_text((400, 44), "SPECIMEN", fontsize=18, fontname="hebo", color=(1, 1, 1))
    head = [("Account statement", 16), (f"Statement date: {ddmmmyyyy(stmt_date).title()}", 12),
            (f"Account holder: {p['full']}", 12), (f"Address: {p['address']}", 11), (f"Account: NW-{p['account']}", 11)]
    y = 110
    for text, size in head:
        page.insert_text((36, y), text, fontsize=size, fontname="helv", color=(0.1, 0.12, 0.2))
        y += size + 12
    y += 10
    for i, (desc, amt) in enumerate([("Opening balance", "1,204.10"), ("Salary - Fabrikam Ltd", "+2,350.00"),
                                     ("Contoso Power", "-58.40"), ("Card purchase", "-112.75"), ("Closing balance", "3,382.95")]):
        page.insert_text((36, y), (stmt_date - dt.timedelta(days=25 - i * 5)).strftime("%d/%m/%Y"), fontsize=10, fontname="helv")
        page.insert_text((140, y), desc, fontsize=10, fontname="helv")
        page.insert_text((470, y), amt, fontsize=10, fontname="helv")
        y += 22
    page.insert_text((36, y + 30), "This is a fictional specimen document generated for software testing.", fontsize=9, fontname="helv")
    doc.set_metadata({"producer": "Northwind Statements 7.1", "creator": "Northwind Bank", "title": "Account statement",
                      "creationDate": fitz.get_pdf_now(), "modDate": fitz.get_pdf_now()})
    return doc


def receipt() -> Image.Image:
    img = Image.new("RGB", (900, 1300), (252, 250, 245))
    d = ImageDraw.Draw(img)
    for i, (t, s, b) in enumerate([("Fabrikam Café (fictional)", 40, True), ("12 Market Street, Utopia City", 24, False),
                                   ("RECEIPT · SPECIMEN", 28, True), ("", 20, False), ("Flat white            4.20", 28, False),
                                   ("Croissant             3.10", 28, False), ("TOTAL                 7.30", 32, True),
                                   ("Paid by card", 24, False), (TODAY.strftime("%d/%m/%Y 09:41"), 24, False)]):
        d.text((60, 80 + i * 95), t, font=font(s, b, mono=not b and i > 3), fill=INK)
    return img


def save_jpeg(img: Image.Image, path: Path, exif_orientation: int | None = None):
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        img.save(path, "JPEG", quality=90, exif=exif)
    else:
        img.save(path, "JPEG", quality=90)


def scanned_pdf(doc: fitz.Document) -> bytes:
    """Prints a digital PDF to an image and wraps it in a new PDF: a scan, with no text layer."""
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L").filter(ImageFilter.GaussianBlur(0.6)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    out = fitz.open()
    page = out.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
    out.set_metadata({"producer": "ScanSnap Manager", "creator": "Office scanner", "creationDate": fitz.get_pdf_now(), "modDate": fitz.get_pdf_now()})
    return out.tobytes(garbage=3, deflate=True)


def years_ago(n: int, month: int, day: int) -> dt.date:
    return dt.date(TODAY.year - n, month, day)


PEOPLE = {
    "C01": dict(given="Tariro Grace", surname="Mapfumo", sex="F", pob="Utopia City", dob=years_ago(34, 3, 15), number="UA4821937", account="10021"),
    "C02": dict(given="Kudakwashe", surname="Ndlovu", sex="M", pob="Port Utopia", dob=years_ago(41, 7, 2), number="63-482193K-42", account="10022"),
    "C03": dict(given="Farai", surname="Chinamasa", sex="M", pob="Utopia City", dob=years_ago(29, 11, 30), number="08-117245F-08", account="10023"),
    "C04": dict(given="Nyasha", surname="Mutasa", sex="F", pob="Lakeside", dob=years_ago(52, 1, 9), number="UB7730415", account="10024"),
    "C05": dict(given="Tendai", surname="Moyo", sex="M", pob="Utopia City", dob=years_ago(38, 5, 21), number="UC2209876", account="10025"),
    "C06": dict(given="Rutendo", surname="Banda", sex="F", pob="Port Utopia", dob=years_ago(27, 9, 14), number="42-305518R-42", account="10026"),
    "C07": dict(given="Simbarashe", surname="Gumbo", sex="M", pob="Hillview", dob=years_ago(45, 12, 3), number="15-660284S-15", account="10027"),
    "C08": dict(given="Vimbai", surname="Chari", sex="F", pob="Utopia City", dob=years_ago(31, 6, 18), number="UD5518230", account="10028"),
    "C09": dict(given="Tawanda", surname="Shumba", sex="M", pob="Lakeside", dob=years_ago(36, 2, 27), number="27-918374T-27", account="10029"),
    "C10": dict(given="Precious", surname="Makoni", sex="F", pob="Hillview", dob=years_ago(33, 8, 8), number="", account="10030"),
    "C11": dict(given="Blessing", surname="Musoni", sex="M", pob="Utopia City", dob=years_ago(16, 4, 4), number="44-551902B-44", account="10031"),
    "C12": dict(given="Ruvimbo", surname="Zhou", sex="F", pob="Port Utopia", dob=years_ago(39, 10, 12), number="", account="10032"),
}
for cid, p in PEOPLE.items():
    p["full"] = f"{p['given']} {p['surname']}"
    p["address"] = f"{int(cid[1:]) * 7 + 3} Jacaranda Avenue, Borrowdale, Utopia City UC{int(cid[1:]) + 10}"
    p["issue"] = TODAY - dt.timedelta(days=900)
    p["expiry"] = TODAY + dt.timedelta(days=1460)
PEOPLE["C04"]["expiry"] = TODAY - dt.timedelta(days=40)
PEOPLE["C04"]["issue"] = TODAY - dt.timedelta(days=3690)
STATEMENT_PASSWORD = "Gumbo-1203"          # C07: the kind of password banks set (a name and part of the date of birth)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []

    def case(cid, title, files, expect):
        p = PEOPLE[cid]
        cases.append({"case": cid, "title": title,
                      "applicant": {"full_name": p["full"], "date_of_birth": p["dob"].isoformat(), "address": p["address"]},
                      "files": files, "expect": expect})

    def put(cid, name, data):
        folder = OUT / cid
        folder.mkdir(exist_ok=True)
        (folder / name).write_bytes(data)

    def jpg_bytes(img, orient=None):
        buf = io.BytesIO()
        save_jpeg(img, buf, orient)
        return buf.getvalue()

    def id_truth(p, kind):
        return {"doc_type": kind, "full_name": p["full"], "date_of_birth": p["dob"].isoformat(), "document_number": p["number"], "expiry_date": p["expiry"].isoformat()}

    recent, old = TODAY - dt.timedelta(days=20), TODAY - dt.timedelta(days=150)

    p = PEOPLE["C01"]
    put("C01", "passport.jpg", jpg_bytes(passport(p)))
    put("C01", "electricity_bill.pdf", bill_pdf(p, recent).tobytes())
    case("C01", "Clean application: passport photo and an electricity bill", [
        {"file": "passport.jpg", "declared_type": "identity", "truth": id_truth(p, "passport")},
        {"file": "electricity_bill.pdf", "declared_type": "proof_of_address", "truth": {"doc_type": "utility_bill", "full_name": p["full"], "document_date": recent.isoformat()}}],
        {"status": "ready_for_review", "fail": [], "doc_status": {"passport.jpg": "ok", "electricity_bill.pdf": "ok"}})

    p = PEOPLE["C02"]
    put("C02", "national_id_photo.jpg", jpg_bytes(national_id(p).rotate(90, expand=True), orient=6))   # stored sideways; EXIF says rotate
    put("C02", "bank_statement_scan.pdf", scanned_pdf(statement_pdf(p, recent)))
    case("C02", "A phone photo saved sideways (EXIF rotation) and a scanned statement with no text layer", [
        {"file": "national_id_photo.jpg", "declared_type": "identity", "truth": id_truth(p, "national_id")},
        {"file": "bank_statement_scan.pdf", "declared_type": "proof_of_address", "truth": {"doc_type": "bank_statement", "full_name": p["full"], "document_date": recent.isoformat()}}],
        {"status": "ready_for_review", "fail": [], "doc_status": {"national_id_photo.jpg": "ok", "bank_statement_scan.pdf": "ok"}})

    p = PEOPLE["C03"]
    put("C03", "national_id_blurred.jpg", jpg_bytes(national_id(p).filter(ImageFilter.GaussianBlur(9))))
    case("C03", "A blurred photo of an ID: stopped before any AI call", [
        {"file": "national_id_blurred.jpg", "declared_type": "identity"}],
        {"status": "action_required", "fail": ["FILE_POOR_QUALITY"], "doc_status": {"national_id_blurred.jpg": "poor_quality"}, "ai_calls": 0})

    p = PEOPLE["C04"]
    put("C04", "passport.jpg", jpg_bytes(passport(p)))
    case("C04", "An expired passport", [{"file": "passport.jpg", "declared_type": "identity", "truth": id_truth(p, "passport")}],
         {"status": "action_required", "fail": ["ID_EXPIRED", "MISSING_PROOF_OF_ADDRESS"], "doc_status": {"passport.jpg": "ok"}})

    p = PEOPLE["C05"]
    put("C05", "passport.jpg", jpg_bytes(passport(p, mrz_dob_override=p["dob"] - dt.timedelta(days=365 * 5 + 1))))
    case("C05", "A passport whose MRZ date of birth was edited without fixing its check digit", [
        {"file": "passport.jpg", "declared_type": "identity", "truth": id_truth(p, "passport")}],
        {"status": "action_required", "fail": ["MRZ_CHECK_DIGITS", "MISSING_PROOF_OF_ADDRESS"], "doc_status": {"passport.jpg": "ok"}})

    p = PEOPLE["C06"]
    put("C06", "national_id.jpg", jpg_bytes(national_id(p)))
    put("C06", "electricity_bill.pdf", bill_pdf(p, recent, name_override="Chipo Marufu").tobytes())
    case("C06", "A utility bill in someone else's name", [
        {"file": "national_id.jpg", "declared_type": "identity", "truth": id_truth(p, "national_id")},
        {"file": "electricity_bill.pdf", "declared_type": "proof_of_address", "truth": {"doc_type": "utility_bill", "full_name": "Chipo Marufu", "document_date": recent.isoformat()}}],
        {"status": "ready_for_review", "fail": ["NAME_MATCHES_APPLICATION"], "doc_status": {"national_id.jpg": "ok", "electricity_bill.pdf": "ok"}})

    p = PEOPLE["C07"]
    put("C07", "national_id.jpg", jpg_bytes(national_id(p)))
    st = statement_pdf(p, recent)
    put("C07", "bank_statement_protected.pdf", st.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=STATEMENT_PASSWORD, owner_pw="northwind-owner-secret",
                                                          permissions=fitz.PDF_PERM_PRINT))
    case("C07", "A password-protected bank statement: wrong password, then the right one", [
        {"file": "national_id.jpg", "declared_type": "identity", "truth": id_truth(p, "national_id")},
        {"file": "bank_statement_protected.pdf", "declared_type": "proof_of_address", "password": STATEMENT_PASSWORD,
         "truth": {"doc_type": "bank_statement", "full_name": p["full"], "document_date": recent.isoformat()}}],
        {"status": "action_required", "fail": ["FILE_NEEDS_PASSWORD"], "doc_status": {"national_id.jpg": "ok", "bank_statement_protected.pdf": "needs_password"},
         "after_unlock": {"status": "ready_for_review", "fail": []}})

    p = PEOPLE["C08"]
    buf = io.BytesIO()
    passport(p).save(buf, format="HEIF", quality=85)
    put("C08", "IMG_4417.HEIC", buf.getvalue())
    put("C08", "electricity_bill.pdf", bill_pdf(p, old).tobytes())
    case("C08", "An iPhone HEIC photo of a passport and a five-month-old bill", [
        {"file": "IMG_4417.HEIC", "declared_type": "identity", "truth": id_truth(p, "passport")},
        {"file": "electricity_bill.pdf", "declared_type": "proof_of_address", "truth": {"doc_type": "utility_bill", "full_name": p["full"], "document_date": old.isoformat()}}],
        {"status": "action_required", "fail": ["POA_RECENT"], "doc_status": {"IMG_4417.HEIC": "ok", "electricity_bill.pdf": "ok"}})

    p = PEOPLE["C09"]
    put("C09", "national_id.jpg", jpg_bytes(national_id(p)))
    put("C09", "proof_of_address.jpg", jpg_bytes(receipt()))
    case("C09", "A café receipt uploaded as proof of address", [
        {"file": "national_id.jpg", "declared_type": "identity", "truth": id_truth(p, "national_id")},
        {"file": "proof_of_address.jpg", "declared_type": "proof_of_address", "truth": {"doc_type": "other"}}],
        {"status": "action_required", "fail": ["WRONG_DOCUMENT", "MISSING_PROOF_OF_ADDRESS"], "doc_status": {"national_id.jpg": "ok", "proof_of_address.jpg": "ok"}})

    put("C10", "national_id.pdf", b"This is a plain text file renamed to .pdf, not a PDF document.\n")
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Override PartName="/word/document.xml" ContentType="application/vnd.ms-word.document.macroEnabled.main+xml"/></Types>')
        zf.writestr("word/document.xml", "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'><w:body><w:p><w:r><w:t>Utility bill</w:t></w:r></w:p></w:body></w:document>")
        zf.writestr("word/vbaProject.bin", b"\xd0\xcf\x11\xe0 fictional macro project (inert test bytes)")
    put("C10", "utility_bill.docm", z.getvalue())
    case("C10", "A text file renamed to .pdf, and a macro-enabled Word file: both stopped before any AI call", [
        {"file": "national_id.pdf", "declared_type": "identity"}, {"file": "utility_bill.docm", "declared_type": "proof_of_address"}],
        {"status": "action_required", "fail": ["FILE_UNSUPPORTED_TYPE", "FILE_REJECTED_MACRO"],
         "doc_status": {"national_id.pdf": "unsupported_type", "utility_bill.docm": "rejected_macro"}, "ai_calls": 0})

    p = PEOPLE["C11"]
    put("C11", "national_id.jpg", jpg_bytes(national_id(p)))
    case("C11", "An applicant under 18", [{"file": "national_id.jpg", "declared_type": "identity", "truth": id_truth(p, "national_id")}],
         {"status": "action_required", "fail": ["MINIMUM_AGE", "MISSING_PROOF_OF_ADDRESS"], "doc_status": {"national_id.jpg": "ok"}})

    p = PEOPLE["C12"]
    st = statement_pdf(p, recent)
    created = TODAY - dt.timedelta(days=20)
    st.set_metadata({"producer": "Adobe Photoshop 25.0 (Windows)", "creator": "Adobe Photoshop", "title": "Account statement",
                     "creationDate": created.strftime("D:%Y%m%d090000Z"), "modDate": (TODAY - dt.timedelta(days=2)).strftime("D:%Y%m%d221500Z")})
    put("C12", "bank_statement.pdf", st.tobytes())
    case("C12", "A statement saved with Photoshop after it was issued (a tamper signal for the reviewer)", [
        {"file": "bank_statement.pdf", "declared_type": "proof_of_address", "truth": {"doc_type": "bank_statement", "full_name": p["full"], "document_date": recent.isoformat()}}],
        {"status": "action_required", "fail": ["MISSING_IDENTITY"], "warn": ["PDF_EDIT_SIGNALS"], "doc_status": {"bank_statement.pdf": "ok"}})

    (OUT / "cases.json").write_text(json.dumps({"generated": TODAY.isoformat(), "note": "Fictional specimens. Utopia (UTO) is the ICAO Doc 9303 specimen state.",
                                                "cases": cases}, indent=2) + "\n", encoding="utf-8")
    print(f"{len(cases)} cases, {sum(len(c['files']) for c in cases)} files -> {OUT}")


if __name__ == "__main__":
    main()
