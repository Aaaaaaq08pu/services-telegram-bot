# -*- coding: utf-8 -*-
"""اختبارات استجابات مزود التفاعلات دون إرسال أي طلب خارجي."""

import unittest
from unittest.mock import patch

import bot


class FakeResponse:
    def __init__(self, payload, status_code=200, content_type="application/json"):
        self.payload = payload
        self.status_code = status_code
        self.headers = {"content-type": content_type}

    def json(self):
        return self.payload


class BuztResponseTests(unittest.TestCase):
    def test_success_response_with_object_payload(self):
        result = bot.parse_buzt_response({"success": True, "data": {"message": "تم", "order_id": 18}})
        self.assertEqual(result, {"success": True, "message": "تم", "order_id": 18})

    def test_success_response_with_numeric_order_id(self):
        result = bot.parse_buzt_response({"success": True, "data": 18})
        self.assertTrue(result["success"])
        self.assertEqual(result["order_id"], 18)

    def test_failure_response_with_numeric_payload_does_not_raise(self):
        result = bot.parse_buzt_response({"success": False, "data": 0})
        self.assertFalse(result["success"])
        self.assertIsNone(result["order_id"])
        self.assertIn("رفض", result["message"])
        self.assertIn("0", result["message"])

    def test_unexpected_response_does_not_raise(self):
        result = bot.parse_buzt_response(1)
        self.assertFalse(result["success"])
        self.assertIn("int", result["message"])

    def test_missing_nonce_does_not_submit_a_request(self):
        with (
            patch.object(bot, "get_buzt_nonce", return_value=None),
            patch.object(bot.requests, "post") as post,
        ):
            result = bot.spam_service_boost("https://t.me/PublicChannel", 10)

        self.assertFalse(result["success"])
        self.assertIn("رمز جلسة", result["message"])
        post.assert_not_called()

    def test_service_uses_safe_parser_for_numeric_failure(self):
        with (
            patch.object(bot, "get_buzt_nonce", return_value="test-nonce"),
            patch.object(bot.requests, "post", return_value=FakeResponse({"success": False, "data": 0})),
        ):
            result = bot.spam_service_boost("https://t.me/PublicChannel", 10)
        self.assertFalse(result["success"])
        self.assertIn("رفض", result["message"])


if __name__ == "__main__":
    unittest.main()
