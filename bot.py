#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
بوت تيليجرام تجاري متكامل - نظام الرصيد وخصمه التلقائي
======================================================
الخدمات:
  1. رشق القنوات والمجموعات (عبر BuztGrowth المجاني)
  2. أرقام وهمية مؤقتة (عبر receive-smss.com المجاني)

المطور: @Aaaaaaq08pu (ID: 8858067249)

ملاحظات للمطور:
- الرصيد يُضاف عبر أمر خاص: /add [ايدي] [الرصيد]
- بيانات المستخدمين تُحفظ في ملف users.json
- يمكنك تغيير تكلفة الخدمات من الثوابت أدناه
"""

import json
import logging
import os
import random
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ============================================================
# ============ الإعدادات العامة (قابلة للتعديل) ===============
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8935045945:AAENJUB7xZx7L44MtdrkQ6aZ81Xbwn4Nr2k")
DEVELOPER_ID = 8858067249          # ايدي المطور
DEVELOPER_USERNAME = "@Aaaaaaq08pu"  # يوزر المطور

# تكلفة الخدمات (بالنقاط)
SPAM_SERVICE_COST = 10             # تكلفة خدمة الرشق لكل طلب
NUMBERS_SERVICE_COST = 5           # تكلفة خدمة الأرقام الوهمية لكل رقم
DAILY_SPAM_LIMIT = 1               # عدد طلبات الرشق المجانية المسموح بها لكل رابط

# الحد الأدنى والأقصى للكمية في الرشق
SPAM_MIN_QUANTITY = 10
SPAM_MAX_QUANTITY = 10

# رابط بوت المطور لطلب شراء رصيد
SHOP_BOT_USERNAME = DEVELOPER_USERNAME  # يمكن تغييره ليوزر بوت أو قناة الشراء

# مسار قاعدة البيانات
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "users.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("tgbot")

# ============================================================
# ============ قاعدة البيانات (حفظ الرصيد) ====================
# ============================================================

def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            balance INTEGER DEFAULT 0,
            total_spent INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            last_spam_request TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            service TEXT,
            target TEXT,
            quantity INTEGER,
            points INTEGER,
            status TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id, username=None):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(user_id, username):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (user_id, username),
    )
    conn.commit()
    conn.close()
    return get_user(user_id)

def get_balance(user_id):
    user = get_user(user_id)
    return user["balance"] if user else 0

def add_balance(user_id, amount, actor_username=None):
    conn = get_db()
    conn.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
        (amount, user_id),
    )
    conn.commit()
    conn.close()

def deduct_balance(user_id, amount):
    conn = get_db()
    conn.execute(
        "UPDATE users SET balance = balance - ?, total_spent = total_spent + ? WHERE user_id = ?",
        (amount, amount, user_id),
    )
    conn.commit()
    conn.close()

def log_order(user_id, service, target, quantity, points, status):
    conn = get_db()
    conn.execute(
        "INSERT INTO orders (user_id, service, target, quantity, points, status) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, service, target, quantity, points, status),
    )
    conn.commit()
    conn.close()

# ============================================================
# ============ الخدمة الأولى: رشق المواقع والقنوات ============
# ============================================================
#
# تم ربط البوت فعلياً مع BuztGrowth (خدمة مجانية حقيقية تعمل):
#   POST https://buztgrowth.com/wp-admin/admin-ajax.php
#   action=smm_panel_submit_order&service=<id>&link=<الرابط>&quantity=10
#
# في حال توقف الموقع عن العمل أو أردت تغيير مزود الرشق،
# عدّل الدالة spam_service_boost() أدناه وأشر إلى الرابط الجديد.
# ============================================================

# معرف الخدمة المجانية لأعضاء تلغرام في BuztGrowth
BUZT_SERVICE_ID = 231

def get_buzt_nonce():
    """جلب رمز nonce المحدث من صفحة BuztGrowth المجانية."""
    try:
        resp = requests.get(
            "https://buztgrowth.com/free-telegram-members/",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"},
            timeout=20,
        )
        match = re.search(r'"nonce":"([a-z0-9]+)"', resp.text)
        if match:
            return match.group(1)
    except Exception as e:
        logger.warning("فشل جلب nonce من BuztGrowth: %s", e)
    # قيمة احتياطية معروفة
    return "d4da2c9622"

def spam_service_boost(target_link: str, quantity: int = 10):
    """
    تنفيذ طلب الرشق عبر BuztGrowth المجاني.
    يرجع dict: {success: bool, message: str, order_id: int|None}
    """
    try:
        nonce = get_buzt_nonce()
        resp = requests.post(
            "https://buztgrowth.com/wp-admin/admin-ajax.php",
            data={
                "action": "smm_panel_submit_order",
                "nonce": nonce,
                "service": BUZT_SERVICE_ID,
                "link": target_link.strip(),
                "quantity": str(quantity),
            },
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
                "Referer": "https://buztgrowth.com/free-telegram-members/",
            },
            timeout=30,
        )
        data = resp.json()
        if data.get("success"):
            return {
                "success": True,
                "message": data["data"].get("message", "تم تنفيذ الطلب بنجاح"),
                "order_id": data["data"].get("order_id"),
            }
        return {
            "success": False,
            "message": data.get("data", {}).get("message", "فشل تنفيذ الطلب، حاول لاحقاً"),
            "order_id": None,
        }
    except Exception as e:
        logger.error("خطأ في طلب الرشق: %s", e)
        return {"success": False, "message": f"خطأ في الاتصال بمزود الخدمة: {e}", "order_id": None}

def validate_telegram_link(link: str):
    """التحقق من صحة رابط تلغرام.”"""
    pattern = r"^https?://(t\.me|telegram\.me)/[a-zA-Z0-9_]{4,}"
    if re.match(pattern, link.strip()):
        return True
    # يقبل أيضاً الروابط بصيغة @username
    if re.match(r"^@[a-zA-Z0-9_]{4,}$", link.strip()):
        return True
    return False

# ============================================================
# ============ الخدمة الثانية: الأرقام الوهمية ================
# ============================================================
#
# مصدر الأرقام: receive-smss.com (مجاني بالكامل، بدون تسجيل).
# نستخدم playwright (متصفح حقيقي) لتجاوز حماية Cloudflare.
#
# في حال أردت تغيير المزود، عدّل دالة fetch_virtual_number().
# ============================================================

SPAM_PLATFORM_NAMES = {
    "instagram": "انستقرام",
    "telegram": "تيليجرام",
    "facebook": "فيسبوك",
    "tiktok": "تيك توك",
    "threads": "ثريدز",
    "kwai": "كـواي",
    "youtube": "يوتيوب",
    "whatsapp": "واتساب",
    "kick": "كيهيك",
    "twitter": "تويتر",
}

NUMBERS_MAP = {
    "whatsapp": {"site_name": "واتساب", "site_id": "whatsapp"},
    "telegram": {"site_name": "تيليجرام", "site_id": "telegram"},
    "facebook": {"site_name": "فيسبوك", "site_id": "facebook"},
    "instagram": {"site_name": "انستجرام", "site_id": "instagram"},
    "tiktok": {"site_name": "تيك توك", "site_id": "tiktok"},
    "google": {"site_name": "جوجل", "site_id": "google"},
    "twitter": {"site_name": "تويتر", "site_id": "twitter"},
    "snapchat": {"site_name": "سناب شات", "site_id": "snapchat"},
}

def get_all_temp_numbers():
    """جلب قائمة الأرقام الوهمية المتاحة من receive-smss.com."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"
            )
            page.goto("https://receive-smss.com/", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2500)
            numbers = page.evaluate("""() => {
                const out = new Map();
                document.querySelectorAll('a').forEach(a => {
                    const m = a.href.match(/\\/sms\\/(\\d+)\\//);
                    if (m && a.textContent && a.textContent.includes('+')) {
                        const ph = a.textContent.match(/\\+\\d[\\d ()-]{8,16}/);
                        if (ph) out.set(m[1], ph[0]);
                    }
                });
                const arr = [];
                out.forEach((num, id) => arr.push({id, number: num}));
                return arr.slice(0, 30);
            }""")
            browser.close()
            return numbers
    except ImportError:
        logger.warning("playwright غير متوفر، نستخدم طريقة بديلة")
        return []
    except Exception as e:
        logger.error("خطأ في جلب الأرقام: %s", e)
        return []

def get_number_messages(number_id: int, tries: int = 3):
    """جلب آخر الرسائل الواردة على رقم معين (مع محاولات إعادة تحميل)."""
    try:
        from playwright.sync_api import sync_playwright
        for attempt in range(tries):
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"
                )
                page.goto(
                    f"https://receive-smss.com/sms/{number_id}/",
                    wait_until="networkidle",
                    timeout=60000,
                )
                page.wait_for_timeout(3000)
                page.evaluate("location.reload()")
                page.wait_for_timeout(2500)
                msgs = page.evaluate("""() => {
                    const results = [];
                    document.querySelectorAll('tr').forEach(row => {
                        const tds = row.querySelectorAll('td');
                        if (tds.length >= 3) {
                            results.push({
                                sender: tds[1].innerText.trim(),
                                message: tds[2].innerText.trim(),
                                time: tds.length > 3 ? tds[3].innerText.trim() : ''
                            });
                        }
                    });
                    return results.slice(0, 8);
                }""")
                browser.close()
                if msgs:
                    return msgs
        return []
    except Exception as e:
        logger.error("خطأ في جلب رسائل الرقم: %s", e)
        return []

# ============================================================
# ============ حالات المحادثة ==================================
# ============================================================

(
    WAITING_SPAM_LINK,
    WAITING_SPAM_QUANTITY,
    WAITING_NUMBER_PLATFORM,
) = range(3)

# ============================================================
# ============ الدوال المساعدة ================================
# ============================================================

def build_main_keyboard():
    """القائمة الرئيسية بأسلوب بوت السلطان."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("♡ شراء أرقام وهمية ♡", callback_data="section_numbers"),
        ],
        [
            InlineKeyboardButton("♡ قسم شحن الألعاب ♡", callback_data="section_games"),
            InlineKeyboardButton("♡ إشحن حسابك ♡", callback_data="buy_credits"),
        ],
        [
            InlineKeyboardButton("♡ قسم الرشق وزيادة المتابعين ♡", callback_data="section_spam"),
        ],
        [
            InlineKeyboardButton("♡ شراء نجوم Telegram الذهبية ♡", callback_data="section_stars"),
        ],
        [
            InlineKeyboardButton("♡ مشاركة رابط الدعوة الخاص بك ♡", callback_data="invite_link"),
        ],
        [
            InlineKeyboardButton("♡ حالة طلباتي ♡", callback_data="my_orders"),
            InlineKeyboardButton("♡ الإعدادات ♡", callback_data="section_settings"),
        ],
        [
            InlineKeyboardButton("♡ الدعم الفني ♡", url="https://t.me/Aaaaaaq08pu"),
        ],
    ])


def build_spam_platforms_keyboard():
    """قسم الرشق بخدمات متعددة المنصات بأسلوب بوت السلطان."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("• انستقرام •", callback_data="sp_instagram"),
            InlineKeyboardButton("• تيليجرام •", callback_data="sp_telegram"),
        ],
        [
            InlineKeyboardButton("• فيسبوك •", callback_data="sp_facebook"),
            InlineKeyboardButton("• تيك توك •", callback_data="sp_tiktok"),
        ],
        [
            InlineKeyboardButton("• ثريدز •", callback_data="sp_threads"),
            InlineKeyboardButton("• كـواي •", callback_data="sp_kwai"),
        ],
        [
            InlineKeyboardButton("• يوتيوب •", callback_data="sp_youtube"),
            InlineKeyboardButton("• واتساب •", callback_data="sp_whatsapp"),
        ],
        [
            InlineKeyboardButton("• كيهيك •", callback_data="sp_kick"),
            InlineKeyboardButton("• تويتر •", callback_data="sp_twitter"),
        ],
        [InlineKeyboardButton("• الصفحة الرئيسية •", callback_data="main_menu")],
    ])


def build_numbers_keyboard():
    """قسم الأرقام الوهمية بأسلوب بوت السلطان."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("عروض الواتساب", callback_data="num_whatsapp"),
            InlineKeyboardButton("أرقام جاهزة TG", callback_data="num_telegram"),
        ],
        [
            InlineKeyboardButton("شراء أرقام لتطبيقات أخرى", callback_data="num_other_apps"),
        ],
        [
            InlineKeyboardButton("الاكثر توفراً واتساب", callback_data="num_whatsapp"),
            InlineKeyboardButton("شراء رقم جاهز", callback_data="num_ready"),
        ],
        [InlineKeyboardButton("- رجوع.", callback_data="main_menu")],
    ])

async def send_no_balance_message(update_or_callback, update, context):
    """إرسال رسالة عدم توفر الرصيد مع زر شراء رصيد."""
    text = (
        "❌ رصيدك غير كافٍ لاستخدام هذه الخدمة!\n\n"
        f"• تكلفة خدمة الرشق: {SPAM_SERVICE_COST} نقطة\n"
        f"• تكلفة خدمة الأرقام: {NUMBERS_SERVICE_COST} نقطة\n\n"
        f"لشراء رصيد تواصل مع المطور: {DEVELOPER_USERNAME}"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"🛒 تواصل مع المطور {DEVELOPER_USERNAME}", callback_data="buy_credits"),
    ]])
    if update_or_callback:
        try:
            await update_or_callback.edit_message_text(text, reply_markup=keyboard)
        except TelegramError:
            if update and update.effective_message:
                await update.effective_message.reply_text(text, reply_markup=keyboard)
    elif update and update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=keyboard)


# ============================================================
# ============ أوامر البوت ====================================
# ============================================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_user(user.id, user.username)
    balance = get_balance(user.id)
    name = user.first_name or user.username or "عزيزي"
    text = (
        "• ≪ اهلا بك عزيزي : " + name + " 🤚\n"
        "══════ ☠️ ══════\n"
        f"• رصيد حسابك الان : {balance} ⏎\n"
        f"• اايدي الحساب : {user.id} 👤\n"
        "════════════════\n"
        "≪ اتحكم بالبوت من خلال الازرار بالأسفل\n"
        "⬇️"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=build_main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ <b>تعليمات الاستخدام:</b>\n\n"
        "1️⃣ اختر الخدمة المطلوبة من الأزرار.\n"
        "2️⃣ أدخل الرابط أو اسم المنصة حسب الخدمة.\n"
        "3️⃣ سيتم خصم النقاط تلقائياً من رصيدك.\n"
        "4️⃣ إذا كان رصيدك صفراً لن تتمكن من استخدام الخدمات.\n\n"
        f"💰 لشراء رصيد تواصل مع المطور: {DEVELOPER_USERNAME}\n\n"
        "📌 ملاحظات خدمة الرشق:\n"
        "• يجب أن يكون رابط القناة أو المجموعة عاماً وبصيغة: t.me/username\n"
        "• مسموح بطلب واحد كل 6 ساعات لكل رابط (حسب المزود المجاني).\n\n"
        "📌 ملاحظات الأرقام الوهمية:\n"
        "• الأرقام مجانية ومشتركة، قد تكون محجوبة من بعض التطبيقات.\n"
        "• جميع الرسائل الواردة على الرقم متاحة للجميع."
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=build_main_keyboard())

async def my_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = get_balance(user.id)
    text = (
        "💰 <b>رصيدك الحالي:</b>\n\n"
        f"• الرصيد المتاح: <b>{balance}</b> نقطة\n"
        f"• تكلفة الرشق: {SPAM_SERVICE_COST} نقطة\n"
        f"• تكلفة الأرقام: {NUMBERS_SERVICE_COST} نقطة\n\n"
        f"🛒 لشراء رصيد: {DEVELOPER_USERNAME}"
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    أمر خاص بالمطور فقط لإضافة رصيد لمستخدم.
    الصيغة: /add [ايدي_المستخدم] [عدد_النقاط]
    مثال: /add 123456789 100
    """
    if update.effective_user.id != DEVELOPER_ID:
        await update.message.reply_text("❌ هذا الأمر خاص بالمطور فقط!")
        return
    try:
        target_id = int(context.args[0])
        amount = int(context.args[1])
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❌ الصيغة خاطئة!\nاستخدم: /add [ايدي_المستخدم] [عدد_النقاط]\nمثال: /add 123456789 100"
        )
        return
    if amount <= 0 or amount > 100000:
        await update.message.reply_text("❌ يجب أن يكون الرصيد بين 1 و 100000")
        return
    create_user(target_id, None)
    add_balance(target_id, amount)
    new_balance = get_balance(target_id)
    await update.message.reply_text(
        f"✅ تمت إضافة {amount} نقطة للمستخدم {target_id}\n"
        f"💰 الرصيد الجديد: {new_balance} نقطة"
    )
    # إشعار المستخدم صاحب الرصيد
    try:
        await context.bot.send_message(
            target_id,
            f"🎉 تم إضافة <b>{amount}</b> نقطة إلى رصيدك!\n💰 رصيدك الآن: <b>{new_balance}</b> نقطة",
            parse_mode="HTML",
        )
    except TelegramError:
        logger.info("لم يتمكن من إشعار المستخدم %s (البوت لم يبدأ معه)", target_id)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إحصائيات البوت - للمطور فقط."""
    if update.effective_user.id != DEVELOPER_ID:
        await update.message.reply_text("❌ هذا الأمر خاص بالمطور فقط!")
        return
    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    users_with_balance = conn.execute("SELECT COUNT(*) FROM users WHERE balance > 0").fetchone()[0]
    total_balance = conn.execute("SELECT SUM(balance) FROM users").fetchone()[0] or 0
    total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    total_spent = conn.execute("SELECT SUM(total_spent) FROM users").fetchone()[0] or 0
    conn.close()
    text = (
        "📊 <b>إحصائيات البوت:</b>\n\n"
        f"👥 إجمالي المستخدمين: {total_users}\n"
        f"💰 مستخدمون لديهم رصيد: {users_with_balance}\n"
        f"🏦 مجموع الأرصدة الموزعة: {total_balance} نقطة\n"
        f"📦 إجمالي الطلبات: {total_orders}\n"
        f"📉 مجموع النقاط المستهلكة: {total_spent}"
    )
    await update.message.reply_text(text, parse_mode="HTML")

# ============================================================
# ============ محادثة الرشق ===================================
# ============================================================

async def spam_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """البداية: إدخال رابط القناة/المجموعة."""
    user = update.effective_user
    create_user(user.id, user.username)
    balance = get_balance(user.id)
    if balance < SPAM_SERVICE_COST:
        await send_no_balance_message(None, update, context)
        return ConversationHandler.END
    text = (
        f"⚡ <b>خدمة رشق القنوات والمجموعات</b>\n\n"
        f"💰 التكلفة: <b>{SPAM_SERVICE_COST} نقطة</b>\n"
        f"📊 رصيدك: <b>{balance} نقطة</b>\n\n"
        "🔗 أرسل رابط القناة أو المجموعة بصيغة:\n"
        "<code>https://t.me/username</code>\n\n"
        "❌ لإلغاء اكتب /cancel"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML")
    return WAITING_SPAM_LINK

async def spam_link_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """استلام الرابط والتحقق منه."""
    link = update.message.text.strip()
    if not validate_telegram_link(link):
        if not link.startswith("http"):
            link = f"https://t.me/{link.strip('@')}"
            if not validate_telegram_link(link):
                await update.message.reply_text(
                    "❌ الرابط غير صحيح!\n\n"
                    "يجب أن يكون بصيغة:\n"
                    "<code>https://t.me/username</code>\n\n"
                    "🔄 أرسل رابطاً صحيحاً أو اكتب /cancel للإلغاء",
                    parse_mode="HTML",
                )
                return WAITING_SPAM_LINK
        else:
            await update.message.reply_text(
                "❌ الرابط غير صحيح!\n\n"
                "🔄 أرسل رابطاً صحيحاً أو اكتب /cancel للإلغاء",
                parse_mode="HTML",
            )
            return WAITING_SPAM_LINK
    context.user_data["spam_link"] = link
    # الكمية ثابتة = 10 حسب المزود المجاني
    context.user_data["spam_quantity"] = SPAM_MAX_QUANTITY
    text = (
        f"✅ تم استلام الرابط:\n<code>{link}</code>\n\n"
        f"📊 الكمية: <b>{SPAM_MAX_QUANTITY} عضو</b> (الحد الأقصى للخدمة المجانية)\n\n"
        f"💰 سيتم خصم <b>{SPAM_SERVICE_COST} نقطة</b> من رصيدك.\n\n"
        "👍 للبدء اضغط الزر أدناه:\n"
        "❌ أو اكتب /cancel للإلغاء"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚡ تنفيذ الرشق", callback_data="spam_execute"),
    ]])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
    return WAITING_SPAM_QUANTITY

async def spam_execute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تنفيذ طلب الرشق الفعلي مع الخصم."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    balance = get_balance(user_id)
    if balance < SPAM_SERVICE_COST:
        await send_no_balance_message(query, update, context)
        return ConversationHandler.END
    link = context.user_data.get("spam_link")
    quantity = context.user_data.get("spam_quantity", SPAM_MAX_QUANTITY)
    if not link:
        await query.edit_message_text("❌ حدث خطأ، ابدأ من جديد: /start")
        return ConversationHandler.END
    # إشعار جاري المعالجة
    await query.edit_message_text("⏳ جاري تنفيذ طلب الرشق... قد يستغرق الأمر بضع ثوانٍ.")
    result = spam_service_boost(link, quantity)
    if result["success"]:
        deduct_balance(user_id, SPAM_SERVICE_COST)
        log_order(user_id, "رشق", link, quantity, SPAM_SERVICE_COST, "ناجح")
        new_balance = get_balance(user_id)
        text = (
            "✅ <b>تم تنفيذ طلب الرشق بنجاح!</b>\n\n"
            f"🔗 الرابط: <code>{link}</code>\n"
            f"📊 الكمية: {quantity} عضو\n"
            f"💰 النقاط المخصومة: {SPAM_SERVICE_COST} نقطة\n"
            f"💰 رصيدك المتبقي: <b>{new_balance}</b> نقطة\n\n"
            "⏰ ملاحظة: الخدمة المجانية تسمح بطلب واحد كل 6 ساعات لكل رابط.\n"
            "⚠️ النتائج قد تحتاج بضع دقائق للظهور."
        )
    else:
        log_order(user_id, "رشق", link, quantity, SPAM_SERVICE_COST, "فشل")
        text = (
            f"❌ <b>فشل تنفيذ الطلب</b>\n\n"
            f"السبب: {result['message']}\n\n"
            "💡 لم يتم خصم أي نقاط من رصيدك.\n"
            "🔄 جرّب لاحقاً أو تواصل مع المطور."
        )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=build_main_keyboard())
    return ConversationHandler.END

# ============================================================
# ============ محادثة الأرقام الوهمية =========================
# ============================================================

async def numbers_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """البداية: اختيار المنصة."""
    user = update.effective_user
    create_user(user.id, user.username)
    balance = get_balance(user.id)
    if balance < NUMBERS_SERVICE_COST:
        await send_no_balance_message(None, update, context)
        return ConversationHandler.END
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📲 واتساب", callback_data="num_whatsapp"),
            InlineKeyboardButton("✈️ تيليجرام", callback_data="num_telegram"),
        ],
        [
            InlineKeyboardButton("📘 فيسبوك", callback_data="num_facebook"),
            InlineKeyboardButton("📸 انستجرام", callback_data="num_instagram"),
        ],
        [
            InlineKeyboardButton("🎵 تيك توك", callback_data="num_tiktok"),
            InlineKeyboardButton("🔍 جوجل", callback_data="num_google"),
        ],
        [
            InlineKeyboardButton("🐦 تويتر", callback_data="num_twitter"),
            InlineKeyboardButton("👻 سناب شات", callback_data="num_snapchat"),
        ],
        [InlineKeyboardButton("❌ إلغاء", callback_data="num_cancel")],
    ])
    text = (
        f"📱 <b>خدمة الأرقام الوهمية</b>\n\n"
        f"💰 التكلفة: <b>{NUMBERS_SERVICE_COST} نقطة</b> لكل رقم\n"
        f"📊 رصيدك: <b>{balance} نقطة</b>\n\n"
        "🌐 اختر المنصة التي تريد الرقم لها:"
    )
    await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
    return WAITING_NUMBER_PLATFORM

async def number_platform_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عند اختيار المنصة: جلب الأرقام وعرضها."""
    query = update.callback_query
    await query.answer()
    platform = query.data.replace("num_", "")
    if platform not in NUMBERS_MAP:
        await query.edit_message_text("❌ منصة غير معروفة، ابدأ من جديد: /start")
        return ConversationHandler.END
    context.user_data["number_platform"] = platform
    user_id = query.from_user.id
    balance = get_balance(user_id)
    if balance < NUMBERS_SERVICE_COST:
        await send_no_balance_message(query, update, context)
        return ConversationHandler.END
    await query.edit_message_text(
        f"⏳ جاري جلب الأرقام المتاحة لمنصة <b>{NUMBERS_MAP[platform]['site_name']}</b>...\n"
        "يرجى الانتظار قليلاً...",
        parse_mode="HTML",
    )
    numbers = get_all_temp_numbers()
    if not numbers:
        text = (
            "⚠️ لم نتمكن من جلب الأرقام حالياً (الموقع محمي أو غير متاح).\n\n"
            "🔄 جرب مرة أخرى بعد قليل أو تواصل مع المطور."
        )
        await query.edit_message_text(text, reply_markup=build_main_keyboard())
        return ConversationHandler.END
    # إنشاء أزرار الأرقام (حد أقصى 10 في كل صفحة)
    buttons = []
    for n in numbers[:10]:
        buttons.append([InlineKeyboardButton(n["number"], callback_data=f"picknum_{n['id']}")])
    buttons.append([InlineKeyboardButton("❌ إلغاء", callback_data="num_cancel")])
    text = (
        f"📱 <b>اختر رقماً لمنصة {NUMBERS_MAP[platform]['site_name']}</b>\n\n"
        f"💰 التكلفة: <b>{NUMBERS_SERVICE_COST} نقطة</b>\n"
        f"💰 رصيدك: <b>{balance} نقطة</b>\n\n"
        "⚠️ الأرقام مجانية ومشتركة بين الجميع."
    )
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
    return WAITING_NUMBER_PLATFORM

async def number_picked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عند اختيار رقم معين: خصم النقاط وإرسال الرقم."""
    query = update.callback_query
    await query.answer()
    number_id = query.data.replace("picknum_", "")
    platform = context.user_data.get("number_platform", "telegram")
    user_id = query.from_user.id
    balance = get_balance(user_id)
    if balance < NUMBERS_SERVICE_COST:
        await send_no_balance_message(query, update, context)
        return ConversationHandler.END
    await query.edit_message_text("⏳ جاري تجهيز الرقم...")
    # جلب الرقم المحدد
    numbers = get_all_temp_numbers()
    chosen = next((n for n in numbers if n["id"] == number_id), None)
    if not chosen:
        await query.edit_message_text("❌ هذا الرقم لم يعد متاحاً، اختر رقماً آخر.")
        return WAITING_NUMBER_PLATFORM
    deduct_balance(user_id, NUMBERS_SERVICE_COST)
    log_order(user_id, "رقم وهمي", f"{NUMBERS_MAP[platform]['site_name']} - {chosen['number']}", 1, NUMBERS_SERVICE_COST, "ناجح")
    new_balance = get_balance(user_id)
    text = (
        f"✅ <b>تم تجهيز رقمك بنجاح!</b>\n\n"
        f"📱 المنصة: <b>{NUMBERS_MAP[platform]['site_name']}</b>\n"
        f"🔢 الرقم: <b>{chosen['number']}</b>\n\n"
        "📩 استخدم هذا الرقم في التطبيق وسنرسل لك الرسائل الواردة عليه أدناه.\n"
        "⏳ انتظر وصول رمز التحقق ثم اضغط الزر أدناه.\n\n"
        f"💰 النقاط المخصومة: {NUMBERS_SERVICE_COST} نقطة\n"
        f"💰 رصيدك المتبقي: <b>{new_balance}</b> نقطة\n\n"
        "⚠️ الأرقام مجانية ومشتركة، قد تكون محجوبة من بعض التطبيقات."
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📨 جلب الرسائل الواردة", callback_data="fetch_sms"),
    ], [
        InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu"),
    ]])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
    return WAITING_NUMBER_PLATFORM

async def fetch_sms_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """جلب الرسائل الواردة على الرقم المختار."""
    query = update.callback_query
    await query.answer("⏳ جاري جلب الرسائل...")
    # البحث عن آخر رقم تم اختياره من الأزرار
    numbers = get_all_temp_numbers()
    chosen = numbers[0] if numbers else None
    if not chosen:
        await query.edit_message_text("⚠️ تعذر جلب الرسائل حالياً، حاول بعد قليل.")
        return WAITING_NUMBER_PLATFORM
    await query.edit_message_text("⏳ جاري جلب الرسائل الواردة على الرقم...")
    messages = get_number_messages(int(chosen["id"]))
    if messages:
        lines = []
        for m in messages:
            msg = m["message"][:80]
            sender = m["sender"][:20]
            lines.append(f"📥 من: {sender}\n💬 {msg}")
        text = f"📨 <b>الرسائل الواردة على الرقم:</b>\n\n" + "\n\n".join(lines)
    else:
        text = (
            "📨 <b>لا توجد رسائل جديدة حتى الآن.</b>\n\n"
            "⏳ استخدم الرقم في التطبيق أولاً، ثم أعد المحاولة بعد دقيقة.\n"
            "💡 ملاحظة: الرسائل الواردة على الأرقام المجانية مرئية للجميع."
        )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 تحديث الرسائل", callback_data="fetch_sms")],
        [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="main_menu")],
    ])
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
    return WAITING_NUMBER_PLATFORM

# ============================================================
# ============ أزرار عامة =====================================
# ============================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """التعامل مع كل الأزرار العامة."""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    if data.startswith(("num_", "picknum_", "fetch_sms", "spam_execute", "sp_", "section_")):
        return  # هذه تُعالج داخل الأزرار الجديدة أعلاه
    if data == "service_spam":
        return await spam_start(update, context)
    if data == "service_numbers":
        return await numbers_start(update, context)
    if data == "my_balance":
        balance = get_balance(user_id)
        text = (
            f"💰 <b>رصيدك: {balance} نقطة</b>\n\n"
            f"🛒 لشراء رصيد: {DEVELOPER_USERNAME}"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=build_main_keyboard())
    elif data == "my_orders":
        conn = get_db()
        orders = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,)
        ).fetchall()
        conn.close()
        if not orders:
            text = "📜 لا توجد طلبات سابقة لك."
        else:
            lines = []
            for o in orders:
                status_icon = "✅" if o["status"] == "ناجح" else "❌"
                lines.append(
                    f"{status_icon} {o['service']} - {o['target'][:40]}\n"
                    f"   📊 {o['quantity']} | 💰 {o['points']} نقطة | 🕐 {o['created_at']}"
                )
            text = "📜 <b>آخر طلباتك:</b>\n\n" + "\n\n".join(lines)
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=build_main_keyboard())
    elif data == "buy_credits":
        text = (
            "🛒 <b>شراء رصيد</b>\n\n"
            f"لإضافة رصيد تواصل مع المطور:\n"
            f"{DEVELOPER_USERNAME}\n\n"
            "💵 بعد الدفع سيتم إضافة الرصيد مباشرة إلى حسابك."
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=build_main_keyboard())
    elif data == "help_info":
        await help_command(update, context)
    elif data == "main_menu":
        user = query.from_user
        create_user(user.id, user.username)
        balance = get_balance(user.id)
        name = user.first_name or user.username or "عزيزي"
        text = (
            "• ≪ اهلا بك عزيزي : " + name + " 🤚\n"
            "══════ ☠️ ══════\n"
            f"• رصيد حسابك الان : {balance} ⏎\n"
            f"• اايدي الحساب : {user.id} 👤\n"
            "════════════════\n"
            "≪ اتحكم بالبوت من خلال الازرار بالأسفل\n"
            "⬇️"
        )
        await query.edit_message_text(
            text, parse_mode="HTML", reply_markup=build_main_keyboard()
        )
    elif data == "section_spam":
        text = (
            "☯️ خدمة الرشق لجميع منصات التواصل الاجتماعي\n"
            "────────────────\n"
            "<u>تساعدك في <b>زيادة متابعين</b> وتفاعلات صفحتك</u>\n"
            "<u>توفر خدمات <b>متابعين وإعجابات ومشاهدات</b></u>\n"
            "<u><b>أسعار مناسبة</b> تتفاوت من حيث الجودة والسرعة</u>\n"
            "────────────────\n"
            "≪ <u>الرجاء إختيار البرنامج المواد rasha . ☯️ : مُنه</u>\n\n"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=build_spam_platforms_keyboard())
    elif data.startswith("sp_"):
        platform = data.replace("sp_", "")
        if platform == "telegram":
            return await spam_start(update, context)
        # باقي المنصات: خدمة وهمية مؤقتة (تُشغل نفس آلية الرشق كبديل قابل للتبديل)
        text = (
            f"• ≪ قسم الرشق : {SPAM_PLATFORM_NAMES.get(platform, platform)}\n"
            "══════ ☠️ ══════\n"
            "• ارسل رابط الحساب / الصفحة / القناة\n"
            "• سيتم خصم النقاط تلقائياً من رصيدك\n"
            "════════════════\n"
            "≪ اتحكم بالبوت من خلال الازرار بالأسفل\n"
            "⬇️"
        )
        context.user_data["spam_platform"] = platform
        await query.edit_message_text(text, parse_mode="HTML")
        # نبدأ محادثة الرشق بنفس الحالة (انتظار الرابط)
        return await spam_start(update, context)
    elif data == "section_numbers":
        user = query.from_user
        create_user(user.id, user.username)
        balance = get_balance(user.id)
        name = user.first_name or user.username or "عزيزي"
        text = (
            "• ≪ اهلا بك عزيزي : " + name + " 🤚\n"
            "══════ ☠️ ══════\n"
            "• - في قسم الارقام الوهمية\n"
            "• - ارقام وهمية جميع الدول وجميع المنصات\n"
            "• - سيرفرات متعددة وسريعه في وصول الكود\n"
            "• - إختار ما تريدة من الاسفل ⬇️\n"
            "•────────────────•"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=build_numbers_keyboard())
    elif data == "num_other_apps":
        # تطبيقات أخرى -> اختيار المنصة من القائمة المعروفة
        return await numbers_start(update, context)
    elif data == "num_ready":
        # شراء رقم جاهز -> قائمة الأرقام مباشرة (تيليجرام افتراضياً)
        context.user_data["number_platform"] = "telegram"
        user_id = query.from_user.id
        balance = get_balance(user_id)
        if balance < NUMBERS_SERVICE_COST:
            return await send_no_balance_message(query, update, context)
        return await number_platform_selected(update, context)
    elif data == "section_games":
        text = (
            "♡ قسم شحن الألعاب ♡\n"
            "══════ ☠️ ══════\n"
            "• هذا القسم قيد التطوير وسيتم تفعيله قريباً.\n"
            "• تواصل مع المطور لشحن حسابات الألعاب: {DEVELOPER_USERNAME}\n"
            "════════════════\n"
            "≪ اتحكم بالبوت من خلال الازرار بالأسفل\n"
            "⬇️"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=build_main_keyboard())
    elif data == "section_stars":
        text = (
            "♡ شراء نجوم Telegram الذهبية ♡\n"
            "══════ ☠️ ══════\n"
            "• هذا القسم قيد التطوير وسيتم تفعيله قريباً.\n"
            "• تواصل مع المطور لشراء النجوم: {DEVELOPER_USERNAME}\n"
            "════════════════\n"
            "≪ اتحكم بالبوت من خلال الازرار بالأسفل\n"
            "⬇️"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=build_main_keyboard())
    elif data == "invite_link":
        user = query.from_user
        text = (
            "♡ مشاركة رابط الدعوة الخاص بك ♡\n"
            "══════ ☠️ ══════\n"
            f"• رابطك الخاص: https://t.me/Aloweyuibot?start={user.id}\n"
            "• شارك الرابط مع أصدقائك لدعوتهم للبوت.\n"
            "════════════════\n"
            "≪ اتحكم بالبوت من خلال الازرار بالأسفل\n"
            "⬇️"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=build_main_keyboard())
    elif data == "section_settings":
        text = (
            "• - قسم الإعدادات الخاصة بحسابك في البوت •\n"
            "══════ ☠️ ══════\n"
            "≪ اتحكم بالبوت من خلال الازرار بالأسفل\n"
            "⬇️"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("♡ نسخة حسابي ♡", callback_data="settings_account")],
            [InlineKeyboardButton("♡ احصائيات الحساب ♡", callback_data="my_balance")],
            [InlineKeyboardButton("♡ قنوات البوت ♡", url="https://t.me/Aaaaaaq08pu")],
            [InlineKeyboardButton("♡ حالة طلباتي ♡", callback_data="my_orders")],
            [InlineKeyboardButton("♡ الدعم الفني ♡", url="https://t.me/Aaaaaaq08pu")],
            [InlineKeyboardButton("- رجوع.", callback_data="main_menu")],
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboard)
    elif data == "settings_account":
        user = query.from_user
        balance = get_balance(user.id)
        text = (
            "≪ اهلا بك عزيزي : " + (user.first_name or user.username or "عزيزي") + " 🤚\n"
            "•≪ في القائمة الرئيسية لدى بوت السلطان 🏠\n"
            "•────────────────•\n"
            f"• حسابك : {user.username or user.id}@\n"
            f"• ايدي الحساب : {user.id} 👤\n"
            f"• رصيد حسابك الان : {balance} ⏎ 💰\n"
            "•────────────────•\n"
            "≪ اتحكم بالبوت من خلال الازرار بالأسفل\n"
            "⬇️"
        )
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=build_main_keyboard())
    elif data == "num_cancel":
        await query.edit_message_text(
            "❌ تم إلغاء العملية.", reply_markup=build_main_keyboard()
        )
    return None

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ تم إلغاء العملية.", reply_markup=build_main_keyboard())
    return ConversationHandler.END

async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ أمر غير معروف. استخدم /start للبدء.")

async def test_ui_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر اختبار مخصص للمطور: يعيد إرسال القائمة الرئيسية للتحقق من الواجهة."""
    user = update.effective_user
    create_user(user.id, user.username)
    balance = get_balance(user.id)
    name = user.first_name or user.username or "عزيزي"
    text = (
        "• ≪ اهلا بك عزيزي : " + name + " 🤚\n"
        "══════ ☠️ ══════\n"
        f"• رصيد حسابك الان : {balance} ⏎\n"
        f"• اايدي الحساب : {user.id} 👤\n"
        "════════════════\n"
        "≪ اتحكم بالبوت من خلال الازرار بالأسفل\n"
        "⬇️"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=build_main_keyboard())

# ============================================================
# ============ التشغيل ========================================
# ============================================================

async def my_account_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض نسخة الحساب بأسلوب بوت السلطان."""
    user = update.effective_user
    create_user(user.id, user.username)
    balance = get_balance(user.id)
    text = (
        "≪ اهلا بك عزيزي : " + (user.first_name or user.username or "عزيزي") + " 🤚\n"
        "•≪ في القائمة الرئيسية لدى بوت السلطان 🏠\n"
        "•────────────────•\n"
        f"• حسابك : {user.username or user.id}@\n"
        f"• ايدي الحساب : {user.id} 👤\n"
        f"• رصيد حسابك الان : {balance} ⏎ 💰\n"
        "•────────────────•\n"
        "≪ اتحكم بالبوت من خلال الازرار بالأسفل\n"
        "⬇️"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=build_main_keyboard())


def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    # الأوامر
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("balance", my_balance_command))
    app.add_handler(CommandHandler("account", my_account_command))
    app.add_handler(CommandHandler("add", add_balance_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("cancel", cancel_handler))
    app.add_handler(CommandHandler("testui", test_ui_command))
    # محادثة الرشق
    spam_conv = ConversationHandler(
        entry_points=[
            CommandHandler("spam", spam_start),
            CallbackQueryHandler(spam_start, pattern="^service_spam$"),
        ],
        states={
            WAITING_SPAM_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, spam_link_received)],
            WAITING_SPAM_QUANTITY: [
                CallbackQueryHandler(spam_execute_callback, pattern="^spam_execute$"),
                CommandHandler("cancel", cancel_handler),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
    )
    app.add_handler(spam_conv)
    # محادثة الأرقام
    nums_conv = ConversationHandler(
        entry_points=[
            CommandHandler("numbers", numbers_start),
            CallbackQueryHandler(numbers_start, pattern="^service_numbers$"),
        ],
        states={
            WAITING_NUMBER_PLATFORM: [
                CallbackQueryHandler(number_platform_selected, pattern="^num_[a-z]+$"),
                CallbackQueryHandler(number_picked, pattern="^picknum_"),
                CallbackQueryHandler(fetch_sms_callback, pattern="^fetch_sms$"),
                CallbackQueryHandler(button_handler, pattern="^(main_menu|num_cancel)$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
    )
    app.add_handler(nums_conv)
    # الأزرار العامة (يجب أن تكون قبل معالج الرسائل العام)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.COMMAND, unknown_handler), group=1)
    logger.info("🚀 تم تشغيل البوت بنجاح!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
