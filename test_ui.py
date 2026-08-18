#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار وحدة: التحقق من دوال بناء الأزرار في bot.py مباشرة."""
import ast
import re

with open("/home/ubuntu/tg_bot/bot.py", encoding="utf-8") as f:
    source = f.read()

# التحقق من البناء النحوي
ast.parse(source)
print("✓ البنية النحوية سليمة")

# استخراج قائمة الأزرار الرئيسية من build_main_keyboard
main_start = source.find("def build_main_keyboard")
main_end = source.find("def build_spam_platforms_keyboard")
main_block = source[main_start:main_end]
labels_main = re.findall(r'InlineKeyboardButton\("([^"]+)"', main_block)
print("\n--- القائمة الرئيسية ---")
for l in labels_main:
    print("  •", l)

# استخراج أزرار قسم الرشق
sp_start = source.find("def build_spam_platforms_keyboard")
sp_end = source.find("def build_numbers_keyboard")
sp_block = source[sp_start:sp_end]
labels_sp = re.findall(r'InlineKeyboardButton\("([^"]+)"', sp_block)
print("\n--- قسم الرشق (المنصات) ---")
for l in labels_sp:
    print("  •", l)

# استخراج أزرار الأرقام الوهمية
num_start = source.find("def build_numbers_keyboard")
num_end = source.find("async def send_no_balance_message")
num_block = source[num_start:num_end]
labels_num = re.findall(r'InlineKeyboardButton\("([^"]+)"', num_block)
print("\n--- قسم الأرقام الوهمية ---")
for l in labels_num:
    print("  •", l)

required_main = ["شراء أرقام وهمية", "قسم الرشق", "الإعدادات", "الدعم الفني", "شحن الألعاب", "نجوم Telegram", "رابط الدعوة"]
missing_main = [r for r in required_main if not any(r in l for l in labels_main)]
required_sp = ["انستقرام", "تيليجرام", "فيسبوك", "تيك توك", "ثريدز", "كـواي", "يوتيوب", "واتساب", "كيهيك", "تويتر"]
missing_sp = [r for r in required_sp if not any(r in l for l in labels_sp)]

if missing_main:
    print("\n!!! أزرار رئيسية مفقودة:", missing_main)
    raise SystemExit(1)
if missing_sp:
    print("\n!!! منصات مفقودة:", missing_sp)
    raise SystemExit(1)
print("\n✓ جميع أزرار القائمة الرئيسية والمنصات موجودة")
