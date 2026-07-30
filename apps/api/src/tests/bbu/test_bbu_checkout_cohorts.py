"""Checkout cohort availability copy stays aligned with real capacity."""

import pytest

from src.bbu_cohorts.models import BBUCohort
from src.bbu_payments.branding import _cohort_dates, _shell
from src.bbu_payments.models import BBUProduct
from src.bbu_payments.router import _product_upcoming_cohorts


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


def test_pinned_cohort_copy_promises_the_exact_cohort():
    html = _cohort_dates([{
        "name": "October 2026 Doula Mentorship",
        "start_date": "2026-10-06",
        "end_date": "2026-11-17",
        "seats_left": 20,
        "full": False,
    }], pinned=True)

    assert "You'll be enrolled in this live cohort." in html
    assert "next live cohort" not in html


@pytest.mark.asyncio
async def test_pinned_offer_lists_only_its_selected_cohort(db, org):
    september = BBUCohort(
        org_id=org.id,
        name="September 2026 Doula Mentorship",
        program="doula",
        start_date="2026-09-08",
        end_date="2099-10-20",
        capacity=20,
        status="open",
    )
    october = BBUCohort(
        org_id=org.id,
        name="October 2026 Doula Mentorship",
        program="doula",
        start_date="2026-10-06",
        end_date="2099-11-17",
        capacity=20,
        status="open",
    )
    db.add(september)
    db.add(october)
    await db.commit()
    await db.refresh(september)
    await db.refresh(october)

    product = BBUProduct(
        org_id=org.id,
        name="October 2026 Doula Mentorship",
        cohort_program="",
        cohort_id=october.id,
    )

    cohorts = await _product_upcoming_cohorts(db, product)

    assert [cohort["id"] for cohort in cohorts] == [october.id]
    assert cohorts[0]["name"] == "October 2026 Doula Mentorship"
