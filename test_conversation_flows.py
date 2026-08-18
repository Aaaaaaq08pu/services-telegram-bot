# -*- coding: utf-8 -*-
"""اختبارات لمحاكاة تدفقات البوت دون Telegram أو خصم رصيد حقيقي."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import bot


class FakeQuery:
    def __init__(self, data, user_id=77):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []
        self.edits = []

    async def answer(self, text=None):
        self.answers.append(text)

    async def edit_message_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


class FakeMessage:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


class ConversationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_number_pick_preserves_the_selected_number_when_refresh_is_empty(self):
        selected = {"id": "222", "number": "+111222333"}
        query = FakeQuery("picknum_222")
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={"number_platform": "telegram", "available_numbers": [selected]})

        async def fake_to_thread(function, *args):
            self.assertIs(function, bot.get_all_temp_numbers)
            return []

        with (
            patch.object(bot.asyncio, "to_thread", side_effect=fake_to_thread),
            patch.object(bot, "get_balance", return_value=100),
            patch.object(bot, "deduct_balance"),
            patch.object(bot, "log_order"),
        ):
            state = await bot.number_picked(update, context)

        self.assertEqual(state, bot.WAITING_NUMBER_PLATFORM)
        self.assertEqual(context.user_data["selected_number"], selected)
        self.assertIn(selected["number"], query.edits[-1][0])

    async def test_fetch_sms_uses_the_saved_selected_number(self):
        selected = {"id": "222", "number": "+111222333"}
        query = FakeQuery("fetch_sms")
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={"selected_number": selected})
        calls = []

        async def fake_to_thread(function, *args):
            calls.append((function, args))
            return [{"sender": "Service", "message": "12345", "time": "now"}]

        with patch.object(bot.asyncio, "to_thread", side_effect=fake_to_thread):
            state = await bot.fetch_sms_callback(update, context)

        self.assertEqual(state, bot.WAITING_NUMBER_PLATFORM)
        self.assertEqual(calls, [(bot.get_number_messages, (222,))])
        self.assertIn("12345", query.edits[-1][0])

    async def test_complete_number_conversation_uses_the_same_selected_number(self):
        selected = {"id": "222", "number": "+111222333"}
        context = SimpleNamespace(user_data={})
        platform_query = FakeQuery("num_telegram")
        pick_query = FakeQuery("picknum_222")
        sms_query = FakeQuery("fetch_sms")
        calls = []

        async def fake_to_thread(function, *args):
            calls.append((function, args))
            if function is bot.get_all_temp_numbers:
                return [selected] if len(calls) == 1 else []
            if function is bot.get_number_messages:
                return [{"sender": "Service", "message": "54321", "time": "now"}]
            self.fail("استدعاء غير متوقع داخل الخيط")

        with (
            patch.object(bot.asyncio, "to_thread", side_effect=fake_to_thread),
            patch.object(bot, "get_balance", return_value=100),
            patch.object(bot, "deduct_balance"),
            patch.object(bot, "log_order"),
        ):
            platform_state = await bot.number_platform_selected(
                SimpleNamespace(callback_query=platform_query), context
            )
            pick_state = await bot.number_picked(SimpleNamespace(callback_query=pick_query), context)
            sms_state = await bot.fetch_sms_callback(SimpleNamespace(callback_query=sms_query), context)

        self.assertEqual(platform_state, bot.WAITING_NUMBER_PLATFORM)
        self.assertEqual(pick_state, bot.WAITING_NUMBER_PLATFORM)
        self.assertEqual(sms_state, bot.WAITING_NUMBER_PLATFORM)
        self.assertEqual(context.user_data["available_numbers"], [selected])
        self.assertEqual(context.user_data["selected_number"], selected)
        self.assertEqual(calls[-1], (bot.get_number_messages, (222,)))
        self.assertIn("54321", sms_query.edits[-1][0])

    async def test_private_invite_link_is_explained_without_starting_an_order(self):
        message = FakeMessage("https://t.me/+I6h4aB62cT9mN2Y0")
        update = SimpleNamespace(message=message)
        context = SimpleNamespace(user_data={})

        state = await bot.spam_link_received(update, context)

        self.assertEqual(state, bot.WAITING_SPAM_LINK)
        self.assertNotIn("spam_link", context.user_data)
        self.assertIn("رابط الدعوة الخاص صحيح", message.replies[-1][0])

    async def test_spam_provider_failure_does_not_deduct_balance(self):
        query = FakeQuery("spam_execute", user_id=77)
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={"spam_link": "https://t.me/PublicChannel", "spam_quantity": 10})

        with (
            patch.object(bot, "get_balance", return_value=100),
            patch.object(bot, "spam_service_boost", return_value={"success": False, "message": "رفض المزود", "order_id": None}),
            patch.object(bot, "deduct_balance") as deduct_balance,
            patch.object(bot, "log_order") as log_order,
        ):
            state = await bot.spam_execute_callback(update, context)

        self.assertEqual(state, bot.ConversationHandler.END)
        deduct_balance.assert_not_called()
        log_order.assert_called_once_with(77, "رشق", "https://t.me/PublicChannel", 10, bot.SPAM_SERVICE_COST, "فشل")
        self.assertIn("لم يتم خصم أي نقاط", query.edits[-1][0])

    async def test_spam_provider_success_deducts_once_and_records_success(self):
        query = FakeQuery("spam_execute", user_id=77)
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={"spam_link": "https://t.me/PublicChannel", "spam_quantity": 10})

        with (
            patch.object(bot, "get_balance", return_value=100),
            patch.object(bot, "spam_service_boost", return_value={"success": True, "message": "تم", "order_id": 123}),
            patch.object(bot, "deduct_balance") as deduct_balance,
            patch.object(bot, "log_order") as log_order,
        ):
            state = await bot.spam_execute_callback(update, context)

        self.assertEqual(state, bot.ConversationHandler.END)
        deduct_balance.assert_called_once_with(77, bot.SPAM_SERVICE_COST)
        log_order.assert_called_once_with(77, "رشق", "https://t.me/PublicChannel", 10, bot.SPAM_SERVICE_COST, "ناجح")
        self.assertIn("تم تنفيذ طلب الرشق بنجاح", query.edits[-1][0])

    async def test_complete_spam_conversation_validates_confirms_and_executes(self):
        context = SimpleNamespace(user_data={})
        user = SimpleNamespace(id=77, username="tester")
        start_message = FakeMessage("/spam")
        link_message = FakeMessage("https://t.me/PublicChannel")
        execute_query = FakeQuery("spam_execute", user_id=77)

        with (
            patch.object(bot, "create_user"),
            patch.object(bot, "get_balance", return_value=100),
            patch.object(bot, "spam_service_boost", return_value={"success": True, "message": "تم", "order_id": 123}),
            patch.object(bot, "deduct_balance") as deduct_balance,
            patch.object(bot, "log_order") as log_order,
        ):
            start_state = await bot.spam_start(
                SimpleNamespace(effective_user=user, effective_message=start_message), context
            )
            link_state = await bot.spam_link_received(SimpleNamespace(message=link_message), context)
            execute_state = await bot.spam_execute_callback(
                SimpleNamespace(callback_query=execute_query), context
            )

        self.assertEqual(start_state, bot.WAITING_SPAM_LINK)
        self.assertEqual(link_state, bot.WAITING_SPAM_QUANTITY)
        self.assertEqual(execute_state, bot.ConversationHandler.END)
        self.assertEqual(context.user_data["spam_link"], "https://t.me/PublicChannel")
        self.assertEqual(context.user_data["spam_quantity"], bot.SPAM_MAX_QUANTITY)
        self.assertIn("تم استلام الرابط", link_message.replies[-1][0])
        deduct_balance.assert_called_once_with(77, bot.SPAM_SERVICE_COST)
        log_order.assert_called_once_with(77, "رشق", "https://t.me/PublicChannel", 10, bot.SPAM_SERVICE_COST, "ناجح")

    async def test_verified_number_reservation_failure_does_not_deduct_balance(self):
        query = FakeQuery("reserve_smsman", user_id=77)
        update = SimpleNamespace(callback_query=query)
        context = SimpleNamespace(user_data={"number_platform": "telegram"})

        async def fake_to_thread(function, *args):
            self.assertIs(function, bot.reserve_sms_man_number)
            self.assertEqual(args, ("telegram",))
            return {"success": False, "message": "لا توجد أرقام"}

        with (
            patch.object(bot.asyncio, "to_thread", side_effect=fake_to_thread),
            patch.object(bot, "get_balance", return_value=100),
            patch.object(bot, "deduct_balance") as deduct_balance,
            patch.object(bot, "log_order") as log_order,
        ):
            state = await bot.reserve_sms_man_number_callback(update, context)

        self.assertEqual(state, bot.ConversationHandler.END)
        deduct_balance.assert_not_called()
        log_order.assert_not_called()
        self.assertIn("لم يتم خصم أي نقاط", query.edits[-1][0])


if __name__ == "__main__":
    unittest.main()
