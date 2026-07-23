"""BBU reseller / bulk-seat redemption codes — data model. Clean-room.

Powers agency & reseller packs (e.g. the $4,500 Agency Package's 16 resellable
trainings): generate N single-use codes tied to a product/course set; redeeming a
code grants the redeemer access to those courses via the course access usergroup
(same gating mechanism as a purchase). Capped-use links Circle couldn't do.
"""
from typing import Optional
from sqlalchemy import Column, Integer, String
from sqlmodel import Field, SQLModel


class BBUSeatCode(SQLModel, table=True):
    __tablename__ = "bbu_seat_code"
    __table_args__ = {"extend_existing": True}

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(sa_column=Column(Integer, nullable=False, index=True))
    code: str = Field(default="", sa_column=Column(String(32), index=True))
    batch_label: str = Field(default="", sa_column=Column(String(200), index=True))
    # what the code grants: comma-separated course_uuids (resolved from a product
    # at generation time so a later product edit doesn't change already-sold packs)
    course_uuids: str = Field(default="", sa_column=Column(String))
    product_id: Optional[int] = Field(default=None)
    # who bought the pack (agency owner) — for reporting; not required to redeem
    owner_email: str = Field(default="", sa_column=Column(String(320), index=True))
    status: str = Field(default="unused", sa_column=Column(String(12)))  # unused|redeemed|void
    redeemed_by_user_id: Optional[int] = Field(default=None)
    redeemed_by_email: str = Field(default="", sa_column=Column(String(320)))
    redeemed_at: str = Field(default="", sa_column=Column(String(40)))
    created_at: str = Field(default="", sa_column=Column(String(40)))
