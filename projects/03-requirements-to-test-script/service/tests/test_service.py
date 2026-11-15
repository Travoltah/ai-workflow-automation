"""Unit tests for the test-script service.

    docker compose run --rm -v "$PWD/sample-input:/samples:ro" testscript-service \
        sh -c "pip install -q pytest && python -m pytest -q tests"
(the service image copies tests/ only when you mount it; see BUILD-GUIDE.md, step 9)
"""
import base64
import io
import os
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import document_reader  # noqa: E402
import excel_builder  # noqa: E402

SAMPLES = Path(os.environ.get("SAMPLES", "/samples"))


def b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


@pytest.mark.skipif(not SAMPLES.is_dir(), reason="sample-input not mounted")
def test_docx_text_tables_and_embedded_wireframe():
    cr = next(SAMPLES.glob("*.docx"))
    result = document_reader.prepare([{"name": cr.name, "mimeType": "", "data": b64(cr), "role": "document"}])
    text = result.blocks[0]["text"]
    assert "## FR-02 Instant settlement" in text                 # headings kept as Markdown
    assert "| BR-04.2 | Overpayment ≤ R10.00 |" in text           # tables kept as Markdown tables
    assert text.index("FR-01") < text.index("BR-04.1")           # document order kept
    assert [b["type"] for b in result.blocks[1:]] == ["text", "image"]   # the embedded wireframe
    assert result.files[0]["images"] == 1 and not result.warnings


@pytest.mark.skipif(not SAMPLES.is_dir(), reason="sample-input not mounted")
def test_images_are_scaled_and_limited():
    png = next(SAMPLES.glob("*.png"))
    files = [{"name": f"w{i}.png", "mimeType": "image/png", "data": b64(png), "role": "wireframe"} for i in range(3)]
    result = document_reader.prepare(files, max_images=2)
    images = [b for b in result.blocks if b["type"] == "image"]
    assert len(images) == 2 and any("Image limit" in w for w in result.warnings)


def test_pdf_passes_through_and_bad_files_warn():
    pdf = base64.b64encode(b"%PDF-1.4 fake").decode()
    result = document_reader.prepare([
        {"name": "fsd.pdf", "mimeType": "application/pdf", "data": pdf},
        {"name": "old.doc", "mimeType": "application/msword", "data": pdf},
        {"name": "data.xlsx", "mimeType": "application/octet-stream", "data": pdf},
    ])
    assert result.blocks[0]["type"] == "document" and result.blocks[0]["source"]["media_type"] == "application/pdf"
    assert len(result.warnings) == 2 and "docx" in result.warnings[0]


def payload():
    row = {"id": "SL-001", "module": "Loan Application", "type": "Functional", "scenario": "Block V2 application",
           "details": "Preconditions: x\n\nSteps:\n1. a\n2. b", "expected": "Blocked", "priority": "High",
           "covers": ["AC1"], "jiraStory": "CPAY-1", "jiraStoryUrl": "https://example.atlassian.net/browse/CPAY-1"}
    return {
        "meta": {"systemName": "Contoso Lend", "title": "Loan Settlement Logic", "changeRequest": "CR-2026-014",
                 "requestedDate": "23 September 2026"},
        "sections": [
            {"letter": "A", "name": "Loan Application Restriction: during [debit] runs", "shortName": "Loan Restriction / Debit",
             "rows": [row, {**row, "id": "SL-002"}]},
            {"letter": "B", "name": "Regression", "shortName": "Regression", "rows": [{**row, "id": "SL-003", "type": "Regression"}]},
            {"letter": "C", "name": "Empty", "rows": []},
        ],
        "stories": [{"section": "A", "ref": "US-01", "jiraKey": "CPAY-1", "title": "t", "tests": 2, "coveragePct": 100}],
        "traceability": [{"story": "CPAY-1", "acId": "AC1", "acText": "x", "source": "document", "tests": ["SL-001"]}],
        "questions": [{"story": "CPAY-1", "question": "What is the cut-off?"}],
    }


def test_workbook_layout_and_formulas():
    wb = load_workbook(io.BytesIO(excel_builder.build_workbook(payload())))
    assert wb.sheetnames == ["Summary", "A – Loan Restriction   Debit", "B – Regression",
                             "Stories & Tickets", "Traceability", "Open Questions"]
    summary = wb["Summary"]
    assert summary["A1"].value == "Contoso Lend – Loan Settlement Logic QA Test Script"
    assert summary["A2"].value == "Change Request – CR-2026-014  |  Requested: 23 September 2026"
    assert [c.value for c in summary[4]] == ["Metric", "PASS", "FAIL", "PENDING", "BLOCKED", "TOTAL"]
    assert summary["B5"].value == "=SUM(B9:B10)"
    assert summary["B9"].value == "=COUNTIF('A – Loan Restriction   Debit'!$G$6:$G$1000,\"PASS\")"
    assert summary["F10"].value == "=COUNTA('B – Regression'!$A$6:$A$1000)"

    sheet = wb["A – Loan Restriction   Debit"]
    assert [c.value for c in sheet[4]][:8] == ["ID #", "Function / Module", "Test Type", "Test Scenario",
                                               "Preconditions / Data / Steps", "Expected Response", "Results", "Comments"]
    assert sheet["A5"].value.startswith("◆ A – ")
    assert sheet["A6"].value == "SL-001" and sheet["G6"].value == "PENDING"
    assert sheet["K6"].hyperlink.target.endswith("/browse/CPAY-1")
    assert sheet.data_validations.dataValidation[0].formula1 == '"PENDING,PASS,FAIL,BLOCKED"'
    assert wb["Traceability"]["F4"].value == "Yes"


def test_file_name_is_safe():
    assert excel_builder.file_name({"systemName": "Contoso Lend", "changeRequest": "CR/014: V1.0"}) == \
        "Contoso_Lend_CR_014_V1.0_QA_Test_Script.xlsx"


def test_figma_links():
    assert document_reader.parse_figma_url("https://www.figma.com/design/AbC123/Loans?node-id=12-34&t=x") == ("AbC123", "12:34")
    assert document_reader.parse_figma_url("https://figma.com/file/AbC123/Loans") == ("AbC123", None)
    with pytest.raises(ValueError):
        document_reader.parse_figma_url("https://example.com/design/AbC123")


def test_figma_without_token_warns(monkeypatch):
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    result = document_reader.prepare([], figma_urls=["https://www.figma.com/design/AbC123/x?node-id=1-2"])
    assert result.blocks == [] and "FIGMA_TOKEN" in result.warnings[0]


def test_figma_frames_are_added(monkeypatch):
    png = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (800, 600), "white").save(png, "PNG")
    calls = []

    def fake_get(url, token=None):
        calls.append(url)
        if "/images/" in url:
            return b'{"err": null, "images": {"1:2": "https://s3.example/frame.png"}}'
        return png.getvalue()

    monkeypatch.setenv("FIGMA_TOKEN", "test-token")
    monkeypatch.setattr(document_reader, "_get", fake_get)
    result = document_reader.prepare([], figma_urls=["https://www.figma.com/design/AbC123/x?node-id=1-2"])
    assert [b["type"] for b in result.blocks] == ["text", "image"]
    assert "ids=1%3A2" in calls[0] and result.files[0]["kind"] == "figma"
