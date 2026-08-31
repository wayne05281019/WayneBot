"""把海選三段稿轉成「開啟 LINE、自己選要傳給誰」。

Telegram 按鈕網址有長度上限，不能把整段中文塞進 line.me。
先開自己的 /line/夜盤 → 手機再跳進 LINE，文字已填好。
"""
from __future__ import annotations

import html
import json
from typing import Dict, Optional
from urllib.parse import quote


LINE_PACKS = (
    ("night", "開 LINE・夜盤", "夜盤判斷"),
    ("layout", "開 LINE・起漲", "起漲與佈局"),
    ("trade", "開 LINE・當沖", "當沖／隔日沖"),
)
PACK_IDS = {p[0] for p in LINE_PACKS}


def line_share_href(text: str) -> str:
    """LINE 官方分享網址：開 App 後自己選聊天室。"""
    return "https://line.me/R/share?text=" + quote(text or "", safe="")


def render_line_hop_html(title: str, text: str) -> str:
    safe_title = html.escape(title or "傳到 LINE")
    payload = json.dumps(text or "", ensure_ascii=False)
    href = html.escape(line_share_href(text or ""), quote=True)
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{safe_title}</title>
<style>
body{{font-family:-apple-system,sans-serif;margin:24px;line-height:1.45;color:#111}}
a.btn{{display:block;text-align:center;padding:16px;background:#06C755;color:#fff;
text-decoration:none;border-radius:10px;font-size:18px;font-weight:700}}
pre{{white-space:pre-wrap;word-break:break-word;background:#f6f7f8;padding:12px;border-radius:8px}}
p.hint{{color:#555}}
</style>
</head>
<body>
<p class="hint">按下面會開啟 LINE，再自己選要傳給誰。不會自動指定哥哥。</p>
<p><a class="btn" id="go" href="{href}">開啟 LINE　{safe_title}</a></p>
<pre id="body"></pre>
<script>
const TEXT = {payload};
const url = "https://line.me/R/share?text=" + encodeURIComponent(TEXT);
const btn = document.getElementById("go");
if (btn) btn.href = url;
document.getElementById("body").textContent = TEXT;
try {{ location.replace(url); }} catch (e) {{}}
</script>
</body>
</html>
"""


def load_pack_text(db_path: str, pack_id: str, as_of: str = "") -> Dict[str, str]:
    from screen_sessions import load_line_pack

    return load_line_pack(db_path, pack_id, as_of)


def hop_response(db_path: str, pack_id: str) -> Optional[Dict[str, str]]:
    pid = str(pack_id or "").strip()
    if pid not in PACK_IDS:
        return None
    row = load_pack_text(db_path, pid)
    if not row or not row.get("text"):
        return {
            "title": "目前沒有這段",
            "html": render_line_hop_html("目前沒有這段", "請先在 Telegram 按一次「海選」。"),
        }
    title = row.get("title") or pid
    return {"title": title, "html": render_line_hop_html(title, row["text"])}
