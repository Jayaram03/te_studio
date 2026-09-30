import json
from datetime import date

from app.normalize import (norm_currency, norm_meal_plan, norm_occupancy, normalize, parse_date, parse_range,
                           parse_weekdays)
from conftest import FIXTURES

TODAY = date(2026, 9, 30)


def test_dates_day_first_and_iso():
    assert parse_date("01/10/2026")[0] == date(2026, 10, 1)        # Indian day-first
    assert parse_date("2026-04-01")[0] == date(2026, 4, 1)         # ISO not misread as 4 Jan
    assert parse_date("31.12.2026")[0] == date(2026, 12, 31)
    assert parse_date("20 Dec 26")[0] == date(2026, 12, 20)
    assert parse_date("1st April 2027")[0] == date(2027, 4, 1)
    assert parse_date("Dec'26")[0].year == 2026
    assert parse_date("garbage") == (None, False)


def test_year_less_ranges_roll_over():
    assert parse_range("20 Dec", "5 Jan", ref=date(2026, 10, 1)) == (date(2026, 12, 20), date(2027, 1, 5))
    # "10 Jan" in a sheet valid from October means next January
    assert parse_range("10 Jan", "31 Mar", ref=date(2026, 10, 1)) == (date(2027, 1, 10), date(2027, 3, 31))


def test_vocabularies():
    assert norm_meal_plan("CPAI") == "CP"
    assert norm_meal_plan("MAPAI") == "MAP"
    assert norm_meal_plan("Breakfast & Dinner") == "MAP"
    assert norm_meal_plan("MAP with breakfast and dinner") == "MAP"
    assert norm_meal_plan("incl. breakfast") == "CP"
    assert norm_meal_plan("Room only") == "EP"
    assert norm_meal_plan("xyz") is None
    assert norm_occupancy("Dbl") == "double"
    assert norm_occupancy("CWB (6-12)") == "child_with_bed"
    assert norm_occupancy("Child without bed (6-11)") == "child_without_bed"
    assert norm_occupancy("Extra bed") == "extra_adult"
    assert norm_occupancy("Adult on extra bed") == "extra_adult"
    assert norm_occupancy("per person twin sharing") == "double"
    assert norm_occupancy("Single supplement") == "single_supplement"
    assert norm_occupancy("SGL/DBL") == "double"
    assert norm_currency("Rs") == "INR" and norm_currency("₹") == "INR" and norm_currency("thb") == "THB"
    assert norm_currency("US$") == "USD"


def test_weekdays():
    assert parse_weekdays("Fri-Sat") == ("fri,sat", True)
    assert parse_weekdays("Weekend (Fri-Sat)") == ("fri,sat", True)
    assert parse_weekdays("Sun to Thu") == ("mon,tue,wed,thu,sun", True)
    assert parse_weekdays("weekdays") == ("mon,tue,wed,thu,sun", True)
    assert parse_weekdays(None) == (None, True)


def _misty():
    return json.loads((FIXTURES / "misty_hills_munnar_2026-27.json").read_text())


def test_missing_validity_is_an_error_until_overridden():
    x = _misty()
    x["validity"] = None
    x["seasons"] = []
    for r in x["hotels"][0]["rates"]:
        r["season_key"] = None
    n = normalize(x, today=TODAY)
    assert n["stats"]["errors"] > 0
    assert any("No validity" in i["message"] for i in n["issues"])
    n = normalize(x, {"valid_from": "2026-10-01", "valid_to": "2027-03-31"}, today=TODAY)
    # without seasons, regular and peak rates now clash on the same dates -> conflicts are flagged
    assert any("Two different rates" in i["message"] for i in n["issues"])


def test_unknown_season_and_bad_meal_plan_are_errors():
    x = _misty()
    x["hotels"][0]["rates"][0]["season_key"] = "festive"
    x["hotels"][0]["rates"][1]["meal_plan"] = "Chef special"
    n = normalize(x, today=TODAY)
    msgs = [i["message"] for i in n["issues"] if i["level"] == "error"]
    assert any("unknown season 'festive'" in m for m in msgs)
    assert any("Chef special" in m for m in msgs)


def test_expired_rates_warn():
    n = normalize(_misty(), today=date(2027, 6, 1))
    assert any("expired" in i["message"] for i in n["issues"])


def test_rate_type_and_tax_unknown_are_summarised():
    x = _misty()
    x["rate_type"] = "unknown"
    x["taxes"] = "unknown"
    for r in x["hotels"][0]["rates"]:
        r["rate_type"] = "unknown"
        r["taxes"] = "unknown"
    n = normalize(x, today=TODAY)
    assert any("not marked as net" in i["message"] for i in n["issues"])
    n = normalize(x, {"rate_type": "net", "taxes": "excluded"}, today=TODAY)
    r = n["hotels"][0]["rates"][0]
    assert r["is_net"] is True and r["taxes_included"] is False
