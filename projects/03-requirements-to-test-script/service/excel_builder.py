"""Builds the QA test script workbook.

Layout (one file per change request):
  Summary              title, change request line, PASS / FAIL / PENDING / BLOCKED / TOTAL,
                       and a breakdown per section. All counts are formulas, so the summary
                       updates while testers fill in the Results column.
  A - <section> ...    one sheet per section (a user story), then a Regression sheet:
                       ID # | Function / Module | Test Type | Test Scenario |
                       Preconditions / Data / Steps | Expected Response | Results | Comments
                       followed by traceability columns: Priority | Covers | Jira Story | QA Ticket.
                       Results is a drop-down (PENDING, PASS, FAIL, BLOCKED) with colours.
  Stories & Tickets    every story with its Jira story, QA ticket, coverage and quality gate.
  Traceability         every acceptance criterion and the tests that cover it.
  Open Questions       questions for the product owner / business analyst.
"""
from __future__ import annotations

import io
import math
import re
from datetime import datetime

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter, quote_sheetname
from openpyxl.worksheet.datavalidation import DataValidation

RESULTS = ["PENDING", "PASS", "FAIL", "BLOCKED"]
FONT = "Arial"

TITLE_FILL = PatternFill("solid", fgColor="262626")
SUBTITLE_FILL = PatternFill("solid", fgColor="404040")
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
BAND_FILL = PatternFill("solid", fgColor="333333")
ROW_FILL = PatternFill("solid", fgColor="F7F7F7")
ALT_FILL = PatternFill("solid", fgColor="EFEFEF")
GRID = Side(style="thin", color="D0D0D0")
BORDER = Border(left=GRID, right=GRID, top=GRID, bottom=GRID)

RESULT_COLOURS = {  # (fill, font)
    "PASS": ("C6EFCE", "006100"),
    "FAIL": ("FFC7CE", "9C0006"),
    "BLOCKED": ("FFEB9C", "9C5700"),
}

SECTION_COLUMNS = [  # (header, width)
    ("ID #", 9), ("Function / Module", 22), ("Test Type", 13), ("Test Scenario", 40),
    ("Preconditions / Data / Steps", 58), ("Expected Response", 48), ("Results", 12), ("Comments", 30),
    ("Priority", 10), ("Covers", 12), ("Jira Story", 13), ("QA Ticket", 13),
]
FIRST_DATA_ROW = 6
LAST_FORMULA_ROW = 1000   # summary formulas look this far down, so testers can add rows


def font(size=10, bold=False, color="000000", italic=False, underline=None):
    return Font(name=FONT, size=size, bold=bold, color=color, italic=italic, underline=underline)


def sheet_title(letter: str, short_name: str) -> str:
    """Excel sheet names: max 31 characters, none of []:*?/\\ ."""
    clean = re.sub(r"[\[\]:*?/\\]", " ", short_name).strip() or "Section"
    return f"{letter} – {clean}"[:31].rstrip()


def text_lines(text: str, width: int) -> int:
    """Rough number of wrapped lines a text needs in a column of the given width."""
    chars = max(width * 1.15, 8)
    return sum(max(1, math.ceil(len(line) / chars)) for line in str(text or "").split("\n"))


def fit_height(values_widths) -> float:
    lines = max((text_lines(v, w) for v, w in values_widths), default=1)
    return min(max(15, lines * 13.5 + 6), 409)


def banner(ws, row: int, text: str, last_col: int, fill, size: int, bold: bool, color: str, height: float, align="center"):
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last_col)
    cell = ws.cell(row=row, column=1, value=text)
    cell.font = font(size, bold, color)
    cell.fill = fill
    cell.alignment = Alignment(horizontal=align, vertical="center", indent=0 if align == "center" else 1)
    for col in range(2, last_col + 1):
        ws.cell(row=row, column=col).fill = fill
    ws.row_dimensions[row].height = height


def header_row(ws, row: int, headers: list[str]):
    for col, title in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col, value=title)
        cell.font = font(10, True, "FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = BORDER
    ws.row_dimensions[row].height = 26


def body_cell(cell, value, fill, wrap=True, center=False, bold=False):
    cell.value = value
    cell.font = font(10, bold)
    cell.fill = fill
    cell.border = BORDER
    cell.alignment = Alignment(horizontal="center" if center else "left", vertical="top", wrap_text=wrap)


def link(cell, key: str, url: str | None):
    if key and url:
        cell.hyperlink = url
        cell.font = font(10, color="0563C1", underline="single")


def add_result_rules(ws, rng: str):
    for value, (fill, colour) in RESULT_COLOURS.items():
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{value}"'],
                                                      fill=PatternFill("solid", fgColor=fill, bgColor=fill),
                                                      font=Font(name=FONT, color=colour, bold=True)))


def build_section_sheet(wb: Workbook, meta: dict, section: dict) -> str:
    ws = wb.create_sheet(sheet_title(section["letter"], section.get("shortName") or section["name"]))
    ncols = len(SECTION_COLUMNS)
    for col, (_, width) in enumerate(SECTION_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.sheet_view.showGridLines = False

    banner(ws, 1, f"{meta['systemName']} – {meta['title']} · QA Test Script", ncols, TITLE_FILL, 14, True, "FFFFFF", 32)
    banner(ws, 2, f"{section['letter']} – {section['name']}", ncols, SUBTITLE_FILL, 10, False, "E0E0E0", 20, align="left")
    ws.row_dimensions[3].height = 6
    header_row(ws, 4, [h for h, _ in SECTION_COLUMNS])
    banner(ws, 5, f"◆ {section['letter']} – {section['name']}", ncols, BAND_FILL, 10, True, "FFFFFF", 18, align="left")

    rows = section.get("rows", [])
    for i, r in enumerate(rows):
        row = FIRST_DATA_ROW + i
        fill = ROW_FILL if i % 2 == 0 else ALT_FILL
        values = [r.get("id"), r.get("module"), r.get("type"), r.get("scenario"), r.get("details"),
                  r.get("expected"), r.get("result") or "PENDING", r.get("comments") or "",
                  r.get("priority"), ", ".join(r.get("covers") or []), r.get("jiraStory") or "", r.get("qaTicket") or ""]
        for col, value in enumerate(values, start=1):
            body_cell(ws.cell(row=row, column=col), value, fill, center=col in (1, 7, 9, 10, 11, 12), bold=col == 7)
        link(ws.cell(row=row, column=11), r.get("jiraStory"), r.get("jiraStoryUrl"))
        link(ws.cell(row=row, column=12), r.get("qaTicket"), r.get("qaTicketUrl"))
        ws.row_dimensions[row].height = fit_height([(values[c], SECTION_COLUMNS[c][1]) for c in (1, 3, 4, 5)])

    last = max(FIRST_DATA_ROW + len(rows) - 1, FIRST_DATA_ROW)
    validation = DataValidation(type="list", formula1='"' + ",".join(RESULTS) + '"', allow_blank=True,
                                showErrorMessage=True, errorTitle="Result", error="Choose PENDING, PASS, FAIL or BLOCKED.")
    ws.add_data_validation(validation)
    validation.add(f"G{FIRST_DATA_ROW}:G{LAST_FORMULA_ROW}")
    add_result_rules(ws, f"G{FIRST_DATA_ROW}:G{LAST_FORMULA_ROW}")
    ws.freeze_panes = ws.cell(row=FIRST_DATA_ROW, column=2)
    ws.auto_filter.ref = f"A4:{get_column_letter(ncols)}{last}"
    ws.print_title_rows = "4:4"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    return ws.title


def build_summary(ws, meta: dict, sections: list[dict], sheet_names: list[str]):
    widths = [44, 13, 13, 13, 13, 13]
    for col, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.sheet_view.showGridLines = False

    banner(ws, 1, f"{meta['systemName']} – {meta['title']} QA Test Script", 6, TITLE_FILL, 14, True, "FFFFFF", 34)
    subtitle = f"Change Request – {meta.get('changeRequest') or meta['title']}"
    if meta.get("requestedDate"):
        subtitle += f"  |  Requested: {meta['requestedDate']}"
    banner(ws, 2, subtitle, 6, SUBTITLE_FILL, 10, False, "E0E0E0", 22, align="left")
    ws.row_dimensions[3].height = 8

    header_row(ws, 4, ["Metric", "PASS", "FAIL", "PENDING", "BLOCKED", "TOTAL"])
    first, last = 9, 9 + len(sections) - 1
    body_cell(ws.cell(row=5, column=1), "All Sections", ROW_FILL, bold=True)
    for col in range(2, 7):
        letter = get_column_letter(col)
        formula = f"=SUM({letter}{first}:{letter}{last})" if sections else 0
        body_cell(ws.cell(row=5, column=col), formula, ROW_FILL, center=True, bold=True)
    ws.row_dimensions[5].height = 20

    banner(ws, 7, "Section Breakdown", 6, SUBTITLE_FILL, 11, True, "FFFFFF", 22, align="left")
    header_row(ws, 8, ["Section", "PASS", "FAIL", "PENDING", "BLOCKED", "Cases"])
    for i, (section, name) in enumerate(zip(sections, sheet_names)):
        row = first + i
        fill = ROW_FILL if i % 2 == 0 else ALT_FILL
        ref = quote_sheetname(name)
        body_cell(ws.cell(row=row, column=1), f"{section['letter']} – {section['name']}", fill, wrap=False)
        ws.cell(row=row, column=1).hyperlink = f"#{ref}!A1"
        for col, status in enumerate(["PASS", "FAIL", "PENDING", "BLOCKED"], start=2):
            body_cell(ws.cell(row=row, column=col),
                      f'=COUNTIF({ref}!$G${FIRST_DATA_ROW}:$G${LAST_FORMULA_ROW},"{status}")', fill, center=True)
        body_cell(ws.cell(row=row, column=6),
                  f"=COUNTA({ref}!$A${FIRST_DATA_ROW}:$A${LAST_FORMULA_ROW})", fill, center=True)
        ws.row_dimensions[row].height = 18

    note_row = last + 3 if sections else 11
    ws.cell(row=note_row, column=1, value="Pass rate (of executed)").font = font(10, True)
    ws.cell(row=note_row, column=2, value="=IFERROR(B5/(B5+C5+E5),0)").number_format = "0%"
    ws.cell(row=note_row + 1, column=1, value="Execution progress").font = font(10, True)
    ws.cell(row=note_row + 1, column=2, value="=IFERROR((B5+C5+E5)/F5,0)").number_format = "0%"
    for r in (note_row, note_row + 1):
        ws.cell(row=r, column=2).font = font(10, True)
    info = [f"Generated {meta.get('generatedAt', '')} by {meta.get('generatedBy', 'Requirements-to-Test-Script workflow')}"]
    if meta.get("model"):
        info.append(f"Model: {meta['model']}")
    if meta.get("usage"):
        info.append(f"Claude usage: {meta['usage']}")
    if meta.get("sources"):
        info.append("Sources: " + ", ".join(meta["sources"]))
    ws.cell(row=note_row + 3, column=1, value="  ·  ".join(info)).font = font(8, italic=True, color="7F7F7F")
    ws.freeze_panes = "A4"


def build_table_sheet(wb: Workbook, title: str, meta: dict, columns: list[tuple[str, int]], rows: list[list], links=None):
    ws = wb.create_sheet(title)
    ws.sheet_view.showGridLines = False
    for col, (_, width) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(col)].width = width
    banner(ws, 1, f"{meta['systemName']} – {meta['title']} · {title}", len(columns), TITLE_FILL, 13, True, "FFFFFF", 28)
    header_row(ws, 3, [h for h, _ in columns])
    for i, values in enumerate(rows):
        row = 4 + i
        fill = ROW_FILL if i % 2 == 0 else ALT_FILL
        for col, value in enumerate(values, start=1):
            body_cell(ws.cell(row=row, column=col), value, fill)
        for col, url in (links(i) if links else []):
            link(ws.cell(row=row, column=col), values[col - 1], url)
        ws.row_dimensions[row].height = fit_height([(v, columns[c][1]) for c, v in enumerate(values) if isinstance(v, str)])
    if not rows:
        ws.cell(row=4, column=1, value="None").font = font(10, italic=True, color="7F7F7F")
    ws.freeze_panes = "A4"
    return ws


def build_workbook(payload: dict) -> bytes:
    meta = {"systemName": "System", "title": "Change Request", **(payload.get("meta") or {})}
    meta.setdefault("generatedAt", datetime.now().strftime("%d %B %Y %H:%M"))
    sections = [s for s in payload.get("sections", []) if s.get("rows")]

    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    names = [build_section_sheet(wb, meta, s) for s in sections]
    build_summary(summary, meta, sections, names)

    stories = payload.get("stories", [])
    build_table_sheet(
        wb, "Stories & Tickets", meta,
        [("Section", 9), ("Story", 9), ("Jira Story", 13), ("QA Ticket", 13), ("Title", 46), ("Origin", 18),
         ("Criteria", 9), ("Generated AC", 12), ("Tests", 8), ("Coverage", 10), ("Quality gate", 14), ("Notes", 50)],
        [[s.get("section"), s.get("ref"), s.get("jiraKey") or "", s.get("qaKey") or "", s.get("title"), s.get("origin"),
          s.get("acCount"), s.get("generatedAc"), s.get("tests"), f"{s.get('coveragePct', 0)}%", s.get("quality"),
          "\n".join(s.get("issues") or [])] for s in stories],
        links=lambda i: [(3, stories[i].get("jiraUrl")), (4, stories[i].get("qaUrl"))],
    )
    trace = payload.get("traceability", [])
    build_table_sheet(
        wb, "Traceability", meta,
        [("Story", 13), ("AC", 7), ("Acceptance criterion", 70), ("Source", 12), ("Covered by tests", 30), ("Covered", 10)],
        [[t.get("story"), t.get("acId"), t.get("acText"), t.get("source"), ", ".join(t.get("tests") or []),
          "Yes" if t.get("tests") else "NO"] for t in trace],
    )
    questions = payload.get("questions", [])
    build_table_sheet(
        wb, "Open Questions", meta,
        [("#", 6), ("Story", 13), ("Question for the product owner / BA", 90), ("Answer", 40)],
        [[i + 1, q.get("story"), q.get("question"), ""] for i, q in enumerate(questions)],
    )

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def file_name(meta: dict) -> str:
    base = f"{meta.get('systemName', '')} {meta.get('changeRequest') or meta.get('title', '')}"
    base = re.sub(r"[^\w.\- ]+", " ", base)
    base = re.sub(r"\s+", "_", base.strip())[:80].rstrip("_.-")   # keep the suffix whole
    return f"{base}_QA_Test_Script.xlsx" if base else "QA_Test_Script.xlsx"
