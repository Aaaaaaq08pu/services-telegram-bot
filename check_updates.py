#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""فحص كل التحديثات المرسلة من البوت بعد رسالة /start."""
import json
import urllib.request

TOKEN = "8935045945:AAENJUB7xZx7L44MtdrkQ6aZ81Xbwn4Nr2k"


def api(method, data=None):
    url = f"https://api.telegram.org/bot{TOKEN}/{method}"
    req = urllib.request.Request(url)
    if data is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(data).encode()
    with urllib.request.urlopen(req, data=data, timeout=30) as r:
        return json.loads(r.read().decode())


res = api("getUpdates")
print("count:", len(res["result"]))
for u in res["result"][-15:]:
    m = u.get("message") or u.get("edited_message")
    if m:
        kb = "KB" if m.get("reply_markup") else "noKB"
        sender = m.get("from", {}).get("id")
        chat = m.get("chat", {}).get("id")
        print(m.get("message_id"), "| from", sender, "| chat", chat, "|", kb, "|", repr((m.get("text") or "")[:100]))
    elif u.get("callback_query"):
        print("CBQ:", json.dumps(u["callback_query"], ensure_ascii=False)[:150])
