"""Machine-readable zone (MRZ) of a passport: parsing and check digits, as defined by ICAO Doc 9303 (TD3 format).

A passport's MRZ is two lines of 44 characters. Line 2 carries check digits for the document number,
date of birth, expiry date and personal number, plus a composite check over all of them. Recomputing
them catches a misread character or an edited field with arithmetic, not with AI judgement.
"""
from __future__ import annotations

import datetime as dt
import re

WEIGHTS = (7, 3, 1)


def char_value(c: str) -> int:
    if c.isdigit():
        return int(c)
    if "A" <= c <= "Z":
        return ord(c) - 55          # A = 10 … Z = 35
    if c == "<":
        return 0
    raise ValueError(f"invalid MRZ character {c!r}")


def check_digit(field: str) -> str:
    return str(sum(char_value(c) * WEIGHTS[i % 3] for i, c in enumerate(field)) % 10)


def clean(line: str) -> str:
    """Upper-case, no spaces, and the look-alike characters OCR and models often produce."""
    return re.sub(r"\s", "", str(line or "")).upper().replace("«", "<").replace("‹", "<")


def mrz_date(yymmdd: str, kind: str) -> str | None:
    """YYMMDD to ISO. Birth dates are in the past; expiry dates may be up to 50 years ahead."""
    if not re.fullmatch(r"\d{6}", yymmdd):
        return None
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    this_year = dt.date.today().year % 100
    if kind == "birth":
        century = 1900 if yy > this_year else 2000
    else:
        century = 2000 if yy <= this_year + 50 else 1900
    try:
        return dt.date(century + yy, mm, dd).isoformat()
    except ValueError:
        return None


def parse_td3(line1: str, line2: str) -> dict:
    """Parses a passport MRZ and checks every check digit. Returns fields, checks and a list of problems."""
    l1, l2 = clean(line1), clean(line2)
    problems = []
    if len(l1) != 44 or len(l2) != 44:
        return {"valid": False, "problems": [f"MRZ lines must be 44 characters (got {len(l1)} and {len(l2)})"], "fields": {}, "checks": {}}
    if not l1.startswith("P"):
        problems.append("line 1 does not start with P (not a passport MRZ)")
    try:
        names = l1[5:].split("<<", 1)
        surname = names[0].replace("<", " ").strip()
        given = names[1].replace("<", " ").strip() if len(names) > 1 else ""
        fields = {
            "issuing_country": l1[2:5].replace("<", ""),
            "surname": surname,
            "given_names": " ".join(given.split()),
            "document_number": l2[0:9].replace("<", ""),
            "nationality": l2[10:13].replace("<", ""),
            "date_of_birth": mrz_date(l2[13:19], "birth"),
            "sex": l2[20],
            "expiry_date": mrz_date(l2[21:27], "expiry"),
        }
        checks = {
            "document_number": check_digit(l2[0:9]) == l2[9],
            "date_of_birth": check_digit(l2[13:19]) == l2[19],
            "expiry_date": check_digit(l2[21:27]) == l2[27],
            "personal_number": check_digit(l2[28:42]) == l2[42] or (l2[28:42] == "<" * 14 and l2[42] in "<0"),
            "composite": check_digit(l2[0:10] + l2[13:20] + l2[21:43]) == l2[43],
        }
    except ValueError as e:
        return {"valid": False, "problems": [str(e)], "fields": {}, "checks": {}}
    problems += [f"check digit for {name} does not match" for name, ok in checks.items() if not ok]
    if fields["date_of_birth"] is None:
        problems.append("date of birth in the MRZ is not a real date")
    if fields["expiry_date"] is None:
        problems.append("expiry date in the MRZ is not a real date")
    return {"valid": not problems, "problems": problems, "fields": fields, "checks": checks}


def build_td3(surname: str, given_names: str, number: str, country: str, nationality: str,
              dob: dt.date, sex: str, expiry: dt.date) -> tuple[str, str]:
    """Builds a valid passport MRZ (used by the specimen generator and the tests)."""
    name = (surname.upper().replace(" ", "<") + "<<" + given_names.upper().replace(" ", "<"))
    l1 = f"P<{country}{name}".ljust(44, "<")[:44]
    num = number.upper().ljust(9, "<")[:9]
    d, e = dob.strftime("%y%m%d"), expiry.strftime("%y%m%d")
    personal = "<" * 14
    body = f"{num}{check_digit(num)}{nationality}{d}{check_digit(d)}{sex}{e}{check_digit(e)}{personal}{check_digit(personal)}"
    composite = check_digit(body[0:10] + body[13:20] + body[21:43])
    return l1, body + composite
