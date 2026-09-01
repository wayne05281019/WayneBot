"""海選整區 LINE：背景生成圖文包，一鍵開 LINE + 一張長圖。"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
from typing import Any, Dict, List, Optional

from line_share_format import LINE_BUCKET_META, LINE_SHARE_SEP, format_line_bucket_body, format_line_stock_block

_TEXT_FONTS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
)
_IMAGE_LABELS = (
    ("glance", "介紹圖"),
    ("card", "高低決策卡"),
    ("chips", "籌碼"),
)


def _text_font(size: int):
    from PIL import ImageFont

    for path in _TEXT_FONTS:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def html_to_plain(fragment: str) -> str:
    s = str(fragment or "")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>\s*", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return html_lib.unescape(s).strip()


def render_line_share_pack(
    stock_id: str,
    db_path: str = None,
    charts_dir: str = None,
) -> Dict[str, Any]:
    """單檔圖文包（不含導航圖，較快）。"""
    from config import get_charts_dir, get_db_path
    from wayne_navigator import NavigatorEngine, render_decision_card_png, render_first_glance_png

    sid = str(stock_id or "").strip()
    db_path = db_path or get_db_path()
    charts_dir = charts_dir or get_charts_dir()
    os.makedirs(charts_dir, exist_ok=True)
    engine = NavigatorEngine(db_path)
    try:
        card = engine.get_decision_card(sid, lookback=20)
    except Exception as exc:
        return {"error": str(exc), "stock_id": sid}
    if card.get("error"):
        return {"error": card.get("error"), "stock_id": sid}
    tape = {}
    try:
        from chip_tape import build_tape

        tape = build_tape(db_path, sid) or {}
    except Exception:
        tape = {}
    sub = os.path.join(charts_dir, sid)
    os.makedirs(sub, exist_ok=True)
    glance = render_first_glance_png(
        sid, card, tape, os.path.join(sub, "glance.png"), db_path=db_path
    ) or ""
    card_png = render_decision_card_png(card, os.path.join(sub, "card.png")) or ""
    chips = ""
    try:
        from chips import generate_chips_image

        chips = generate_chips_image(sid, db_path, os.path.join(sub, "chips.png")) or ""
    except Exception:
        chips = ""
    industry = ""
    try:
        from industry_brief import format_industry_html

        industry = format_industry_html(sid, db_path) or ""
    except Exception:
        industry = ""
    return {
        "stock_id": sid,
        "stock_name": str(card.get("stock_name") or card.get("name") or ""),
        "glance": glance,
        "card": card_png,
        "chips": chips,
        "industry_html": industry,
        "industry_plain": html_to_plain(industry),
        "card_data": card,
    }


def compose_vertical_images(
    image_paths: List[str],
    out_path: str,
    *,
    pad: int = 12,
    max_width: int = 1080,
) -> str:
    """多張圖直向合成一張（給 LINE 一次貼圖）。"""
    from PIL import Image

    imgs = []
    for path in image_paths:
        p = str(path or "").strip()
        if p and os.path.isfile(p):
            imgs.append(Image.open(p).convert("RGB"))
    if not imgs:
        return ""
    width = min(max_width, max(im.width for im in imgs))
    scaled: List[Any] = []
    total_h = pad
    for im in imgs:
        if im.width != width:
            nh = max(1, int(im.height * width / im.width))
            im = im.resize((width, nh), Image.Resampling.LANCZOS)
        scaled.append(im)
        total_h += im.height + pad
    canvas = Image.new("RGB", (width, total_h), (255, 255, 255))
    y = pad
    for im in scaled:
        canvas.paste(im, (0, y))
        y += im.height + pad
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    canvas.save(out_path, "PNG", optimize=True)
    return out_path


def render_text_panel_png(
    text: str,
    out_path: str,
    *,
    width: int = 720,
    font_size: int = 26,
    pad: int = 18,
    bg: tuple = (248, 250, 252),
) -> str:
    """把一檔文字摘要渲成圖，貼在該檔圖表前面。"""
    from PIL import Image, ImageDraw, ImageFont

    lines = [ln for ln in str(text or "").split("\n") if ln is not None]
    if not lines:
        return ""
    font = _text_font(font_size)
    line_h = font_size + 10
    height = pad * 2 + line_h * len(lines)
    img = Image.new("RGB", (width, max(height, 80)), bg)
    draw = ImageDraw.Draw(img)
    y = pad
    for ln in lines:
        draw.text((pad, y), ln, fill=(24, 24, 24), font=font)
        y += line_h
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def render_separator_panel_png(out_path: str, width: int = 720) -> str:
    from PIL import Image, ImageDraw, ImageFont

    height = 56
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    font = _text_font(22)
    tw = draw.textlength(LINE_SHARE_SEP, font=font)
    draw.text(((width - tw) / 2, 16), LINE_SHARE_SEP, fill=(160, 160, 160), font=font)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def compose_stock_section(
    text_block: str,
    pack: Dict[str, Any],
    out_path: str,
    work_dir: str,
) -> str:
    """單檔：文字摘要 → 介紹圖 → 決策卡 → 籌碼（順序固定）。"""
    os.makedirs(work_dir, exist_ok=True)
    parts: List[str] = []
    text_png = os.path.join(work_dir, "text.png")
    if render_text_panel_png(text_block, text_png):
        parts.append(text_png)
    for key, label in _IMAGE_LABELS:
        img_path = str(pack.get(key) or "").strip()
        if not img_path or not os.path.isfile(img_path):
            continue
        cap_png = os.path.join(work_dir, f"{key}_cap.png")
        if render_text_panel_png(label, cap_png, font_size=22, pad=10, bg=(255, 255, 255)):
            parts.append(cap_png)
        parts.append(img_path)
    return compose_vertical_images(parts, out_path) if parts else ""


def compose_stock_strip(
    pack: Dict[str, Any],
    out_path: str,
) -> str:
    """單檔：介紹圖 → 決策卡 → 籌碼。"""
    paths = [pack.get("glance") or "", pack.get("card") or "", pack.get("chips") or ""]
    return compose_vertical_images(paths, out_path)


def _share_root(charts_dir: str, bucket_key: str, as_of: str) -> str:
    return os.path.join(charts_dir, "line_pack", bucket_key, str(as_of or "").replace("-", ""))


def line_rich_asset_url(bucket_key: str, as_of: str, filename: str, base_url: str = "") -> str:
    from config import get_public_base_url

    base = (base_url or get_public_base_url()).rstrip("/")
    ymd = str(as_of or "").replace("-", "")
    return f"{base}/line/rich/{bucket_key}/{ymd}/{filename}"


def line_rich_hop_url(bucket_key: str, base_url: str = "") -> str:
    from config import get_public_base_url

    base = (base_url or get_public_base_url()).rstrip("/")
    return f"{base}/line/rich/{bucket_key}"


def load_bucket_rich_manifest(
    db_path: str,
    bucket_key: str,
    as_of: str = "",
    charts_dir: str = None,
) -> Dict[str, Any]:
    from config import get_charts_dir

    charts_dir = charts_dir or get_charts_dir()
    ymd = str(as_of or "").replace("-", "")
    root = _share_root(charts_dir, bucket_key, ymd)
    manifest_path = os.path.join(root, "manifest.json")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def build_bucket_rich_pack(
    db_path: str,
    bucket_key: str,
    as_of: str = "",
    charts_dir: str = None,
) -> Dict[str, Any]:
    """整區背景生成：文字稿 + 各檔長圖 + 全區 album.png。"""
    from config import get_charts_dir

    charts_dir = charts_dir or get_charts_dir()
    bucket_key = str(bucket_key or "").strip()
    ymd = str(as_of or "").replace("-", "")
    rows = bucket_stock_rows(db_path, bucket_key, ymd)
    title = bucket_title(bucket_key)
    if not rows:
        return {"error": "尚無名單", "bucket_key": bucket_key}

    share_root = _share_root(charts_dir, bucket_key, ymd)
    os.makedirs(share_root, exist_ok=True)
    stocks_out: List[Dict[str, Any]] = []
    strip_paths: List[str] = []
    enriched: List[Dict[str, Any]] = []
    errors: List[str] = []

    for i, row in enumerate(rows, start=1):
        code = str(row.get("stock_id") or "").strip()
        name = str(row.get("stock_name") or "").strip()
        stock_dir = os.path.join(share_root, code)
        os.makedirs(stock_dir, exist_ok=True)
        pack = render_line_share_pack(code, db_path, stock_dir)
        if pack.get("error"):
            errors.append(f"{code} {name}：{pack.get('error')}")
            continue
        item = dict(pack.get("card_data") or {})
        item.setdefault("stock_id", code)
        item.setdefault("stock_name", name or item.get("stock_name") or "")
        if pack.get("industry_plain"):
            item["industry_plain"] = pack.get("industry_plain")
        text_block = format_line_stock_block(item, i, db_path)
        strip_path = os.path.join(stock_dir, "strip.png")
        composed = compose_stock_section(text_block, pack, strip_path, stock_dir)
        if composed:
            strip_paths.append(composed)
        enriched.append(item)
        stocks_out.append(
            {
                "rank": i,
                "stock_id": code,
                "stock_name": name,
                "text_block": text_block,
                "strip_url": line_rich_asset_url(bucket_key, ymd, f"{code}/strip.png"),
                "industry_plain": pack.get("industry_plain") or "",
            }
        )

    if not enriched:
        return {
            "error": "；".join(errors) if errors else "生成失敗",
            "bucket_key": bucket_key,
            "errors": errors,
        }

    album_path = os.path.join(share_root, "album.png")
    album_parts: List[str] = []
    sep_path = os.path.join(share_root, "_sep.png")
    if strip_paths:
        render_separator_panel_png(sep_path)
    for idx, sp in enumerate(strip_paths):
        if idx > 0 and os.path.isfile(sep_path):
            album_parts.append(sep_path)
        album_parts.append(sp)
    album_file = compose_vertical_images(album_parts, album_path) if album_parts else ""
    line_text = build_bucket_line_text(db_path, bucket_key, enriched, ymd)
    manifest = {
        "bucket_key": bucket_key,
        "as_of": ymd,
        "title": title,
        "count": len(enriched),
        "line_text": line_text,
        "album_url": line_rich_asset_url(bucket_key, ymd, "album.png") if album_file else "",
        "stocks": stocks_out,
        "errors": errors,
    }
    with open(os.path.join(share_root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    try:
        from screen_sessions import save_bucket_rich_manifest

        save_bucket_rich_manifest(db_path, manifest)
    except Exception:
        pass
    return manifest


def bucket_stock_rows(db_path: str, bucket_key: str, as_of: str = "") -> List[Dict[str, Any]]:
    from screen_sessions import load_bucket_rows

    rows = load_bucket_rows(db_path, bucket_key, as_of)
    out: List[Dict[str, Any]] = []
    for r in rows:
        sid = str(r.get("stock_id") or "").strip()
        if not sid:
            continue
        out.append(
            {
                "stock_id": sid,
                "stock_name": str(r.get("stock_name") or ""),
                "close": r.get("pick_close"),
                "chase_warning": r.get("chase_warning"),
            }
        )
    return out


def build_bucket_line_text(
    db_path: str,
    bucket_key: str,
    items: List[Dict[str, Any]],
    as_of: str,
) -> str:
    body = format_line_bucket_body(items, bucket_key, db_path)
    if not body:
        return ""
    from line_hop import _date_slash

    as_of_label = _date_slash(as_of) if as_of else ""
    prefix = f"WayneBot 海選　{as_of_label}" if as_of_label else "WayneBot 海選"
    return f"{prefix}\n{body}"


def bucket_title(bucket_key: str) -> str:
    return LINE_BUCKET_META.get(bucket_key, (bucket_key, ""))[0]


def load_latest_bucket_rich_manifest(
    db_path: str,
    bucket_key: str,
    charts_dir: str = None,
) -> Dict[str, Any]:
    """讀取該分類最新一筆圖文包 manifest（磁碟 → DB → 文字稿備援）。"""
    from config import get_charts_dir

    charts_dir = charts_dir or get_charts_dir()
    bucket_key = str(bucket_key or "").strip()
    try:
        from import_health import latest_complete_quote_date

        as_of = latest_complete_quote_date(db_path) or ""
        hit = load_bucket_rich_manifest(db_path, bucket_key, as_of, charts_dir)
        if hit.get("line_text"):
            return hit
    except Exception:
        pass
    root = os.path.join(charts_dir, "line_pack", bucket_key)
    if os.path.isdir(root):
        for name in sorted(os.listdir(root), reverse=True):
            hit = load_bucket_rich_manifest(db_path, bucket_key, name, charts_dir)
            if hit.get("line_text"):
                return hit
    try:
        from screen_sessions import load_bucket_rich_manifest as load_db_manifest

        hit = load_db_manifest(db_path, bucket_key)
        if hit.get("line_text"):
            return hit
    except Exception:
        pass
    return rebuild_manifest_from_line_pack(db_path, bucket_key)


def rebuild_manifest_from_line_pack(db_path: str, bucket_key: str) -> Dict[str, Any]:
    """磁碟圖文包遺失時，用 DB 文字稿組最小 manifest（至少能開 LINE）。"""
    from line_hop import _rebuild_bucket_line_text

    bucket_key = str(bucket_key or "").strip()
    text = _rebuild_bucket_line_text(db_path, bucket_key)
    if not text:
        try:
            from screen_sessions import load_line_pack

            row = load_line_pack(db_path, bucket_key)
            text = str((row or {}).get("text") or "").strip()
        except Exception:
            text = ""
    if not text:
        return {}
    title = bucket_title(bucket_key)
    return {
        "bucket_key": bucket_key,
        "title": title,
        "count": text.count("\n\n") + 1,
        "line_text": text,
        "album_url": "",
        "stocks": [],
        "text_only": True,
    }


def resolve_rich_asset_path(charts_dir: str, bucket_key: str, as_of: str, rel_path: str) -> str:
    """只允許讀 line_pack 目錄內的檔案。"""
    ymd = str(as_of or "").replace("-", "")
    rel = str(rel_path or "").replace("\\", "/").lstrip("/")
    if not rel or ".." in rel.split("/"):
        return ""
    root = os.path.realpath(_share_root(charts_dir, bucket_key, ymd))
    full = os.path.realpath(os.path.join(root, rel))
    if not full.startswith(root + os.sep) and full != root:
        return ""
    return full if os.path.isfile(full) else ""
