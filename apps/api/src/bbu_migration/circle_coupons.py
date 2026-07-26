"""Import Circle's coupon catalogue + redemption history into BBU.

Circle is being shut down. Two things have to survive it:

  1. the **codes themselves**, so a code Anna handed a partner still works here;
  2. the **redemption history** — who redeemed which code, for what, when. This is
     the system of record for funder/grant reporting (the BCBS grant needs a list
     of people served under each funder code). Circle exposes none of it over its
     public API; it only comes out of an admin browser session at /internal_api/.

Coupons land in the live `bbu_coupon` table so they work going forward.
Redemptions land in `bbu_circle_redemption`, a read-only archive — importing a
redemption never grants access, issues a certificate, or touches Stripe.

SAFETY — coupon scope. In Circle a coupon is scoped to specific paywalls. Here it
is scoped to product ids. Names do not line up one-for-one ("Breastfeeding
Virtual" vs "Breastfeeding"), so scope is resolved by normalised match. A 100%-off
code whose scope we cannot fully resolve is imported **inactive**: the failure mode
of guessing wrong is a code that makes every course free. Nothing is auto-activated
that was not already unambiguous — `/verify` lists what needs a human decision.

No Stripe objects are created at import time. `ensure_stripe_objects` runs lazily
on first real use, so this stays safe while the account is still on test keys.

Mounted at /api/v1/bbu/migrate.
  POST /circle-coupons          import coupons + redemptions (dry_run supported)
  GET  /circle-coupons/verify   counts, scope decisions, unmapped names
  GET  /circle-coupons/export   the archive back out as CSV
"""
import csv
import io
import json
import os
import unicodedata
from datetime import datetime
from difflib import get_close_matches

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.bbu_payments.models import BBUProduct, BBUCoupon, BBUCircleRedemption

router = APIRouter()

ORG = 1
ADMIN_KEY = os.environ.get("BBU_MIGRATION_KEY") or os.environ.get("BBU_AFFILIATE_ADMIN_KEY", "")

# Posted straight from the Circle admin tab, so responses carry permissive CORS.
# Safe: every route here is admin-key gated, and `*` forbids cookie credentials.
CORS = {"Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "content-type",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS"}

# Circle paywall names that normalisation alone will not land on the right product.
ALIASES = {
    # Circle carries a typo — "for You" rather than "for Your"
    "preparing for you hospital birth": "Preparing for Your Hospital Birth",
    "preparing for you hospital birth in chicago": "Preparing for Your Hospital Birth",
    "preparing for your hospital birth in chicago": "Preparing for Your Hospital Birth",
    "all access class pass": "All Access Class Pass",
    # both trainings in one — fuzzy match lands on the postpartum course alone
    "certified birth postpartum doula training": "Birth + Postpartum Doula Training Bundle",
    "certified birth and postpartum doula training": "Birth + Postpartum Doula Training Bundle",
    "pase virtual con acceso total a clases": "Pase Virtual con Acceso Total a Clases",
    "comfort measures": "Comfort Measures",
    "breastfeeding infant feeding for perinatal professionals":
        "Breastfeeding for Perinatal Professionals",
    "comfort measures for perinatal professionals": "Comfort Measures for Perinatal Professionals",
    "newborn care for perinatal professionals": "Newborn Care for Perinatal Professionals",
}

# Suffixes Circle appends for delivery format; they are not part of the product name.
NOISE = (" virtual", " in person", " online", " (virtual)", " recorded", " live")


def _check(request: Request, body: dict | None = None):
    if not ADMIN_KEY:
        raise HTTPException(503, "Migration key not configured")
    key = request.query_params.get("key") or request.headers.get("x-bbu-admin-key") \
        or (body or {}).get("key") or ""
    if key != ADMIN_KEY:
        raise HTTPException(403, "Forbidden")


def _norm(s: str) -> str:
    """Fold a paywall/product name to a comparable key."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    for n in NOISE:
        if s.endswith(n):
            s = s[: -len(n)]
    s = "".join(c if c.isalnum() or c.isspace() else " " for c in s)
    return " ".join(s.split())


def _mentorship_target(key: str) -> str | None:
    """Circle dates its mentorship paywalls ("August 2026 Doula Mentorship");
    BBU sells one evergreen product per programme."""
    if "mentorship" not in key:
        return None
    return "Doula Agency Owner Mentorship" if "agency" in key else "Doula Mentorship"


def _resolve(name: str, by_key: dict, keys: list) -> int | None:
    """Circle paywall name -> BBUProduct id, or None when we cannot be sure."""
    key = _norm(name)
    if not key:
        return None
    if key in by_key:
        return by_key[key]
    alias = ALIASES.get(key)
    if alias and _norm(alias) in by_key:
        return by_key[_norm(alias)]
    ment = _mentorship_target(key)
    if ment and _norm(ment) in by_key:
        return by_key[_norm(ment)]
    close = get_close_matches(key, keys, n=1, cutoff=0.88)
    return by_key[close[0]] if close else None


async def _product_index(db: AsyncSession):
    rows = (await db.execute(select(BBUProduct).where(BBUProduct.org_id == ORG))).scalars().all()
    by_key = {_norm(p.name): p.id for p in rows if p.id}
    return by_key, list(by_key.keys())


def _split_paywalls(s: str) -> list:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


@router.options("/circle-coupons")
async def circle_coupons_preflight():
    return PlainTextResponse("", headers=CORS)


@router.post("/circle-coupons")
async def import_circle_coupons(request: Request,
                                db_session: AsyncSession = Depends(get_db_session)):
    """Body: {key, coupons: [...Circle coupon defs...], redemptions: [...], dry_run}

    Accepts text/plain as well as application/json so the Circle admin tab can POST
    without tripping a CORS preflight.
    """
    raw = await request.body()
    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except Exception:
        raise HTTPException(400, "Body must be JSON")
    _check(request, body)

    dry = bool(body.get("dry_run"))
    coupons = body.get("coupons") or []
    redemptions = body.get("redemptions") or []
    now = str(datetime.now())

    by_key, keys = await _product_index(db_session)

    # ---------------------------------------------------------------- coupons
    existing = {c.code.upper(): c for c in (await db_session.execute(
        select(BBUCoupon).where(BBUCoupon.org_id == ORG))).scalars().all()}

    created, updated, held, unmapped_names = 0, 0, [], set()
    coupon_report = []
    for c in coupons:
        code = (c.get("code") or "").strip()
        if not code:
            continue
        is_pct = "percent" in (c.get("type") or "").lower()
        try:
            amt = float(c.get("amount") or 0)
        except Exception:
            amt = 0.0

        all_pw = bool(c.get("all_paywalls"))
        names = _split_paywalls(c.get("paywalls_name"))
        if all_pw or not names:
            applies_to, fully_scoped = "all", True
        else:
            ids = []
            for n in names:
                pid = _resolve(n, by_key, keys)
                if pid:
                    ids.append(pid)
                else:
                    unmapped_names.add(n)
            fully_scoped = len(ids) == len(names) and bool(ids)
            applies_to = ",".join(str(i) for i in sorted(set(ids))) if ids else "all"

        circle_active = (c.get("status") or "").lower() == "active"
        # a 100%-off code we cannot scope exactly would make everything free
        risky = is_pct and amt >= 100 and not fully_scoped
        active = circle_active and fully_scoped and not risky
        if circle_active and not active:
            held.append({"code": code, "reason": "unresolved scope" if not fully_scoped else "risky",
                         "circle_paywalls": names})

        row = existing.get(code.upper())
        if row is None:
            row = BBUCoupon(org_id=ORG, code=code)
            created += 1
        else:
            updated += 1
        row.kind = "percent" if is_pct else "amount"
        row.percent_off = int(amt) if is_pct else 0
        row.amount_off_cents = 0 if is_pct else int(round(amt * 100))
        row.applies_to = applies_to
        row.max_redemptions = int(c.get("max_redemptions") or 0)
        row.times_redeemed = int(c.get("redemptions_count") or 0)
        row.expires_at = (c.get("ends_at") or "") or ""
        row.active = active
        coupon_report.append({"code": code, "applies_to": applies_to, "active": active})
        if not dry:
            db_session.add(row)

    # ------------------------------------------------------------ redemptions
    seen = set()
    for r in (await db_session.execute(select(BBUCircleRedemption).where(
            BBUCircleRedemption.org_id == ORG))).scalars().all():
        seen.add((r.code, r.member_email, r.paywall_name, r.redeemed_on))

    added, dupes = 0, 0
    for r in redemptions:
        code = (r.get("coupon_code") or r.get("code") or "").strip()
        email = (r.get("member_email") or r.get("email") or "").strip().lower()
        pw = (r.get("paywall") or r.get("paywall_name") or "").strip()
        on = (r.get("date") or r.get("redeemed_on") or "")[:10]
        k = (code, email, pw, on)
        if not code or k in seen:
            dupes += 1
            continue
        seen.add(k)
        added += 1
        if not dry:
            db_session.add(BBUCircleRedemption(
                org_id=ORG, code=code, terms=(r.get("coupon_terms") or "")[:120],
                member_name=(r.get("member_name") or "")[:200], member_email=email,
                paywall_name=pw[:300], product_id=_resolve(pw, by_key, keys),
                redeemed_on=on, amount=(r.get("amount") or "")[:24],
                charge_status=(r.get("charge_status") or r.get("status") or "")[:32],
                redemption_status=(r.get("redemption_status") or "")[:32],
                source="circle", imported_at=now))

    if not dry:
        await db_session.commit()

    return JSONResponse({
        "dry_run": dry,
        "coupons": {"created": created, "updated": updated,
                    "held_inactive_for_review": len(held), "held": held[:40]},
        "redemptions": {"imported": added, "skipped_duplicates": dupes},
        "unmapped_paywall_names": sorted(unmapped_names),
        "sample": coupon_report[:15],
    }, headers=CORS)


@router.get("/circle-coupons/verify")
async def verify(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    _check(request)
    reds = (await db_session.execute(select(BBUCircleRedemption).where(
        BBUCircleRedemption.org_id == ORG))).scalars().all()
    coups = (await db_session.execute(select(BBUCoupon).where(
        BBUCoupon.org_id == ORG))).scalars().all()

    per_code: dict = {}
    for r in reds:
        per_code[r.code] = per_code.get(r.code, 0) + 1
    bcbs = [r for r in reds if "BCBS" in r.code.upper()
            or r.code.upper().startswith("SPECIALBEGINNINGS")]
    return {
        "coupons_in_platform": len(coups),
        "active": sum(1 for c in coups if c.active),
        "inactive_awaiting_review": sorted(c.code for c in coups if not c.active),
        "redemptions_archived": len(reds),
        "distinct_codes_with_history": len(per_code),
        "unique_people": len({r.member_email for r in reds if r.member_email}),
        "unmapped_to_a_product": sum(1 for r in reds if not r.product_id),
        "bcbs_related": {"rows": len(bcbs),
                         "unique_people": len({r.member_email for r in bcbs})},
        "top_codes": sorted(per_code.items(), key=lambda kv: -kv[1])[:15],
    }


@router.get("/circle-coupons/export")
async def export(request: Request, db_session: AsyncSession = Depends(get_db_session)):
    """The archive back out as CSV — what the admin team hands a funder."""
    _check(request)
    code = (request.query_params.get("code") or "").strip().upper()
    q = select(BBUCircleRedemption).where(BBUCircleRedemption.org_id == ORG)
    rows = (await db_session.execute(q)).scalars().all()
    if code:
        rows = [r for r in rows if r.code.upper() == code]
    rows.sort(key=lambda r: (r.code, r.redeemed_on))

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["coupon_code", "terms", "member_name", "member_email", "course",
                "product_id", "date_redeemed", "amount", "status", "source"])
    for r in rows:
        w.writerow([r.code, r.terms, r.member_name, r.member_email, r.paywall_name,
                    r.product_id or "", r.redeemed_on, r.amount, r.charge_status, r.source])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="circle-redemptions{"-"+code if code else ""}.csv"'})
