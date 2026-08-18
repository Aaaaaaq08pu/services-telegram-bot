#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""اختبار مباشر: إرسال /testui ومراقبة السجل للتحقق من رد البوت."""
import json
import time
import urllib.request

TOKEN = "8935045945:AAENJUB7xZx7L44MtdrkQ6aZ81Xbwn4Nr2k"
DEV = 8858067249


def api(method, data=None):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    req = urllib.request.Request(url)
    if data is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(data).encode()
    with urllib.request.urlopen(req, data=data, timeout=30) as r:
        return json.loads(r.read().decode())


# ملاحظة: رسالة sendMessage من التوكن نفسه إلى المطور ستصل للمستخدم
# لكنها لن تولّد تحديث للبوت (رسائل البوت نفسه لا تُرسل للبوت).
# الحل الوحيد لاختبار حقيقي: أن يرسل المستخدم نفسه الأمر يدوياً من تطبيقه.
# هنا نرسل /testui عبر API ونتحقق من أن الدالة تعمل بدون استثناء.
res = api("sendMessage", {"chat_id": DEV, "text": "/testui"})
print("sent:", res["ok"])
print("رسالة الاختبار أُرسلت. افتح البوت في تيليجرام وستجد رسالة /testui وصلت.")
print("ملاحظة: البوت لا يستلم هذه الرسالة لأنها من حسابه نفسه؛")
print("الاختبار الحقيقي يتم بإرسال /testui يدوياً من حسابك في تيليجرام.")
