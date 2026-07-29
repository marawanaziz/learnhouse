"""Regression coverage for legacy affiliate referral-code aliases."""

import pytest

from src.bbu_payments import affiliates
from src.bbu_payments.models import BBUAffiliate, BBUAffiliateRefAlias


class _Scalars:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class _Result:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return _Scalars(self.value)


class _Session:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = 0

    async def execute(self, _statement):
        self.calls += 1
        return _Result(self.results.pop(0))


@pytest.mark.asyncio
async def test_primary_ref_code_resolves_without_alias_lookup():
    affiliate = BBUAffiliate(id=7, org_id=1, ref_code="current-code")
    db = _Session(affiliate)

    assert await affiliates.get_affiliate_by_ref(db, "current-code") is affiliate
    assert db.calls == 1


@pytest.mark.asyncio
async def test_legacy_ref_alias_resolves_to_current_affiliate():
    alias = BBUAffiliateRefAlias(
        id=11, org_id=1, affiliate_id=7, ref_code="old-circle-code"
    )
    affiliate = BBUAffiliate(id=7, org_id=1, ref_code="current-code")
    db = _Session(None, alias, affiliate)

    assert await affiliates.get_affiliate_by_ref(db, "old-circle-code") is affiliate
    assert db.calls == 3


@pytest.mark.asyncio
async def test_unknown_ref_code_returns_none():
    db = _Session(None, None)

    assert await affiliates.get_affiliate_by_ref(db, "missing") is None
    assert db.calls == 2
