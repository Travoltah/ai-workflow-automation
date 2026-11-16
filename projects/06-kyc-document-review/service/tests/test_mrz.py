import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mrz import build_td3, check_digit, parse_td3  # noqa: E402

# The specimen passport printed in ICAO Doc 9303 Part 4 (Utopia, Anna Maria Eriksson)
ICAO_L1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
ICAO_L2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"


def test_check_digit_examples():
    assert check_digit("L898902C3") == "6"
    assert check_digit("740812") == "2"
    assert check_digit("120415") == "9"


def test_icao_specimen_is_valid():
    m = parse_td3(ICAO_L1, ICAO_L2)
    assert m["valid"], m["problems"]
    assert m["fields"]["surname"] == "ERIKSSON" and m["fields"]["given_names"] == "ANNA MARIA"
    assert m["fields"]["document_number"] == "L898902C3"
    assert m["fields"]["date_of_birth"] == "1974-08-12"


def test_edited_date_of_birth_is_caught():
    edited = ICAO_L2[:13] + "7508122" + ICAO_L2[20:]   # year changed, check digit left alone
    m = parse_td3(ICAO_L1, edited)
    assert not m["valid"]
    assert any("date_of_birth" in p for p in m["problems"]) and any("composite" in p for p in m["problems"])


def test_misread_character_is_caught():
    m = parse_td3(ICAO_L1, ICAO_L2.replace("L898902C3", "L898902C8"))
    assert not m["valid"]


def test_wrong_length_is_reported():
    assert not parse_td3(ICAO_L1[:40], ICAO_L2)["valid"]


def test_build_round_trip():
    l1, l2 = build_td3("Mapfumo", "Tariro Grace", "UA4821937", "UTO", "UTO", dt.date(1992, 3, 15), "F", dt.date(2030, 1, 31))
    m = parse_td3(l1, l2)
    assert m["valid"], m["problems"]
    assert m["fields"]["given_names"] == "TARIRO GRACE" and m["fields"]["expiry_date"] == "2030-01-31"


def test_spaces_and_lowercase_from_a_reader_are_tolerated():
    m = parse_td3(ICAO_L1.lower(), ICAO_L2[:22] + " " + ICAO_L2[22:])
    assert m["valid"]
