import io
import sys
import zipfile
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFilter
from pillow_heif import register_heif_opener

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intake import inspect  # noqa: E402

register_heif_opener()


def sharp_image(w=1400, h=900) -> Image.Image:
    img = Image.new("RGB", (w, h), (235, 238, 245))
    d = ImageDraw.Draw(img)
    for i in range(0, h, 40):
        d.text((40, i), "SPECIMEN NATIONAL IDENTITY CARD 63-123456K-42 MOYO TENDAI", fill=(20, 30, 60))
        d.line((0, i + 30, w, i + 30), fill=(120, 120, 140), width=2)
    return img


def jpg(img, exif_orientation=None):
    buf = io.BytesIO()
    kw = {}
    if exif_orientation:
        exif = Image.Exif(); exif[0x0112] = exif_orientation; kw["exif"] = exif
    img.save(buf, "JPEG", quality=90, **kw)
    return buf.getvalue()


def pdf(text="Account statement for Tendai Moyo, statement date 27 October 2026", user_pw=None):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text, fontsize=12)
    return doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=user_pw, owner_pw="owner") if user_pw else doc.tobytes()


def test_sharp_photo_is_ok():
    r = inspect(jpg(sharp_image()), "id.jpg")
    assert r["status"] == "ok" and r["pages"][0]["quality"]["problems"] == []


def test_blurred_photo_is_stopped():
    r = inspect(jpg(sharp_image().filter(ImageFilter.GaussianBlur(9))), "id.jpg")
    assert r["status"] == "poor_quality" and "blurred" in r["reason"]


def test_exif_rotation_is_applied():
    stored_sideways = sharp_image().rotate(90, expand=True)          # 900 x 1400 pixels
    r = inspect(jpg(stored_sideways, exif_orientation=6), "id.jpg")
    q = r["pages"][0]["quality"]
    assert (q["width"], q["height"]) == (1400, 900)


def test_heic_is_read():
    buf = io.BytesIO()
    sharp_image().save(buf, format="HEIF")
    r = inspect(buf.getvalue(), "IMG_0001.HEIC")
    assert r["status"] == "ok" and r["mime"] in ("image/heic", "image/heif")


def test_digital_pdf_text_is_extracted():
    r = inspect(pdf(), "statement.pdf")
    assert r["status"] == "ok" and "Tendai Moyo" in r["text"] and r["encryption"] == "none" and not r["scanned"]


def test_password_pdf_needs_password_then_opens_once():
    data = pdf(user_pw="Moyo-0521")
    assert inspect(data, "s.pdf")["status"] == "needs_password"
    wrong = inspect(data, "s.pdf", password="guess")
    assert wrong["status"] == "needs_password" and wrong.get("wrong_password")
    right = inspect(data, "s.pdf", password="Moyo-0521")
    assert right["status"] == "ok" and "Tendai Moyo" in right["text"] and right["encryption"] == "password"


def test_text_file_renamed_to_pdf_is_rejected():
    r = inspect(b"just some text, not a pdf\n", "national_id.pdf")
    assert r["status"] == "unsupported_type"


def test_macro_word_file_is_rejected():
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("word/vbaProject.bin", b"inert")
    assert inspect(z.getvalue(), "bill.docm")["status"] == "rejected_macro"


def test_corrupt_pdf():
    assert inspect(b"%PDF-1.7\n garbage garbage", "x.pdf")["status"] in ("corrupt", "unsupported_type")


def sparse_document() -> Image.Image:
    """A sharp page that is mostly white paper: a receipt or a short letter."""
    img = Image.new("RGB", (900, 1300), (252, 250, 245))
    d = ImageDraw.Draw(img)
    for i, t in enumerate(["Fabrikam Cafe", "Flat white  4.20", "Croissant  3.10", "TOTAL  7.30"]):
        d.text((60, 80 + i * 90), t, fill=(25, 35, 60))
    return img


def test_sharp_white_paper_is_not_rejected():
    # regression: the first version scored blank white paper as "glare" and rejected sharp scans
    r = inspect(jpg(sparse_document()), "receipt.jpg")
    assert r["status"] == "ok", r.get("reason")


def test_blurred_white_paper_is_still_rejected():
    r = inspect(jpg(sparse_document().filter(ImageFilter.GaussianBlur(6))), "receipt.jpg")
    assert r["status"] == "poor_quality"
