"""海選 LINE 轉寄：按鈕走 /line/… 中轉頁，再喚起手機 LINE App。"""
from __future__ import annotations

import html
import json
from typing import Any, Dict, Optional
from urllib.parse import quote


LINE_PACKS = (
    ("night", "開 LINE・夜盤", "夜盤判斷"),
    ("layout", "開 LINE・起漲", "起漲與佈局"),
    ("trade", "開 LINE・短線", "短線說明"),
)
PACK_IDS = {p[0] for p in LINE_PACKS}


def _date_slash(ymd: str) -> str:
    d = str(ymd or "").replace("-", "")
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}/{d[4:6]}/{d[6:]}"
    return str(ymd or "")


def line_share_href(text: str) -> str:
    """LINE 官方分享網址（網頁／備援）。"""
    return "https://line.me/R/share?text=" + quote(text or "", safe="")


def line_app_href(text: str) -> str:
    """手機 LINE URL Scheme（Telegram 內建瀏覽器較易喚起 App）。"""
    return "line://msg/text/" + quote(text or "", safe="")


def line_hop_url(pack_id: str, base_url: str = "") -> str:
    """Telegram 按鈕用：走自家 /line/… 中轉，不直接塞超長 line.me。"""
    from config import get_public_base_url

    base = (base_url or get_public_base_url()).rstrip("/")
    pid = str(pack_id or "").strip()
    return f"{base}/line/{pid}"


def hop_redirect_for_text(text: str) -> Optional[str]:
    body = (text or "").strip()
    if not body:
        return None
    return line_share_href(body)


def render_line_redirect_html_for_url(line_share_url: str) -> str:
    """只有 line.me 網址時的備援頁。"""
    url = str(line_share_url or "").strip()
    if not url:
        return "<!DOCTYPE html><html><body>無內容</body></html>"
    safe = html.escape(url, quote=True)
    payload = json.dumps(url, ensure_ascii=False)
    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="refresh" content="0;url={safe}">'
        "</head><body>"
        '<p style="font-family:sans-serif;text-align:center;margin-top:2em">'
        "正在開啟 LINE…</p>"
        f'<p style="text-align:center"><a href="{safe}">點此開啟 LINE</a></p>'
        f"<script>location.replace({payload});</script>"
        "</body></html>"
    )


def render_line_redirect_html(text: str) -> str:
    """中轉頁：手機先試 line://，失敗再改 line.me/R/share。"""
    body = (text or "").strip()
    if not body:
        return "<!DOCTYPE html><html><body>無內容</body></html>"
    share_url = line_share_href(body)
    app_url = line_app_href(body)
    safe_share = html.escape(share_url, quote=True)
    safe_app = html.escape(app_url, quote=True)
    share_json = json.dumps(share_url, ensure_ascii=False)
    app_json = json.dumps(app_url, ensure_ascii=False)
    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta http-equiv="refresh" content="1;url={safe_share}">'
        "</head><body>"
        '<p style="font-family:sans-serif;text-align:center;margin-top:2em">'
        "正在開啟 LINE…</p>"
        '<p style="text-align:center;font-size:1.05em">'
        f'<a href="{safe_app}" style="display:inline-block;margin:0.5em;padding:0.6em 1em;'
        'background:#06c755;color:#fff;text-decoration:none;border-radius:8px">'
        "開啟 LINE App</a></p>"
        f'<p style="text-align:center"><a href="{safe_share}">改用瀏覽器分享</a></p>'
        "<script>"
        "(function(){"
        f"var share={share_json},app={app_json};"
        "var mobile=/iPhone|iPad|iPod|Android/i.test(navigator.userAgent||'');"
        "function goShare(){try{location.replace(share);}catch(e){location.href=share;}}"
        "function goApp(){try{location.href=app;}catch(e){}"
        "setTimeout(goShare,900);}"
        "if(mobile){goApp();}else{goShare();}"
        "})();"
        "</script>"
        "</body></html>"
    )


def render_line_rich_share_html(manifest: Dict[str, Any]) -> str:
    """整區：開 LINE 選聯絡人帶文字；預覽與長圖皆為「文字→圖」逐檔排列。"""
    text = str(manifest.get("line_text") or "").strip()
    title = html.escape(str(manifest.get("title") or "海選"))
    count = int(manifest.get("count") or 0)
    album_url = str(manifest.get("album_url") or "").strip()
    safe_album = html.escape(album_url, quote=True) if album_url else ""
    stocks = manifest.get("stocks") or []
    share_url = line_share_href(text)
    app_url = line_app_href(text)
    share_json = json.dumps(share_url, ensure_ascii=False)
    app_json = json.dumps(app_url, ensure_ascii=False)
    album_json = json.dumps(album_url, ensure_ascii=False)
    safe_text = html.escape(text)

    stock_blocks = []
    for st in stocks:
        block = html.escape(str(st.get("text_block") or ""))
        strip = html.escape(str(st.get("strip_url") or ""), quote=True)
        if not block and not strip:
            continue
        text_pre = (
            f'<pre class="stock-text">{block}</pre>'
            if block
            else ""
        )
        img = (
            f'<img src="{strip}" alt="圖表" class="stock-img" loading="lazy">'
            if strip
            else ""
        )
        stock_blocks.append(
            f'<article class="stock-card">{text_pre}{img}</article>'
        )
    stocks_html = "\n".join(stock_blocks)
    album_block = (
        f'<img id="album" src="{safe_album}" alt="全區長圖" class="album">'
        if safe_album
        else ""
    )

    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}｜WayneBot LINE</title>"
        "<style>"
        "body{font-family:sans-serif;margin:0;padding:16px;background:#fafafa;color:#111}"
        ".btn{display:inline-block;margin:8px 4px;padding:12px 16px;border-radius:10px;text-decoration:none;font-weight:600}"
        ".green{background:#06c755;color:#fff}.blue{background:#1e6fff;color:#fff}"
        ".stock-card{margin:0 0 1.25em;padding:0 0 1em;border-bottom:1px solid #ddd}"
        ".stock-text{white-space:pre-wrap;font-size:15px;line-height:1.55;background:#f8fafc;"
        "padding:12px;border-radius:10px;margin:0 0 10px;border:1px solid #e8ecf0}"
        ".stock-img{width:100%;max-width:720px;display:block;margin:0 auto;border-radius:8px}"
        ".album{width:100%;max-width:720px;display:block;margin:1em auto;border-radius:8px}"
        ".summary{white-space:pre-wrap;font-size:14px;line-height:1.5;background:#fff;padding:12px;"
        "border-radius:10px;border:1px solid #e0e0e0;margin-bottom:1em}"
        "</style>"
        "</head><body>"
        f"<h2 style=\"text-align:center;margin-top:0\">{title}　{count} 檔</h2>"
        "<p style=\"text-align:center;line-height:1.6\">"
        "① 會開啟 LINE，請<b>選聯絡人</b>送出文字總彙整<br>"
        "② 再貼下方「全區長圖」（每檔文字後面接圖表）</p>"
        '<p style="text-align:center">'
        f'<a class="btn green" id="openLine" href="{html.escape(app_url, quote=True)}">'
        "傳文字到 LINE・選聯絡人</a>"
        f'<a class="btn blue" id="saveAlbum" href="{safe_album}" download="waynebot.png">下載全區長圖</a>'
        "</p>"
        f'<details open><summary style="font-weight:600;margin-bottom:8px">文字總彙整預覽</summary>'
        f'<div class="summary">{safe_text}</div></details>'
        f"<h3 style=\"font-size:1em;margin:1.2em 0 0.6em\">圖文預覽（文字→圖，逐檔）</h3>"
        f'<div style="max-width:720px;margin:0 auto">{stocks_html}</div>'
        "<h3 style=\"font-size:1em;margin:1.2em 0 0.6em\">全區長圖（貼到 LINE 同一則）</h3>"
        f"{album_block}"
        "<script>"
        "(function(){"
        f"var share={share_json},app={app_json},album={album_json};"
        "var mobile=/iPhone|iPad|iPod|Android/i.test(navigator.userAgent||'');"
        "function goShare(){try{location.replace(share);}catch(e){location.href=share;}}"
        "function goApp(){try{location.href=app;}catch(e){}"
        "setTimeout(goShare,900);}"
        "if(mobile){setTimeout(goApp,400);}"
        "var btn=document.getElementById('saveAlbum');"
        "if(btn&&navigator.share&&album){"
        "btn.addEventListener('click',function(ev){"
        "fetch(album).then(function(r){return r.blob();}).then(function(blob){"
        "var file=new File([blob],'waynebot.png',{type:'image/png'});"
        "if(navigator.canShare&&navigator.canShare({files:[file]})){"
        "ev.preventDefault();return navigator.share({files:[file],title:'WayneBot'});}"
        "}).catch(function(){});"
        "});}"
        "})();"
        "</script>"
        "</body></html>"
    )


def load_pack_text(db_path: str, pack_id: str, as_of: str = "") -> Dict[str, str]:
    from screen_sessions import load_line_pack

    return load_line_pack(db_path, pack_id, as_of)


def hop_stock_response(db_path: str, stock_id: str) -> Dict[str, str]:
    from screen_sessions import load_line_stock

    sid = str(stock_id or "").strip()
    if not sid:
        return {"redirect": None, "error": "缺少代號"}
    row = load_line_stock(db_path, sid)
    text = str((row or {}).get("text") or "").strip()
    if not text:
        text = _rebuild_stock_line_text(db_path, sid)
    if not text:
        return {"redirect": None, "error": f"查無 {sid}，請先按一次海選"}
    return {"redirect": hop_redirect_for_text(text), "text": text}


def hop_response(db_path: str, pack_id: str) -> Optional[Dict[str, str]]:
    pid = str(pack_id or "").strip()
    if not pid:
        return None
    row = load_pack_text(db_path, pid)
    text = str((row or {}).get("text") or "").strip() if row else ""
    if not text:
        text = _rebuild_bucket_line_text(db_path, pid)
    if not text:
        return {"redirect": None, "error": "查無內容，請先按一次海選"}
    return {"redirect": hop_redirect_for_text(text), "text": text}


def _rebuild_bucket_line_text(db_path: str, pack_id: str) -> str:
    try:
        from import_health import latest_complete_quote_date
        from line_share_format import format_line_bucket_body, LINE_BUCKET_META
        from screen_sessions import load_bucket_rows

        if pack_id not in LINE_BUCKET_META:
            return ""
        as_of = latest_complete_quote_date(db_path) or ""
        rows = load_bucket_rows(db_path, pack_id, as_of)
        if not rows:
            return ""
        items = []
        for r in rows:
            items.append(
                {
                    "stock_id": r.get("stock_id"),
                    "stock_name": r.get("stock_name"),
                    "close": r.get("pick_close"),
                    "chase_warning": r.get("chase_warning"),
                }
            )
        body = format_line_bucket_body(items, pack_id, db_path)
        if not body:
            return ""
        return f"WayneBot 海選　{_date_slash(as_of)}\n{body}"
    except Exception:
        return ""


def _rebuild_stock_line_text(db_path: str, stock_id: str) -> str:
    try:
        from import_health import latest_complete_quote_date
        from line_share_format import LINE_BUCKET_META, format_line_stock_block
        from screen_sessions import load_bucket_rows

        as_of = latest_complete_quote_date(db_path) or ""
        sid = str(stock_id or "").strip()
        for bucket in LINE_BUCKET_META:
            for r in load_bucket_rows(db_path, bucket, as_of):
                if str(r.get("stock_id") or "") != sid:
                    continue
                item = dict(r)
                item["stock_id"] = sid
                title, _ = LINE_BUCKET_META.get(bucket, (bucket, ""))
                return "\n".join(
                    [
                        f"WayneBot 海選　{_date_slash(as_of)}",
                        f"【{title}】",
                        format_line_stock_block(item, 1, db_path),
                    ]
                )
        return ""
    except Exception:
        return ""


# 相容舊測試／呼叫
def render_line_hop_html(title: str, text: str) -> str:
    del title
    return render_line_redirect_html(text)
