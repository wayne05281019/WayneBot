# -*- coding: utf-8 -*-
"""台股大盤日K：只疊飆大本人還沒收回的位（收到 2026-10-19 18:58）。

個股情境預估不走這裡。沒有把他沒寫的浪號、價、日期補進去。
「還有約 4000 點」沒有換成價。56000 是他 10/07 的測距，10/17 已收回，不上這張。
45000＝10/19 18:57「99% 會看到」。不是止跌價，也不是 C-4 反彈價。
45546＝他寫的 9/16 低點，00:49 說 99% 必破。庫內那根低點差不到 1 點就貼同一軌，不另畫。
40000 以下＝18:58 彎腰撿鑽石的條件，只留水平，不拿來當下一組的目標價。
39000 左右＝C 不見得破。31117、35000 不是他的目標，不畫。
47451、46429、46816 是別人的價，不畫成他的。
18:52：第一組裡 C-4 機率最高，其次 C-5 走完再第一組反彈 B。這兩個沒有價。
18:55：可以像 7 月畫 60 分下降趨勢線；跌破下降軌才把第一組標成完成，後面還有 2～3 組。
7 月那幾張（181095970、181132138、181145877、181149602）下降斜線沒有印出兩個轉折價，
文字也沒寫兩個錨點（41600～41800 是那條線當晚大約在的區間，不是兩個高點）。錨點缺，不假畫。
所以這張不把第一組標成完成，2～3 組只留組數，不另畫路徑、不補未來價。
C-4 沒有反彈價，虛線不往上拐。10/26、C-3-3、「過 2 天還有 5」他沒明文收回。
抄底窗跟下降軌分開：他說「今天可以抄」才把當天盤中當窗，不要求精確進場價。不是黃金買點。

視覺借 DC 情境預估臉（虛線未走路徑、浪標、粉 pin、演化帶、關鍵日豎線、右側紅價標）；
折線／位階／日期只認他自己說的，不准抄 DC 個股目標到大盤。

硬規則：演化標籤／帶／線不准壓到縮圖 K（一律 x > 最後一根）。
排版：路徑 mid-gutter；說明去重數字走右側欄交錯軌；紅價標只印一次；圖上說明氣泡精簡。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

# 他寫出來的整數。39000＝「39000左右」。48240 他註明是台指期。
ZONE_LO = 39000.0
ZONE_HI = 48240.0
BROKE_LEVEL = 47500.0
# 10/19 18:57：45000 是 99% 會看到。不是止跌價，也不是 C-4 反彈價。
NOT_FLOOR = 45000.0
# 18:58：殺到 40000 以下才是彎腰撿鑽石。只留水平，不進未走折線。
DIAMOND_BELOW = 40000.0
# 他寫的 9/16 低點。官方那根是 45546.56，差不到 1 點就用那一軌。
BREAK_SAID = 45546.0
DATE_YMD = "20261026"
# 7 月下降斜線的兩個轉折價：圖上沒印、文字沒寫。缺了就不畫。
DESCENDING_RAIL_ANCHORS: tuple[tuple[str, float], ...] = ()

# DC 視覺臉（對齊 scenario_forecast_chart v4 配色；路徑內容仍是飆大）
_ZONE = "#ce93d8"
_CHANNEL = "#ba68c8"
_LINE = "#6a1b9a"
_INK = "#311b92"
_WAVE_PROJ = "#ffffff"
_WAVE_EDGE = "#1b5e20"  # 跌綠：未走下降虛線描邊（台股慣例）
_PIN = "#ff4081"
_TAG_HOT = "#e53935"
_DATE_RED = "#c62828"

# 演化區起點：最後一根右側，標籤／帶不准回蓋 K
_ZONE_PAD = 0.85


def weekday_steps(start_ymd: str, end_ymd: str) -> int | None:
    """start 之後、到 end 為止的週一到週五天數。對不上就不要畫豎線。"""
    try:
        start = datetime.strptime(str(start_ymd)[:8], "%Y%m%d")
        end = datetime.strptime(str(end_ymd)[:8], "%Y%m%d")
    except ValueError:
        return None
    if end <= start:
        return None
    n = 0
    cur = start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            n += 1
        if n > 40:
            return None
    return n or None


def market_wave_caption_lines(session_ymd: str) -> tuple[str, ...]:
    """完整說明（測試／文案用）。圖上縮圖另走精簡兩行，避免演化區互壓。"""
    stamp = ""
    raw = str(session_ymd or "")[:8]
    if len(raw) == 8 and raw.isdigit():
        stamp = f"{raw[:4]}/{raw[4:6]}/{raw[6:8]}"
    head = f"官方日K至 {stamp}" if stamp else "官方日K"
    return (
        head,
        "他 10/19 18:52　C-4 機率最高",
        "其次 C-5 走完再第一組反彈 B；這兩個沒有價",
        "下降軌兩個轉折沒印出來，不畫，第一組不標完成",
        "還有 2～3 組，只留組數，不另畫路徑",
        "過兩天還有 5、或還在 C-3-3，他沒劃掉",
        "10/26 他沒收回；C-4 無反彈價",
        "45000 有 99% 會看到；45546 必破",
        "40000 以下才撿鑽石；39000 C 不見得破",
        "56000 已收回不畫；約 4000 點不換價",
        "虛線＝未走（不往上拐）",
    )


def _chart_caption_lines(session_ymd: str) -> tuple[str, ...]:
    """縮圖只留兩行：日期＋虛線註。其餘已由浪標／位階／日期小標承載。"""
    stamp = ""
    raw = str(session_ymd or "")[:8]
    if len(raw) == 8 and raw.isdigit():
        stamp = f"{raw[:4]}/{raw[4:6]}/{raw[6:8]}"
    head = f"官方日K至 {stamp}" if stamp else "官方日K"
    return (head, "虛線未走・第一組未標完成・2～3組無價")


def _biaoke_dc_proj_path(
    last_i: float, last_close: float, steps: int | None
) -> list[tuple[float, float]]:
    """未走虛線折點：只經他自己點過的整數價＋官方最後收。不准發明中間價／反彈高。

    現況＝C-4 機率最高，但沒有反彈價，所以折線不往上拐。
    下行仍只經他說 99% 會看到的 45000 → 約 39000（C 不見得破）。
    撿鑽石那條水平不插進這條折線，也不拿來當第 2、第 3 組的價。
    「過年後再往下」大盤句他沒說，不畫。
    """
    s = float(steps if steps is not None else 8)
    x0 = last_i + _ZONE_PAD
    x_nf = last_i + max(s * 0.55, 3.0)
    x_end = last_i + s + max(s * 1.15, 10.0)
    y0 = float(last_close)
    # 路徑從演化區起點接出（不從 K 棒心長標籤）
    pts: list[tuple[float, float]] = [(x0, y0)]
    if y0 > BROKE_LEVEL + 50.0:
        pts.append((last_i + max(s * 0.18, 1.2), float(BROKE_LEVEL)))
    pts.append((max(x_nf, x0 + 1.0), float(NOT_FLOOR)))
    pts.append((max(x_end, x0 + 2.0), float(ZONE_LO)))
    return pts


def _path_y_at(pts: list[tuple[float, float]], x: float) -> float:
    """折線上 x 對應的 y（線性插值）。"""
    if not pts:
        return 0.0
    if x <= pts[0][0]:
        return float(pts[0][1])
    for i in range(1, len(pts)):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        if x <= x1 or i == len(pts) - 1:
            if abs(x1 - x0) < 1e-9:
                return float(y1)
            t = (x - x0) / (x1 - x0)
            return float(y0 + t * (y1 - y0))
    return float(pts[-1][1])


def _dodge_note_ys(
    rows: list[tuple[float, str]], *, min_gap: float
) -> list[tuple[float, float, str]]:
    """右側說明欄 y 交錯避讓：由高到低排，互不壓。"""
    gap = max(float(min_gap), 1.0)
    items = sorted(((float(y), str(t)) for y, t in rows if t), key=lambda t: -t[0])
    out: list[tuple[float, float, str]] = []
    last_y: float | None = None
    for y, t in items:
        yy = y
        if last_y is not None and yy > last_y - gap:
            yy = last_y - gap
        out.append((y, yy, t))
        last_y = yy
    return out


def break_track_y(work) -> float:
    """99% 必破貼在 9/16 低點那一軌。差不到 1 點不另畫一條。"""
    y = float(BREAK_SAID)
    if work is None:
        return y
    try:
        dates = work["date"].astype(str).str[:8]
        hit = work.loc[dates == "20260916"]
    except (TypeError, KeyError, AttributeError):
        return y
    if hit is None or len(hit) == 0 or "low" not in hit.columns:
        return y
    try:
        lo = float(hit["low"].iloc[0])
    except (TypeError, ValueError, IndexError):
        return y
    if abs(lo - y) < 1.0:
        return lo
    return y


def _draw_map_pin(ax, x: float, y: float) -> None:
    ax.plot(x, y, marker="o", ms=6.5, color=_PIN, zorder=9, clip_on=True)
    ax.plot(
        x,
        y,
        marker="v",
        ms=10,
        color=_PIN,
        markeredgecolor="#c2185b",
        markeredgewidth=0.55,
        zorder=9,
        clip_on=True,
    )


def _draw_wave_dot(ax, x: float, y: float, label: str, *, fp, color: str) -> None:
    ax.plot(x, y, "o", ms=9.0, color=color, mfc="#fafafa", mew=1.3, zorder=8, clip_on=True)
    # 標在圓左上方，不准字壓在虛線上
    ax.annotate(
        label,
        xy=(x, y),
        xytext=(8, 14),
        textcoords="offset points",
        color=color,
        fontproperties=fp,
        ha="left",
        va="bottom",
        zorder=9,
        clip_on=True,
    )


def paint_biaoke_market_marks(ax, work) -> None:
    """演化／研發區只在最後一根右側。標籤不准壓縮圖 K。

    三軌：路徑 mid-gutter → 右側說明欄（去重數字、交錯）→ 最右紅價只印一次。
    """
    if work is None or len(work) < 2:
        return
    try:
        last_close = float(work["close"].iloc[-1])
    except (TypeError, ValueError, KeyError):
        return
    if not (20000.0 <= last_close <= 80000.0):
        return
    n = len(work)
    last_i = float(n - 1)
    last_ymd = str(work["date"].iloc[-1])[:8]
    steps = weekday_steps(last_ymd, DATE_YMD)
    # 右側三軌要夠寬：路徑／說明／紅價
    gutter = 32.0 if steps is None else float(max(steps + 30, 40))
    x_right = last_i + gutter
    lo = min(float(ax.get_ylim()[0]), ZONE_LO - 900.0)
    hi = max(float(ax.get_ylim()[1]), ZONE_HI + 2200.0)
    ax.set_ylim(lo, hi)
    ax.set_xlim(-0.8, x_right)

    x0 = last_i + _ZONE_PAD
    # 三軌硬分：路徑 ≤0.30・說明右對齊在紅價左側・紅價貼最右
    path_x_hi = last_i + gutter * 0.30
    tag_x = x_right - 0.12
    note_right = tag_x - 3.4
    hline_xmax = note_right - 0.55

    # 淡紫演化帶：只右側，不准蓋 K
    ax.fill_between(
        [x0, x_right - 0.25],
        [ZONE_LO, ZONE_LO],
        [ZONE_HI, ZONE_HI],
        color=_ZONE,
        alpha=0.20,
        zorder=1,
    )
    # ZONE_LO 灰帶也只在右側
    ax.fill_between(
        [x0, x_right - 0.25],
        [ZONE_LO - 200.0, ZONE_LO - 200.0],
        [ZONE_LO + 900.0, ZONE_LO + 900.0],
        color="#9e9e9e",
        alpha=0.12,
        zorder=1,
    )

    from wayne_navigator import _fp

    fp_s = _fp(6.6, "bold")
    fp_w = _fp(8.2, "bold")
    fp_d = _fp(6.4, "bold")
    fp_date = _fp(5.9, "bold")

    # —— DC 未走虛線路徑（收在 mid-gutter）——
    proj = _biaoke_dc_proj_path(last_i, last_close, steps)
    clipped: list[tuple[float, float]] = []
    if len(proj) >= 2:
        for px, py in proj:
            clipped.append((min(float(px), path_x_hi), float(py)))
        ax.plot(
            [last_i, clipped[0][0]],
            [last_close, clipped[0][1]],
            color=_WAVE_EDGE,
            lw=0.85,
            ls=(0, (3, 3)),
            zorder=5,
            alpha=0.45,
            clip_on=True,
        )
        px = [p[0] for p in clipped]
        py = [p[1] for p in clipped]
        amp = max((max(py) - min(py)) * 0.10, abs(py[-1]) * 0.012)
        ax.fill_between(px, [y - amp for y in py], [y + amp for y in py], color=_CHANNEL, alpha=0.13, zorder=4)
        ax.plot(px, py, color="#212121", lw=2.4, ls=(0, (5, 3)), zorder=5, alpha=0.42, clip_on=True)
        ax.plot(px, py, color=_WAVE_PROJ, lw=1.65, ls=(0, (5, 3)), zorder=5, alpha=0.98, clip_on=True)
        ax.plot(px, py, color=_WAVE_EDGE, lw=1.0, ls=(0, (5, 3)), zorder=5, alpha=0.55, clip_on=True)

        # 浪標貼第一段（還在最後收附近），不准滑到 45000 pin 上
        seg_end_x = float(clipped[1][0]) if len(clipped) >= 2 else path_x_hi
        wave_x = min(max(x0 + 1.35, x0 + 0.55), (x0 + seg_end_x) * 0.5)
        wave_x = min(wave_x, path_x_hi - 1.0)
        wave_y = _path_y_at(clipped, wave_x)
        # 短標貼路徑，長句走右側欄，避免字蓋回 K。
        # 下降軌錨點缺，不把第一組標成完成，也不另畫第 2、第 3 組。
        _draw_wave_dot(ax, wave_x, wave_y, "第一組", fp=fp_w, color=_INK)
        # C-3-3 註：併入右側說明欄，不准再疊在路徑上
        pin_450 = next((p for p in clipped if abs(p[1] - NOT_FLOOR) < 1.0), None)
        if pin_450 is not None and pin_450[0] >= x0:
            _draw_map_pin(ax, pin_450[0], float(NOT_FLOOR))
        if clipped[-1][0] >= x0:
            _draw_map_pin(ax, clipped[-1][0], float(ZONE_LO))
    else:
        wave_y = float(last_close)

    # 水平位：線停在說明欄左；紅價只印一次；說明去重數字、右對齊在紅價左側。
    # 45546 與 9/16 官方低差不到 1 點時，線的 y 用那根低點，紅標仍印他寫的 45546。
    break_y = break_track_y(work)
    price_tags: list[tuple[float, str, str]] = [
        (ZONE_HI, "48240", "台指期未站上"),
        (BROKE_LEVEL, "47500", "10/15破壞"),
        (break_y, "45546", "99%必破"),
        (NOT_FLOOR, "45000", "99%會看到"),
        (DIAMOND_BELOW, "40000", "以下撿鑽石"),
        (ZONE_LO, "39000", "C不見得破"),
    ]
    level_rows: list[tuple[float, str]] = [
        (price, text) for price, _tag, text in price_tags
    ]
    y_span = max(hi - lo, 1.0)
    min_gap = max(y_span * 0.055, 780.0)
    dodged = _dodge_note_ys(level_rows, min_gap=min_gap)
    # 浪句不跟價標搶同一軌：排在 47500 與 45546 中間。
    wave_notes = ("C-4最高・無價", "其次C-5再B・無價", "還有2～3組・不另畫")
    gap_w = max(min_gap * 0.55, 520.0)
    ceiling = float(BROKE_LEVEL) - gap_w
    floor = float(break_y) + gap_w
    top = min(float(wave_y), ceiling)
    need = gap_w * (len(wave_notes) - 1)
    if top - need < floor:
        top = floor + need
    for i, text in enumerate(wave_notes):
        yy = top - i * gap_w
        dodged.append((yy, yy, text))

    for price, tag, _text in price_tags:
        ax.plot(
            [x0, hline_xmax],
            [price, price],
            color=_LINE,
            lw=0.95,
            ls=(0, (4, 3)),
            zorder=6,
            clip_on=True,
        )
        ax.text(
            tag_x,
            price,
            tag,
            color="#ffffff",
            fontproperties=fp_d,
            ha="right",
            va="center",
            zorder=8,
            clip_on=True,
            bbox=dict(boxstyle="round,pad=0.14", facecolor=_TAG_HOT, edgecolor="none", alpha=0.95),
        )

    for anchor_y, note_y, text in dodged:
        if abs(note_y - anchor_y) > 40.0:
            ax.plot(
                [hline_xmax + 0.1, note_right - 0.15],
                [anchor_y, note_y],
                color=_LINE,
                lw=0.5,
                alpha=0.45,
                zorder=6,
                clip_on=True,
            )
        ax.text(
            note_right,
            note_y,
            text,
            color=_INK,
            fontproperties=fp_s,
            va="center",
            ha="right",
            zorder=7,
            clip_on=True,
            bbox=dict(
                boxstyle="round,pad=0.08",
                facecolor="#f3e5f5",
                edgecolor="none",
                alpha=0.94,
            ),
        )

    if steps is not None:
        x_d = last_i + float(steps)
        if x_d >= x0:
            x_d = min(max(x_d, x0 + 1.2), path_x_hi - 0.35)
            ax.axvline(x_d, color=_DATE_RED, lw=1.05, ls=(0, (3, 3)), zorder=6, clip_on=True)
            # mid-gutter 單顆小日期標（合併 C-4 註，少一層框）
            date_y = min(float(ZONE_HI) + abs(hi - lo) * 0.028, hi - abs(hi - lo) * 0.055)
            ax.text(
                x_d,
                date_y,
                "10/26 C-4起或之後",
                color="#ffffff",
                fontproperties=fp_date,
                ha="center",
                va="bottom",
                zorder=7,
                clip_on=True,
                bbox=dict(
                    boxstyle="round,pad=0.09",
                    facecolor=_DATE_RED,
                    edgecolor="none",
                    alpha=0.95,
                ),
            )

    # 圖上只兩行精簡說明，完整句留給 market_wave_caption_lines
    lines = _chart_caption_lines(last_ymd)
    ax.text(
        x0 + 0.1,
        hi - (hi - lo) * 0.006,
        "\n".join(lines),
        color=_INK,
        fontproperties=fp_s,
        ha="left",
        va="top",
        zorder=8,
        clip_on=True,
        bbox=dict(
            boxstyle="round,pad=0.14",
            facecolor="#f3e5f5",
            edgecolor="#ce93d8",
            linewidth=0.5,
            alpha=0.93,
        ),
    )


_DIP_TODAY = re.compile(
    r"(今天.{0,12}抄|抄底.{0,40}今天第一次|可開始抄底|今天可以抄)"
)


def read_dip_session(
    speech: str,
    *,
    price_then: float | None = None,
    low_already: float | None = None,
) -> dict | None:
    """他說今天可以抄：窗＝當天盤中。不要求一句精確進場價。

    距離只用當時價對當天已經走出的低點。收盤後才知道的低點不要傳進來當他開口報的價。
    沒說「今天可以抄」就回 None。不是黃金買點，不改 leave_zero。
    """
    blob = str(speech or "")
    if not _DIP_TODAY.search(blob):
        return None
    dist = None
    if price_then is not None and low_already is not None:
        dist = round(float(price_then) - float(low_already), 2)
    return {
        "window": "當日盤中",
        "exact_entry": None,
        "distance_to_printed_low": dist,
    }
