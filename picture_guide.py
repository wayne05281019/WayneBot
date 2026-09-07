# -*- coding: utf-8 -*-
"""哥哥圖文說明：手機長圖 9 頁，說明頁「圖文」一次一張、按第 N 張換頁。"""
from __future__ import annotations

import os
from typing import List, Sequence, Tuple

CACHE_VER = "v6"
# 話筒一次一張：加寬加大字給老花；圖可以往下。
PAGE_WIDTH = 1440
MARGIN = 72
TITLE_SIZE = 76
BODY_SIZE = 50
FOOT_SIZE = 34
TITLE_LINE = 94
BODY_LINE = 74
PAGE_SLUGS = (
    "cover",
    "menu",
    "charts",
    "hub",
    "discipline",
    "screen",
    "lists",
    "streak",
    "oops",
)

# 每頁對應真實截圖（側欄已裁；紅圈標該頁要按的位置）
PAGE_SHOTS = {
    "cover": "cover_menu.png",
    "menu": "cover_menu.png",
    "charts": "charts.png",
    "hub": "hub.png",
    "discipline": "discipline.png",
    "screen": "screen.png",
    "lists": "lists.png",
    "streak": "streak.png",
    "oops": "oops.png",
}

# 禁止 emoji：NotoSansTC 會畫成方塊。鍵盤寫「鍵盤」，加號寫「+」。
PAGES: Sequence[Tuple[str, str, str]] = (
    (
        "cover",
        "WayneBot 圖文說明",
        "第一次用，先做這三步\n"
        "\n"
        "1  點輸入列旁邊的鍵盤圖示（四格那顆）\n"
        "   叫出兩排按鈕。不見就打 /menu\n"
        "\n"
        "2  直接打四碼看圖，例如 2330\n"
        "   不要先按「決策卡」\n"
        "\n"
        "3  三張圖出來後，籌碼／營收／產業\n"
        "   在圖下面那一排，不在右邊四格鍵盤\n"
        "\n"
        "這本說明給手機看。一次只看一張。\n"
        "按「第 2 張」換頁，這一張會換成下一張。\n"
        "挑股只認高低卡表的黃金買點。\n"
        "圖上紅箭頭不是買訊。",
    ),
    (
        "menu",
        "兩排主選單在哪",
        "不在訊息最下面。\n"
        "點輸入列旁邊的四格鍵盤圖示，展開兩排。\n"
        "\n"
        "漢堡鈕在輸入列左邊。\n"
        "四格圖示在輸入列右邊。\n"
        "打完字若只剩英文鍵盤，再點一次四格。\n"
        "也可打 /menu。\n"
        "\n"
        "第一排（左到右）\n"
        "決策卡　當沖　持股　觀察　海選　AI倉\n"
        "\n"
        "第二排（左到右）\n"
        "隔日沖　大盤　資金　說明　連買區　回報\n"
        "\n"
        "決策卡＝刷新上一檔，不是海選名單。\n"
        "還沒查過股，請直接打四碼，不要先按決策卡。\n"
        "畫面怪按最右「回報」。",
    ),
    (
        "charts",
        "查一檔：一次三張圖",
        "打股名或代號，例如 2330 或 台積電。\n"
        "一次出三張。點縮圖可放大。\n"
        "\n"
        "介紹圖：這一檔現在熱不熱、獲利離 0 多遠。\n"
        "決策卡：高低卡表。進場只認表，不認紅箭頭。\n"
        "導航圖：近半年走勢，對照自己在哪。\n"
        "\n"
        "名稱撞名時：\n"
        "藍字＝奇摩網頁\n"
        "左邊按鈕＝看這檔\n"
        "右邊「+」＝加入觀察",
    ),
    (
        "hub",
        "圖下面那一排",
        "查完才出現，不是主選單那兩排。\n"
        "\n"
        "籌碼　三大法人買賣超圖\n"
        "營收　月營收、季報毛利\n"
        "產業　同業中位數＋這族法人，講人話\n"
        "觀察　加入自選（還沒買）\n"
        "記買入　記真實持股\n"
        "接著打「張數 價格」，例 1 68.5\n"
        "零股請寫「200股 631.6」\n"
        "不要只打 2，會被當成 2 張。\n"
        "\n"
        "找不到產業：在圖下面。\n"
        "不在輸入列右邊的四格鍵盤。",
    ),
    (
        "discipline",
        "粉紅紀律不是買訊",
        "介紹圖粉紅「紀律」、決策卡「今日態度」\n"
        "只講現在怎樣：先別追，或有持股先出一點。\n"
        "不是買訊，也不改海選名單。\n"
        "\n"
        "決策卡也會寫月線還在往上、已走空、或在整理。\n"
        "只是讓你對位置，不是買訊。\n"
        "\n"
        "現在高點跟熱度都退了\n"
        "→ 先別追、也先別加碼；有持股就先出一點\n"
        "現在價到高了\n"
        "→ 先別追；有持股可先出一點\n"
        "現在很熱但價沒過前高\n"
        "→ 先別追熱度\n"
        "現在高點跟熱度都沒了\n"
        "→ 先別追；有持股先出一點\n"
        "\n"
        "黃金買點＝獲利剛離開 0，或還在 0.x% 綠底。\n"
        "（以前叫起漲）\n"
        "重點觀察＝還壓在近 60 個日曆天收盤低。\n"
        "注意，不是立刻買。",
    ),
    (
        "screen",
        "海選怎麼轉 LINE",
        "海選＝昨收全市場佈局名單。\n"
        "不是盤中即時掃描。\n"
        "按一次等 2～5 分鐘，不要連按。\n"
        "\n"
        "左鍵（代號＋股名）＝看這檔完整圖\n"
        "右「+」＝加入觀察\n"
        "\n"
        "轉 LINE 有兩個入口，不要搞混\n"
        "・股名右「開 LINE・傳這檔」\n"
        "  只傳這一檔，直跳 LINE，再選聯絡人\n"
        "・區底「一鍵傳 LINE」\n"
        "  進勾選頁，可勾好幾檔再傳\n"
        "  （介紹圖＋決策卡一組）\n"
        "\n"
        "當沖／隔日沖不在晨間海選。\n"
        "請按主選單那兩顆。",
    ),
    (
        "lists",
        "三種清單不要搞混",
        "觀察＝自選，還沒買。頁上每檔兩排：\n"
        "上排　股名（看這檔）　籌碼\n"
        "下排　買入（記真實持股）　刪（移出觀察）\n"
        "\n"
        "持股＝你手記的真實買入。頁上：\n"
        "股名　賣出；底下還有成交／復盤／AI倉\n"
        "\n"
        "AI倉＝假錢對照組（最多 3 檔）\n"
        "不是你口袋裡的股票。\n"
        "頁上「AI操盤」立刻跑一輪模擬買賣，不推播。\n"
        "每晚 20:00 雲端也會跑，不會傳到話筒。",
    ),
    (
        "streak",
        "連買區",
        "官方法人連續買超名單，不是下單訊號。\n"
        "\n"
        "先選：外資／投信／外資+投信\n"
        "再點天數。上市櫃一起列，不再分市場。\n"
        "選到一半按錯：改按別顆就取消，再按連買區重來。\n"
        "\n"
        "名單：代號、股名、N 日連買張數與佔成交%。\n"
        "點股名看出完整圖，按籌碼核對官方法人表。\n"
        "四格鍵盤被收掉時打 /menu 可重新釘住兩排。",
    ),
    (
        "oops",
        "按錯了怎麼辦",
        "一打開先按了「決策卡」\n"
        "那顆是刷新上一檔。還沒查過就直接打四碼。\n"
        "\n"
        "「當沖」沒名單：週末／收盤後本來就空。\n"
        "改看海選或隔日沖。平日 09:00–13:30 才有當沖。\n"
        "\n"
        "「海選」等很久：那是掃全市場；不要連按。\n"
        "觀察跟持股搞混：觀察＝還沒買；持股＝按過記買入才會在。\n"
        "持股跟 AI倉搞混：持股＝你手記的；AI倉＝假錢對照組。\n"
        "找不到產業：在圖下面那一排。\n"
        "\n"
        "「回報」按下去又反悔：改按其他按鈕即可，不會送出。\n"
        "主選單不見：點輸入列旁邊四格鍵盤圖示，或打 /menu。\n"
        "畫面怪、數字怪：按第二排最右「回報」，打字或傳截圖。\n"
        "不用給程式密鑰、不用給機器人密碼。",
    ),
)

_BG = (246, 241, 232)
_INK = (26, 36, 51)
_MUTED = (90, 98, 110)
_ACCENT = (196, 92, 38)
_LINE = (214, 204, 188)
_CARD = (255, 255, 255)
_SHADOW = (214, 206, 194)


def _font_paths() -> Tuple[str, str]:
    here = os.path.dirname(os.path.abspath(__file__))
    regular = os.path.join(here, "fonts", "NotoSansTC-w560.ttf")
    bold = os.path.join(here, "fonts", "NotoSansTC-w860.ttf")
    return regular, bold


def _load_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    regular, bold_path = _font_paths()
    path = bold_path if bold and os.path.isfile(bold_path) else regular
    if os.path.isfile(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap(draw, text: str, font, max_w: int) -> List[str]:
    lines: List[str] = []
    for para in (text or "").split("\n"):
        if para == "":
            lines.append("")
            continue
        buf = ""
        for ch in para:
            trial = buf + ch
            try:
                w = draw.textlength(trial, font=font)
            except Exception:
                w = len(trial) * (getattr(font, "size", 28) * 0.9)
            if w <= max_w or not buf:
                buf = trial
            else:
                lines.append(buf)
                buf = ch
        if buf:
            lines.append(buf)
    return lines


def _page_path(out_dir: str, slug: str) -> str:
    return os.path.join(out_dir, f"{CACHE_VER}-{slug}.png")


def asset_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "picture_guide_assets")


def _page_shot(slug: str):
    from PIL import Image

    name = PAGE_SHOTS.get(slug)
    if not name:
        return None
    path = os.path.join(asset_dir(), name)
    if not os.path.isfile(path) or os.path.getsize(path) < 8_000:
        return None
    return Image.open(path).convert("RGB")


def _fit_width(im, max_w: int):
    from PIL import Image

    w, h = im.size
    if w <= 0 or h <= 0:
        return im
    if w == max_w:
        return im
    nh = max(1, int(round(h * max_w / w)))
    return im.resize((max_w, nh), Image.Resampling.LANCZOS)


def _shot_card(shot, max_w: int):
    """白底圓角卡＋淺影，截圖放大貼上。"""
    from PIL import Image, ImageDraw

    inner = max_w - 16
    shot = _fit_width(shot, inner)
    pad = 18
    lift = 10
    card_w = shot.width + pad * 2
    card_h = shot.height + pad * 2
    out = Image.new("RGB", (card_w + lift, card_h + lift), _BG)
    d = ImageDraw.Draw(out)
    d.rounded_rectangle((lift, lift, card_w + lift - 1, card_h + lift - 1), 22, fill=_SHADOW)
    d.rounded_rectangle((0, 0, card_w - 1, card_h - 1), 22, fill=_CARD, outline=_LINE, width=3)
    out.paste(shot, (pad, pad))
    return out


def render_page(slug: str, title: str, body: str, out_path: str) -> str:
    from PIL import Image, ImageDraw

    title_font = _load_font(TITLE_SIZE, bold=True)
    body_font = _load_font(BODY_SIZE)
    foot_font = _load_font(FOOT_SIZE)
    probe = Image.new("RGB", (PAGE_WIDTH, 200), _BG)
    pdraw = ImageDraw.Draw(probe)
    max_w = PAGE_WIDTH - 2 * MARGIN
    title_lines = _wrap(pdraw, title, title_font, max_w)
    body_lines = _wrap(pdraw, body, body_font, max_w)
    shot = _page_shot(slug)
    if shot is not None:
        shot = _shot_card(shot, max_w)
        shot_h = shot.height + 36
    else:
        shot_h = 0
    height = (
        MARGIN
        + 48
        + len(title_lines) * TITLE_LINE
        + 28
        + len(body_lines) * BODY_LINE
        + shot_h
        + 96
    )
    height = max(height, 1600)
    img = Image.new("RGB", (PAGE_WIDTH, height), _BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, PAGE_WIDTH, 22), fill=_ACCENT)
    y = MARGIN
    draw.text((MARGIN, y), "WayneBot", font=foot_font, fill=_MUTED)
    y += 48
    for line in title_lines:
        draw.text((MARGIN, y), line, font=title_font, fill=_INK)
        y += TITLE_LINE
    y += 10
    draw.line((MARGIN, y, PAGE_WIDTH - MARGIN, y), fill=_LINE, width=4)
    y += 32
    for line in body_lines:
        if line == "":
            y += 22
            continue
        draw.text((MARGIN, y), line, font=body_font, fill=_INK)
        y += BODY_LINE
    if shot is not None:
        y += 20
        img.paste(shot, (MARGIN, y))
        y += shot.height
    idx = PAGE_SLUGS.index(slug) + 1 if slug in PAGE_SLUGS else 0
    foot = f"{idx} / {len(PAGE_SLUGS)}" if idx else CACHE_VER
    draw.text((MARGIN, height - 64), foot, font=foot_font, fill=_MUTED)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", compress_level=4, dpi=(144, 144))
    return out_path


def picture_guide_dir(charts_dir: str | None = None) -> str:
    if not charts_dir:
        try:
            from config import get_charts_dir

            charts_dir = get_charts_dir()
        except Exception:
            charts_dir = os.path.join("data", "charts")
    path = os.path.join(str(charts_dir), "picture_guide", CACHE_VER)
    os.makedirs(path, exist_ok=True)
    return path


def render_picture_guide(out_dir: str | None = None, *, force: bool = False) -> List[str]:
    """產出 9 張長圖；已有快取就沿用。"""
    dest = out_dir or picture_guide_dir()
    os.makedirs(dest, exist_ok=True)
    paths: List[str] = []
    for slug, title, body in PAGES:
        path = _page_path(dest, slug)
        if force or not os.path.isfile(path) or os.path.getsize(path) < 8_000:
            render_page(slug, title, body, path)
        paths.append(path)
    return paths


def page_copy_blob() -> str:
    return "\n".join(f"{slug}\n{title}\n{body}" for slug, title, body in PAGES)
