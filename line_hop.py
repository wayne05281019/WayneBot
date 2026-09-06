"""海選 LINE 轉寄：按鈕走 /line/… 中轉頁，再喚起手機 LINE App。"""
from __future__ import annotations

import html
import json
from typing import Any, Dict, Optional
from urllib.parse import quote


LINE_PACKS = (
    ("night", "開 LINE・夜盤", "夜盤判斷"),
    ("layout", "開 LINE・黃金買點", "黃金買點與佈局"),
    ("trade", "開 LINE・短線", "短線說明"),
)
PACK_IDS = {p[0] for p in LINE_PACKS}

# 手機內建瀏覽器對超長 line.me 網址常失敗；超過則改 Web Share / 剪貼簿
LINE_SHARE_URL_SAFE_LEN = 2000
# 中文 URL 編碼後約 5～6 倍；保守估計純文字上限
LINE_SHARE_TEXT_SAFE_LEN = 380


def _line_share_urls_safe(text: str) -> tuple:
    body = (text or "").strip()
    share_url = line_share_href(body)
    app_url = line_app_href(body)
    auto = len(body) <= LINE_SHARE_TEXT_SAFE_LEN and len(share_url) <= LINE_SHARE_URL_SAFE_LEN
    return share_url, app_url, auto


def _line_share_page_script(text_json: str, *, auto_open: bool) -> str:
    """長文：Web Share → 剪貼簿 → 短網址；短句：維持 line:// 喚起。"""
    auto_script = "if(mobile){goApp();}else{goShare();}" if auto_open else ""
    return (
        "<script>"
        "(function(){"
        f"var body={text_json};"
        "var mobile=/iPhone|iPad|iPod|Android/i.test(navigator.userAgent||'');"
        "function goShare(){"
        "var u='https://line.me/R/share?text='+encodeURIComponent(body);"
        "try{location.replace(u);}catch(e){location.href=u;}"
        "}"
        "function goApp(){"
        "var u='line://msg/text/'+encodeURIComponent(body);"
        "try{location.href=u;}catch(e){}"
        "setTimeout(goShare,900);"
        "}"
        "async function copyText(){"
        "try{if(navigator.clipboard&&navigator.clipboard.writeText){"
        "await navigator.clipboard.writeText(body);return true;}}"
        "catch(e){}"
        "var ta=document.createElement('textarea');"
        "ta.value=body;ta.style.position='fixed';ta.style.left='-9999px';"
        "document.body.appendChild(ta);ta.select();"
        "var ok=false;try{ok=document.execCommand('copy');}catch(e){}"
        "document.body.removeChild(ta);return ok;"
        "}"
        "async function shareLong(ev){"
        "if(ev&&ev.preventDefault)ev.preventDefault();"
        "if(navigator.share){"
        "try{await navigator.share({text:body,title:'WayneBot'});return;}catch(e){}"
        "}"
        "var ok=await copyText();"
        "var msg=ok?'已複製全文。請開 LINE → 選聯絡人 → 長按貼上。':'請手動全選下方文字複製';"
        "alert(msg);"
        "if(mobile){try{location.href='line://';}catch(e){}}"
        "}"
        "var btn=document.getElementById('shareLine');"
        "if(btn){btn.addEventListener('click',shareLong);}"
        f"{auto_script}"
        "})();"
        "</script>"
    )


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
    """中轉頁：短句 line://；長文 Web Share / 剪貼簿。"""
    body = (text or "").strip()
    if not body:
        return "<!DOCTYPE html><html><body>無內容</body></html>"
    share_url, app_url, auto_open = _line_share_urls_safe(body)
    body_json = json.dumps(body, ensure_ascii=False)
    if auto_open:
        safe_share = html.escape(share_url, quote=True)
        safe_app = html.escape(app_url, quote=True)
        share_json = json.dumps(share_url, ensure_ascii=False)
        app_json = json.dumps(app_url, ensure_ascii=False)
        refresh = f'<meta http-equiv="refresh" content="1;url={safe_share}">'
        btn = (
            f'<a id="shareLine" href="{safe_app}" style="display:inline-block;margin:0.5em;padding:0.6em 1em;'
            'background:#06c755;color:#fff;text-decoration:none;border-radius:8px">'
            "開啟 LINE App</a>"
        )
        script = (
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
        )
        hint = ""
    else:
        refresh = ""
        btn = (
            '<button id="shareLine" type="button" style="display:inline-block;margin:0.5em;padding:0.6em 1em;'
            'background:#06c755;color:#fff;border:none;border-radius:8px;font-size:1.05em">'
            "複製文字並開 LINE</button>"
        )
        script = _line_share_page_script(body_json, auto_open=False)
        hint = (
            '<p style="text-align:center;color:#b45309;font-size:0.95em">'
            "文字較長，按綠色鈕：先分享或複製全文，再開 LINE 選聯絡人貼上</p>"
        )
    safe_share = html.escape(share_url, quote=True)
    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"{refresh}"
        "</head><body>"
        '<p style="font-family:sans-serif;text-align:center;margin-top:2em">'
        "正在開啟 LINE…</p>"
        f"{hint}"
        f'<p style="text-align:center;font-size:1.05em">{btn}</p>'
        f'<p style="text-align:center"><a href="{safe_share}">改用瀏覽器分享（短句才有效）</a></p>'
        f"{script}"
        "</body></html>"
    )


def selected_line_text(manifest: Dict[str, Any], stock_ids: Optional[list] = None) -> str:
    """重建 LINE 文字：只含勾選檔。stock_ids 空／None＝全部。"""
    from line_share_format import LINE_SHARE_SEP, line_bucket_header

    stocks = list(manifest.get("stocks") or [])
    want = None
    if stock_ids is not None:
        want = {str(x).strip() for x in stock_ids if str(x).strip()}
    picked = []
    for st in stocks:
        sid = str(st.get("stock_id") or "").strip()
        if want is not None and sid not in want:
            continue
        block = str(st.get("text_block") or "").strip()
        if block:
            picked.append(block)
    full = str(manifest.get("line_text") or "").strip()
    if not picked:
        return full if want is None else ""
    if want is None and len(picked) == len(
        [st for st in stocks if str(st.get("text_block") or "").strip()]
    ):
        return full
    first = full.split("\n", 1)[0] if full else ""
    as_of = str(manifest.get("as_of") or "").strip()
    prefix = (
        first
        if first.startswith("WayneBot")
        else (f"WayneBot 海選　{_date_slash(as_of)}" if as_of else "WayneBot 海選")
    )
    title = str(manifest.get("title") or "海選").strip()
    bucket_key = str(manifest.get("bucket_key") or "").strip()
    header = (
        line_bucket_header(bucket_key, len(picked))
        if bucket_key
        else f"＝＝{title}＝＝\n共 {len(picked)} 檔"
    )
    return prefix + "\n" + header + "\n" + ("\n" + LINE_SHARE_SEP + "\n").join(picked)


def _line_picker_script() -> str:
    """勾選檔後：複製對應名單、傳勾選的介紹圖／決策卡。"""
    return """<script>(function(){
var data=JSON.parse(document.getElementById('pickPayload').textContent||'{}');
function boxes(){return Array.prototype.slice.call(document.querySelectorAll('.stock-pick'));}
function checkedIds(){return boxes().filter(function(el){return el.checked;}).map(function(el){return String(el.value);});}
function setAll(on){boxes().forEach(function(el){el.checked=!!on;}); syncCount();}
function syncCount(){
  var n=checkedIds().length, el=document.getElementById('pickCount');
  if(el) el.textContent='已勾 '+n+' 檔';
}
function selectedStocks(){
  var ids=checkedIds(), map={};
  (data.stocks||[]).forEach(function(st){map[String(st.stock_id)]=st;});
  return ids.map(function(id){return map[id];}).filter(Boolean);
}
function selectedText(){
  var blocks=selectedStocks().map(function(st){return String(st.text_block||'').trim();}).filter(Boolean);
  if(!blocks.length) return '';
  var header=(data.header||('＝＝'+(data.title||'海選')+'＝＝'))+'\\n共 '+blocks.length+' 檔';
  return String(data.prefix||'WayneBot 海選')+'\\n'+header+'\\n'+blocks.join('\\n'+(data.sep||'────────────')+'\\n');
}
async function copyText(body){
  try{if(navigator.clipboard&&navigator.clipboard.writeText){await navigator.clipboard.writeText(body);return true;}}catch(e){}
  var ta=document.createElement('textarea');ta.value=body;ta.style.position='fixed';ta.style.left='-9999px';
  document.body.appendChild(ta);ta.select();
  var ok=false;try{ok=document.execCommand('copy');}catch(e){}
  document.body.removeChild(ta);return ok;
}
async function shareText(ev){
  if(ev&&ev.preventDefault)ev.preventDefault();
  var body=selectedText();
  if(!body){alert('請先勾要傳的檔');return;}
  if(navigator.share){try{await navigator.share({text:body,title:'WayneBot'});return;}catch(e){}}
  var ok=await copyText(body);
  alert(ok?'已複製勾選名單。請開 LINE → 選聯絡人 → 長按貼上。':'請手動全選下方文字複製');
  var mobile=/iPhone|iPad|iPod|Android/i.test(navigator.userAgent||'');
  if(mobile){try{location.href='line://';}catch(e){}}
}
async function shareImages(ev){
  if(ev&&ev.preventDefault)ev.preventDefault();
  var picked=selectedStocks();
  if(!picked.length){alert('請先勾要傳的檔');return;}
  var files=[], names=[];
  for(var i=0;i<picked.length;i++){
    var st=picked[i], sid=String(st.stock_id||'stock');
    var urls=[st.glance_url,st.card_url,(!st.glance_url&&!st.card_url)?st.strip_url:''];
    for(var u=0;u<urls.length;u++){
      var url=String(urls[u]||'');
      if(!url) continue;
      try{
        var r=await fetch(url);var blob=await r.blob();
        var kind=u===0&&st.glance_url?'glance':(u===1&&st.card_url?'card':'strip');
        var fn=sid+'-'+kind+'.png';
        files.push(new File([blob],fn,{type:'image/png'}));
        names.push(fn);
      }catch(e){}
    }
  }
  if(navigator.share&&files.length){
    try{
      if(navigator.canShare&&navigator.canShare({files:files})){
        await navigator.share({files:files,title:'WayneBot'});return;
      }
    }catch(e){}
  }
  alert('這支手機一次傳多張圖不穩。請改長按勾選檔的介紹圖／決策卡 → 分享 → LINE。');
}
var shareBtn=document.getElementById('shareLine');
if(shareBtn) shareBtn.addEventListener('click',shareText);
var imgBtn=document.getElementById('sharePicked');
if(imgBtn) imgBtn.addEventListener('click',shareImages);
var allBtn=document.getElementById('pickAll');
if(allBtn) allBtn.addEventListener('click',function(){setAll(true);});
var noneBtn=document.getElementById('pickNone');
if(noneBtn) noneBtn.addEventListener('click',function(){setAll(false);});
boxes().forEach(function(el){el.addEventListener('change',syncCount);});
syncCount();
var album=String(data.album_url||'');
var albumBtn=document.getElementById('saveAlbum');
if(albumBtn&&navigator.share&&album){
  albumBtn.addEventListener('click',function(ev){
    fetch(album).then(function(r){return r.blob();}).then(function(blob){
      var file=new File([blob],'waynebot.png',{type:'image/png'});
      if(navigator.canShare&&navigator.canShare({files:[file]})){
        ev.preventDefault();return navigator.share({files:[file],title:'WayneBot'});
      }
    }).catch(function(){});
  });
}
})();</script>"""


def render_line_rich_share_html(manifest: Dict[str, Any]) -> str:
    """備援頁：介紹圖／決策卡在前；可勾選哪幾檔再轉 LINE。"""
    text = str(manifest.get("line_text") or "").strip()
    raw_title = str(manifest.get("title") or "海選")
    title = html.escape(raw_title)
    count = int(manifest.get("count") or 0)
    album_url = str(manifest.get("album_url") or "").strip()
    text_only = bool(manifest.get("text_only"))
    safe_album = html.escape(album_url, quote=True) if album_url else ""
    stocks = manifest.get("stocks") or []
    from line_share_format import LINE_SHARE_SEP, line_bucket_header, line_plain_to_html

    safe_text = line_plain_to_html(text)
    first = text.split("\n", 1)[0] if text else ""
    prefix = first if first.startswith("WayneBot") else "WayneBot 海選"
    bucket_key = str(manifest.get("bucket_key") or "").strip()
    header_label = (
        line_bucket_header(bucket_key, 0).split("\n", 1)[0]
        if bucket_key
        else f"＝＝{raw_title}＝＝"
    )
    pick_payload = {
        "prefix": prefix,
        "title": raw_title,
        "header": header_label,
        "sep": LINE_SHARE_SEP,
        "album_url": album_url,
        "stocks": [
            {
                "stock_id": str(st.get("stock_id") or "").strip(),
                "stock_name": str(st.get("stock_name") or "").strip(),
                "text_block": str(st.get("text_block") or ""),
                "glance_url": str(st.get("glance_url") or ""),
                "card_url": str(st.get("card_url") or ""),
                "strip_url": str(st.get("strip_url") or ""),
            }
            for st in stocks
        ],
    }
    payload_json = json.dumps(pick_payload, ensure_ascii=False).replace("<", "\\u003c")

    stock_blocks = []
    for st in stocks:
        sid = str(st.get("stock_id") or "").strip()
        name = html.escape(f"{sid} {st.get('stock_name') or ''}".strip())
        glance = html.escape(str(st.get("glance_url") or ""), quote=True)
        card = html.escape(str(st.get("card_url") or ""), quote=True)
        strip = html.escape(str(st.get("strip_url") or ""), quote=True)
        imgs = []
        if glance:
            imgs.append(f'<img src="{glance}" alt="介紹圖" class="stock-img" loading="lazy">')
        if card:
            imgs.append(f'<img src="{card}" alt="決策卡" class="stock-img" loading="lazy">')
        if not imgs and strip:
            imgs.append(f'<img src="{strip}" alt="圖表" class="stock-img" loading="lazy">')
        from stock_links import yahoo_hop_url

        hop = yahoo_hop_url(sid)
        if not imgs:
            continue
        safe_sid = html.escape(sid, quote=True)
        hop_bit = (
            f'<a class="y" href="{html.escape(hop, quote=True)}">奇摩</a>'
            if hop
            else ""
        )
        pick = (
            f'<label class="pick"><input class="stock-pick" type="checkbox" value="{safe_sid}" checked>'
            f"<span>{name}</span></label>{hop_bit}"
        )
        stock_blocks.append(
            f'<article class="stock-card" data-sid="{safe_sid}">{pick}{"".join(imgs)}</article>'
        )
    stocks_html = "\n".join(stock_blocks)
    album_block = (
        f'<img id="album" src="{safe_album}" alt="全區長圖" class="album">'
        if safe_album
        else ""
    )
    text_only_note = ""
    if text_only:
        text_only_note = (
            '<p style="text-align:center;color:#b45309;font-size:0.95em">'
            "圖已過期，請回 Telegram 再按一次「一鍵傳 LINE」。</p>"
        )
    extra_script = (
        f'<script type="application/json" id="pickPayload">{payload_json}</script>'
        + _line_picker_script()
    )
    album_btn = (
        f'<a class="btn blue" id="saveAlbum" href="{safe_album}" download="waynebot.png">分享全區長圖</a>'
        if safe_album
        else ""
    )
    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}｜WayneBot LINE</title>"
        "<style>"
        "body{font-family:-apple-system,sans-serif;margin:0 auto;padding:8px;"
        "max-width:390px;background:#fafafa;color:#111;font-size:16px}"
        ".btn{display:inline-block;margin:4px;padding:10px 12px;border-radius:10px;"
        "text-decoration:none;font-weight:600;border:none;font-size:15px}"
        ".green{background:#06c755;color:#fff}.blue{background:#1e6fff;color:#fff}"
        ".ghost{background:#eef2f7;color:#111}"
        ".stock-card{margin:0 0 0.55em;padding:0 0 0.45em;border-bottom:1px solid #e5e7eb}"
        ".pick{display:flex;align-items:center;gap:8px;font-weight:700;margin:0 0 4px}"
        ".pick input{width:22px;height:22px;flex:none}"
        "a.y{font-size:13px;color:#1e6fff;margin-left:6px}"
        ".stance{color:#c41e3a;font-weight:700}"
        ".summary .stance{color:#c41e3a;font-weight:700}"
        ".stock-img{width:100%;max-width:100%;max-height:168px;object-fit:contain;"
        "object-position:top;display:block;margin:0 auto 4px;border-radius:6px;"
        "background:#fff;border:1px solid #e8ecf0}"
        ".album{width:100%;max-width:100%;max-height:168px;object-fit:contain;"
        "display:block;margin:0.5em auto;border-radius:6px}"
        ".summary{white-space:pre-wrap;font-size:15px;line-height:1.45;background:#fff;padding:8px;"
        "border-radius:8px;border:1px solid #e0e0e0;margin:6px 0}"
        ".toolbar{text-align:center;margin:4px 0}"
        "h2{font-size:1.15em;margin:0 0 4px}"
        "p.hint{text-align:center;line-height:1.4;margin:0 0 6px;font-size:14px;color:#334155}"
        "</style>"
        "</head><body>"
        f"<h2 style=\"text-align:center\">{title}　{count} 檔</h2>"
        "<p class=\"hint\">勾要傳的檔（介紹圖＋決策卡）。圖是縮圖，傳出仍是完整卡 → LINE → 選聯絡人。</p>"
        f"{text_only_note}"
        '<p class="toolbar">'
        '<button class="btn ghost" id="pickAll" type="button">全選</button>'
        '<button class="btn ghost" id="pickNone" type="button">全不選</button>'
        '<span id="pickCount" style="display:inline-block;margin:8px 4px;color:#334155">已勾 0 檔</span>'
        "</p>"
        '<p class="toolbar">'
        '<button class="btn green" id="shareLine" type="button">複製勾選名單到 LINE</button>'
        '<button class="btn green" id="sharePicked" type="button">傳勾選的圖到 LINE</button>'
        f"{album_btn}"
        "</p>"
        '<details><summary style="font-weight:600">名單文字</summary>'
        f'<div class="summary">{safe_text}</div></details>'
        f'<div style="max-width:390px;margin:0 auto">{stocks_html}</div>'
        f"{album_block}"
        f"{extra_script}"
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
                        format_line_stock_block(item, 1, db_path, bucket_key=bucket),
                    ]
                )
        return ""
    except Exception:
        return ""


# 相容舊測試／呼叫
def render_line_hop_html(title: str, text: str) -> str:
    del title
    return render_line_redirect_html(text)


def render_yahoo_hop_html(stock_id: str, stock_name: str = "", db_path: str = "") -> str:
    """點開立刻進該檔奇摩報價（股名＋現價）。不放 og:image；不用 HTTP 302，避免 LINE 預覽跟著抓奇摩大圖。"""
    from stock_links import line_yahoo_quote_url

    sid = str(stock_id or "").strip()
    name = str(stock_name or "").strip()
    target = line_yahoo_quote_url(sid, db_path)
    if not sid or not target:
        return "<!DOCTYPE html><html><body>查無代號</body></html>"
    label = html.escape(f"{sid} {name}".strip())
    safe = html.escape(target, quote=True)
    js_url = json.dumps(target, ensure_ascii=False)
    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{label}</title>"
        f"<script>location.replace({js_url});</script>"
        "</head><body>"
        f'<p style="font-family:sans-serif;text-align:center;margin-top:2em">'
        f"正在開啟 {label} 奇摩報價…</p>"
        '<p style="text-align:center">'
        f'<a href="{safe}">若沒跳轉，點這裡開 {label}</a></p>'
        "</body></html>"
    )
