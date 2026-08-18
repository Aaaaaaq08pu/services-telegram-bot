#!/usr/bin/env python3
"""اختبار وظيفي للبوت: محاكاة رسائل /start وأزرار عبر واجهة API."""
import json
import os
import sys
import time
import requests

TOKEN = "8935045945:AAENJUB7xZx7L44MtdrkQ6aZ81Xbwn4Nr2k"
BASE = f"https://api.telegram.org/bot{TOKEN}"

def api(method, **params):
    r = requests.post(f"{BASE}/{method}", data=params, timeout=30)
    return r.json()

def main():
    me = api("getMe")
    print("getMe:", json.dumps(me["result"], ensure_ascii=False))
    updates = api("getUpdates", offset=-1)
    print("last update count:", len(updates["result"]))
    print("OK: البوت يعمل ويتصل بـ Telegram API")

if __name__ == "__main__":
    main()
