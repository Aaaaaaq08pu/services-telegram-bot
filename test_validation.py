# -*- coding: utf-8 -*-
"""اختبارات منطقية محلية لا تتصل بـ Telegram أو بمصادر الأرقام."""

import unittest

from bot import is_private_invite_link, validate_telegram_link


class TelegramLinkValidationTests(unittest.TestCase):
    def test_accepts_public_telegram_links(self):
        self.assertTrue(validate_telegram_link("https://t.me/PublicChannel_1"))
        self.assertTrue(validate_telegram_link("@PublicChannel_1"))

    def test_accepts_private_invite_link_syntax(self):
        link = "https://t.me/+I6h4aB62cT9mN2Y0"
        self.assertTrue(validate_telegram_link(link))
        self.assertTrue(is_private_invite_link(link))

    def test_rejects_non_telegram_urls(self):
        self.assertFalse(validate_telegram_link("https://example.com/channel"))
        self.assertFalse(validate_telegram_link("https://t.me/+bad"))

    def test_public_links_are_not_marked_private(self):
        self.assertFalse(is_private_invite_link("https://t.me/PublicChannel_1"))


if __name__ == "__main__":
    unittest.main()
