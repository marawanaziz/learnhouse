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
    kind: str = Field(default="course", sa_column=Column(String(20)))  # course | bundle
    # comma-separated course_uuids this product grants access to
    course_uuids: str = Field(default="", sa_column=Column(String))
    price_cents: int = Field(default=0)
    currency: str = Field(default="usd", sa_column=Column(String(8)))
    public: bool = Field(default=True)
    description: str = Field(default="", sa_column=Column(String))
    image_url: str = Field(default="", sa_column=Column(String))


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
    extra: Optional[dict] = Field(default=None, sa_column=Column(JSON))
