"""產業說明圖卡：深底、大字、產業鏈小框、同鏈比價表。話筒文字氣泡太擠時改送這張。"""
from __future__ import annotations

import os
from typing import Any, Dict, List

from industry_brief import (
    attach_fine_industry,
    flow_story_lines,
    format_bijia_cells,
    format_month_zh,
    industry_snapshot,
    peer_mix_label,
    peer_note_line,
    _vs_peer,
)

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
    try:
        from trading_calendar import format_trading_date_zh

        as_s = format_trading_date_zh(as_of) or (as_of or "—")
    except Exception:
        as_s = f"{as_of[:4]}/{as_of[4:6]}/{as_of[6:]}" if len(str(as_of or "")) == 8 else (as_of or "—")
    try:
        from decision_card_signals import format_produced_clock

        produced = format_produced_clock()
    except Exception:
        produced = ""
    three = int(snap["three_net"] or 0)
    flow_story, streak_line = flow_story_lines(snap)
    sign = "+" if three > 0 else ""
    lines = [f"基準日：{as_s}"]
    if produced:
        lines.append(f"產出：{produced}")
    lines.extend([f"法人合計：{sign}{three:,}張", flow_story])
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
    listing = str(snap.get("listing") or "").strip()
    name_disp = f"{name}　{listing}" if listing else name
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
    items: List[tuple] = [("banner", sid, name_disp, tags0)]
    if snap.get("is_etf"):
        from universe import etf_card_kind_label

        kind = etf_card_kind_label(snap.get("asset_type") or "", sid)
        kind_txt = f"{kind} ETF" if kind else "ETF／指數商品"
        items.append(("h", f"這檔是{kind_txt}"))
        items.append(("p", "沒有單一公司的產業面。進場仍先看高低卡。成分股現在不畫。"))
    else:
        ind = snap["industry"] or "未分類（母體還沒寫到產業）"
        items.append(("h", "這檔是什麼"))
        items.append(("kv", "官方產業別", ind))
        chain = str(snap.get("fine_chain") or "").strip()
        if chain:
            items.append(("kv", "產業鏈", chain))
        extras = [str(t) for t in list(snap.get("extra_tags") or []) if str(t)]
        if extras:
            items.append(("kv", "跨族", "／".join(extras)))
        peer_lab = peer_mix_label(snap) if snap["peer_n"] else "名單不足"
        finest = str(snap.get("fine_finest") or "").strip()
        if finest and snap.get("peer_source") == "chain" and snap["peer_n"]:
            peer_lab = f"{peer_lab}（{finest}）"
        items.append(("kv", "同業", peer_lab))
        if tags0:
            items.append(("muted", "產業鏈來自籌碼K公開個股頁"))
            items.append(("muted", "同業＝同一產業鏈才比；跨族檔另標他還有的鏈。"))
        elif snap.get("peer_source") == "none":
            items.append(("muted", "還沒產業鏈，不拿證交所粗分類硬比。"))

        mlabel = str(snap.get("month_label") or "").strip()
        if not mlabel:
            month = str(snap.get("month") or "")
            mlabel = format_month_zh(month) if len(month) >= 6 else (month or "—")
        items.append(("h", "營收看同業"))
        items.append(("kv", "月營收", mlabel))
        if snap["my_yoy"] is not None:
            items.append(("kv", "這檔年增", f"{snap['my_yoy']:+.1f}%"))
            if snap["my_mom"] is not None:
                items.append(("kv", "這檔月增", f"{snap['my_mom']:+.1f}%"))
            if snap["yoy_med"] is not None:
                items.append(
                    ("kv", "同業中位年增", f"{snap['yoy_med']:+.1f}%（{snap['yoy_n']}家有月報）")
                )
            items.append(("p", _vs_peer(snap["my_yoy"], snap["yoy_med"], "%")))
        else:
            if listing == "興櫃":
                items.append(("p", "興櫃沒有免登入的全市場月營收彙總，沒官方列就不顯示。"))
            else:
                items.append(("p", "這檔還沒有月營收列"))
                latest_m = str(snap.get("latest_month") or "")
                if latest_m:
                    items.append(("muted", f"市場已有{format_month_zh(latest_m)}，這檔尚未公告。"))
        if snap.get("vol") is not None and snap.get("vol_med") is not None and float(snap["vol_med"] or 0) > 0:
            ratio = float(snap["vol"]) / float(snap["vol_med"])
            vol_s = f"{int(round(float(snap['vol']))):,}張　同業中位 {int(round(float(snap['vol_med']))):,}張（量比 {ratio:.1f}）"
            if int(snap.get("vol_em_n") or 0):
                vol_s += f"；含興櫃{int(snap['vol_em_n'])}家日均量"
            items.append(("kv", "量比", vol_s))
        if snap["my_gm"] is not None:
            season_s = str(snap.get("season_label") or "").strip() or f"{snap['year']}Q{snap['season']}"
            items.append(("kv", "季報", season_s))
            items.append(("kv", "這檔毛利率", f"{snap['my_gm']:.1f}%"))
            if snap["gm_med"] is not None:
                items.append(("kv", "同業中位毛利率", f"{snap['gm_med']:.1f}%"))
            items.append(("p", _vs_peer(snap["my_gm"], snap["gm_med"], "pt")))
        else:
            items.append(("p", "這檔還沒有季報列"))

        bijia = snap.get("bijia") or {}
        items.append(("h", "同鏈比價"))
        if bijia.get("ok") and bijia.get("rows"):
            items.append(("kv", "範圍", str(bijia.get("scope") or bijia.get("chain") or "")))
            items.append(("kv", "基準", str(bijia.get("eps_label") or "")))
            cd = str(bijia.get("close_date") or "")
            if len(cd) == 8:
                items.append(("kv", "收盤日", f"{cd[:4]}/{cd[4:6]}/{cd[6:]}"))
            elif cd:
                items.append(("kv", "收盤日", cd))
            items.append(("bijia_head",))
            lag_mine = str(bijia.get("flag") or "") == "lag"
            for r in bijia["rows"]:
                items.append(
                    (
                        "bijia_row",
                        format_bijia_cells(r),
                        bool(r.get("is_mine")),
                        lag_mine and bool(r.get("is_mine")),
                    )
                )
            if bijia.get("read"):
                items.append(("p", str(bijia["read"])))
            flag = str(bijia.get("flag") or "")
            flag_text = str(bijia.get("flag_text") or "").strip()
            if flag and flag_text:
                items.append(("bijia_flag", flag, flag_text))
        else:
            items.append(("muted", str(bijia.get("note") or "同鏈比價不足").strip()))

        items.append(("h", "本族群產業狀況簡述"))
        for ln in _flow_lines(snap):
            if "：" in ln:
                lab, _, val = ln.partition("：")
                if lab and val and "：" not in val:
                    items.append(("kv", lab, val))
                    continue
            items.append(("p", ln))

        if snap["stronger"] or snap["weaker"]:
            items.append(("h", "同業月營收對照"))

            def _peer_items(label: str, rows: List[Dict[str, Any]]) -> None:
                items.append(("p", label))
                if not rows:
                    items.append(("muted", "—"))
                    return
                for r in rows:
                    tags = [str(t) for t in list(r.get("fine_tags") or []) if str(t)]
                    if not tags:
                        tag = str(r.get("fine_finest") or "").strip()
                        tags = [tag] if tag else []
                    pname = str(r["stock_name"])
                    listing_p = str(r.get("listing") or "").strip()
                    if listing_p:
                        pname = f"{pname}　{listing_p}"
                    items.append(
                        (
                            "peer_inline",
                            str(r["stock_id"]),
                            pname,
                            float(r.get("yoy") or 0),
                            tags[-3:],
                        )
                    )

            _peer_items("較強", snap["stronger"])
            _peer_items("較弱", snap["weaker"])
            note = peer_note_line(snap)
            if note:
                items.append(("muted", note))

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

    # 同鏈比價表欄位（右緣對齊數字，左緣代號／名）
    BIJIA_MARK_W = 72
    BIJIA_SID_W = 100
    BIJIA_CLOSE_W = 120
    BIJIA_EPS_W = 140
    BIJIA_MULT_W = 120
    BIJIA_ROW_H = 52
    MINE_BG = (36, 64, 88)
    LAG_BG = (255, 214, 10)       # 高反差黃
    LAG_FG = (12, 14, 18)         # 近黑字
    DEAR_BG = (200, 36, 56)       # 高反差紅
    DEAR_FG = (255, 245, 245)
    LAG_ROW_BG = (72, 58, 8)      # 這檔列：深琥珀底
    LAG_ROW_FG = (255, 230, 80)   # 這檔列：亮黃字

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
        elif kind == "bijia_head":
            measured.append((kind, item, BIJIA_ROW_H))
            y += BIJIA_ROW_H
        elif kind == "bijia_row":
            measured.append((kind, item, BIJIA_ROW_H + 6))
            y += BIJIA_ROW_H + 6
        elif kind == "bijia_flag":
            measured.append((kind, item, BIJIA_ROW_H + 16))
            y += BIJIA_ROW_H + 16
        elif kind == "kv":
            lab, val = item[1], item[2]
            avail = max(80.0, max_w - body_f.getlength(lab) - 28)
            wraps = _wrap_px(val, body_f, avail)
            h = max(line_h, len(wraps) * line_h)
            measured.append((kind, item, h))
            y += h
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
        elif kind == "bijia_head":
            # 欄：標記 | 代號 | 名稱…… | 收盤 | EPS | 價/EPS
            x0 = pad_x
            x_sid = x0 + BIJIA_MARK_W
            x_name = x_sid + BIJIA_SID_W
            x_mult_r = pad_x + max_w
            x_eps_r = x_mult_r - BIJIA_MULT_W
            x_close_r = x_eps_r - BIJIA_EPS_W
            name_right = x_close_r - BIJIA_CLOSE_W - 12

            def _col(label: str, x_left: float, x_right: float, *, right: bool = False):
                if right:
                    tw = body_f.getlength(label)
                    tx, ty = centered_text_xy(
                        body_f, label, (x_right - tw, cy, x_right, cy + BIJIA_ROW_H)
                    )
                else:
                    tx, ty = centered_text_xy(
                        body_f, label, (x_left, cy, x_left + body_f.getlength(label) + 2, cy + BIJIA_ROW_H)
                    )
                dr.text((tx, ty), label, font=body_f, fill=MUTED + (255,))

            _col("", x0, x_sid)
            _col("代號", x_sid, x_name)
            _col("名稱", x_name, name_right)
            _col("收盤", x_close_r - BIJIA_CLOSE_W, x_close_r, right=True)
            _col("EPS", x_eps_r - BIJIA_EPS_W, x_eps_r, right=True)
            _col("價/EPS", x_mult_r - BIJIA_MULT_W, x_mult_r, right=True)
            # 底線
            dr.line(
                [(pad_x, cy + BIJIA_ROW_H - 6), (pad_x + max_w, cy + BIJIA_ROW_H - 6)],
                fill=CARD_INNER + (255,),
                width=1,
            )
            cy += BIJIA_ROW_H
        elif kind == "bijia_row":
            cells = item[1]
            is_mine = bool(item[2])
            lag_hi = bool(item[3]) if len(item) > 3 else False
            row_top = cy
            row_bot = cy + BIJIA_ROW_H
            if is_mine:
                bg = LAG_ROW_BG if lag_hi else MINE_BG
                dr.rounded_rectangle(
                    (pad_x - 8, row_top, pad_x + max_w + 8, row_bot),
                    radius=12,
                    fill=bg + (255,),
                )
            x0 = pad_x
            x_sid = x0 + BIJIA_MARK_W
            x_name = x_sid + BIJIA_SID_W
            x_mult_r = pad_x + max_w
            x_eps_r = x_mult_r - BIJIA_MULT_W
            x_close_r = x_eps_r - BIJIA_EPS_W
            name_right = x_close_r - BIJIA_CLOSE_W - 12
            if lag_hi:
                fill = LAG_ROW_FG
            elif is_mine:
                fill = HEAD
            else:
                fill = TEXT

            def _draw_left(txt: str, x_left: float, x_right: float):
                raw = str(txt or "")
                limit = max(20.0, x_right - x_left - 4)
                if body_f.getlength(raw) > limit:
                    while len(raw) > 1 and body_f.getlength(raw + "…") > limit:
                        raw = raw[:-1]
                    raw = raw + "…"
                tx, ty = centered_text_xy(
                    body_f, raw, (x_left, row_top, x_left + body_f.getlength(raw) + 2, row_bot)
                )
                dr.text((tx, ty), raw, font=body_f, fill=fill + (255,))

            def _draw_right(txt: str, x_left: float, x_right: float):
                tw = body_f.getlength(txt)
                tx, ty = centered_text_xy(
                    body_f, txt, (x_right - tw, row_top, x_right, row_bot)
                )
                dr.text((tx, ty), txt, font=body_f, fill=fill + (255,))

            _draw_left(cells.get("mark") or "", x0, x_sid)
            _draw_left(cells.get("sid") or "", x_sid, x_name)
            _draw_left(cells.get("name") or "", x_name, name_right)
            _draw_right(cells.get("close") or "", x_close_r - BIJIA_CLOSE_W, x_close_r)
            _draw_right(cells.get("eps") or "", x_eps_r - BIJIA_EPS_W, x_eps_r)
            _draw_right(cells.get("mult") or "", x_mult_r - BIJIA_MULT_W, x_mult_r)
            cy += BIJIA_ROW_H + 6
        elif kind == "bijia_flag":
            flag, text = item[1], item[2]
            bar_h = BIJIA_ROW_H + 8
            if flag == "lag":
                bg, fg = LAG_BG, LAG_FG
            else:
                bg, fg = DEAR_BG, DEAR_FG
            dr.rounded_rectangle(
                (pad_x - 8, cy, pad_x + max_w + 8, cy + bar_h),
                radius=14,
                fill=bg + (255,),
            )
            # 黑／白字置中，字級略大
            flag_f = head_f
            wraps = _wrap_px(str(text), flag_f, max_w - 24) or [str(text)]
            # 單行優先；過長縮成兩行仍置中
            block_h = len(wraps) * (head_h - 10)
            y0 = cy + (bar_h - block_h) / 2.0
            for ln in wraps[:2]:
                tw = flag_f.getlength(ln)
                tx, ty = centered_text_xy(
                    flag_f, ln, (pad_x + (max_w - tw) / 2.0, y0, pad_x + (max_w + tw) / 2.0, y0 + head_h - 10)
                )
                dr.text((tx, ty), ln, font=flag_f, fill=fg + (255,))
                y0 += head_h - 10
            cy += bar_h + 8
        elif kind == "kv":
            lab, val = item[1], item[2]
            avail = max(80.0, max_w - body_f.getlength(lab) - 28)
            wraps = _wrap_px(val, body_f, avail) or [val]
            lx, ly = centered_text_xy(
                body_f, lab, (pad_x, cy, pad_x + body_f.getlength(lab) + 2, cy + line_h)
            )
            dr.text((lx, ly), lab, font=body_f, fill=MUTED + (255,))
            for ln in wraps:
                ln_w = body_f.getlength(ln)
                px, py = centered_text_xy(
                    body_f, ln, (pad_x + max_w - ln_w, cy, pad_x + max_w, cy + line_h)
                )
                dr.text((px, py), ln, font=body_f, fill=TEXT + (255,))
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

