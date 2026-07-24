"""BBU native-Stripe payments — data models.

Clean-room module (NOT derived from apps/api/ee). Adds course sales on top of
the AGPL core: products map a LearnHouse course to a Stripe price; orders record
completed purchases and drive enrollment.
"""
from typing import Optional
from sqlalchemy import Column, Integer, String, JSON
from sqlmodel import Field, SQLModel


class BBUProduct(SQLModel, table=True):
    """A sellable product: a single course or a bundle of courses."""
    __tablename__ = "bbu_product"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    name: str = Field(sa_column=Column(String(300)))
    kind: str = Field(default="course", sa_column=Column(String(20)))  # course | bundle | ebook
    # comma-separated course_uuids this product grants access to
    course_uuids: str = Field(default="", sa_column=Column(String))
    price_cents: int = Field(default=0)
    currency: str = Field(default="usd", sa_column=Column(String(8)))
    public: bool = Field(default=True)
    description: str = Field(default="", sa_column=Column(String))
    image_url: str = Field(default="", sa_column=Column(String))
    # for kind="ebook": stored file under the content volume + display filename
    asset_path: str = Field(default="", sa_column=Column(String))
    asset_filename: str = Field(default="", sa_column=Column(String(300)))
    # comma-separated selling points shown on the native offer page
    benefits: str = Field(default="", sa_column=Column(String))
    # store bucket for categorization (e.g. Birth, Postpartum, Spanish, Professional)
    category: str = Field(default="", sa_column=Column(String(60)))
    # order bumps: comma-separated product ids offered as add-ons at checkout
    bump_offer_ids: str = Field(default="", sa_column=Column(String))
    # mentorship "buy into a cohort": on purchase, enroll the buyer into a cohort.
    # cohort_program (doula|agency) → the next open cohort of that program; OR a
    # specific cohort_id pins the purchase to one dated cohort ("September 2026").
    cohort_program: str = Field(default="", sa_column=Column(String(24)))
    cohort_id: Optional[int] = Field(default=None)
    # reseller/bulk pack: buying this product auto-generates N single-use seat
    # codes for the buyer (the agency owner), who gets a self-serve portal to
    # view/share/redeem them. 0 = not a seat pack.
    seat_count: int = Field(default=0)


class BBUOrder(SQLModel, table=True):
    """A purchase. Created pending at checkout, marked paid by the webhook."""
    __tablename__ = "bbu_order"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    product_id: int = Field(default=0)
    stripe_session_id: str = Field(default="", sa_column=Column(String(255), index=True))
    stripe_payment_intent: str = Field(default="", sa_column=Column(String(255)))
    email: str = Field(default="", sa_column=Column(String(320), index=True))
    user_id: Optional[int] = Field(default=None)
    amount_cents: int = Field(default=0)
    currency: str = Field(default="usd", sa_column=Column(String(8)))
    status: str = Field(default="pending", sa_column=Column(String(20)))  # pending | paid | refunded
    course_uuids: str = Field(default="", sa_column=Column(String))
    created_at: str = Field(default="", sa_column=Column(String(40)))
    paid_at: str = Field(default="", sa_column=Column(String(40)))
    # affiliate attribution captured at checkout (ref code from cookie)
    affiliate_ref: str = Field(default="", sa_column=Column(String(64), index=True))
    # secure e-book delivery token (set on fulfillment for kind="ebook" orders)
    download_token: str = Field(default="", sa_column=Column(String(64), index=True))
    extra: Optional[dict] = Field(default=None, sa_column=Column(JSON))


class BBUCoupon(SQLModel, table=True):
    """A discount / promo code. Mirrored to a Stripe Coupon + Promotion Code so
    buyers enter it natively on Stripe Checkout (allow_promotion_codes) — Stripe
    enforces expiry, redemption caps and minimum spend. This row is the admin
    system-of-record and drives reporting."""
    __tablename__ = "bbu_coupon"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    code: str = Field(default="", sa_column=Column(String(64), index=True))
    kind: str = Field(default="percent", sa_column=Column(String(12)))   # percent | amount
    percent_off: int = Field(default=0)                                  # 1..100
    amount_off_cents: int = Field(default=0)
    currency: str = Field(default="usd", sa_column=Column(String(8)))
    # "all" or a comma-separated list of product ids the code is valid on
    # (BBU-side reporting / validate preview; Stripe applies it to the whole cart).
    applies_to: str = Field(default="all", sa_column=Column(String))
    min_amount_cents: int = Field(default=0)
    max_redemptions: int = Field(default=0)                              # 0 = unlimited
    times_redeemed: int = Field(default=0)
    expires_at: str = Field(default="", sa_column=Column(String(40)))    # ISO; "" = no expiry
    active: bool = Field(default=True)
    stripe_coupon_id: str = Field(default="", sa_column=Column(String(64)))
    stripe_promo_id: str = Field(default="", sa_column=Column(String(64)))
    created_at: str = Field(default="", sa_column=Column(String(40)))


# ===========================================================================
# Affiliate program
# ---------------------------------------------------------------------------
# Everything about the program (rate, what's commissionable, windows, payout
# terms) is stored as EDITABLE SETTINGS — never hard-coded — so Anna can change
# "50% -> 40%" or "start paying on renewals" from the admin without a redeploy.
# ===========================================================================


class BBUAffiliateSettings(SQLModel, table=True):
    """Single-row, org-scoped program configuration. All knobs live here so the
    rules are data, not code. Per-affiliate overrides live on BBUAffiliate."""
    __tablename__ = "bbu_affiliate_settings"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    default_commission_rate: float = Field(default=0.50)          # 0.50 = 50%
    # which events pay a commission: any of "first_sale","renewal","mentorship"
    commissionable_events: str = Field(default="first_sale", sa_column=Column(String(120)))
    commission_basis: str = Field(default="net_after_fees", sa_column=Column(String(24)))  # net_after_fees | gross
    attribution_window_days: int = Field(default=60)
    attribution_model: str = Field(default="last_click", sa_column=Column(String(16)))
    refund_hold_days: int = Field(default=30)
    payout_schedule: str = Field(default="monthly", sa_column=Column(String(16)))  # monthly | biweekly | manual
    min_payout_cents: int = Field(default=5000)                   # $50
    self_referral_allowed: bool = Field(default=False)
    exclude_zero_revenue: bool = Field(default=True)              # grant/100%-off earn nothing
    stripe_fee_pct: float = Field(default=0.029)                 # for net_after_fees estimate
    stripe_fee_flat_cents: int = Field(default=30)
    updated_at: str = Field(default="", sa_column=Column(String(40)))


class BBUAffiliate(SQLModel, table=True):
    """An affiliate/partner. Optional per-affiliate overrides supersede the
    program defaults so a specific partner can get a custom deal later."""
    __tablename__ = "bbu_affiliate"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    name: str = Field(default="", sa_column=Column(String(200)))
    email: str = Field(default="", sa_column=Column(String(320), index=True))
    ref_code: str = Field(default="", sa_column=Column(String(64), index=True))
    status: str = Field(default="pending", sa_column=Column(String(20)))  # pending|onboarding|active|suspended
    stripe_connect_account_id: str = Field(default="", sa_column=Column(String(64)))
    payouts_enabled: bool = Field(default=False)
    # optional overrides (None => use settings)
    commission_rate: Optional[float] = Field(default=None)
    commissionable_events: Optional[str] = Field(default=None, sa_column=Column(String(120)))
    legacy_source: str = Field(default="", sa_column=Column(String(24)))  # thrivecart|circle|""
    portal_token: str = Field(default="", sa_column=Column(String(64), index=True))  # magic link to portal
    created_at: str = Field(default="", sa_column=Column(String(40)))


class BBUReferralClick(SQLModel, table=True):
    """A click on an affiliate link — for analytics + basic fraud signal."""
    __tablename__ = "bbu_referral_click"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    affiliate_id: int = Field(sa_column=Column(Integer, index=True))
    ref_code: str = Field(default="", sa_column=Column(String(64)))
    landing_path: str = Field(default="", sa_column=Column(String))
    ip_hash: str = Field(default="", sa_column=Column(String(64)))
    created_at: str = Field(default="", sa_column=Column(String(40)))


class BBUCommission(SQLModel, table=True):
    """A commission owed to an affiliate for a specific order."""
    __tablename__ = "bbu_commission"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    affiliate_id: int = Field(sa_column=Column(Integer, index=True))
    order_id: int = Field(default=0, index=True)
    event: str = Field(default="first_sale", sa_column=Column(String(24)))
    basis_cents: int = Field(default=0)     # amount the rate was applied to
    rate: float = Field(default=0.50)
    amount_cents: int = Field(default=0)
    currency: str = Field(default="usd", sa_column=Column(String(8)))
    status: str = Field(default="pending", sa_column=Column(String(16)))  # pending|available|paid|reversed
    available_at: str = Field(default="", sa_column=Column(String(40)))   # created + hold
    payout_id: Optional[int] = Field(default=None)
    created_at: str = Field(default="", sa_column=Column(String(40)))


class BBUPayout(SQLModel, table=True):
    """A batch transfer to an affiliate's connected account."""
    __tablename__ = "bbu_payout"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    affiliate_id: int = Field(sa_column=Column(Integer, index=True))
    amount_cents: int = Field(default=0)
    currency: str = Field(default="usd", sa_column=Column(String(8)))
    stripe_transfer_id: str = Field(default="", sa_column=Column(String(64)))
    status: str = Field(default="pending", sa_column=Column(String(16)))  # pending|paid|failed
    period: str = Field(default="", sa_column=Column(String(24)))
    created_at: str = Field(default="", sa_column=Column(String(40)))
