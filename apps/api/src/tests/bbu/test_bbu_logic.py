"""Pure-logic regression tests for the clean-room BBU modules.

Covers the money/credential logic that isn't exercised by the happy-path
integration flows: coupon discount math + validation, the credential state
machine (lapse/expire, date math incl. Feb-29), and the reminder-window
selection. No DB / app fixtures — just the pure functions on in-memory models,
so this runs fast and stays green regardless of environment.
"""
import datetime as dt

from src.bbu_credentials.models import BBUCredential
from src.bbu_credentials import service as S
from src.bbu_payments.models import BBUCoupon
from src.bbu_payments import coupons as C
from src.bbu_payments.helpers import merge_course_uuids

UTC = dt.timezone.utc


def _iso(days_from_now: int) -> str:
    return (dt.datetime.now(UTC) + dt.timedelta(days=days_from_now)).isoformat()


# --------------------------------------------------------------------------- #
# Coupon discount math
# --------------------------------------------------------------------------- #
def test_percent_discount():
    assert C.compute_discount_cents(BBUCoupon(kind="percent", percent_off=20), 14900) == 2980


def test_amount_discount_caps_at_subtotal():
    c = BBUCoupon(kind="amount", amount_off_cents=2500)
    assert C.compute_discount_cents(c, 1500) == 1500      # $25 off $15 -> $15
    assert C.compute_discount_cents(c, 82500) == 2500     # $25 off $825 -> $25


# --------------------------------------------------------------------------- #
# Coupon validation
# --------------------------------------------------------------------------- #
def test_coupon_rejected_when_inactive():
    assert C.validate_for(BBUCoupon(kind="percent", percent_off=10, active=False), 1, 5000)[0] is False


def test_coupon_rejected_when_expired():
    c = BBUCoupon(kind="percent", percent_off=10, active=True, expires_at=_iso(-1))
    assert C.validate_for(c, 1, 5000)[0] is False


def test_coupon_min_amount():
    c = BBUCoupon(kind="amount", amount_off_cents=1000, active=True, min_amount_cents=10000)
    assert C.validate_for(c, 1, 5000)[0] is False    # below min
    assert C.validate_for(c, 1, 15000)[0] is True     # above min


def test_coupon_max_redemptions():
    c = BBUCoupon(kind="percent", percent_off=10, active=True, max_redemptions=5, times_redeemed=5)
    assert C.validate_for(c, 1, 5000)[0] is False


def test_coupon_applies_to():
    c = BBUCoupon(kind="percent", percent_off=10, active=True, applies_to="3,4")
    assert C.validate_for(c, 9, 5000)[0] is False    # not in list
    assert C.validate_for(c, 3, 5000)[0] is True      # in list


# --------------------------------------------------------------------------- #
# Credential date math + state machine
# --------------------------------------------------------------------------- #
def test_add_years_feb29():
    d = dt.datetime(2024, 2, 29, tzinfo=UTC)
    assert S._add_years(d, 3) == dt.datetime(2027, 2, 28, tzinfo=UTC)


def test_effective_status_full():
    assert S.compute_effective_status(BBUCredential(status="full", full_expires_at=_iso(30))) == "full"
    assert S.compute_effective_status(BBUCredential(status="full", full_expires_at=_iso(-1))) == "expired"


def test_effective_status_provisional():
    assert S.compute_effective_status(BBUCredential(status="provisional", provisional_expires_at=_iso(30))) == "provisional"
    assert S.compute_effective_status(BBUCredential(status="provisional", provisional_expires_at=_iso(-1))) == "lapsed"


# --------------------------------------------------------------------------- #
# Reminder window selection (mirror of service.run_reminders)
# --------------------------------------------------------------------------- #
def _window(days: int):
    marks = [m for m in S.REMINDER_DAYS if days <= m]
    return min(marks) if marks else None


def test_reminder_windows():
    assert _window(85) == 90
    assert _window(50) == 60
    assert _window(25) == 30
    assert _window(200) is None     # too early — no reminder yet


# --------------------------------------------------------------------------- #
# Order-bump course merge (access-control path)
# --------------------------------------------------------------------------- #
def test_merge_course_uuids_dedup_and_order():
    # primary grants A,B; a bump grants B,C -> A,B,C once, order preserved
    assert merge_course_uuids(["course_A,course_B", "course_B,course_C"]) == "course_A,course_B,course_C"


def test_merge_course_uuids_handles_empties():
    assert merge_course_uuids(["", "course_A", ""]) == "course_A"
    assert merge_course_uuids([]) == ""
    # whitespace + trailing commas don't produce blank entries
    assert merge_course_uuids([" course_A , course_B ,"]) == "course_A,course_B"
