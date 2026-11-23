"""主題鏈「加層、不換底」本機樣張（HTML→PNG）。

底標：籌碼K／櫃買 ``stock_fine_industry``（主／次／鏈）照舊。
加層：全景五大頁視圖＋★只認 ``industry_fine.TAUGHT_GROUPS`` 已教過檔號。
不准用主題鏈名單覆蓋全市場底標；非買訊；僅本機預覽，不上話筒。
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from industry_fine import TAUGHT_GROUPS, extra_tags_for, get_db_path, split_chain

TAIPEI = ZoneInfo("Asia/Taipei")
UA = {"User-Agent": "Mozilla/5.0 (WayneBot theme-chain-preview)"}

# 樣張用：04 頁結構對齊使用者附圖；★ 仍只依 TAUGHT_GROUPS，對不上不准發明。
PAGE04_FLOW = ("建置", "供電", "能源", "冷卻")
PAGE04_SEGMENTS: Tuple[Dict[str, Any], ...] = (
    {
        "side": "01 建置",
        "groups": (
            {
                "title": "廠務工程",
                "taught_tag": "無塵室",
                "sids": ("2404", "6139", "6196"),
            },
        ),
    },
    {
        "side": "02 供電",
        "groups": (
            {
                "title": "重電",
                "taught_tag": "重電",
                "sids": ("1519", "1513", "4588", "1503", "1514", "2371"),
            },
        ),
    },
    {
        "side": "03 能源",
        "groups": (
            {
                "title": "風電／材料",
                "taught_tag": "",  # 世紀鋼／上緯不在 TAUGHT_GROUPS → 無★
                "sids": ("9958", "3708"),
            },
        ),
    },
    {
        "side": "04 冷卻",
        "groups": (
            {
                "title": "散熱",
                "taught_tag": "散熱",
                # 8996 高力＝題材觀察，不在 TAUGHT_GROUPS → 不准標★
                "sids": ("3017", "3653", "3324", "6933", "8996"),
            },
        ),
    },
)


@dataclass(frozen=True)
class Quote:
    sid: str
    name: str
    close: float
    change: float
    pct: float
    volume_shares: int
    market: str
    source: str

    @property
    def has_official_close(self) -> bool:
        return self.close > 0 and self.volume_shares > 0


def _taught_sid_set() -> frozenset:
    out: set = set()
    for members in TAUGHT_GROUPS.values():
        out.update(str(x) for x in members)
    return frozenset(out)


def is_taught(sid: str) -> bool:
    return str(sid).strip() in _taught_sid_set()


def taught_tags(sid: str) -> List[str]:
    return list(extra_tags_for(sid))


def _clean_num(raw: Any, is_float: bool = True) -> float:
    s = str(raw or "").strip().replace(",", "").replace("%", "")
    if not s or s in {"--", "---", "－", "—"}:
        return 0.0
    s = s.replace("+", "")
    try:
        return float(s) if is_float else float(int(float(s)))
    except ValueError:
        return 0.0


def _http_json(url: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _parse_twse_sign_diff(sign_raw: Any, diff_raw: Any) -> float:
    diff = abs(_clean_num(diff_raw, is_float=True))
    blob = str(sign_raw or "")
    if "-" in blob or "跌" in blob or "green" in blob.lower():
        return -diff
    if "+" in blob or "漲" in blob or "red" in blob.lower():
        return diff
    # 平盤：sign 空白
    if diff == 0:
        return 0.0
    return diff


def fetch_official_quotes(as_of: str, sids: Iterable[str]) -> Dict[str, Quote]:
    """TWSE MI_INDEX + TPEx wn1430；V=0 或無收盤不上價。"""
    day = str(as_of or "").replace("-", "")[:8]
    want = {str(s).strip() for s in sids if str(s).strip()}
    out: Dict[str, Quote] = {}
    if not day or not want:
        return out

    twse = _http_json(
        "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
        f"?response=json&date={day}&type=ALLBUT0999"
    )
    if str(twse.get("stat") or "").upper() == "OK":
        for table in twse.get("tables") or []:
            fields = table.get("fields") or []
            if "收盤價" not in fields:
                continue
            for row in table.get("data") or []:
                if len(row) < 11:
                    continue
                sid = str(row[0]).strip()
                if sid not in want:
                    continue
                vol = int(_clean_num(row[2], is_float=False))
                close = _clean_num(row[8], is_float=True)
                chg = _parse_twse_sign_diff(row[9], row[10])
                if close <= 0 or vol <= 0:
                    continue
                ref = close - chg
                pct = round(chg / ref * 100.0, 2) if ref else 0.0
                out[sid] = Quote(
                    sid=sid,
                    name=str(row[1]).strip(),
                    close=close,
                    change=chg,
                    pct=pct,
                    volume_shares=vol,
                    market="TW",
                    source="twse:MI_INDEX",
                )

    yyyy, mm, dd = day[:4], day[4:6], day[6:]
    roc = f"{int(yyyy) - 1911}/{mm}/{dd}"
    tpex = _http_json(
        "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/"
        f"stk_wn1430_result.php?l=zh-tw&d={roc}&o=json&se=EW"
    )
    for table in tpex.get("tables") or []:
        for row in table.get("data") or []:
            if len(row) < 8:
                continue
            sid = str(row[0]).strip()
            if sid not in want or sid in out:
                continue
            close = _clean_num(row[2], is_float=True)
            chg = _clean_num(row[3], is_float=True)
            vol = int(_clean_num(row[7], is_float=False))
            if close <= 0 or vol <= 0:
                continue
            ref = close - chg
            pct = round(chg / ref * 100.0, 2) if ref else 0.0
            out[sid] = Quote(
                sid=sid,
                name=str(row[1]).strip().rstrip("*"),
                close=close,
                change=chg,
                pct=pct,
                volume_shares=vol,
                market="TWO",
                source="tpex:wn1430",
            )
    return out


def load_base_chain(sid: str, db_path: Optional[str] = None) -> str:
    """底標：stock_fine_industry.chain（籌碼K）。缺就空字串，不准自造。"""
    path = db_path or get_db_path()
    if not path or not os.path.isfile(path):
        return ""
    import sqlite3

    con = sqlite3.connect(path)
    try:
        row = con.execute(
            "SELECT chain FROM stock_fine_industry WHERE stock_id=? LIMIT 1",
            (str(sid).strip(),),
        ).fetchone()
    finally:
        con.close()
    return str(row[0]).strip() if row and row[0] else ""


def _fmt_price(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return f"{v:,.0f}.00" if v >= 100 else f"{v:.2f}"
    if v >= 100:
        return f"{v:,.2f}"
    return f"{v:.2f}"


def _chg_class(chg: float) -> str:
    if chg > 0:
        return "up"
    if chg < 0:
        return "down"
    return "flat"


def _chg_arrow(chg: float) -> str:
    if chg > 0:
        return "▲"
    if chg < 0:
        return "▼"
    return "○"


def _stock_card_html(q: Quote, *, star: bool) -> str:
    cls = _chg_class(q.change)
    star_s = '<span class="star">★</span> ' if star else ""
    name = html.escape(q.name)
    sid = html.escape(q.sid)
    price = html.escape(_fmt_price(q.close))
    pct = html.escape(f"{q.pct:+.2f}%")
    chg = html.escape(f"{q.change:+.2f}")
    arrow = _chg_arrow(q.change)
    return f"""
    <div class="stock">
      <div class="stock-top">{star_s}<span class="name">{name}</span>
        <span class="sid">{sid}</span></div>
      <div class="stock-mid">
        <span class="lbl">收</span>
        <span class="price {cls}">{price}</span>
        <span class="pct {cls}">{arrow} {pct}</span>
      </div>
      <div class="stock-bot">漲跌 {chg}</div>
    </div>"""


def build_lookup_layer_html(
    sid: str = "3017",
    as_of: str = "2026-11-23",
    quote: Optional[Quote] = None,
    base_chain: Optional[str] = None,
) -> str:
    """樣張 A：查股／產業卡一角——底標＋主題鏈加層並存。"""
    day = as_of.replace("-", "")[:8]
    day_dash = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    chain = base_chain if base_chain is not None else load_base_chain(sid)
    parts = split_chain(chain)
    base_face = " → ".join(parts) if parts else "（庫無底標）"
    tags = taught_tags(sid)
    theme = tags[0] if tags else ""
    theme_line = (
        f"主題鏈：{theme}（已教過★）"
        if theme
        else "主題鏈：—（此檔不在 TAUGHT_GROUPS）"
    )
    q = quote
    quote_block = ""
    if q and q.has_official_close:
        cls = _chg_class(q.change)
        quote_block = f"""
        <div class="quote-row">
          <span class="q-lbl">收</span>
          <span class="q-price {cls}">{html.escape(_fmt_price(q.close))}</span>
          <span class="q-pct {cls}">{_chg_arrow(q.change)} {html.escape(f"{q.pct:+.2f}%")}</span>
          <span class="q-chg">漲跌 {html.escape(f"{q.change:+.2f}")}</span>
        </div>
        <div class="src">官方收 {html.escape(day_dash)} · {html.escape(q.source)} · V={q.volume_shares:,}</div>
        """
    else:
        quote_block = '<div class="src miss">無官方收或 V=0，不上價</div>'

    name = (q.name if q else sid)
    star = "★ " if is_taught(sid) else ""
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<title>加層樣張 A · {html.escape(sid)}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 28px 32px;
    font-family: "Noto Sans TC", "Microsoft JhengHei", "PingFang TC", sans-serif;
    background: #f3f4f6; color: #1f2937;
  }}
  .card {{
    max-width: 720px; margin: 0 auto; background: #fff;
    border-radius: 16px; border: 1px solid #e5e7eb;
    padding: 22px 24px 20px; box-shadow: 0 1px 2px rgba(0,0,0,.04);
  }}
  .eyebrow {{ font-size: 13px; color: #6b7280; letter-spacing: .02em; }}
  .title {{ font-size: 26px; font-weight: 800; margin: 6px 0 14px; }}
  .title .star {{ color: #d97706; }}
  .layers {{ display: grid; gap: 10px; margin-bottom: 16px; }}
  .layer {{
    border-radius: 12px; padding: 12px 14px; border: 1px solid #e5e7eb;
  }}
  .layer.base {{ background: #f8fafc; }}
  .layer.theme {{
    background: linear-gradient(180deg, #f5f3ff 0%, #faf8ff 100%);
    border-color: #ddd6fe;
  }}
  .layer .k {{
    font-size: 12px; font-weight: 700; color: #6b7280; margin-bottom: 4px;
  }}
  .layer .v {{ font-size: 16px; font-weight: 700; line-height: 1.35; }}
  .layer.theme .v {{ color: #5b21b6; }}
  .note {{
    font-size: 12px; color: #6b7280; line-height: 1.55; margin: 0 0 14px;
  }}
  .quote-row {{
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px 14px;
    padding: 12px 0 4px; border-top: 1px solid #f3f4f6;
  }}
  .q-lbl {{ color: #9ca3af; font-size: 13px; }}
  .q-price {{ font-size: 28px; font-weight: 800; font-variant-numeric: tabular-nums; }}
  .q-pct {{ font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums; }}
  .q-chg {{ font-size: 13px; color: #6b7280; }}
  .up {{ color: #dc2626; }}
  .down {{ color: #059669; }}
  .flat {{ color: #6b7280; }}
  .src {{ font-size: 11px; color: #9ca3af; margin-top: 6px; }}
  .src.miss {{ color: #b45309; }}
  .badge {{
    display: inline-block; font-size: 11px; font-weight: 700;
    padding: 2px 8px; border-radius: 999px; background: #ede9fe; color: #5b21b6;
    margin-left: 8px; vertical-align: middle;
  }}
</style>
</head>
<body>
  <div class="card">
    <div class="eyebrow">樣張 A · 查股／產業卡示意 · 加層不換底 · 非買訊</div>
    <div class="title"><span class="star">{star}</span>{html.escape(name)}
      <span style="color:#9ca3af;font-size:18px;font-weight:600">{html.escape(sid)}</span>
      <span class="badge">預覽</span>
    </div>
    <div class="layers">
      <div class="layer base">
        <div class="k">底標（籌碼K／櫃買 stock_fine_industry · 全市場仍吃這套）</div>
        <div class="v">{html.escape(base_face)}</div>
      </div>
      <div class="layer theme">
        <div class="k">加層（主題鏈視圖 · ★只認 TAUGHT_GROUPS）</div>
        <div class="v">{html.escape(theme_line)}</div>
      </div>
    </div>
    <p class="note">兩層並存：洞燭法人％、查股同鏈比價繼續用底標；主題鏈全景／★龍頭是加視圖，不准用 ~71 檔覆蓋 1900+ 底標。金融／生技等不在主題圖的只看底標。</p>
    {quote_block}
  </div>
</body>
</html>"""


def build_panorama_page04_html(
    as_of: str,
    quotes: Dict[str, Quote],
) -> str:
    """樣張 B：04 能源、廠務與散熱主題鏈全景。"""
    day = as_of.replace("-", "")[:8]
    day_dash = f"{day[:4]}-{day[4:6]}-{day[6:]}"
    try:
        wd = datetime.strptime(day, "%Y%m%d").replace(tzinfo=TAIPEI).strftime("%a")
        wd_map = {
            "Mon": "一",
            "Tue": "二",
            "Wed": "三",
            "Thu": "四",
            "Fri": "五",
            "Sat": "六",
            "Sun": "日",
        }
        wd_zh = wd_map.get(wd, wd)
    except ValueError:
        wd_zh = "?"

    shown = 0
    segs_html: List[str] = []
    for seg in PAGE04_SEGMENTS:
        groups_html: List[str] = []
        for g in seg["groups"]:
            cards: List[str] = []
            for sid in g["sids"]:
                q = quotes.get(sid)
                if not q or not q.has_official_close:
                    continue
                cards.append(_stock_card_html(q, star=is_taught(sid)))
                shown += 1
            if not cards:
                continue
            n = len(cards)
            groups_html.append(
                f"""<div class="group">
              <div class="group-h"><span>{html.escape(g["title"])}</span>
                <span class="cnt">{n}檔</span></div>
              <div class="grid">{"".join(cards)}</div>
            </div>"""
            )
        if not groups_html:
            continue
        segs_html.append(
            f"""<div class="seg">
          <div class="side">{html.escape(seg["side"])}</div>
          <div class="seg-body">{"".join(groups_html)}</div>
        </div>"""
        )

    flow = " → ".join(PAGE04_FLOW)
    n_seg = len(segs_html)
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<title>主題鏈全景樣張 · 04</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 18px 20px 14px;
    font-family: "Noto Sans TC", "Microsoft JhengHei", "PingFang TC", sans-serif;
    background: #f7f5f2; color: #1f2937; width: 1080px;
  }}
  .head {{ display: flex; justify-content: space-between; align-items: baseline; }}
  .brand {{ font-size: 13px; color: #9ca3af; }}
  .meta {{ font-size: 13px; color: #6b7280; }}
  h1 {{
    margin: 10px 0 4px; font-size: 28px; font-weight: 800; color: #4c1d95;
  }}
  .flow {{ font-size: 13px; color: #6b7280; margin-bottom: 4px; }}
  .sum {{ font-size: 12px; color: #6b7280; margin-bottom: 8px; }}
  .legend {{ font-size: 11px; color: #9ca3af; margin-bottom: 12px; }}
  .banner {{
    font-size: 11px; color: #5b21b6; background: #f5f3ff; border: 1px solid #ddd6fe;
    border-radius: 8px; padding: 8px 10px; margin-bottom: 12px; line-height: 1.45;
  }}
  .seg {{
    display: grid; grid-template-columns: 56px 1fr; gap: 10px;
    margin-bottom: 12px; align-items: stretch;
  }}
  .side {{
    writing-mode: vertical-rl; text-orientation: mixed;
    background: #6d4c41; color: #fff; border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-weight: 800; font-size: 14px; letter-spacing: .12em; padding: 10px 0;
  }}
  .seg-body {{ display: flex; flex-direction: column; gap: 8px; }}
  .group {{
    background: #fff; border: 1px solid #e7e5e4; border-radius: 12px; overflow: hidden;
  }}
  .group-h {{
    display: flex; justify-content: space-between; align-items: center;
    background: #f5f0eb; padding: 7px 12px; font-size: 13px; font-weight: 700;
    color: #44403c;
  }}
  .cnt {{ font-weight: 600; color: #a8a29e; font-size: 12px; }}
  .grid {{
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 0;
  }}
  .stock {{
    padding: 10px 12px; border-top: 1px solid #f5f5f4;
    border-right: 1px solid #f5f5f4;
  }}
  .stock:nth-child(3n) {{ border-right: none; }}
  .stock-top {{ display: flex; align-items: baseline; gap: 6px; margin-bottom: 4px; }}
  .star {{ color: #d97706; font-size: 13px; }}
  .name {{ font-weight: 800; font-size: 14px; }}
  .sid {{ margin-left: auto; color: #a8a29e; font-size: 12px; font-variant-numeric: tabular-nums; }}
  .stock-mid {{
    display: flex; align-items: baseline; gap: 8px; font-variant-numeric: tabular-nums;
  }}
  .lbl {{ color: #a8a29e; font-size: 12px; }}
  .price {{ font-size: 18px; font-weight: 800; }}
  .pct {{ margin-left: auto; font-size: 14px; font-weight: 700; }}
  .stock-bot {{ font-size: 11px; color: #78716c; margin-top: 2px; }}
  .up {{ color: #dc2626; }}
  .down {{ color: #059669; }}
  .flat {{ color: #78716c; }}
  .foot {{
    margin-top: 8px; padding-top: 8px; border-top: 1px solid #e7e5e4;
    font-size: 10px; color: #a8a29e; line-height: 1.5;
  }}
</style>
</head>
<body>
  <div class="head">
    <div class="brand">台股產業鏈收盤全景</div>
    <div class="meta">{html.escape(day_dash)} 收盤 · 4/5</div>
  </div>
  <h1>04 能源、廠務與散熱</h1>
  <div class="flow">{html.escape(flow)}</div>
  <div class="sum">{n_seg} 個環節 · {shown} 檔 · 收盤價 (元) / 漲跌幅 (%)</div>
  <div class="legend">★ = TAUGHT_GROUPS 已教過（主題鏈加層）　無★ = 題材觀察／未教過　不准發明★</div>
  <div class="banner">樣張預覽 · 加層不換底：底標仍是籌碼K／櫃買全市場鏈；本頁只是主題鏈視圖。V=0 不上價。非買訊。未接話筒。</div>
  {"".join(segs_html)}
  <div class="foot">
    收盤日期 {html.escape(day_dash)} ({wd_zh})｜資料來源：TPEx 每日收盤、TWSE MI_INDEX<br/>
    紅 ▲ 上漲｜綠 ▼ 下跌｜○ 平盤｜僅供資訊參考，非投資建議<br/>
    按既有產業分類＋已教過主題鏈整理，非公司間供貨關係；閱讀順序不代表推薦排名。
  </div>
</body>
</html>"""


def _screenshot_html(html_str: str, out_png: str, *, width: int, height: int, dpr: float = 2.0) -> str:
    from playwright.sync_api import sync_playwright

    out = Path(out_png)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"]
        )
        page = browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=dpr,
        )
        page.set_content(html_str, wait_until="load")
        # 高度跟內容：用 full_page 避免裁切
        page.screenshot(path=str(out), full_page=True)
        browser.close()
    return str(out.resolve())


def render_preview_pair(
    out_dir: str,
    as_of: str = "2026-11-23",
    sid: str = "3017",
) -> Dict[str, str]:
    """渲 A（單檔加層卡）＋ B（04 全景）到 out_dir。"""
    sids: List[str] = [sid]
    for seg in PAGE04_SEGMENTS:
        for g in seg["groups"]:
            sids.extend(g["sids"])
    # unique keep order
    seen = set()
    ordered: List[str] = []
    for x in sids:
        if x not in seen:
            seen.add(x)
            ordered.append(x)

    quotes = fetch_official_quotes(as_of, ordered)
    base = load_base_chain(sid)
    q = quotes.get(sid)

    html_a = build_lookup_layer_html(sid=sid, as_of=as_of, quote=q, base_chain=base)
    html_b = build_panorama_page04_html(as_of=as_of, quotes=quotes)

    out_a = os.path.join(out_dir, "theme-chain-layer-A-3017.png")
    out_b = os.path.join(out_dir, "theme-chain-panorama-B-04.png")
    # also keep html beside for debug
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir, "theme-chain-layer-A-3017.html").write_text(html_a, encoding="utf-8")
    Path(out_dir, "theme-chain-panorama-B-04.html").write_text(html_b, encoding="utf-8")

    path_a = _screenshot_html(html_a, out_a, width=760, height=520, dpr=2.0)
    path_b = _screenshot_html(html_b, out_b, width=1100, height=1400, dpr=2.0)
    return {
        "A": path_a,
        "B": path_b,
        "quotes_n": str(len(quotes)),
        "base_chain": base,
        "taught": ",".join(taught_tags(sid)),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="主題鏈加層樣張 HTML→PNG")
    p.add_argument(
        "--out-dir",
        default="/opt/cursor/artifacts",
        help="PNG 輸出目錄",
    )
    p.add_argument("--as-of", default="2026-11-23")
    p.add_argument("--sid", default="3017")
    args = p.parse_args(list(argv) if argv is not None else None)
    info = render_preview_pair(args.out_dir, as_of=args.as_of, sid=args.sid)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
