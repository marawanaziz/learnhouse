"""Exercise the real referral/checkout boundaries without external payments."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from starlette.requests import Request
from src.bbu_payments import affiliates, offers_router as offers, router as payments
from src.bbu_payments.models import BBUOrder, BBUProduct


def request(body=None, cookie="", query=""):
    async def receive():
        return {"type": "http.request", "body": json.dumps(body or {}).encode()}
    return Request({
        "type": "http", "method": "POST", "scheme": "https",
        "path": "/api/v1/payments/1/offers/offer_6/checkout",
        "query_string": query.encode(),
        "headers": [(b"host", b"learn.birthandbabyuniversity.com"),
                    (b"cookie", cookie.encode())],
    }, receive)


class ReferralCheckoutTests(unittest.IsolatedAsyncioTestCase):
    async def check_checkout(self, body, cookie, affiliate, expected):
        product = BBUProduct(id=6, org_id=1, name="Breastfeeding",
                             price_cents=4700, currency="usd",
                             course_uuids="course_family", stripe_product_id="prod_fixture")
        db = SimpleNamespace(add=Mock(), commit=AsyncMock())
        lookup = AsyncMock(return_value=affiliate)
        create = Mock(return_value=SimpleNamespace(id="cs_fixture", url="https://checkout.stripe.com/fixture"))
        with patch.object(offers, "_get_product", AsyncMock(return_value=product)), \
             patch.object(offers, "_is_group_member", AsyncMock(return_value=False)), \
             patch.object(affiliates, "get_affiliate_by_ref", lookup), \
             patch("src.bbu_payments.stripe_sync.ensure_product"), \
             patch.object(offers.stripe, "api_key", "sk_test_fixture"), \
             patch.object(offers.stripe.checkout.Session, "create", create):
            result = await offers.checkout(1, "offer_6", request(body, cookie), db,
                                           SimpleNamespace(id=42, email="buyer@example.test"))
        self.assertEqual(result["session_id"], "cs_fixture")
        self.assertEqual(create.call_args.kwargs["metadata"]["affiliate_ref"], expected)
        orders = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], BBUOrder)]
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0].affiliate_ref, expected)
        self.assertEqual(orders[0].amount_cents, 4700)
        if body.get("affiliate_ref") or cookie:
            lookup.assert_awaited_once()
            self.assertEqual(lookup.await_args.args[2], 1)
        return lookup

    async def test_server_action_ref_survives_to_stripe_and_order(self):
        await self.check_checkout({"affiliate_ref": "mbfmama"}, "",
            SimpleNamespace(ref_code="mbfmama", status="active"), "mbfmama")

    async def test_direct_cookie_ref_survives(self):
        lookup = await self.check_checkout({}, "bbu_ref=mbfmama",
            SimpleNamespace(ref_code="mbfmama", status="active"), "mbfmama")
        self.assertEqual(lookup.await_args.args[1], "mbfmama")

    async def test_alias_is_canonicalized(self):
        await self.check_checkout({"affiliate_ref": "old-code"}, "",
            SimpleNamespace(ref_code="mbfmama", status="active"), "mbfmama")

    async def test_unknown_or_other_org_ref_gets_no_credit(self):
        await self.check_checkout({"affiliate_ref": "unknown"}, "", None, "")

    async def test_suspended_ref_gets_no_credit(self):
        await self.check_checkout({"affiliate_ref": "mbfmama"}, "",
            SimpleNamespace(ref_code="mbfmama", status="suspended"), "")

    async def test_ordinary_checkout_is_unchanged(self):
        lookup = await self.check_checkout({}, "", None, "")
        lookup.assert_not_awaited()

    async def check_redirect(self, query, destination):
        affiliate = SimpleNamespace(ref_code="mbfmama")
        with patch.object(payments.aff, "get_affiliate_by_ref", AsyncMock(return_value=affiliate)), \
             patch.object(payments.aff, "get_settings", AsyncMock(return_value=SimpleNamespace(attribution_window_days=60))), \
             patch.object(payments.aff, "log_click", AsyncMock()):
            response = await payments.referral_redirect("mbfmama", request(query=query), Mock())
        self.assertEqual(response.headers["location"], "https://learn.birthandbabyuniversity.com" + destination)
        self.assertIn("bbu_ref=mbfmama", response.headers["set-cookie"])

    async def test_default_referral_opens_public_store(self):
        await self.check_redirect("", "/store")

    async def test_explicit_class_destination_is_preserved(self):
        await self.check_redirect("next=%2Fstore%2Foffers%2Foffer_6", "/store/offers/offer_6")

    async def test_external_destination_falls_back_to_store(self):
        await self.check_redirect("next=https%3A%2F%2Fexample.test", "/store")


if __name__ == "__main__":
    unittest.main()
