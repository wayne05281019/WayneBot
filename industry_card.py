"""產業說明圖卡：深底、大字、細項小框。話筒文字氣泡太擠時改送這張。"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from industry_brief import attach_fine_industry, industry_snapshot, _vs_peer

try:
    from config import get_charts_dir, get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"

    def get_charts_dir():
        return os.path.join("data", "charts")


def _card_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    try:
        from wayne_navigator import _WEIGHT_BOLD, _WEIGHT_TEXT, _weight_font_path

        path = _weight_font_path(_WEIGHT_BOLD if bold else _WEIGHT_TEXT)
        if path:
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    for path in (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ):
        try:
            return ImageFont.truetype(path, size, index=0)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap_px(text: str, font, max_w: float) -> List[str]:
    raw = str(text or "")
    if not raw:
        return [""]
    out: List[str] = []
    cur = ""
    for ch in raw:
        trial = cur + ch
        if font.getlength(trial) <= max_w:
            cur = trial
        else:
            if cur:
                out.append(cur)
            cur = ch
    if cur:
        out.append(cur)
    return out or [""]


def _flow_lines(snap: Dict[str, Any]) -> List[str]:
    as_of = snap["as_of"]
    as_s = f"{as_of[:4]}/{as_of[4:6]}/{as_of[6:]}" if len(str(as_of or "")) == 8 else (as_of or "—")
    three = int(snap["three_net"] or 0)
    if three > 0 and snap["industry"] in (snap.get("inflow") or []):
        flow_story = "本產業今天在法人買超最多的前3大族群產業裡。"
    elif three < 0 and snap["industry"] in (snap.get("outflow") or []):
        flow_story = "本產業今天在法人賣超最多的前3大族群產業裡。"
    elif three > 0:
        flow_story = "本產業法人合計買超，但還不是當日最熱的前3大族群產業。"
    elif three < 0:
        flow_story = "本產業法人合計賣超。"
    else:
        flow_story = "本產業法人加總接近 0，或法人還沒寫進這天。"
    streak_line = ""
    if int(snap.get("buy_streak") or 0) >= 2:
        streak_line = f"本產業法人連 {int(snap['buy_streak'])} 個交易日合計買超"
    elif int(snap.get("sell_streak") or 0) >= 2:
        streak_line = f"本產業法人連 {int(snap['sell_streak'])} 個交易日合計賣超"
    elif int(snap.get("buy_streak") or 0) == 1:
        streak_line = "本產業今天合計買超（尚未連兩日）"
    elif int(snap.get("sell_streak") or 0) == 1:
        streak_line = "本產業今天合計賣超（尚未連兩日）"
    sign = "+" if three > 0 else ""
    lines = [f"基準日：{as_s}", f"法人合計：{sign}{three:,}張", flow_story]
    if streak_line:
        lines.append(streak_line)
    return lines


def render_industry_png(
    stock_id: str,
    db_path: str = None,
    save_path: str = None,
    *,
    allow_fetch: bool = True,
) -> str:
    from PIL import Image, ImageDraw

    path = db_path or get_db_path()
    snap = attach_fine_industry(industry_snapshot(path, stock_id), path, allow_fetch=allow_fetch)
    sid = str(snap["stock_id"])
    name = str(snap["stock_name"] or sid)
    charts = get_charts_dir()
    os.makedirs(charts, exist_ok=True)
    out = save_path or os.path.join(charts, f"{sid}_industry.png")

    W = 1080
    pad_x = 44
    max_w = W - pad_x * 2
    title_f = _card_font(48, bold=True)
    head_f = _card_font(36, bold=True)
    body_f = _card_font(32)
    chip_f = _card_font(26, bold=True)
    line_h = 46
    head_h = 56

    BG = (15, 22, 32)
    CARD = (24, 37, 51)
    TEXT = (236, 242, 248)
    HEAD = (120, 200, 255)
    MUTED = (168, 186, 204)
    CHIP_BG = (18, 48, 72)
    CHIP_BD = (90, 180, 230)
    CHIP_FG = (220, 242, 255)

    items: List[tuple] = [("title", f"產業說明　{sid} {name}")]
    if snap.get("is_etf"):
        items.append(("h", "這檔是 ETF／指數商品"))
        items.append(("p", "沒有單一公司的產業面。看成分與資金頁即可。"))
    else:
        ind = snap["industry"] or "未分類（母體還沒寫到產業）"
        items.append(("h", "這檔是什麼"))
        items.append(("p", f"產業：{ind}"))
        items.append(
            ("p", f"同業：{snap['peer_n']}家現股（不含ETF）" if snap["peer_n"] else "同業名單不足")
        )
        if snap.get("fine_tags"):
            items.append(("chips", list(snap["fine_tags"])))
            items.append(("muted", "細項來自籌碼K公開個股頁"))
        items.append(("muted", "產業名來自證交所／櫃買公司基本資料產業別。"))
        items.append(("muted", "同業＝同一官方產業別全組，不是更細的產品線。"))
        if ind == "半導體業":
            items.append(("muted", "半導體業含代工、記憶體、設計，不是只跟晶圓代工比。"))

        month = str(snap.get("month") or "")
        mlabel = f"{month[:4]}/{month[4:]}" if len(month) >= 6 else (month or "—")
        items.append(("h", "營收看同業"))
        items.append(("p", f"月營收：{mlabel}"))
        if snap["my_yoy"] is not None:
            items.append(("p", f"這檔年增：{snap['my_yoy']:+.1f}%"))
            if snap["my_mom"] is not None:
                items.append(("p", f"這檔月增：{snap['my_mom']:+.1f}%"))
            if snap["yoy_med"] is not None:
                items.append(
                    ("p", f"同業中位年增：{snap['yoy_med']:+.1f}%（{snap['yoy_n']}家有月報）")
                )
            items.append(("p", _vs_peer(snap["my_yoy"], snap["yoy_med"], "%")))
        else:
            items.append(("p", "這檔還沒有月營收列"))
        if snap["my_gm"] is not None:
            items.append(("p", f"季報：{snap['year']}Q{snap['season']}"))
            items.append(("p", f"這檔毛利率：{snap['my_gm']:.1f}%"))
            if snap["gm_med"] is not None:
                items.append(("p", f"同業中位毛利率：{snap['gm_med']:.1f}%"))
            items.append(("p", _vs_peer(snap["my_gm"], snap["gm_med"], "pt")))
        else:
            items.append(("p", "這檔還沒有季報列"))

        items.append(("h", "本族群產業狀況簡述"))
        for ln in _flow_lines(snap):
            items.append(("p", ln))

        if snap["stronger"] or snap["weaker"]:
            items.append(("h", "同業月營收對照"))

            def _peer_items(label: str, rows: List[Dict[str, Any]]) -> None:
                items.append(("p", label))
                if not rows:
                    items.append(("muted", "—"))
                    return
                for r in rows:
                    yoy = float(r.get("yoy") or 0)
                    tag = str(r.get("fine_finest") or "").strip()
                    line = f"{r['stock_id']}  {r['stock_name']}  {yoy:+.1f}%"
                    if tag:
                        items.append(("peer", line, [tag]))
                    else:
                        items.append(("p", line))

            _peer_items("較強", snap["stronger"])
            _peer_items("較弱", snap["weaker"])
            if any((r.get("fine_finest") or "") for r in (snap["stronger"] + snap["weaker"])):
                items.append(("muted", "小框是籌碼K細項；年增對照仍是證交所同一產業別全組。"))

    y = 36
    measured: List[tuple] = []
    for item in items:
        kind = item[0]
        if kind == "chips":
            x = 0
            rows_h = 44
            for tag in item[1]:
                tw = chip_f.getlength(tag) + 28
                if x and x + tw > max_w:
                    x = 0
                    rows_h += 52
                x += tw + 12
            measured.append((kind, item, rows_h + 8))
            y += rows_h + 8
        elif kind == "peer":
            extra = 44 if item[2] else 0
            wraps = _wrap_px(item[1], body_f, max_w)
            h = len(wraps) * line_h + extra
            measured.append((kind, item, h))
            y += h
        elif kind == "h":
            measured.append((kind, item, head_h + 8))
            y += head_h + 8
        elif kind == "title":
            wraps = _wrap_px(item[1], title_f, max_w)
            h = len(wraps) * 58 + 12
            measured.append((kind, item, h))
            y += h
        else:
            wraps = _wrap_px(item[1], body_f, max_w)
            h = len(wraps) * line_h
            measured.append((kind, item, h))
            y += h

    H = y + 56
    im = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle((20, 16, W - 20, H - 16), radius=28, fill=CARD)
    cy = 40

    def _chips_at(x0: float, y0: float, tags: List[str], max_right: float) -> float:
        x, y = x0, y0
        chip_h = 40
        for tag in tags:
            tw = chip_f.getlength(tag)
            w = tw + 28
            if x > x0 and x + w > max_right:
                x = x0
                y += chip_h + 10
            dr.rounded_rectangle(
                (x, y, x + w, y + chip_h),
                radius=10,
                fill=CHIP_BG,
                outline=CHIP_BD,
                width=2,
            )
            dr.text((x + 14, y + 6), tag, font=chip_f, fill=CHIP_FG)
            x += w + 12
        return y + chip_h

    for kind, item, _h in measured:
        if kind == "title":
            for ln in _wrap_px(item[1], title_f, max_w):
                dr.text((pad_x, cy), ln, font=title_f, fill=TEXT)
                cy += 58
            cy += 12
        elif kind == "h":
            cy += 8
            dr.text((pad_x, cy), item[1], font=head_f, fill=HEAD)
            cy += head_h
        elif kind == "chips":
            cy = _chips_at(pad_x, cy, item[1], pad_x + max_w) + 12
        elif kind == "peer":
            for ln in _wrap_px(item[1], body_f, max_w):
                dr.text((pad_x, cy), ln, font=body_f, fill=TEXT)
                cy += line_h
            if item[2]:
                cy = _chips_at(pad_x, cy, item[2], pad_x + max_w) + 8
        else:
            fill = MUTED if kind == "muted" else TEXT
            for ln in _wrap_px(item[1], body_f, max_w):
                dr.text((pad_x, cy), ln, font=body_f, fill=fill)
                cy += line_h
    im.save(out, "PNG", optimize=True)
    return out
