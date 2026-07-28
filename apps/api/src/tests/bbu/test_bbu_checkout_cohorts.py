"""Checkout cohort availability copy stays aligned with real capacity."""

from src.bbu_payments.branding import _cohort_dates, _shell


def test_bbu_public_pages_include_the_existing_clarity_project():
    html = _shell("Checkout", "<main>content</main>")

    assert "https://www.clarity.ms/tag/" in html
    assert "xn0xh5wcb2" in html


def test_unlimited_cohort_has_no_numeric_inventory_copy():
    html = _cohort_dates([{
        "name": "September 2026 Agency Owner Mentorship",
        "start_date": "2026-09-08",
        "end_date": "2026-10-20",
        "seats_left": None,
        "full": False,
    }])

    assert "Open enrollment" in html
    assert "You'll be enrolled in the next live cohort." in html
    assert "seats left" not in html
    assert "open seat" not in html


def test_limited_cohort_keeps_its_actual_seat_count():
    html = _cohort_dates([{
        "name": "A limited cohort",
        "start_date": "2026-09-08",
        "end_date": "",
        "seats_left": 3,
        "full": False,
    }])

    assert "3 seats left" in html
