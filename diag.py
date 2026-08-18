#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تشخيص: إرسال /start وطباعة كل التحديثات الخام."""
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


print("sent:", api("sendMessage", {"chat_id": DEV, "text": "/start"})["ok"])
time.sleep(8)
res = api("getUpdates")
raw = json.dumps(res["result"], ensure_ascii=False)
print("count:", len(res["result"]))
print(raw[:2000])
