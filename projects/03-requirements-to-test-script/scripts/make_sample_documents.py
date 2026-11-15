"""Creates the sample inputs in sample-input/: a Change Request (.docx, with an embedded
wireframe) and two wireframe images.

The company and system are fictional (Contoso Lend). Run inside the service container,
which already has python-docx and Pillow:

    docker compose run --rm -v "$PWD/sample-input:/out" -v "$PWD/scripts:/scripts:ro" \
        testscript-service python /scripts/make_sample_documents.py /out
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import docx
from docx.shared import Cm, Pt
from PIL import Image, ImageDraw, ImageFont

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "sample-input")
INK, LINE, MUTED, ACCENT, WARN = "#1F2937", "#9CA3AF", "#6B7280", "#1D4ED8", "#B91C1C"


def f(size, bold=False):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def frame(title: str):
    img = Image.new("RGB", (1200, 800), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1199, 64], fill="#F3F4F6", outline=LINE)
    d.text((24, 18), "Contoso Lend · Operations", font=f(22, True), fill=INK)
    d.text((880, 22), "ops.user@contoso", font=f(18), fill=MUTED)
    d.text((24, 92), title, font=f(30, True), fill=INK)
    return img, d


def field(d, x, y, label, value, w=520):
    d.text((x, y), label, font=f(16), fill=MUTED)
    d.rectangle([x, y + 26, x + w, y + 70], outline=LINE, width=2)
    d.text((x + 12, y + 37), value, font=f(18), fill=INK)


def button(d, x, y, text, primary=True, w=230):
    d.rounded_rectangle([x, y, x + w, y + 54], 8, fill=ACCENT if primary else "white", outline=ACCENT, width=2)
    d.text((x + 22, y + 15), text, font=f(18, True), fill="white" if primary else ACCENT)


def settle_screen() -> Image.Image:
    img, d = frame("Settle loan - LN-20481")
    field(d, 24, 150, "Customer", "Thandi Mokoena  (CUS-7731)")
    field(d, 24, 240, "Outstanding balance", "R 12 450.00")
    field(d, 24, 330, "Settlement method", "Instant EFT")
    field(d, 24, 420, "Settlement amount", "R 12 450.00")
    d.rectangle([600, 150, 1170, 490], outline=LINE, width=2)
    d.text((620, 166), "Settlement quote", font=f(20, True), fill=INK)
    for i, (k, v) in enumerate([("Capital", "R 11 900.00"), ("Interest to date", "R 480.00"),
                                ("Fees", "R 70.00"), ("Quote valid until", "Today 23:59")]):
        d.text((620, 214 + i * 42), k, font=f(18), fill=MUTED)
        d.text((960, 214 + i * 42), v, font=f(18), fill=INK)
    d.line([620, 390, 1150, 390], fill=LINE, width=2)
    d.text((620, 404), "Total to settle", font=f(20, True), fill=INK)
    d.text((960, 404), "R 12 450.00", font=f(20, True), fill=INK)
    button(d, 24, 540, "Settle now")
    button(d, 280, 540, "Cancel", primary=False, w=150)
    d.text((24, 620), "Only users with the Settlement Supervisor role see “Settle now”.", font=f(16), fill=MUTED)
    d.text((24, 648), "Hidden when feature flag INSTANT_SETTLEMENT is off.", font=f(16), fill=MUTED)
    return img


def failed_screen() -> Image.Image:
    img, d = frame("Loan LN-20481 - settlement status")
    d.rectangle([24, 150, 1170, 250], fill="#FEF2F2", outline=WARN, width=2)
    d.text((48, 168), "Settlement failed after 3 attempts", font=f(22, True), fill=WARN)
    d.text((48, 206), "Bank response: insufficient funds (code 51). Customer notified by SMS and e-mail.", font=f(17), fill=INK)
    d.text((24, 280), "Attempts", font=f(22, True), fill=INK)
    headers = ["#", "Time", "Method", "Result"]
    xs = [24, 110, 420, 700]
    for x, h in zip(xs, headers):
        d.text((x + 12, 328), h, font=f(17, True), fill=MUTED)
    rows = [("1", "09:00", "Instant EFT", "Failed - code 51"), ("2", "11:00", "Instant EFT", "Failed - code 51"),
            ("3", "13:00", "Instant EFT", "Failed - code 51")]
    for r, row in enumerate(rows):
        y = 366 + r * 48
        d.rectangle([24, y, 1170, y + 44], outline=LINE)
        for x, v in zip(xs, row):
            d.text((x + 12, y + 11), v, font=f(17), fill=INK)
    button(d, 24, 540, "Retry settlement", w=260)
    button(d, 310, 540, "Mark for manual follow-up", primary=False, w=330)
    d.text((24, 620), "“Retry settlement” is enabled only for the Settlement Supervisor role.", font=f(16), fill=MUTED)
    return img


def png(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    return buffer.getvalue()


def add_table(document, rows):
    table = document.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    for r, values in enumerate(rows):
        for c, value in enumerate(values):
            cell = table.cell(r, c)
            cell.text = value
            if r == 0:
                cell.paragraphs[0].runs[0].bold = True


def change_request(settle_png: bytes):
    d = docx.Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    d.add_heading("Contoso Lend – Change Request CR-2026-014: Loan Settlement Logic V1.0", 0)
    add_table(d, [["Field", "Value"], ["System", "Contoso Lend Loan Management System (LMS)"],
                  ["Change request", "CR-2026-014 Loan Settlement Logic V1.0"], ["Requested", "23 September 2026"],
                  ["Requested by", "Head of Collections"], ["Priority", "High"]])

    d.add_heading("1. Background", 1)
    d.add_paragraph("Customers increasingly want to settle loans early through the Operations team. Today settlement is "
                    "manual, takes up to five business days and conflicts with the nightly debit order run. This change "
                    "introduces instant settlement, automatic retries for failed settlements and refunds of overpayments.")
    d.add_heading("2. Scope", 1)
    for item in ["Restrict new loan applications while debit order processing runs.", "Instant settlement by EFT or card.",
                 "Retry failed settlements automatically.", "Refund overpayments after settlement.",
                 "Permissions and a feature flag for the new functions."]:
        d.add_paragraph(item, style="List Bullet")

    d.add_heading("3. Functional requirements", 1)
    d.add_heading("FR-01 Loan application restriction during debit order processing", 2)
    d.add_paragraph("While the debit order processing batch runs (normally 01:00–04:00), customers with an active V1 or V2 "
                    "loan product must not be able to submit a new loan application, and the Apply option must be hidden "
                    "for their other products. When the batch completes, the Preapproved Service sends a reactivation "
                    "message and limits become active again.")
    d.add_paragraph("Acceptance criteria", style="Heading 3")
    for ac in ["Given a customer with an active V2 loan and debit order processing in progress, when they submit a new "
               "application, then the submission is blocked and all product limits show as Expired.",
               "The same restriction applies to customers with a V1 (CMS Service V1) loan product.",
               "After processing completes and the reactivation message is received, the customer can apply again.",
               "A customer whose debit order was only partly recovered stays in arrears and remains blocked, with an "
               "arrears-related message."]:
        d.add_paragraph(ac, style="List Number")

    d.add_heading("FR-02 Instant settlement", 2)
    d.add_paragraph("An Operations user with the Settlement Supervisor role can settle a loan in full from the Settle loan "
                    "screen (see wireframe below). The system shows a settlement quote (capital, interest to date, fees) "
                    "valid until 23:59 on the day it is created. Supported methods are Instant EFT and debit card. "
                    "The settlement amount must equal the quote total; partial settlement is not allowed. On success the "
                    "loan status changes to Settled within 60 seconds and the customer receives an SMS and e-mail confirmation.")
    d.add_picture(io.BytesIO(settle_png), width=Cm(15))
    d.add_paragraph("Figure 1 – Settle loan screen (wireframe)").italic = True

    d.add_heading("FR-03 Failed settlement retries", 2)
    d.add_paragraph("If a settlement payment fails, the system retries automatically up to 3 times at 2-hour intervals. "
                    "Bank response codes 51 (insufficient funds) and 91 (issuer unavailable) are retryable; code 14 "
                    "(invalid account) is not retried. After the final failed attempt the loan status becomes "
                    "Settlement Failed, the customer is notified, and a Settlement Supervisor can retry manually or mark "
                    "the loan for manual follow-up.")

    d.add_heading("FR-04 Refunds and reversals", 2)
    d.add_paragraph("If the amount received is higher than the settlement quote, the overpayment is refunded to the source "
                    "account within 2 business days. Overpayments of R10.00 or less are not refunded; they are written off "
                    "to the sundry income account. A settlement reversed by the bank within 40 days reopens the loan with "
                    "its previous balance and status, and the instalment schedule is restored.")
    add_table(d, [["Rule", "Condition", "Outcome"],
                  ["BR-04.1", "Overpayment > R10.00", "Refund to source account within 2 business days"],
                  ["BR-04.2", "Overpayment ≤ R10.00", "Write off to sundry income"],
                  ["BR-04.3", "Bank reversal ≤ 40 days after settlement", "Reopen loan, restore balance and schedule"],
                  ["BR-04.4", "Bank reversal > 40 days after settlement", "Route to Collections for manual review"]])

    d.add_heading("FR-05 Permissions and feature flag", 2)
    d.add_paragraph("Only the Settlement Supervisor role can see and use Settle now and Retry settlement. Every settlement, "
                    "retry, refund and reversal is written to the audit log with user, time, loan and amount. All new "
                    "functions are behind the feature flag INSTANT_SETTLEMENT; when it is off the screens behave as today.")

    d.add_heading("4. Out of scope", 1)
    d.add_paragraph("Customer self-service settlement in the mobile app; changes to the debit order batch schedule.")
    d.save(OUT / "CR-2026-014 Loan Settlement Logic V1.0.docx")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    settle, failed = settle_screen(), failed_screen()
    settle.save(OUT / "wireframe-settle-loan.png")
    failed.save(OUT / "wireframe-settlement-failed.png")
    change_request(png(settle))
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
