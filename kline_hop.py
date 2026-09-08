# -*- coding: utf-8 -*-
"""查股圖下「K線」：自家一頁。先進即時日K＋成交量，可改 15／60 分與五日／十日／月／季。"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from stock_links import quote_market, tradingview_exchange

INTERVALS = ("D", "15", "60", "5D", "10D", "M", "Q")
_BAR_LIMIT = 1600

_PAGE = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>@@TITLE@@</title>
<style>
html,body{margin:0;height:100%;background:#f4f6f8;color:#1f2933;
font-family:"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;}
body{display:flex;flex-direction:column;min-height:100%;}
header{padding:10px 12px 2px}
h1{margin:0;font-size:18px;font-weight:700;letter-spacing:.02em}
.sub{margin:4px 0 0;font-size:13px;color:#546e7a;line-height:1.45}
nav{display:flex;flex-wrap:wrap;gap:6px;padding:8px 12px 10px}
nav button{appearance:none;border:1px solid #c5ced6;background:#fff;color:#1f2933;
border-radius:8px;padding:8px 11px;font-size:14px;line-height:1;min-height:40px}
nav button.on{background:#1565c0;border-color:#1565c0;color:#fff;font-weight:700}
#stage{flex:1;position:relative;min-height:320px;margin:0 8px 8px;background:#fff;
border:1px solid #d7dee4;border-radius:10px;overflow:hidden}
#tv,canvas{position:absolute;inset:0;width:100%;height:100%}
#empty{display:none;margin:3em 1.2em;text-align:center;color:#607d8b;font-size:15px}
.note{margin:0 12px 10px;font-size:12px;color:#78909c}
</style>
</head>
<body>
<header>
<h1>@@HEAD@@</h1>
<p class="sub">@@SUB@@</p>
</header>
<nav>
<button type="button" data-i="D">日K</button>
<button type="button" data-i="15">15分</button>
<button type="button" data-i="60">60分</button>
<button type="button" data-i="5D">五日</button>
<button type="button" data-i="10D">十日</button>
<button type="button" data-i="M">月線</button>
<button type="button" data-i="Q">季線</button>
</nav>
<div id="stage">
<div id="tv"></div>
<canvas id="own" hidden></canvas>
<p id="empty"></p>
</div>
<p class="note">不是買訊。高低卡／獲利不會畫在這張圖上。</p>
<script src="https://s3.tradingview.com/tv.js"></script>
<script>
var D=@@DATA@@;
var UP="#e53935", DN="#00897b";
function $(id){return document.getElementById(id);}
function setOn(key){
  document.querySelectorAll("nav button").forEach(function(b){
    b.classList.toggle("on", b.getAttribute("data-i")===key);
  });
}
function wipe(){
  var st=$("stage");
  st.innerHTML='<div id="tv"></div><canvas id="own" hidden></canvas><p id="empty"></p>';
}
function showEmpty(msg){
  $("tv").style.display="none";
  var cv=$("own"); cv.hidden=true; cv.style.display="none";
  var el=$("empty"); el.style.display="block"; el.textContent=msg;
}
function mountTv(iv){
  wipe();
  setOn(iv);
  if(typeof TradingView==="undefined"||!TradingView.widget){
    showEmpty("即時圖還在載入，請稍後再切一次日K／15分／60分。");
    return;
  }
  $("empty").style.display="none";
  new TradingView.widget({
    autosize:true,
    symbol:D.sym,
    interval:iv,
    timezone:"Asia/Taipei",
    theme:"light",
    style:"1",
    locale:"zh_TW",
    hide_top_toolbar:true,
    hide_side_toolbar:true,
    allow_symbol_change:false,
    save_image:false,
    calendar:false,
    hide_volume:false,
    withdateranges:false,
    enable_publishing:false,
    container_id:"tv",
    support_host:"https://www.tradingview.com"
  });
}
function ymd(t){
  var s=String(t||"").replace(/-/g,"").slice(0,8);
  if(s.length!==8) return t||"";
  return s.slice(0,4)+"/"+s.slice(4,6)+"/"+s.slice(6,8);
}
function drawOwn(bars){
  wipe();
  if(!bars||!bars.length){
    showEmpty("這檔還沒有日K可以疊五日／十日／月線／季線。");
    return;
  }
  $("empty").style.display="none";
  var cv=$("own");
  cv.hidden=false;
  cv.style.display="block";
  var box=$("stage");
  var w=Math.max(280, box.clientWidth||320);
  var h=Math.max(240, box.clientHeight||360);
  var dpr=window.devicePixelRatio||1;
  cv.width=Math.floor(w*dpr); cv.height=Math.floor(h*dpr);
  cv.style.width=w+"px"; cv.style.height=h+"px";
  var g=cv.getContext("2d");
  g.setTransform(dpr,0,0,dpr,0,0);
  g.fillStyle="#fff"; g.fillRect(0,0,w,h);
  var padL=48, padR=10, padT=12, gap=8, volH=Math.floor(h*0.22);
  var plotH=h-padT-volH-gap-22;
  var n=Math.min(bars.length, Math.max(12, Math.floor((w-padL-padR)/7)));
  var view=bars.slice(-n);
  var hi=-1e9, lo=1e9, vmax=1;
  view.forEach(function(b){
    if(b.h>hi)hi=b.h; if(b.l<lo)lo=b.l;
    if(b.v>vmax)vmax=b.v;
  });
  if(!(hi>lo)){hi=lo+1;}
  var slot=(w-padL-padR)/view.length;
  function yx(px){return padT+(hi-px)/(hi-lo)*plotH;}
  g.strokeStyle="#eceff1"; g.beginPath();
  for(var i=0;i<4;i++){
    var yy=padT+plotH*i/3;
    g.moveTo(padL,yy); g.lineTo(w-padR,yy);
  }
  g.stroke();
  g.font="11px sans-serif"; g.fillStyle="#78909c";
  g.fillText(hi.toFixed(hi>=100?1:2), 6, padT+10);
  g.fillText(lo.toFixed(lo>=100?1:2), 6, padT+plotH);
  view.forEach(function(b, i){
    var x=padL+slot*(i+0.5);
    var up=b.c>=b.o;
    g.strokeStyle=up?UP:DN; g.fillStyle=up?UP:DN;
    g.beginPath(); g.moveTo(x,yx(b.h)); g.lineTo(x,yx(b.l)); g.stroke();
    var y1=yx(Math.max(b.o,b.c)), y2=yx(Math.min(b.o,b.c));
    var bw=Math.max(3, slot*0.62);
    g.fillRect(x-bw/2, y1, bw, Math.max(1, y2-y1));
    var vh=Math.max(1, (b.v/vmax)*volH);
    var vy=padT+plotH+gap+(volH-vh);
    g.globalAlpha=0.85;
    g.fillRect(x-bw/2, vy, bw, vh);
    g.globalAlpha=1;
  });
  g.fillStyle="#90a4ae";
  g.fillText("量（張）", 6, padT+plotH+gap+12);
  var last=view[view.length-1];
  g.fillText(ymd(view[0].t), padL, h-6);
  g.textAlign="right";
  g.fillText(ymd(last.t), w-padR, h-6);
  g.textAlign="left";
}
function go(iv){
  setOn(iv);
  if(iv==="D"||iv==="15"||iv==="60"){ mountTv(iv); return; }
  drawOwn((D.packed||{})[iv]||[]);
}
document.querySelectorAll("nav button").forEach(function(b){
  b.addEventListener("click", function(){ go(b.getAttribute("data-i")); });
});
go(D.start||"D");
</script>
</body>
</html>
"""


def normalize_interval(raw: str) -> str:
    s = str(raw or "D").strip().upper()
    aliases = {
        "DAY": "D",
        "1D": "D",
        "日": "D",
        "日K": "D",
        "15M": "15",
        "60M": "60",
        "5": "5D",
        "10": "10D",
        "MON": "M",
        "MONTH": "M",
        "QTR": "Q",
        "3M": "Q",
    }
    s = aliases.get(s, s)
    return s if s in INTERVALS else "D"


def plain_market_label(stock_id: str, db_path: Optional[str] = None) -> str:
    m = quote_market(stock_id, db_path)
    if m in ("TWO", "TPEX", "OTC", "ROCO"):
        return "上櫃"
    if m in ("EM", "ESB", "EMERGING"):
        return "興櫃"
    return "上市"


def _ymd(raw: str) -> str:
    d = str(raw or "").replace("-", "").replace("/", "")[:8]
    return d if len(d) == 8 and d.isdigit() else ""


def _merge_bars(chunk: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "t": chunk[-1]["t"],
        "o": chunk[0]["o"],
        "h": max(b["h"] for b in chunk),
        "l": min(b["l"] for b in chunk),
        "c": chunk[-1]["c"],
        "v": int(round(sum(float(b["v"]) for b in chunk))),
    }


def aggregate_n_day(bars: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    """從最新往回每 n 根日K疊一根；最後一根是目前這段（可能不滿 n 日）。"""
    if n < 1 or not bars:
        return []
    chunks: List[List[Dict[str, Any]]] = []
    i = len(bars)
    while i > 0:
        start = max(0, i - n)
        chunks.append(bars[start:i])
        i = start
    chunks.reverse()
    return [_merge_bars(c) for c in chunks if c]


def aggregate_calendar(bars: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    key = None
    chunk: List[Dict[str, Any]] = []

    def _key(t: str) -> str:
        d = _ymd(t)
        if not d:
            return ""
        if kind == "M":
            return d[:6]
        month = int(d[4:6])
        return f"{d[:4]}Q{(month - 1) // 3 + 1}"

    for b in bars:
        k = _key(str(b.get("t") or ""))
        if not k:
            continue
        if key is None:
            key = k
        if k != key:
            groups.append(_merge_bars(chunk))
            chunk = [b]
            key = k
        else:
            chunk.append(b)
    if chunk:
        groups.append(_merge_bars(chunk))
    return groups


def load_daily_bars(
    stock_id: str, db_path: Optional[str] = None, limit: int = _BAR_LIMIT
) -> List[Dict[str, Any]]:
    sid = str(stock_id or "").strip()
    if not sid or not db_path:
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT date, open, high, low, close, volume
            FROM daily_quotes
            WHERE stock_id=?
            ORDER BY date DESC
            LIMIT ?;
            """,
            (sid, int(limit)),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for row in reversed(rows):
        d = _ymd(str(row["date"] or ""))
        try:
            o = float(row["open"])
            h = float(row["high"])
            l = float(row["low"])
            c = float(row["close"])
            v = float(row["volume"] or 0)
        except (TypeError, ValueError, KeyError):
            continue
        if not d or c <= 0:
            continue
        if h < max(o, c, l) or l > min(o, c, h):
            h = max(h, o, c)
            l = min(l, o, c)
        out.append({"t": d, "o": o, "h": h, "l": l, "c": c, "v": max(0, v)})
    return out


def _stock_name(stock_id: str, db_path: Optional[str] = None) -> str:
    sid = str(stock_id or "").strip()
    if not sid or not db_path:
        return ""
    try:
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT stock_name FROM daily_quotes WHERE stock_id=? ORDER BY date DESC LIMIT 1;",
            (sid,),
        ).fetchone()
        if not row:
            try:
                row = conn.execute(
                    "SELECT stock_name FROM stock_directory WHERE stock_id=? LIMIT 1;",
                    (sid,),
                ).fetchone()
            except Exception:
                row = None
        conn.close()
        return str((row[0] if row else "") or "").strip()
    except Exception:
        return ""


def packed_series(bars: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "5D": aggregate_n_day(bars, 5),
        "10D": aggregate_n_day(bars, 10),
        "M": aggregate_calendar(bars, "M"),
        "Q": aggregate_calendar(bars, "Q"),
    }


def render_kline_html(
    stock_id: str,
    db_path: str = "",
    interval: str = "D",
) -> str:
    sid = str(stock_id or "").strip()
    if not sid:
        return (
            "<!DOCTYPE html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            "<title>查無代號</title></head><body>查無代號</body></html>"
        )
    start = normalize_interval(interval)
    ex = tradingview_exchange(sid, db_path or None)
    name = _stock_name(sid, db_path or None)
    head = f"{sid} {name}".strip()
    if not ex:
        return (
            "<!DOCTYPE html><html lang='zh-Hant'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_esc(head or sid)}</title></head><body>"
            f"<p style='font-family:sans-serif;margin:2em;text-align:center'>"
            f"{_esc(head or sid)}　興櫃沒有這張即時K，請回 Telegram 看介紹圖與決策卡。"
            "</p></body></html>"
        )
    market = plain_market_label(sid, db_path or None)
    bars = load_daily_bars(sid, db_path or None)
    payload = {
        "sid": sid,
        "sym": f"{ex}:{sid}",
        "start": start,
        "packed": packed_series(bars),
    }
    sub = f"{market}　一進先鎖定即時日K，底下是成交量。可自己改 15 分／60 分，或五日／十日／月線／季線。"
    page = (
        _PAGE.replace("@@TITLE@@", _esc(f"{head}　K線"))
        .replace("@@HEAD@@", _esc(head))
        .replace("@@SUB@@", _esc(sub))
        .replace("@@DATA@@", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    )
    return page


def _esc(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
