import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mrz import build_td3  # noqa: E402
from validation import addresses_match, names_match, validate  # noqa: E402

TODAY = dt.date(2026, 11, 16)
CONFIG = {"min_age": 18, "proof_of_address_max_age_days": 90, "id_formats": {"UTO:passport": "^[A-Z0-9]{9}$"},
          "suspicious_producers": ["photoshop"]}
FORM = {"applicant": {"full_name": "Tariro Grace Mapfumo", "date_of_birth": "1992-03-15", "address": "10 Jacaranda Avenue, Borrowdale, Utopia City UC11"}}


def f(v):
    return {"value": v, "as_printed": v, "confidence": "high"}


def passport_doc(dob="1992-03-15", expiry="2030-01-31", mrz_dob=None, name="Tariro Grace Mapfumo"):
    l1, l2 = build_td3("Mapfumo", "Tariro Grace", "UA4821937", "UTO", "UTO", dt.date.fromisoformat(dob), "F", dt.date.fromisoformat(expiry))
    if mrz_dob:
        l2 = l2[:13] + mrz_dob + l2[19:]
    return {"document_id": 1, "filename": "passport.jpg", "declared_type": "identity", "status": "ok", "pdf_meta": {},
            "extraction": {"doc_type": "passport", "readability": "clear", "fields": {
                "full_name": f(name), "date_of_birth": f(dob), "document_number": f("UA4821937"), "expiry_date": f(expiry),
                "issuing_country": f("UTO"), "mrz_line1": f(l1), "mrz_line2": f(l2)}}}


def bill_doc(date="2026-10-27", name="Tariro Grace Mapfumo", meta=None):
    return {"document_id": 2, "filename": "bill.pdf", "declared_type": "proof_of_address", "status": "ok", "pdf_meta": meta or {},
            "extraction": {"doc_type": "utility_bill", "readability": "clear", "fields": {
                "full_name": f(name), "document_date": f(date), "address": f("10 Jacaranda Avenue, Borrowdale, Utopia City UC11")}}}


def codes(r, result="fail"):
    return {c["code"] for c in r["checks"] if c["result"] == result}


def test_clean_application_is_ready_for_review_never_approved():
    r = validate(FORM, [passport_doc(), bill_doc()], CONFIG, TODAY)
    assert r["status"] == "ready_for_review" and not codes(r)
    assert {"MRZ_CHECK_DIGITS", "MRZ_MATCHES_PAGE", "ID_EXPIRED", "POA_RECENT", "NAME_MATCHES_APPLICATION"} <= codes(r, "pass")


def test_expired_id_needs_the_customer():
    r = validate(FORM, [passport_doc(expiry="2026-10-01"), bill_doc()], CONFIG, TODAY)
    assert "ID_EXPIRED" in codes(r) and r["status"] == "action_required"


def test_edited_mrz_is_caught():
    r = validate(FORM, [passport_doc(mrz_dob="870315"), bill_doc()], CONFIG, TODAY)
    assert {"MRZ_CHECK_DIGITS", "MRZ_MATCHES_PAGE"} <= codes(r)


def test_old_proof_of_address_and_name_mismatch():
    r = validate(FORM, [passport_doc(), bill_doc(date="2026-06-01", name="Chipo Marufu")], CONFIG, TODAY)
    assert {"POA_RECENT", "NAME_MATCHES_APPLICATION"} <= codes(r)


def test_under_18():
    r = validate(FORM, [passport_doc(dob="2010-04-04"), bill_doc()], CONFIG, TODAY)
    assert "MINIMUM_AGE" in codes(r)


def test_password_file_needs_customer_and_missing_documents_wait():
    doc = {"document_id": 3, "filename": "st.pdf", "declared_type": "proof_of_address", "status": "needs_password", "status_reason": None, "pdf_meta": {}, "extraction": None}
    r = validate(FORM, [passport_doc(), doc], CONFIG, TODAY)
    assert "FILE_NEEDS_PASSWORD" in codes(r) and "MISSING_PROOF_OF_ADDRESS" not in codes(r) and r["status"] == "action_required"


def test_wrong_document_type():
    receipt = bill_doc()
    receipt["extraction"]["doc_type"] = "other"
    r = validate(FORM, [passport_doc(), receipt], CONFIG, TODAY)
    assert {"WRONG_DOCUMENT", "MISSING_PROOF_OF_ADDRESS"} <= codes(r)


def test_pdf_edit_signals_warn_only():
    r = validate(FORM, [passport_doc(), bill_doc(meta={"producer": "Adobe Photoshop 25.0", "creationDate": "D:20261020090000Z", "modDate": "D:20261114221500Z"})], CONFIG, TODAY)
    assert "PDF_EDIT_SIGNALS" in codes(r, "warn") and r["status"] == "ready_for_review"


def test_name_and_address_matching():
    assert names_match("Tariro Grace Mapfumo", "MAPFUMO TARIRO GRACE") is False   # order matters: first name, then surname
    assert names_match("Tariro Grace Mapfumo", "Mrs Tariro Mapfumo")
    assert not names_match("Tariro Mapfumo", "Chipo Marufu")
    assert addresses_match("10 Jacaranda Avenue, Borrowdale", "10 JACARANDA AVE BORROWDALE UTOPIA") is True
