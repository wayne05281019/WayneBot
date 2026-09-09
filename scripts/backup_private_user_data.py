#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從本機／拷下來的 wayne_market.db 匯出某一 uid 的持股／觀察／成交／AI 倉。

公開 GitHub Release zip 只有行情，救不回持股。輸出 JSON 請放自己電腦或加密雲端，
不要上傳 Release、不要貼聊天。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_db_path, get_telegram_chat_id  # noqa: E402
from wayne_db import export_private_user_payload  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="匯出某一 Telegram uid 的私人資料")
    parser.add_argument("uid", nargs="?", default="", help="Telegram uid；空白＝TELEGRAM_CHAT_ID")
    parser.add_argument("--db", default="", help="sqlite 路徑；空白＝WAYNE_DB_PATH")
    parser.add_argument("-o", "--out", default="", help="輸出 JSON 路徑")
    args = parser.parse_args()
    uid = str(args.uid or get_telegram_chat_id() or "").strip()
    if not uid:
        print("請給 uid，或設 TELEGRAM_CHAT_ID", file=sys.stderr)
        return 2
    db = str(args.db or get_db_path())
    payload = export_private_user_payload(db, uid)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        path = Path(args.out)
        path.write_text(text, encoding="utf-8")
        print(path)
        return 0
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
