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


def _blend(a, b, t: float):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _lighten(rgb, amt: float = 0.18):
    return _blend(rgb, (255, 255, 255), amt)


def _darken(rgb, amt: float = 0.18):
    return _blend(rgb, (0, 0, 0), amt)


def _ink_box(font, text: str):
    bbox = font.getbbox(str(text or ""))
    return bbox[0], bbox[1], bbox[2], bbox[3]


def centered_text_xy(font, text: str, box) -> tuple:
    """ImageDraw.text 原點：讓真實墨水框的中心對上 box 幾何中心。"""
    x0, y0, x1, y1 = box
    l, t, r, b = _ink_box(font, text)
    tw, th = r - l, b - t
    return x0 + (x1 - x0 - tw) / 2.0 - l, y0 + (y1 - y0 - th) / 2.0 - t


def _chip_wh(font, tag: str, *, pad_x: int = 18, height: int = 46) -> tuple:
    l, _t, r, _b = _ink_box(font, tag)
    return int(round((r - l) + pad_x * 2)), height


def draw_fine_chip(im, box, text: str, bg, bd, fg, font) -> None:
    """膠囊小框：外光＋陰影＋垂直漸層＋內高光，文字用 mm 錨點上下左右居中。"""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    x0, y0, x1, y1 = (int(round(v)) for v in box)
    w, h = max(8, x1 - x0), max(8, y1 - y0)
    rad = h / 2.0
    pad = 10
    layer = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))

    glow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(
        (pad - 2, pad - 1, pad + w + 2, pad + h + 3),
        radius=rad + 2,
        fill=bd + (70,),
    )
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(3.0)))

    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        (pad, pad + 4, pad + w, pad + h + 4),
        radius=rad,
        fill=(0, 0, 0, 140),
    )
    layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(2.4)))

    body = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    bd_draw = ImageDraw.Draw(body)
    for yy in range(h):
        t = yy / max(h - 1, 1)
        col = _blend(_lighten(bg, 0.38), _darken(bg, 0.22), t) + (255,)
        bd_draw.line([(pad, pad + yy), (pad + w - 1, pad + yy)], fill=col)
    mask = Image.new("L", layer.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (pad, pad, pad + w, pad + h), radius=rad, fill=255
    )
    body.putalpha(mask)
    layer.alpha_composite(body)

    gloss = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    gh = max(8, int(h * 0.42))
    ImageDraw.Draw(gloss).rounded_rectangle(
        (pad + 2, pad + 2, pad + w - 2, pad + gh),
        radius=max(4, rad - 4),
        fill=(255, 255, 255, 22),
    )
    r, g, b, a = gloss.split()
    gloss = Image.merge("RGBA", (r, g, b, ImageChops.multiply(a, mask)))
    layer.alpha_composite(gloss)

    ink = ImageDraw.Draw(layer)
    inner = (pad, pad, pad + w, pad + h)
    ink.rounded_rectangle(inner, radius=rad, outline=_lighten(bd, 0.12) + (255,), width=2)
    ink.rounded_rectangle(
        (pad + 2, pad + 2, pad + w - 2, pad + h - 2),
        radius=max(2, rad - 2),
        outline=(255, 255, 255, 55),
        width=1,
    )
    cx = pad + w / 2.0
    cy = pad + h / 2.0 + 2  # CJK 視覺中心略低於 em 盒中線
    ink.text((cx, cy), text, font=font, fill=fg + (255,), anchor="mm")

    dest = (x0 - pad, y0 - pad)
    if im.mode != "RGBA":
        rgba = im.convert("RGBA")
        rgba.alpha_composite(layer, dest)
        im.paste(rgba.convert(im.mode))
    else:
        im.alpha_composite(layer, dest)


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
    k = 0
    while k < len(out):
        cur = out[k]
        starts_punct = bool(cur) and cur[0] in "。、；：），,．"
        orphan = bool(cur.strip()) and (len(cur.strip()) <= 2 or starts_punct)
        if orphan and k > 0:
            joined = out[k - 1] + cur
            if font.getlength(joined) <= max_w or starts_punct:
                out[k - 1] = joined
                out.pop(k)
                k = max(0, k - 1)
                continue
            if len(out[k - 1]) >= 2:
                out[k] = out[k - 1][-1] + cur
                out[k - 1] = out[k - 1][:-1]
        k += 1
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
    allow_fetch: bool = False,
    max_fetch: int = 1,
) -> str:
    from PIL import Image, ImageDraw

    path = db_path or get_db_path()
    snap = attach_fine_industry(
        industry_snapshot(path, stock_id), path, allow_fetch=allow_fetch, max_fetch=max_fetch
    )
    sid = str(snap["stock_id"])
    name = str(snap["stock_name"] or sid)
    charts = get_charts_dir()
    os.makedirs(charts, exist_ok=True)
    out = save_path or os.path.join(charts, f"{sid}_industry.png")

    W = 1080
    pad_x = 48
    max_w = W - pad_x * 2
    title_f = _card_font(48, bold=True)
    head_f = _card_font(34, bold=True)
    body_f = _card_font(32)
    chip_f = _card_font(26, bold=True)
    line_h = 48
    head_h = 58
    CHIP_H = 48
    CHIP_GAP = 12

    BG = (12, 18, 28)
    CARD = (22, 34, 48)
    CARD_EDGE = (78, 118, 158)
    CARD_INNER = (40, 58, 78)
    TEXT = (236, 242, 248)
    HEAD = (132, 208, 255)
    MUTED = (168, 186, 204)
    tags0 = list(snap.get("fine_tags") or [])
    items: List[tuple] = [("banner", sid, name, tags0)]
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
        if tags0:
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
                    tag = str(r.get("fine_finest") or "").strip()
                    items.append(
                        (
                            "peer_inline",
                            str(r["stock_id"]),
                            str(r["stock_name"]),
                            float(r.get("yoy") or 0),
                            [tag] if tag else [],
                        )
                    )

            _peer_items("較強", snap["stronger"])
            _peer_items("較弱", snap["weaker"])
            if any((r.get("fine_finest") or "") for r in (snap["stronger"] + snap["weaker"])):
                items.append(("muted", "小框是籌碼K細項；年增對照仍是證交所同一產業別全組。"))

    from industry_fine import chip_color

    def _chip_row_h(tags: List[str], start_x: float) -> int:
        if not tags:
            return 0
        x = start_x
        rows = 1
        for tag in tags:
            w, _h = _chip_wh(chip_f, tag, height=CHIP_H)
            if x > start_x and x + w > pad_x + max_w:
                x = start_x
                rows += 1
            x += w + CHIP_GAP
        return rows * (CHIP_H + 10)

    y = 36
    measured: List[tuple] = []
    for item in items:
        kind = item[0]
        if kind == "banner":
            tags = item[3]
            name_txt = f"{item[1]} {item[2]}"
            name_w = title_f.getlength(name_txt)
            h = 62 + 14 + max(62, _chip_row_h(tags, pad_x + name_w + 18) or 62)
            measured.append((kind, item, h))
            y += h
        elif kind == "peer_inline":
            tags = item[4]
            left = f"{item[1]}  {item[2]}"
            left_w = body_f.getlength(left)
            h = max(line_h, _chip_row_h(tags, pad_x + left_w + 14) or line_h)
            measured.append((kind, item, h + 10))
            y += h + 10
        elif kind == "h":
            measured.append((kind, item, head_h + 10))
            y += head_h + 10
        else:
            wraps = _wrap_px(item[1], body_f, max_w)
            h = len(wraps) * line_h
            measured.append((kind, item, h))
            y += h

    H = y + 64
    im = Image.new("RGBA", (W, H), BG + (255,))
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle((18, 14, W - 18, H - 14), radius=30, fill=CARD + (255,))
    dr.rounded_rectangle((18, 14, W - 18, H - 14), radius=30, outline=CARD_EDGE + (255,), width=2)
    dr.rounded_rectangle((22, 18, W - 22, H - 18), radius=26, outline=CARD_INNER + (180,), width=1)
    cy = 42

    def _chips_at(x0: float, mid_y: float, tags: List[str], max_right: float) -> float:
        """mid_y＝列的垂直中線；小框貼齊這條中線。"""
        x = x0
        y = mid_y - CHIP_H / 2.0
        row_bottom = y + CHIP_H
        for tag in tags:
            w, h = _chip_wh(chip_f, tag, height=CHIP_H)
            if x > x0 and x + w > max_right:
                x = x0
                y = row_bottom + 10
            bg, bd, fg = chip_color(tag)
            draw_fine_chip(im, (x, y, x + w, y + h), tag, bg, bd, fg, chip_f)
            x += w + CHIP_GAP
            row_bottom = max(row_bottom, y + h)
        return row_bottom if tags else mid_y + CHIP_H / 2.0

    def _text_mid_y(font, text: str, y_top: float) -> float:
        l, t, r, b = _ink_box(font, text)
        return y_top + (t + b) / 2.0

    for kind, item, _h in measured:
        if kind == "banner":
            kicker = "產業說明"
            tx, ty = centered_text_xy(head_f, kicker, (pad_x, cy, W - pad_x, cy + 48))
            dr.text((tx, ty), kicker, font=head_f, fill=HEAD + (255,))
            cy += 52
            name_txt = f"{item[1]} {item[2]}"
            name_box_h = 58
            nx, ny = centered_text_xy(
                title_f, name_txt, (pad_x, cy, pad_x + title_f.getlength(name_txt) + 2, cy + name_box_h)
            )
            dr.text((nx, ny), name_txt, font=title_f, fill=TEXT + (255,))
            tags = item[3]
            if tags:
                mid = _text_mid_y(title_f, name_txt, ny)
                chip_x = pad_x + title_f.getlength(name_txt) + 18
                end_y = _chips_at(chip_x, mid, tags, pad_x + max_w)
                cy = max(cy + name_box_h, end_y + 12)
            else:
                cy += name_box_h
            cy += 6
        elif kind == "h":
            cy += 10
            bar_y0 = cy + 10
            bar_y1 = cy + head_h - 16
            dr.rounded_rectangle(
                (pad_x, bar_y0, pad_x + 8, bar_y1),
                radius=4,
                fill=HEAD + (255,),
            )
            hx, hy = centered_text_xy(
                head_f, item[1], (pad_x + 20, cy, pad_x + 20 + head_f.getlength(item[1]) + 4, cy + head_h - 6)
            )
            dr.text((hx, hy), item[1], font=head_f, fill=HEAD + (255,))
            cy += head_h
        elif kind == "peer_inline":
            left = f"{item[1]}  {item[2]}"
            pct = f"{item[3]:+.1f}%"
            lx, ly = centered_text_xy(
                body_f, left, (pad_x, cy, pad_x + body_f.getlength(left) + 2, cy + line_h)
            )
            dr.text((lx, ly), left, font=body_f, fill=TEXT + (255,))
            pct_w = body_f.getlength(pct)
            px, py = centered_text_xy(
                body_f, pct, (pad_x + max_w - pct_w, cy, pad_x + max_w, cy + line_h)
            )
            tags = item[4]
            if tags:
                mid = _text_mid_y(body_f, left, ly)
                end_y = _chips_at(
                    pad_x + body_f.getlength(left) + 14,
                    mid,
                    tags,
                    pad_x + max_w - pct_w - 16,
                )
                dr.text((px, py), pct, font=body_f, fill=TEXT + (255,))
                cy = max(cy + line_h, end_y + 10)
            else:
                dr.text((px, py), pct, font=body_f, fill=TEXT + (255,))
                cy += line_h
        else:
            fill = MUTED if kind == "muted" else TEXT
            for ln in _wrap_px(item[1], body_f, max_w):
                tx, ty = centered_text_xy(
                    body_f, ln, (pad_x, cy, pad_x + body_f.getlength(ln) + 2, cy + line_h)
                )
                dr.text((tx, ty), ln, font=body_f, fill=fill + (255,))
                cy += line_h
    im.convert("RGB").save(out, "PNG", optimize=True)
    return out

