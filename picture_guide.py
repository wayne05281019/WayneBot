# -*- coding: utf-8 -*-
"""哥哥圖文說明：手機長圖 9 頁，說明頁「圖文」一次一張、按第 N 張換頁。

藍底白字對齊產業圖卡／大盤跑馬燈。一次只渲正在看的那一張，換頁才渲下一張。
"""
from __future__ import annotations

import os
from typing import List, Optional, Sequence, Tuple

CACHE_VER = "v14"
# 九頁同一張 9:16 一屏。超長海報在話筒裡會整張縮小，字會小到不能看。
# 1080×1920＝手機直式一屏；點開幾乎滿版。內文以 ≥50px 畫，390 寬話筒點開約 18–20 點。
PAGE_WIDTH = 1080
PAGE_HEIGHT = 1920
MARGIN = 40
TITLE_SIZE = 76
BODY_SIZE = 52
MAX_TITLE_SIZE = 84
MAX_BODY_SIZE = 64
MIN_TITLE_SIZE = 68
MIN_BODY_SIZE = 48
BOTTOM_PAD = 48
TEXT_SHOT_GAP = 96
SHOT_TOP_RATIO = 0.52
CHROME_TOP = 8
DOT_ROW_H = 28
TG_PHOTO_MAX_BYTES = 9_800_000
FLIP_W = 540
FLIP_H = 960
FLIP_FRAMES = 8
FLIP_MS = 55
_BREAK_AFTER = set("、。；：，,．）)」」】》 \u3000")
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
        "1  點輸入列旁邊的四格鍵盤圖示\n"
        "   叫出兩排按鈕。不見就打 /menu\n"
        "\n"
        "2  直接打四碼看圖，例如 2330\n"
        "   不要先按「決策卡」\n"
        "\n"
        "3  三張圖出來後，籌碼／營收／產業\n"
        "   在圖下面那一排，不在右邊四格鍵盤\n"
        "\n"
        "這本說明給手機看。一次只看一張。\n"
        "按「第 2 張」看下一張；要回去按上一張。\n"
        "換頁時這一張會滑走，換成下一張。\n"
        "挑股只認高低卡表的黃金買點。\n"
        "圖上紅箭頭不是買訊。",
    ),
    (
        "menu",
        "兩排主選單在哪",
        "不在訊息最下面。點輸入列旁邊的四格鍵盤圖示展開兩排。也可打 /menu。\n"
        "\n"
        "第一排（左到右）\n"
        "決策卡　當沖　持股　觀察　海選　AI倉\n"
        "\n"
        "第二排（左到右）\n"
        "隔日沖　大盤　資金　連買區　說明　回報\n"
        "\n"
        "「大盤」最上頭是時段跑馬燈（循環短圖），下面才是數字與橫式日K。\n"
        "美股當天沒開會寫原因，並附前一交易日收盤。沒接到的市場不寫。\n"
        "\n"
        "決策卡＝刷新上一檔，不是海選。還沒查過請直接打四碼。畫面怪按最右「回報」。\n"
        "\n"
        "平日自動（台灣）\n"
        "06:30 早報　12:45 尾盤可切版\n"
        "16:30 官方收盤寫庫　20:00 AI倉模擬買賣，不推播",
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
        "產業　一張圖卡：同業中位＋本產業法人\n"
        "・股名旁公開細項小框；沒抓到不畫、不留空白\n"
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
        "介紹圖「紀律」、決策卡「今日態度」只講現在怎樣，不是買訊。\n"
        "句子跟下面那張 20 日表的數字、底色對齊。不改海選。\n"
        "徽章才寫月K還在往上、已走空或在整理。不是買訊。\n"
        "\n"
        "高點跟熱度都退了 → 先別追；有持股先出一點\n"
        "價到高了、熱度沒跟上 → 先出一點、不要追\n"
        "很熱但價沒過前高 → 先出一點、不要追高\n"
        "高點跟熱度都沒了 → 這波先當結束；先出一點\n"
        "\n"
        "黃金買點＝獲利剛離開 0（以前叫起漲）\n"
        "重點觀察＝還壓在近 60 個日曆天收盤低，不是立刻買\n"
        "如何賣：最高價＝20日高，對最高溫。不自動賣。",
    ),
    (
        "screen",
        "海選怎麼轉 LINE",
        "海選＝依最近一次官方收盤掃全市場。\n"
        "不是盤中即時掃描。\n"
        "主選單第一排「海選」就是圖上紅圈那顆。\n"
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
        "AI倉＝假錢對照組（50 萬切 3 等份）\n"
        "平常最多用 1 份；大盤超跌才動第 2 份抄低。\n"
        "第 3 份永遠留現金，不買滿。\n"
        "不是你口袋裡的股票。\n"
        "頁上「AI操盤」立刻跑一輪模擬買賣，不推播。\n"
        "盤後融合與每晚 20:00 雲端也會跑，不會傳到話筒。",
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
        "名單：代號、股名、N日連買張數與佔成交%。\n"
        "點股名看出完整圖，按籌碼核對官方法人表。\n"
        "四格鍵盤被收掉時打 /menu 可重新釘住兩排。",
    ),
    (
        "oops",
        "按錯了怎麼辦",
        "一打開先按了「決策卡」：那顆是刷新上一檔。還沒查過就直接打四碼。\n"
        "\n"
        "「當沖」沒名單：週末／收盤後本來就空。平日 09:00–13:30 才有。\n"
        "「海選」等很久：掃全市場；不要連按。\n"
        "觀察＝還沒買；持股＝按過記買入才會在。\n"
        "持股＝你手記的；AI倉＝假錢對照組。\n"
        "找不到產業：在圖下面那一排。按下去是一張圖卡。\n"
        "\n"
        "「回報」按下去又反悔：改按其他按鈕即可，不會送出。\n"
        "主選單不見：點四格鍵盤圖示，或打 /menu。\n"
        "畫面怪按第二排最右「回報」。不用給密鑰或密碼。",
    ),
)

# 對齊產業圖卡／大盤跑馬燈：深藍底、白字、青標。
_BG = (18, 26, 38)
_INK = (236, 242, 248)
_MUTED = (168, 186, 204)
_ACCENT = (140, 210, 255)
_LINE = (70, 96, 122)
_CARD = (12, 20, 32)
_LABEL_BG = (28, 52, 78)


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


def _ink_box(font, text: str):
    bbox = font.getbbox(str(text or ""))
    return bbox[0], bbox[1], bbox[2], bbox[3]


def _centered_text_xy(font, text: str, box) -> tuple:
    """讓真實墨水框的中心對上 box 幾何中心。"""
    x0, y0, x1, y1 = box
    l, t, r, b = _ink_box(font, text)
    tw, th = r - l, b - t
    return x0 + (x1 - x0 - tw) / 2.0 - l, y0 + (y1 - y0 - th) / 2.0 - t


def _text_w(draw, text: str, font) -> float:
    """用實際墨水寬，避免 textlength 低估、最後一個句號被拼回去後超出右緣。"""
    try:
        tl = float(draw.textlength(text, font=font))
    except Exception:
        tl = len(text or "") * (getattr(font, "size", 28) * 0.9)
    try:
        l, _t, r, _b = font.getbbox(text)
        return max(tl, float(r - l))
    except Exception:
        return tl


def _wrap_line(draw, text: str, font, first_w: float, rest_w: float) -> List[str]:
    """CJK 折行：盡量在頓號／句號切開。不把 /menu 從斜線拆開；不把溢出的句號拼回去。"""
    if not text:
        return [""]
    pad = 12.0
    lines: List[str] = []
    buf = ""
    limit = max(24.0, float(first_w) - pad)
    for ch in text:
        trial = buf + ch
        if _text_w(draw, trial, font) <= limit or not buf:
            buf = trial
            continue
        cut = -1
        for i in range(len(buf) - 1, 0, -1):
            if buf[i] in _BREAK_AFTER:
                cut = i + 1
                break
        if cut > 0 and cut < len(buf):
            lines.append(buf[:cut].rstrip())
            buf = buf[cut:].lstrip() + ch
        else:
            lines.append(buf)
            buf = ch
        limit = max(24.0, float(rest_w) - pad)
    if buf:
        if (
            len(buf) <= 2
            and lines
            and _text_w(draw, lines[-1] + buf, font) <= limit
        ):
            lines[-1] = lines[-1] + buf
        else:
            lines.append(buf)
    out: List[str] = []
    for ln in lines:
        if out and ln.strip() in "。、；：，,．":
            out[-1] = out[-1] + ln.strip()
        elif ln.strip():
            out.append(ln)
        else:
            out.append(ln)
    return out or [""]


def _hang_prefix(para: str) -> str:
    for p in ("1  ", "2  ", "3  ", "・", "→ "):
        if para.startswith(p):
            return p
    if para.startswith("   "):
        return "   "
    return ""


def _layout_body(draw, body: str, font, max_w: int) -> List[Tuple[int, str] | None]:
    """段落、編號、箭頭採懸吊縮排。None＝段距。"""
    out: List[Tuple[int, str] | None] = []
    for para in (body or "").split("\n"):
        if para == "":
            out.append(None)
            continue
        prefix = _hang_prefix(para)
        hang = int(_text_w(draw, prefix, font)) if prefix else 0
        rest_w = max(max_w - hang, int(max_w * 0.62))
        wrapped = _wrap_line(draw, para, font, max_w, rest_w)
        for i, ln in enumerate(wrapped):
            out.append((hang if i else 0, ln))
    return out


def _page_path(out_dir: str, slug: str) -> str:
    return os.path.join(out_dir, f"{CACHE_VER}-{slug}.png")


def _flip_path(out_dir: str, src: int, dst: int) -> str:
    return os.path.join(out_dir, f"{CACHE_VER}-flip-{int(src)}-{int(dst)}.gif")


def asset_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "picture_guide_assets")


def page_index(slug: str) -> int:
    try:
        return list(PAGE_SLUGS).index(slug)
    except ValueError:
        return 0


def page_copy(slug: str) -> Tuple[str, str]:
    for s, title, body in PAGES:
        if s == slug:
            return title, body
    raise KeyError(slug)


def _page_shot(slug: str):
    from PIL import Image

    name = PAGE_SHOTS.get(slug)
    if not name:
        return None
    path = os.path.join(asset_dir(), name)
    if not os.path.isfile(path) or os.path.getsize(path) < 8_000:
        return None
    im = Image.open(path).convert("RGB")
    return _trim_guide_shot(name, im)


def _is_caption_fill(c) -> bool:
    """配圖底那條米色說明條：(255, 246, 236)。"""
    r, g, b = c[:3]
    return r >= 240 and 228 <= g <= 252 and 200 <= b <= 245 and (r - b) >= 8


def _strip_caption_bar(im):
    """整條說明色帶裁掉。殘字「見就打/menu）」就是這條被切一半。"""
    w, h = im.size
    px = im.load()
    cut = h
    for y in range(h - 1, max(h // 4, 8), -1):
        n = 0
        hits = 0
        for x in range(0, w, 4):
            n += 1
            if _is_caption_fill(px[x, y]):
                hits += 1
        if n and hits / n >= 0.38:
            cut = y
            continue
        if cut < h:
            break
    if h - cut >= 8:
        return im.crop((0, 0, w, max(1, cut - 8)))
    return im


def _trim_guide_shot(name: str, im):
    """先去掉底欄說明，再裁聊天區。兩排按鈕與四格圖示要在，殘字不能在。"""
    im = _strip_caption_bar(im)
    keyboard = {
        "cover_menu.png",
        "lists.png",
        "streak.png",
        "oops.png",
        "screen.png",
    }
    w, h = im.size
    if name in keyboard and w >= 1400:
        left = int(w * 0.08)
        right = int(w * 0.93)
        top = int(h * 0.20)
        return im.crop((left, top, right, h))
    if name in {"charts.png", "hub.png"} and w >= 1400:
        left = int(w * 0.14)
        right = int(w * 0.86)
        return im.crop((left, 0, right, h))
    if name == "discipline.png" and w >= 900:
        left = int(w * 0.16)
        right = int(w * 0.84)
        return im.crop((left, 0, right, h))
    return im


def _fit_box(im, max_w: int, max_h: int):
    from PIL import Image

    w, h = im.size
    if w <= 0 or h <= 0 or max_w <= 0 or max_h <= 0:
        return im
    scale = min(max_w / w, max_h / h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    if (nw, nh) == (w, h):
        return im
    return im.resize((nw, nh), Image.Resampling.LANCZOS)


def _fit_cover(im, max_w: int, max_h: int, *, keep: str = "center"):
    """鋪滿目標框：放大後裁切，不留左右空白。寬圖裁左右；高圖依 keep 留頂或置中。"""
    from PIL import Image

    w, h = im.size
    if w <= 0 or h <= 0 or max_w <= 0 or max_h <= 0:
        return im
    scale = max(max_w / w, max_h / h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    if (nw, nh) != (w, h):
        im = im.resize((nw, nh), Image.Resampling.LANCZOS)
        w, h = im.size
    left = max(0, (w - max_w) // 2)
    if keep == "top":
        top = 0
    elif keep == "bottom":
        top = max(0, h - max_h)
    else:
        top = max(0, (h - max_h) // 2)
    return im.crop((left, top, left + max_w, top + max_h))


def _shot_card(shot, max_w: int, max_h: int, *, keep: str = "center"):
    """截圖等比放入卡片。不硬鋪滿、不裁按鈕、不留底欄殘字；不夠高就留深藍。"""
    from PIL import Image, ImageDraw

    pad = 12
    inner_w = max(1, max_w - pad * 2)
    inner_h = max(1, max_h - pad * 2)
    if keep == "cover":
        shot = _fit_cover(shot, inner_w, inner_h, keep="center")
        card_h = max_h
    else:
        shot = _fit_box(shot, inner_w, inner_h)
        card_h = min(max_h, shot.size[1] + pad * 2)
    sw, sh = shot.size
    out = Image.new("RGB", (max_w, card_h), _BG)
    d = ImageDraw.Draw(out)
    d.rounded_rectangle((0, 0, max_w - 1, card_h - 1), 16, fill=_CARD, outline=_ACCENT, width=3)
    x = pad + max(0, (inner_w - sw) // 2)
    y = pad + max(0, (card_h - pad * 2 - sh) // 2)
    out.paste(shot, (x, y))
    return out


def _text_block_h(rows: List[Tuple[int, str] | None], line_h: int, gap_h: int) -> int:
    h = 0
    for row in rows:
        h += gap_h if row is None else line_h
    return h


def _save_page_image(img, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "PNG", compress_level=3, dpi=(300, 300))
    if os.path.getsize(out_path) > TG_PHOTO_MAX_BYTES:
        img.convert("RGB").save(
            out_path,
            "JPEG",
            quality=95,
            optimize=True,
            subsampling=0,
            dpi=(300, 300),
        )


def _draw_dots(draw, y: int, current: int, n: int, x0: int, x1: int) -> None:
    """九頁同一排圓點；這一張實心青，其餘空心。"""
    n = max(1, int(n))
    current = max(0, min(int(current), n - 1))
    r = 7
    gap = 18
    total = n * (r * 2) + (n - 1) * gap
    start = x0 + max(0, (x1 - x0 - total) // 2)
    cy = y + DOT_ROW_H // 2
    for i in range(n):
        cx = start + i * (r * 2 + gap) + r
        box = (cx - r, cy - r, cx + r, cy + r)
        if i == current:
            draw.ellipse(box, fill=_ACCENT)
        else:
            draw.ellipse(box, outline=_LINE, width=2)


def _chrome_h() -> int:
    return CHROME_TOP + 36 + DOT_ROW_H + 8


def render_page(slug: str, title: str, body: str, out_path: str) -> str:
    """上半置中標題＋內文；配圖固定在下半，中間留空，不要黏在一起。"""
    from PIL import Image, ImageDraw

    max_w = PAGE_WIDTH - 2 * MARGIN
    shot_top_min = int(PAGE_HEIGHT * SHOT_TOP_RATIO)
    chrome = _chrome_h()
    probe = Image.new("RGB", (PAGE_WIDTH, 200), _BG)
    pdraw = ImageDraw.Draw(probe)
    title_size = TITLE_SIZE
    body_size = BODY_SIZE
    title_lines: List[str] = []
    body_rows: List[Tuple[int, str] | None] = []
    title_lh = body_lh = gap_h = 0
    title_font = body_font = None
    text_h = 0
    text_budget = shot_top_min - TEXT_SHOT_GAP
    scales = (1.22, 1.14, 1.08, 1.0, 0.94, 0.90)
    for scale in scales:
        title_size = max(MIN_TITLE_SIZE, min(MAX_TITLE_SIZE, int(round(TITLE_SIZE * scale))))
        body_size = max(MIN_BODY_SIZE, min(MAX_BODY_SIZE, int(round(BODY_SIZE * scale))))
        title_font = _load_font(title_size, bold=True)
        body_font = _load_font(body_size)
        title_lh = max(int(round(title_size * 1.34)), title_size + 18)
        body_lh = max(int(round(body_size * 1.36)), body_size + 10)
        gap_h = max(int(round(body_size * 0.28)), 10)
        title_lines = _wrap_line(pdraw, title, title_font, max_w, max_w)
        body_rows = _layout_body(pdraw, body, body_font, max_w)
        text_h = (
            chrome
            + 8
            + len(title_lines) * title_lh
            + 36
            + _text_block_h(body_rows, body_lh, gap_h)
        )
        if text_h <= text_budget:
            break
    assert title_font is not None and body_font is not None
    img = Image.new("RGB", (PAGE_WIDTH, PAGE_HEIGHT), _BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, PAGE_WIDTH, CHROME_TOP), fill=_ACCENT)
    draw.rectangle((0, 0, 10, PAGE_HEIGHT), fill=_ACCENT)
    brand_font = _load_font(26, bold=True)
    mark_font = _load_font(26, bold=True)
    idx = page_index(slug)
    n = len(PAGE_SLUGS)
    y = CHROME_TOP + 8
    draw.text((MARGIN, y), "WayneBot 圖文", font=brand_font, fill=_ACCENT)
    mark = f"{idx + 1}／{n}"
    mw = _text_w(draw, mark, mark_font)
    draw.text((PAGE_WIDTH - MARGIN - mw, y), mark, font=mark_font, fill=_INK)
    y += 32
    _draw_dots(draw, y, idx, n, MARGIN, PAGE_WIDTH - MARGIN)
    y += DOT_ROW_H + 10
    title_box_h = max(title_lh, 72)
    for line in title_lines:
        tx, ty = _centered_text_xy(
            title_font, line, (MARGIN, y, PAGE_WIDTH - MARGIN, y + title_box_h)
        )
        draw.text((tx, ty), line, font=title_font, fill=_INK)
        y += title_lh
    y += 10
    tw0 = 0.0
    for ln in title_lines:
        tw0 = max(tw0, _text_w(draw, ln, title_font))
    rule_w = min(max_w - 48, max(tw0 + 64, 220))
    rx0 = (PAGE_WIDTH - rule_w) / 2.0
    draw.line((rx0, y, rx0 + rule_w, y), fill=_LINE, width=3)
    y += 26
    for row in body_rows:
        if row is None:
            y += gap_h
            continue
        indent, line = row
        draw.text((MARGIN + indent, y), line, font=body_font, fill=_INK)
        y += body_lh
    text_end = y
    y_floor = max(shot_top_min, text_end + TEXT_SHOT_GAP)
    avail_h = PAGE_HEIGHT - BOTTOM_PAD - y_floor
    shot = _page_shot(slug)
    if shot is not None and avail_h >= 80:
        card = _shot_card(shot, max_w, avail_h)
        card_h = card.size[1]
        y_shot = PAGE_HEIGHT - BOTTOM_PAD - card_h
        if y_shot < y_floor:
            y_shot = y_floor
        img.paste(card, (MARGIN, y_shot))
    _save_page_image(img, out_path)
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


def ensure_page(slug: str, out_dir: str | None = None, *, force: bool = False) -> str:
    """只渲這一張。第一次按圖文不必先做完九張。"""
    dest = out_dir or picture_guide_dir()
    os.makedirs(dest, exist_ok=True)
    title, body = page_copy(slug)
    path = _page_path(dest, slug)
    if force or not os.path.isfile(path) or os.path.getsize(path) < 8_000:
        render_page(slug, title, body, path)
    return path


def render_picture_guide(out_dir: str | None = None, *, force: bool = False) -> List[str]:
    """產出 9 張長圖；已有快取就沿用。測試／本機對圖用；話筒走 ensure_page。"""
    dest = out_dir or picture_guide_dir()
    os.makedirs(dest, exist_ok=True)
    return [ensure_page(slug, dest, force=force) for slug, _t, _b in PAGES]


def render_flip_gif(
    src_path: str,
    dst_path: str,
    out_path: str,
    *,
    forward: bool = True,
) -> str:
    """舊頁滑出、新頁滑入。半尺寸 GIF，換頁後再換成原圖。"""
    from PIL import Image, ImageDraw, ImageEnhance

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    a = Image.open(src_path).convert("RGB").resize((FLIP_W, FLIP_H), Image.Resampling.LANCZOS)
    b = Image.open(dst_path).convert("RGB").resize((FLIP_W, FLIP_H), Image.Resampling.LANCZOS)
    frames = []
    n = FLIP_FRAMES
    for i in range(n):
        t = (i + 1) / float(n)
        e = t * t * (3.0 - 2.0 * t)
        dx = int(round(FLIP_W * e))
        canvas = Image.new("RGB", (FLIP_W, FLIP_H), _BG)
        if forward:
            canvas.paste(a, (-dx, 0))
            canvas.paste(b, (FLIP_W - dx, 0))
            seam = FLIP_W - dx
        else:
            canvas.paste(a, (dx, 0))
            canvas.paste(b, (dx - FLIP_W, 0))
            seam = dx
        overlay = Image.new("RGBA", (FLIP_W, FLIP_H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        glow = max(8, int(28 * (1.0 - abs(0.5 - t) * 2)))
        x0 = max(0, seam - glow)
        x1 = min(FLIP_W - 1, seam + glow)
        od.rectangle((x0, 0, x1, FLIP_H), fill=_ACCENT + (int(90 * (1.0 - abs(0.5 - t) * 2)),))
        mixed = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        if i == 0:
            mixed = ImageEnhance.Brightness(mixed).enhance(1.08)
        frames.append(mixed)
    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        duration=FLIP_MS,
        loop=1,
        optimize=True,
        disposal=2,
    )
    return out_path


def ensure_flip_gif(
    src_slug: str,
    dst_slug: str,
    out_dir: str,
    *,
    force: bool = False,
) -> Optional[str]:
    src_i = page_index(src_slug)
    dst_i = page_index(dst_slug)
    if src_i == dst_i:
        return None
    src = ensure_page(src_slug, out_dir)
    dst = ensure_page(dst_slug, out_dir)
    path = _flip_path(out_dir, src_i, dst_i)
    if force or not os.path.isfile(path) or os.path.getsize(path) < 4_000:
        render_flip_gif(src, dst, path, forward=dst_i > src_i)
    return path


def parse_guide_callback(data: str) -> Tuple[Optional[int], int]:
    """pg:3 或 pg:2-3 → (from_page, to_page)。舊按鈕只有目標頁。"""
    rest = str(data or "")
    if rest.startswith("pg:"):
        rest = rest[3:]
    rest = rest.strip()
    if "-" in rest:
        a, b = rest.split("-", 1)
        return int(a), int(b)
    return None, int(rest or "0")


def page_copy_blob() -> str:
    return "\n".join(f"{slug}\n{title}\n{body}" for slug, title, body in PAGES)
