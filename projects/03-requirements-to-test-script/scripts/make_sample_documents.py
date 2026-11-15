"""Creates the sample inputs in sample-input/: a Functional Specification (.docx, with an embedded
wireframe) and two wireframe images.

The company and app are fictional (Contoso Pay). The FSD has 4 requirements taken from the user
stories of project 02 (../02-jira-test-case-generator/sample-stories/stories.json: S01, S04, S06,
S08), kept small so a live run costs under $1 of Claude usage. It mixes formats the way a real FSD
does: FR-01 lists its acceptance criteria, FR-02 and FR-04 are prose only (so the workflow has to
write the criteria), and FR-03 is a business-rule table.
Run inside the service container, which already has python-docx and Pillow:

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
DOC_NAME = "FSD-2026-031 Contoso Pay Wallet Enhancements V1.0.docx"
INK, LINE, MUTED, ACCENT = "#1F2937", "#9CA3AF", "#6B7280", "#1D4ED8"


def f(size, bold=False):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def frame(title: str):
    img = Image.new("RGB", (1200, 800), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 1199, 64], fill="#F3F4F6", outline=LINE)
    d.text((24, 18), "Contoso Pay", font=f(22, True), fill=INK)
    d.text((960, 22), "Alex Rivera", font=f(18), fill=MUTED)
    d.text((24, 92), title, font=f(30, True), fill=INK)
    return img, d


def field(d, x, y, label, value, w=520):
    d.text((x, y), label, font=f(16), fill=MUTED)
    d.rectangle([x, y + 26, x + w, y + 70], outline=LINE, width=2)
    d.text((x + 12, y + 37), value, font=f(18), fill=INK)


def button(d, x, y, text, primary=True, w=230):
    d.rounded_rectangle([x, y, x + w, y + 54], 8, fill=ACCENT if primary else "white", outline=ACCENT, width=2)
    d.text((x + 22, y + 15), text, font=f(18, True), fill="white" if primary else ACCENT)


def send_money_screen() -> Image.Image:
    img, d = frame("Send money - Confirm")
    field(d, 24, 150, "To", "Jordan Lee  (@jordanlee)")
    field(d, 24, 240, "Amount", "$250.00")
    field(d, 24, 330, "From", "Contoso Pay balance  ($1,180.40 available)")
    field(d, 24, 420, "Note (optional)", "Concert tickets")
    d.rectangle([600, 150, 1170, 450], outline=LINE, width=2)
    d.text((620, 166), "Summary", font=f(20, True), fill=INK)
    for i, (k, v) in enumerate([("Amount", "$250.00"), ("Fee", "$0.00"),
                                ("Sent today", "$0.00 of $2,500.00"), ("Arrives", "Instantly")]):
        d.text((620, 214 + i * 42), k, font=f(18), fill=MUTED)
        d.text((900, 214 + i * 42), v, font=f(18), fill=INK)
    d.line([620, 386, 1150, 386], fill=LINE, width=2)
    d.text((620, 400), "Jordan receives", font=f(20, True), fill=INK)
    d.text((900, 400), "$250.00", font=f(20, True), fill=INK)
    button(d, 24, 540, "Send $250.00")
    button(d, 280, 540, "Edit", primary=False, w=150)
    d.text((24, 620), "Shown after the customer taps Continue. Nothing is sent until Send is tapped.", font=f(16), fill=MUTED)
    d.text((24, 648), "Unverified customers do not see this screen; they are asked to verify their identity first.",
           font=f(16), fill=MUTED)
    return img


def freeze_card_screen() -> Image.Image:
    img, d = frame("Card ending 4821")
    d.rounded_rectangle([24, 150, 520, 430], 18, fill="#1E3A8A")
    d.text((52, 178), "Contoso Pay debit", font=f(20, True), fill="white")
    d.text((52, 330), "**** **** **** 4821", font=f(24, True), fill="white")
    d.text((52, 380), "ALEX RIVERA      12/29", font=f(18), fill="#BFDBFE")
    d.text((24, 456), "Status: Active", font=f(20, True), fill=INK)
    d.rectangle([600, 150, 1170, 520], fill="#F9FAFB", outline=LINE, width=2)
    d.text((624, 170), "Freeze this card?", font=f(22, True), fill=INK)
    for i, line in enumerate(["Card payments and ATM withdrawals will be",
                              "declined while the card is frozen.",
                              "Recurring payments continue unless you",
                              "block them too."]):
        d.text((624, 216 + i * 30), line, font=f(17), fill=INK)
    d.rectangle([624, 350, 648, 374], outline=INK, width=2)
    d.text((662, 350), "Also block recurring payments", font=f(17), fill=INK)
    button(d, 624, 420, "Freeze card", w=200)
    button(d, 846, 420, "Cancel", primary=False, w=150)
    d.text((24, 620), "Unfreeze asks for the customer's PIN or biometrics.", font=f(16), fill=MUTED)
    d.text((24, 648), "Card status in the app updates within 5 seconds of the change.", font=f(16), fill=MUTED)
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


def criteria(document, items):
    document.add_paragraph("Acceptance criteria", style="Heading 3")
    for item in items:
        document.add_paragraph(item, style="List Number")


def requirement(document, ref, title, story, text=None):
    document.add_heading(f"{ref} {title}", 2)
    p = document.add_paragraph()
    p.add_run("User story: ").bold = True
    p.add_run(story).italic = True
    if text:
        document.add_paragraph(text)


def specification(send_png: bytes):
    d = docx.Document()
    d.styles["Normal"].font.name = "Calibri"
    d.styles["Normal"].font.size = Pt(11)
    d.add_heading("Contoso Pay – Functional Specification FSD-2026-031: Wallet Enhancements V1.0", 0)
    add_table(d, [["Field", "Value"], ["System", "Contoso Pay Mobile App"],
                  ["Document", "FSD-2026-031 Wallet Enhancements V1.0"], ["Requested", "2 November 2026"],
                  ["Requested by", "Head of Digital Channels"], ["Priority", "High"]])

    d.add_heading("1. Background", 1)
    d.add_paragraph("Contoso Pay is a fictional mobile wallet. Account-takeover attempts rose last quarter, and customers ask "
                    "for faster ways to pay friends and to withdraw money. This release locks accounts after repeated "
                    "failed sign-ins, adds instant transfers and an instant withdrawal option, and lets customers freeze "
                    "a misplaced card from the app.")

    d.add_heading("2. Scope", 1)
    for item in ["Account lockout after failed sign-in attempts.", "Send money to another Contoso Pay customer.",
                 "Instant withdrawal to a saved bank account, with a fee.", "Freeze and unfreeze a card from the app."]:
        d.add_paragraph(item, style="List Bullet")

    d.add_heading("3. Functional requirements", 1)

    requirement(d, "FR-01", "Account lockout after failed sign-in attempts",
                "As a Contoso Pay customer, I want my account to be locked after several failed sign-in attempts so "
                "that nobody can guess my password.")
    criteria(d, ["After 5 consecutive failed sign-in attempts, the account is locked for 15 minutes.",
                 "While locked, sign-in is refused even with the correct password, and the message says when the "
                 "customer can try again.",
                 "A successful sign-in resets the failed-attempt counter."])

    requirement(d, "FR-02", "Send money to a contact",
                "As a verified customer, I want to send money to another Contoso Pay user so that I can pay friends "
                "instantly.",
                "A verified customer can send money to another Contoso Pay customer from their balance. Before sending, "
                "the customer sees a confirmation screen with the recipient's name and the amount (see Figure 1). The "
                "minimum transfer is $1.00 and a verified customer can send up to $2,500.00 per day in total. If the "
                "balance is lower than the amount, the transfer is blocked with the message \"Insufficient balance\".")
    d.add_picture(io.BytesIO(send_png), width=Cm(15))
    d.add_paragraph("Figure 1 – Send money confirmation screen (wireframe)").italic = True

    requirement(d, "FR-03", "Instant withdrawal fee",
                "As a customer, I want to see the instant withdrawal fee before I confirm so that there are no "
                "surprises.",
                "Customers can withdraw their balance to a saved bank account instantly for a fee. The fee and the "
                "amount the customer will receive are shown before they confirm.")
    add_table(d, [["Rule", "Condition", "Outcome"],
                  ["BR-03.1", "Instant withdrawal", "Fee is 1.5% of the amount"],
                  ["BR-03.2", "1.5% of the amount is below $0.25", "Fee is $0.25 (minimum)"],
                  ["BR-03.3", "1.5% of the amount is above $15.00", "Fee is $15.00 (maximum)"],
                  ["BR-03.4", "Any fee or amount", "Rounded to the nearest cent"]])

    requirement(d, "FR-04", "Freeze and unfreeze a card",
                "As a customer who misplaced my card, I want to freeze it from the app so that nobody can use it while "
                "I look for it.",
                "A customer can freeze their card from the card screen with one tap and a confirmation (see the "
                "separate card wireframe). While frozen, card payments and ATM withdrawals are declined. Recurring "
                "payments already set up continue unless the customer chooses to block them too. Unfreezing requires "
                "the customer's PIN or biometrics.")

    d.add_heading("4. Out of scope", 1)
    d.add_paragraph("Transfers to people outside Contoso Pay; standard (free) withdrawals, which are unchanged; changes "
                    "to card limits; the web banking channel.")
    d.save(OUT / DOC_NAME)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    send, freeze = send_money_screen(), freeze_card_screen()
    send.save(OUT / "wireframe-send-money.png")
    freeze.save(OUT / "wireframe-freeze-card.png")
    specification(png(send))
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
