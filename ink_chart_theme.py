"""墨線圖例微調（ink-legend-polish）：結構＋大量區。

基準＝ink-frame-align 視覺穩定。只做外科手術：刪免責、量柱貼底、左貼 axes、
刪 footer 多餘橫線、壓／撐略加大、KEY 略呼吸。不准重排 axes／打爛 annotation。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from matplotlib import colors as mcolors
from matplotlib import font_manager as fm
from matplotlib import patheffects as pe
from matplotlib.collections import LineCollection, PathCollection
from matplotlib.legend import Legend
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Polygon, Rectangle
from matplotlib.text import Annotation, Text
from matplotlib.transforms import Bbox

import logging
import os as _os

_MODULE_DIR = _os.path.dirname(_os.path.abspath(__file__))
_log = logging.getLogger(__name__)


def _bundled_font(weight: int) -> str:
    name = f"NotoSansTC-w{int(weight)}.ttf"
    for p in (
        _os.path.join(_MODULE_DIR, "fonts", name),
        _os.path.join(_MODULE_DIR, name),
        _os.environ.get(f"WAYNE_FONT_W{int(weight)}", "") or "",
    ):
        if p and _os.path.isfile(p):
            return p
    return _os.path.join(_MODULE_DIR, "fonts", name)


FONT_H = _bundled_font(860)
FONT_M = _bundled_font(560)

INK = "#0B0B0B"
INK2 = "#3A3A3A"
MUTE = "#7A7A7A"
PAPER = "#FFFFFF"
RULE = "#ECEEF1"
RULE_V = "#F3F4F6"
YELLOW = "#F5C518"
# 今 K 縮圖實體取樣（正式柱／baseline）：亮紅 #E53935、亮綠 #00897B
# 不准再用加深的 #D61F26／#0A7A58（目視偏褐／髒綠）
UP = "#E53935"
DN = "#00897B"
PRESS = "#B01030"
# 2026-10-29：撐／下一層撐加深（縮圖可讀）；壓色不動
HOLD = "#045A2E"
VIOLET = "#4A2499"
NEXT_H = "#08307A"
SPIKE = "#E8A200"
CALL = "#D45500"
# v2d：現任大量區桃色加深（對齊 paint _FILL）；不准再洗成過淡 #FFF1E4 α0.32
SKIN = "#FFB74D"
SKIN_HATCH = "#E09040"
LAYER_FACE = "#F2F4F7"
LAYER_HATCH = "#A0AAB4"
GRAYTAG = "#5C5C5C"
LIMIT_UP = UP  # 漲停底＝今 K 亮紅
LIMIT_DN = DN  # 跌停底＝今綠 K
RAIL = "#0B0B0B"  # 升階：徽章左側色軌寬度基準
USE_SHADOW = False  # 修訂 A：標籤／外框一律扁平無陰影
VARIANT = "frame"

# 正式色 → 墨線色（對齊今 K 取樣，不再加深）
CANDLE_MAP = {"#e53935": UP, "#00897b": DN, "#d61f26": UP, "#0a7a58": DN}
CANDLE_EDGE = {"#e53935": "#B71C1C", "#00897b": "#00695C", "#d61f26": "#B71C1C", "#0a7a58": "#00695C"}


def fp(size: float, heavy: bool = True) -> fm.FontProperties:
    return fm.FontProperties(fname=FONT_H if heavy else FONT_M, size=size)


def _hex(c: Any) -> str:
    try:
        r, g, b, _a = mcolors.to_rgba(c)
        return mcolors.to_hex((r, g, b))
    except Exception:
        return ""


def _alpha(c: Any) -> float:
    try:
        return float(mcolors.to_rgba(c)[3])
    except Exception:
        return 1.0


class Ink:
    def __init__(self, fig, kind: str, *, lazy: bool = False):
        self.fig = fig
        self.kind = kind
        self.records: List[Dict[str, Any]] = []
        self.shells: List[Tuple[str, Bbox]] = []
        self.ren = None
        self.W = 0.0
        self.H = 0.0
        # lazy=True：等 align／grow 後再第一次 draw，少一次無效 Agg
        if not lazy:
            self.redraw()

    def redraw(self) -> None:
        """整圖 Agg draw 一次並刷新 renderer。查股大量區曾因 ink 連 draw 20 次拖到兩分多鐘。"""
        self.fig.canvas.draw()
        self.ren = self.fig.canvas.get_renderer()
        self.W = float(self.fig.bbox.width)
        self.H = float(self.fig.bbox.height)

    # ---------- 基本工具 ----------
    def pt(self, v: float) -> float:
        return float(v) * self.fig.dpi / 72.0

    def measure(self, s: str, prop) -> Tuple[float, float, float]:
        w, h, d = self.ren.get_text_width_height_descent(s, prop, ismath=False)
        return float(w), float(h), float(d)

    def ext(self, art) -> Bbox:
        return art.get_window_extent(self.ren)

    def shell_ext(self, t: Text) -> Bbox:
        bp = t.get_bbox_patch()
        if bp is not None and bp.get_visible():
            try:
                t.update_bbox_position_size(self.ren)
            except Exception:
                pass
            return bp.get_window_extent(self.ren)
        return t.get_window_extent(self.ren)

    def _container_add(self, container, art):
        if hasattr(container, "add_artist"):
            container.add_artist(art)
        return art

    def rect(self, container, x0, y0, x1, y1, *, fc, ec="none", lw=0.0, z=20.0, ls="-", hatch=None, hatchcolor=None, gid="ink:shell", alpha=1.0):
        r = Rectangle(
            (x0 / self.W, y0 / self.H),
            (x1 - x0) / self.W,
            (y1 - y0) / self.H,
            transform=self.fig.transFigure,
            facecolor=fc,
            edgecolor=ec,
            linewidth=lw,
            linestyle=ls,
            zorder=z,
            clip_on=False,
            alpha=alpha,
        )
        if hatch:
            r.set_hatch(hatch)
            if hatchcolor:
                r.set_hatchcolor(hatchcolor)
        r.set_gid(gid)
        return self._container_add(container, r)

    def poly(self, container, pts_px, *, fc, ec="none", lw=0.0, z=20.0, gid="ink:shell"):
        pts = [(x / self.W, y / self.H) for x, y in pts_px]
        p = Polygon(pts, closed=True, transform=self.fig.transFigure, facecolor=fc, edgecolor=ec, linewidth=lw, zorder=z, clip_on=False)
        p.set_gid(gid)
        return self._container_add(container, p)

    def text(self, container, x, y, s, *, prop, color, ha="center", va="baseline", z=21.0, gid="ink:value"):
        t = Text(x / self.W, y / self.H, s, fontproperties=prop, color=color, ha=ha, va=va, transform=self.fig.transFigure, zorder=z, clip_on=False)
        t.set_gid(gid)
        return self._container_add(container, t)

    def line(self, container, xs_px, ys_px, *, color, lw, z=20.0, ls="-", gid="ink:rule"):
        ln = Line2D([x / self.W for x in xs_px], [y / self.H for y in ys_px], transform=self.fig.transFigure, color=color, linewidth=lw, linestyle=ls, zorder=z, clip_on=False, solid_capstyle="butt")
        ln.set_gid(gid)
        return self._container_add(container, ln)

    def move_text_px(self, t: Text, x: float, y: float, *, ha: str, va: str) -> None:
        """把既有 Text 移到像素位置（Annotation 走 xyann＋textcoords 反算）。"""
        if isinstance(t, Annotation):
            tf = t._get_xy_transform(self.ren, t.anncoords) if hasattr(t, "_get_xy_transform") else None
            if tf is None:
                tf = t.axes.transData if t.axes else self.fig.transFigure
            xd, yd = tf.inverted().transform((x, y))
            t.xyann = (float(xd), float(yd))
        else:
            t.set_transform(self.fig.transFigure)
            t.set_position((x / self.W, y / self.H))
        t.set_ha(ha)
        t.set_va(va)
        t.set_clip_on(False)

    def record(self, original: str, parts: List[str], role: str, shell: Bbox) -> None:
        self.records.append({"original": original, "parts": parts, "role": role})
        self.shells.append((role, shell))

    def shadow_effect(self, off_pt: float = 2.2):
        return [pe.withSimplePatchShadow(offset=(off_pt, -off_pt), shadow_rgbFace=INK, alpha=1.0, rho=1.0)]

    # ---------- 雙色徽章：先規劃、再解疊、後畫 ----------
    def plan_badge(
        self,
        t: Text,
        label: str,
        value: str,
        *,
        fill: str,
        on_fill: str,
        value_color: str,
        edge: str,
        tier: int,
        role: str,
        size: Optional[float] = None,
        container=None,
        anchor: Optional[str] = None,
    ) -> Dict[str, Any]:
        size0 = float(size or t.get_fontsize())
        shell = self.shell_ext(t)
        ha = anchor or t.get_ha()
        # 外殼尺寸＝正式外殼（智能定位已挑過位置）；字太寬才略縮字級
        tw, th = float(shell.width), float(shell.height)
        prop = fp(size0, heavy=True)
        wl = wv = 0.0
        padx = 0.0
        for sc in (1.0, 0.97, 0.94, 0.91, 0.88, 0.85):
            prop = fp(size0 * sc, heavy=True)
            wl, _hl, _dl = self.measure(label, prop)
            wv, _hv, _dv = self.measure(value, prop)
            padx = (tw - wl - wv) / 4.0
            if padx >= self.pt(1.5):
                break
        # 升階：一級更疏、三級更扁，字階一眼主次
        min_pad = self.pt(2.4 if tier == 1 else (1.6 if tier == 2 else 1.2))
        padx = max(padx, min_pad)
        _w, href, dref = self.measure("撐壓9g", prop)
        box_h = max(th, href + 2 * self.pt(1.35 if tier == 1 else (0.95 if tier == 2 else 0.55)))
        if tier == 3:
            box_h = min(box_h, href + 2 * self.pt(0.5))
        wlab = wl + 2 * padx
        wval = wv + 2 * padx
        total = wlab + wval
        cy = 0.5 * (shell.y0 + shell.y1)
        if ha == "left":
            x0 = shell.x0
        elif ha == "right":
            x0 = shell.x1 - total
        else:
            x0 = 0.5 * (shell.x0 + shell.x1) - total / 2
        return {
            "t": t, "label": label, "value": value, "original": str(t.get_text()),
            "fill": fill, "on_fill": on_fill, "value_color": value_color, "edge": edge,
            "tier": tier, "role": role, "prop": prop, "href": href, "dref": dref,
            "x0": x0, "xm": x0 + wlab, "x1": x0 + total,
            "y0": cy - box_h / 2, "y1": cy + box_h / 2,
            "min_h": href + 2 * self.pt(0.4),
            "cont": container if container is not None else (t.axes if t.axes is not None else self.fig),
        }

    def resolve_badges(self, plans: List[Dict[str, Any]]) -> None:
        """成對上下貼放的徽章不准互壓（含一級徽章的硬陰影）：先對稱收高度，仍不夠才各退一半。"""
        # 無陰影：上下徽章至少留足空隙，避免貼近被看成底投影
        shadow = self.pt(1.8) if USE_SHADOW else 0.0
        breath = 0.0 if USE_SHADOW else self.pt(2.8)
        # 升階：徽章離框更遠，主圖呼吸感
        margin = self.pt(3.6)
        for pl in plans:
            ax = pl["t"].axes
            if ax is None:
                continue
            ab = ax.get_window_extent(self.ren)
            dx = 0.0
            if pl["x0"] < ab.x0 + margin:
                dx = ab.x0 + margin - pl["x0"]
            elif pl["x1"] > ab.x1 - margin:
                dx = (ab.x1 - margin) - pl["x1"]
            if dx:
                for k in ("x0", "xm", "x1"):
                    pl[k] += dx
        for _ in range(8):
            moved = False
            for i in range(len(plans)):
                for j in range(i + 1, len(plans)):
                    a, b = plans[i], plans[j]
                    xo = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
                    if xo <= 0:
                        continue
                    up, lo = (a, b) if (a["y0"] + a["y1"]) >= (b["y0"] + b["y1"]) else (b, a)
                    gap = (shadow if up["tier"] == 1 else 0.0) + self.pt(0.9) + breath
                    ov = lo["y1"] + gap - up["y0"]
                    if ov <= 0.25:
                        continue
                    su = max(0.0, min(ov, (up["y1"] - up["y0"]) - up["min_h"]))
                    sl = max(0.0, min(ov, (lo["y1"] - lo["y0"]) - lo["min_h"]))
                    got = 0.0
                    # 對稱收：每邊收 s/2，接縫處各得 s/2
                    take_u = min(su, ov)
                    up["y0"] += take_u / 2
                    up["y1"] -= take_u / 2
                    got += take_u / 2
                    rem = ov - got
                    if rem > 0:
                        take_l = min(sl, 2 * rem)
                        lo["y0"] += take_l / 2
                        lo["y1"] -= take_l / 2
                        got += take_l / 2
                    rem = ov - got
                    if rem > 0.25:
                        up["y0"] += rem / 2
                        up["y1"] += rem / 2
                        lo["y0"] -= rem / 2
                        lo["y1"] -= rem / 2
                    moved = True
            if not moved:
                break

    def draw_badge(self, pl: Dict[str, Any]) -> Bbox:
        """升階標籤語言：色軌＋白體＋統一墨邊（一級實、二級實、三級虛）。無陰影。"""
        t = pl["t"]
        cont = pl["cont"]
        x0, xm, x1, y0, y1 = pl["x0"], pl["xm"], pl["x1"], pl["y0"], pl["y1"]
        tier = pl["tier"]
        edge = INK if tier <= 2 else pl["edge"]
        z0 = float(max(t.get_zorder(), 12)) + 0.5
        lw_edge = 1.55 if tier == 1 else (1.25 if tier == 2 else 1.0)
        rail = self.pt(5.5 if tier == 1 else 4.0)
        # 白體底（扁平，無 offset）
        self.rect(cont, x0, y0, x1, y1, fc=PAPER, z=z0 + 0.01)
        if tier <= 2:
            # 左側色塊（標名）＋更寬墨色軌（升階臉）
            self.rect(cont, x0, y0, xm, y1, fc=pl["fill"], z=z0 + 0.02)
            self.rect(cont, x0, y0, x0 + rail, y1, fc=RAIL, z=z0 + 0.03)
        else:
            self.rect(cont, x0, y0, xm, y1, fc=pl["fill"], z=z0 + 0.02, alpha=0.92)
        self.rect(
            cont, x0, y0, x1, y1, fc="none", ec=edge, lw=lw_edge,
            ls=((0, (2.2, 1.5)) if tier == 3 else "-"), z=z0 + 0.04,
        )
        if tier <= 2:
            self.line(cont, [xm, xm], [y0 + self.pt(1.0), y1 - self.pt(1.0)], color="#D8D8D8", lw=0.9, z=z0 + 0.035)
        base = 0.5 * (y0 + y1) - pl["href"] / 2 + pl["dref"]
        prop = pl["prop"]
        lab_x0 = x0 + rail
        t.set_text(pl["label"])
        t.set_fontproperties(prop)
        t.set_color(pl["on_fill"] if tier <= 2 else pl["value_color"])
        t.set_bbox(None)
        t.set_zorder(z0 + 0.06)
        t.set_gid("ink:label")
        self.move_text_px(t, 0.5 * (lab_x0 + xm) if tier <= 2 else 0.5 * (x0 + xm), base, ha="center", va="baseline")
        self.text(cont, 0.5 * (xm + x1), base, pl["value"], prop=prop, color=pl["value_color"] if tier > 1 else INK, z=z0 + 0.06)
        bb = Bbox.from_extents(x0, y0, x1, y1)
        self.record(pl["original"], [pl["label"], pl["value"]], pl["role"], bb)
        if isinstance(t, Annotation) and t.arrow_patch is not None:
            shell_rect = self.rect(cont, x0, y0, x1, y1, fc="none", ec="none", lw=0, z=z0 - 0.2, gid="ink:hit")
            ap = dict(t.arrowprops or {})
            ap["patchA"] = shell_rect
            t.arrowprops = ap
            t.arrow_patch.set_patchA(shell_rect)
            t.arrow_patch.set_color(edge if edge != INK else "#3A3A3A")
            t.arrow_patch.set_linewidth(2.15)  # 箭頭加粗
            try:
                t.arrow_patch.set_mutation_scale(max(float(t.arrow_patch.get_mutation_scale() or 12), 18.0))
            except Exception:
                pass
        return bb

    # ---------- 單色外殼 ----------
    def sticker(self, t: Text, *, fc: str, tc: str, ec: Optional[str] = None, pad: float = 0.3, shadow: bool = False, size: Optional[float] = None, heavy: bool = True, role: str = "sticker", lw: float = 0.0, boxstyle: str = "square") -> None:
        if size:
            t.set_fontproperties(fp(size, heavy=heavy))
        else:
            t.set_fontproperties(fp(t.get_fontsize(), heavy=heavy))
        t.set_color(tc)
        t.set_bbox(dict(boxstyle=f"{boxstyle},pad={pad}", facecolor=fc, edgecolor=ec or fc, linewidth=lw))
        bp = t.get_bbox_patch()
        if shadow and USE_SHADOW and bp is not None:
            bp.set_path_effects(self.shadow_effect())
        t.set_clip_on(False)
        self.record(str(t.get_text()), [str(t.get_text())], role, self.shell_ext(t))


# ====================================================================
# 共用：K、量、帶、線、格、刻度
# ====================================================================

def _map_color(c: Any, mp: Dict[str, str]) -> Any:
    h = _hex(c)
    if h in mp:
        a = _alpha(c)
        r, g, b, _ = mcolors.to_rgba(mp[h])
        return (r, g, b, a)
    return c


def restyle_candles_and_bars(ax, *, volume: bool = False) -> None:
    """K 實體＝同色直角 Rectangle；不准加深描邊／半透明把窄柱糊成圓角。"""
    candle_rects: List[Rectangle] = []
    for p in ax.patches:
        if not isinstance(p, Rectangle):
            continue
        fc = _hex(p.get_facecolor())
        ec = _hex(p.get_edgecolor())
        if fc in CANDLE_MAP:
            new_fc = _map_color(p.get_facecolor(), CANDLE_MAP)
            p.set_facecolor(new_fc)
            # 與大量圖／正式柱一致：邊＝面、直角、不透明；加深描邊＋AA＝遠看圓角元兇
            if not volume:
                p.set_edgecolor(new_fc)
                p.set_linewidth(0.0)
                p.set_alpha(1.0)
                try:
                    p.set_antialiased(False)
                except Exception:
                    pass
                candle_rects.append(p)
            elif ec in CANDLE_MAP:
                p.set_edgecolor(_map_color(p.get_edgecolor(), CANDLE_MAP))
        elif volume and fc == "#f9a825":
            p.set_facecolor(SPIKE)
            p.set_edgecolor(INK)
            p.set_linewidth(1.05)
            p.set_hatch("///")
            p.set_hatchcolor("#B88400")
        elif volume and fc == "#42a5f5":
            p.set_facecolor(NEXT_H)
            p.set_edgecolor(INK)
            p.set_linewidth(1.05)
    # 結構圖柱多、像素窄 → 實體略加寬，遠看才不像細膠囊
    if not volume and len(candle_rects) >= 120:
        for p in candle_rects:
            old_w = float(p.get_width())
            new_w = min(old_w * 1.18, 0.86)
            if new_w > old_w + 1e-9:
                cx = float(p.get_x()) + old_w / 2.0
                p.set_width(new_w)
                p.set_x(cx - new_w / 2.0)
    for c in ax.collections:
        if isinstance(c, LineCollection) and len(c.get_paths()) >= 20:
            cols = c.get_colors()
            if len(cols):
                c.set_colors([_map_color(col, CANDLE_MAP) for col in cols])
            # 影線端改 butt，避免 round cap 把窄 K 頂底糊圓
            try:
                c.set_capstyle("butt")
            except Exception:
                pass


def restyle_bands(ax) -> None:
    for p in list(ax.patches):
        if not isinstance(p, Rectangle):
            continue
        fc = _hex(p.get_facecolor())
        try:
            wide = p.get_width() >= 0.9 and p.get_transform() != ax.transData
        except Exception:
            wide = False
        if fc in ("#ffe0b2", "#ffcc80", "#ffd7a8", "#ffb74d") and wide:
            # v2d 加深桃底＋細斜線；右端不准出現白塊假影
            p.set_facecolor(SKIN)
            p.set_alpha(0.60)
            p.set_hatch("////")
            p.set_hatchcolor(SKIN_HATCH)
            p.set_edgecolor("none")
            p.set_linewidth(0)
            try:
                p.set_antialiased(False)
            except Exception:
                pass
        elif fc in ("#9e9e9e", "#78909c", "#90a4ae", "#607d8b") and wide:
            # 下一層深灰價帶（v2c α≈0.38）；點紋略留層次
            p.set_facecolor(LAYER_FACE if fc == "#9e9e9e" else fc)
            p.set_alpha(0.38 if fc != "#9e9e9e" else 0.45)
            p.set_hatch("..")
            p.set_hatchcolor(LAYER_HATCH)
            p.set_edgecolor("none")
            try:
                p.set_antialiased(False)
            except Exception:
                pass
        # 資料座標的壓／撐色帶：消右端白截斷（裁到 xlim 內側）
        try:
            in_data = p.get_transform() == ax.transData
        except Exception:
            in_data = False
        if in_data and 0.05 < abs(float(p.get_width())) and float(p.get_height()) > 0:
            x0, x1 = ax.get_xlim()
            px = float(p.get_x())
            pw = float(p.get_width())
            if pw > (x1 - x0) * 0.15:  # 橫跨多日的帶
                left = max(px, float(x0))
                right = min(px + pw, float(x1))
                if right > left + 1e-9:
                    p.set_x(left)
                    p.set_width(right - left)


def restyle_levels(ax) -> None:
    """主壓／主撐加粗墨線；下一層維持虛線；通道紫改墨紫。"""
    for c in ax.collections:
        if not isinstance(c, LineCollection) or len(c.get_paths()) >= 20:
            continue
        col = _hex(c.get_colors()[0]) if len(c.get_colors()) else ""
        dashed = any(dash is not None for _off, dash in c.get_linestyle())
        if col == "#ad1457":
            c.set_colors([PRESS])
            c.set_linewidths([1.0 if dashed else 2.35])
        elif col in ("#1b5e20", "#0a4d1c"):
            c.set_colors([HOLD])
            c.set_linewidths([1.0 if dashed else 2.35])
        elif col in ("#1565c0", "#0a3d8f", "#062e70"):
            c.set_colors([NEXT_H])
            c.set_linewidths([0.95])
    for ln in ax.lines:
        col = _hex(ln.get_color())
        ls = ln.get_linestyle()
        if col == "#ad1457" and ls == "-":
            ln.set_color(PRESS)
            ln.set_linewidth(2.2)
        elif col in ("#1b5e20", "#0a4d1c") and ls == "-":
            ln.set_color(HOLD)
            ln.set_linewidth(2.2)
        elif col == "#6a1b9a" and ls == "--" and len(ln.get_xdata()) == 2:
            ln.set_color(VIOLET)
            ln.set_linewidth(1.35)
        elif col == "#90a4ae":
            ln.set_color("#6E6E6E")
            ln.set_linestyle((0, (3.5, 2.8)))
            ln.set_linewidth(0.75)
        elif col in ("#5f7a92", "#5F7A92"):
            # 個股大量區淡灰藍平行軌（#717／v2e）：保持虛線可見，不准洗成實線／過淡
            ln.set_color("#5f7a92")
            ln.set_linestyle((0, (2.4, 2.0)))
            ln.set_linewidth(max(float(ln.get_linewidth() or 1.0), 1.35))
    for c in ax.collections:
        if isinstance(c, PathCollection):
            fc = _hex(c.get_facecolor()[0]) if len(c.get_facecolor()) else ""
            if fc == "#6a1b9a":
                c.set_facecolor(PAPER)
                c.set_edgecolor(VIOLET)
                c.set_linewidth(1.6)
    for ln in ax.lines:
        if ln.get_marker() == "o" and ln.get_linestyle() in ("None", "", " "):
            mfc = _hex(ln.get_markerfacecolor())
            if mfc == "#ad1457":
                ln.set_markerfacecolor(PRESS)
            elif mfc in ("#1b5e20", "#0a4d1c"):
                ln.set_markerfacecolor(HOLD)
            ln.set_markeredgecolor(INK)
            ln.set_markeredgewidth(0.9)


def restyle_grid_ticks(ax, *, ylab_size: float = 11.0, xlab_size: float = 11.0, heavy_y: bool = True) -> None:
    # 升階：格線退成髮絲，呼吸感留給 K／徽章
    for g in ax.get_ygridlines():
        g.set_color(RULE)
        g.set_linestyle("-")
        g.set_linewidth(0.35)
        g.set_alpha(0.9)
    for g in ax.get_xgridlines():
        g.set_color(RULE_V)
        g.set_linestyle((0, (1.0, 2.2)))
        g.set_linewidth(0.35)
        g.set_alpha(0.85)
    ax.tick_params(colors=INK, width=1.05)
    for lab in ax.get_yticklabels():
        lab.set_fontproperties(fp(ylab_size, heavy=heavy_y))
        lab.set_color(INK2)
    for lab in ax.get_xticklabels():
        lab.set_fontproperties(fp(xlab_size, heavy=True))
        lab.set_color(INK)


def panel_shadow(ink: Ink, bb_px: Bbox, *, off_pt: float = 3.2, z: float = -5.0) -> None:
    """面板硬陰影。修訂／定稿：USE_SHADOW=False → 什麼都不加（不准 offset patch）。"""
    if not USE_SHADOW:
        return
    off = ink.pt(off_pt)
    ink.rect(ink.fig, bb_px.x0 + off, bb_px.y0 - off, bb_px.x1 + off, bb_px.y1 - off, fc=INK, z=z, gid="ink:shadow")
    ink.rect(ink.fig, bb_px.x0, bb_px.y0, bb_px.x1, bb_px.y1, fc=PAPER, z=z + 0.5, gid="ink:card")


def kill_seam_ticks(*axes) -> None:
    """匡縫短豎／刻度刺：主圖底、量圖頂、訊號列 — 刻度線全關（量圖日期字可留）。"""
    for ax in axes:
        if ax is None:
            continue
        keep_labels = bool(any(t.get_visible() and str(t.get_text()).strip() for t in ax.get_xticklabels()))
        ax.tick_params(axis="x", which="both", length=0, bottom=False, top=False)
        for ln in list(ax.xaxis.get_majorticklines()) + list(ax.xaxis.get_minorticklines()):
            ln.set_visible(False)
            ln.set_markersize(0.0)
        if keep_labels:
            ax.tick_params(axis="x", labelbottom=True)


def close_struct_frame_seam(frames: List[FancyBboxPatch]) -> None:
    """結構圖中／下匡若有縫，把兩匡對接消縫，避免縫裡藏短豎。"""
    if len(frames) < 2:
        return
    ordered = sorted(frames, key=lambda p: -(p.get_y() + p.get_height()))
    # header, mid, vol（或 mid, vol）
    body = ordered[1:] if len(ordered) >= 3 else ordered
    if len(body) < 2:
        return
    mid, vol = body[0], body[1]
    mid_bot = float(mid.get_y())
    vol_top = float(vol.get_y() + vol.get_height())
    gap = mid_bot - vol_top
    if gap <= 0.02:
        return
    # 各擴一半＋微重疊，縫消失
    grow = gap * 0.5 + 0.08
    mid.set_y(mid_bot - grow)
    mid.set_height(float(mid.get_height()) + grow)
    vol.set_height(float(vol.get_height()) + grow)


def scrub_flat(fig) -> Dict[str, int]:
    """定稿保險：剝光 Shadow path_effects、刪 ink:shadow offset patch。回傳計數供自證。"""
    n_pe = 0
    n_shadow_patch = 0
    for art in fig.findobj(lambda a: hasattr(a, "get_path_effects")):
        try:
            effects = list(art.get_path_effects() or [])
        except Exception:
            continue
        cleaned = [e for e in effects if "Shadow" not in type(e).__name__]
        if len(cleaned) != len(effects):
            art.set_path_effects(cleaned)
            n_pe += 1
        if isinstance(art, Text):
            bp = art.get_bbox_patch()
            if bp is not None:
                try:
                    be = list(bp.get_path_effects() or [])
                except Exception:
                    be = []
                bc = [e for e in be if "Shadow" not in type(e).__name__]
                if len(bc) != len(be):
                    bp.set_path_effects(bc)
                    n_pe += 1
    for container in [fig] + list(fig.axes):
        for p in list(getattr(container, "patches", [])):
            gid = str(p.get_gid() or "")
            if gid == "ink:shadow":
                try:
                    p.remove()
                    n_shadow_patch += 1
                except Exception:
                    p.set_visible(False)
                    n_shadow_patch += 1
    return {"cleared_shadow_pe": n_pe, "removed_shadow_patches": n_shadow_patch}


# ====================================================================
# 標籤分角色
# ====================================================================

_SPLIT_RE = re.compile(r"^(.*\S)[ \u3000]+(\S+)$")


def split_label(s: str) -> Optional[Tuple[str, str]]:
    m = _SPLIT_RE.match(str(s or "").strip())
    if not m:
        return None
    return m.group(1).strip(), m.group(2).strip()


def label_role(s: str) -> str:
    s = str(s or "").strip()
    if s.startswith("下一層量日"):
        return "layer_day"
    if s.startswith("下一層壓"):
        return "next_press"
    if s.startswith("下一層撐"):
        return "next_hold"
    if s.startswith("大量區壓") or re.match(r"^壓\s", s):
        return "press"
    if s.startswith("大量區撐") or re.match(r"^撐\s", s):
        return "hold"
    if s.startswith("昨收"):
        return "prev_close"
    if s.startswith("今收"):
        return "today_close"
    if any(k in s for k in ("平行撐", "平行壓", "下降壓", "上升軌", "上昇軌", "上軌", "下軌")):
        return "channel"
    if "爆大量" in s:
        return "spike"
    if s.startswith("原文目標") or "原文目標" in s:
        return "target"
    return ""


ROLE_STYLE = {
    # 升階色階：一級高對比、二級實、三級淡（形狀統一＝色軌＋白體）
    "press": dict(fill=PRESS, on_fill=PAPER, value_color=PRESS, edge=INK, tier=1),
    "hold": dict(fill=HOLD, on_fill=PAPER, value_color=HOLD, edge=INK, tier=1),
    "today_close": dict(fill=INK, on_fill=PAPER, value_color=INK, edge=INK, tier=1),
    "prev_close": dict(fill=GRAYTAG, on_fill=PAPER, value_color=INK2, edge=INK, tier=2),
    "channel": dict(fill=VIOLET, on_fill=PAPER, value_color=VIOLET, edge=INK, tier=2),
    "next_press": dict(fill="#F7E8EC", on_fill=PRESS, value_color=PRESS, edge=PRESS, tier=3),
    "next_hold": dict(fill="#C5D4EC", on_fill=NEXT_H, value_color=NEXT_H, edge=NEXT_H, tier=3),
    "spike": dict(fill=SPIKE, on_fill=INK, value_color=INK, edge=INK, tier=2),
    "layer_day": dict(fill=NEXT_H, on_fill=PAPER, value_color=NEXT_H, edge=INK, tier=2),
}


def _clamp_badges_below_seam(ink: Ink, plans: List[Dict[str, Any]], seam_top: float, *, min_gap_px: float = 16.0) -> None:
    """徽章在縫下方：頂邊離縫至少 min_gap_px（display y，越大越高）。"""
    gap = float(min_gap_px)
    for pl in plans:
        if pl.get("role") not in ("spike", "layer_day"):
            continue
        # 只處理縫下方（y1 接近或低於 seam）
        if pl["y1"] > seam_top + ink.pt(8):
            continue
        target = seam_top - gap
        if pl["y1"] > target:
            dy = pl["y1"] - target
            pl["y0"] -= dy
            pl["y1"] -= dy


def _style_vol_event_label(ink: Ink, t: Text, role: str) -> None:
    """爆大量／下一層量日＝細標＋小貼紙，不准畫成實心大框蓋量柱。"""
    s = str(t.get_text() or "")
    parts = split_label(s)
    if role == "spike":
        fc, tc = SPIKE, INK
    else:
        fc, tc = NEXT_H, PAPER
    # 壓成單行細標：保留原字，外殼小 pad
    size = min(max(float(t.get_fontsize()), 10.0), 12.0)
    if parts:
        # 「爆大量 08/25」→ 兩段仍同一氣泡，字級收斂
        t.set_text(f"{parts[0]} {parts[1]}")
    t.set_fontproperties(fp(size, heavy=True))
    t.set_color(tc if role == "layer_day" else INK)
    t.set_bbox(
        dict(
            boxstyle="square,pad=0.22",
            facecolor=fc if role == "spike" else NEXT_H,
            edgecolor=INK,
            linewidth=0.95,
            alpha=0.92,
        )
    )
    t.set_zorder(max(float(t.get_zorder()), 14))
    t.set_clip_on(False)
    # 箭頭改細，不准跟着外殼變巨
    if isinstance(t, Annotation) and t.arrow_patch is not None:
        t.arrow_patch.set_linewidth(1.35)
        t.arrow_patch.set_color("#4A4A4A")
        try:
            t.arrow_patch.set_mutation_scale(min(float(t.arrow_patch.get_mutation_scale() or 12), 14.0))
        except Exception:
            pass
        try:
            t.arrow_patch.set_alpha(0.85)
        except Exception:
            pass
    ink.record(s, [str(t.get_text())], role, ink.shell_ext(t))


def badge_all_labels(ink: Ink, axes, *, vol_ax=None) -> None:
    # 只略抬「大量區壓／撐」；爆大量／下一層量日走細標，不准進實心徽章
    if ink.kind == "vol":
        bumped = False
        for ax in axes:
            for t in list(ax.texts):
                if not t.get_visible():
                    continue
                role = label_role(str(t.get_text() or ""))
                if role in ("press", "hold"):
                    t.set_fontproperties(fp(max(float(t.get_fontsize()) * 1.10, 14.5), heavy=True))
                    bumped = True
        if bumped:
            ink.redraw()
    plans = []
    for ax in axes:
        for t in list(ax.texts):
            if not t.get_visible():
                continue
            s = str(t.get_text() or "")
            # 個股淡灰藍趨勢小標（名＋最新價）保留原貌，不准墨線徽章拆掉價
            try:
                if str(t.get_gid() or "").startswith("ink:quiet-rail"):
                    continue
            except Exception:
                pass
            role = label_role(s)
            if not role or role not in ROLE_STYLE or "\n" in s:
                continue
            # 量區事件標：細標，不走 plan_badge（外殼跟 Annotation 窗體會爆成蓋柱大框）
            if role in ("spike", "layer_day"):
                _style_vol_event_label(ink, t, role)
                continue
            parts = split_label(s)
            if not parts:
                continue
            st = ROLE_STYLE[role]
            plans.append(ink.plan_badge(t, parts[0], parts[1], role=role, **st))
    ink.resolve_badges(plans)
    if vol_ax is not None:
        seam = float(vol_ax.get_window_extent(ink.ren).y1)
        _clamp_badges_below_seam(ink, plans, seam, min_gap_px=max(16.0, ink.pt(12.0)))
    _nudge_labels_off_recent_k(ink, plans)
    for pl in plans:
        ink.draw_badge(pl)


def _nudge_labels_off_recent_k(ink: Ink, plans: List[Dict[str, Any]]) -> None:
    """結構／主圖右側「下一層壓／撐」等不准壓住最近 K。"""
    for pl in plans:
        if pl.get("role") not in ("next_press", "next_hold", "prev_close", "today_close"):
            continue
        ax = pl["t"].axes
        if ax is None:
            continue
        ab = ax.get_window_extent(ink.ren)
        # 落在右 18% 內 → 往左讓出最近 K
        edge = ab.x0 + 0.82 * ab.width
        if pl["x1"] < edge:
            continue
        dx = min(pl["x1"] - edge, ink.pt(56))
        if dx <= 0.5:
            continue
        for k in ("x0", "xm", "x1"):
            pl[k] -= dx


def _ma_stamp_colors(t: Text) -> Tuple[str, str]:
    """圓章底色取自 bbox／邊，不准用字色當底（白字→白底會吞掉 季／月）。"""
    bp = t.get_bbox_patch()
    face = _hex(bp.get_facecolor()) if bp is not None else ""
    edge = _hex(bp.get_edgecolor()) if bp is not None else ""
    txt = _hex(t.get_color())
    # 淺底（原版）→ 用邊色當實心底；深／彩邊才是辨識色
    light = face in ("", "#ffffff", "#fff", "#e8eaf6", "#fffde7", "#e0f7fa", "#fff3e0", "#f3e5f5")
    col = edge if (light and edge and edge not in ("#000000", "#000", INK.lower())) else (face or edge or txt)
    if not col or col in ("#ffffff", "#fff"):
        col = txt if txt not in ("#ffffff", "#fff", PAPER.lower()) else "#5c6bc0"
    # 亮度：淺底墨字、深底白字（黃／橙系一律墨字）
    try:
        r, g, b, _a = mcolors.to_rgba(col)
        lum = 0.299 * r + 0.587 * g + 0.114 * b
    except Exception:
        lum = 0.5
    warm = col.lower() in ("#f9a825", "#fbc02d", "#ffb300", "#ef6c00", "#e65100", "#ff6f00", "#ffc107", YELLOW.lower())
    tc = INK if (lum >= 0.45 or warm) else PAPER
    # 月線黃系強制墨字；白字＋白描邊會吞字
    if col.lower() in ("#f9a825", "#fbc02d", "#ffb300", "#ffc107", YELLOW.lower()):
        tc = INK
    return col, tc


def ma_badges(ink: Ink, ax) -> None:
    for t in list(ax.texts):
        s = str(t.get_text() or "").strip()
        if s not in ("5", "10", "月", "季") or t.get_bbox_patch() is None:
            continue
        col, tc = _ma_stamp_colors(t)
        t.set_color(tc)
        # 圓章：實心底＋墨邊；描邊用對比色，白描邊不准吞白字
        t.set_fontproperties(fp(max(11.0, float(t.get_fontsize()) + 0.8), heavy=True))
        t.set_bbox(dict(boxstyle="circle,pad=0.28", facecolor=col, edgecolor=INK, linewidth=1.45))
        halo = PAPER if tc == INK else INK
        t.set_path_effects([pe.withStroke(linewidth=1.35, foreground=halo)])
        t.set_zorder(12.5)
        t.set_clip_on(False)
        t.set_gid(f"ink:ma:{s}")
        ink.record(s, [s], "ma_badge", ink.shell_ext(t))


# ====================================================================
# 結構圖
# ====================================================================

def _struct_axes(fig):
    ov = None
    others = []
    for ax in fig.axes:
        p = ax.get_position()
        if p.x0 <= 0.001 and p.width >= 0.999 and not ax.axison:
            ov = ax
        else:
            others.append(ax)
    others.sort(key=lambda a: a.get_position().height, reverse=True)
    return ov, others[0], others[1] if len(others) > 1 else None


def _kv_pairs(s: str) -> Optional[List[Tuple[str, str]]]:
    """「最近收盤 2026-10-27　開 146.5…」→ [(最近收盤, 2026-10-27), (開, 146.5)…]；拼回必須等於原字。"""
    val = r"[-+]?\d[\d,./\-:]*(?:張|元|%|＝壓|＝撐)?"
    pairs = re.findall(r"([^\d\s\u3000／]+?)\s*(" + val + ")", s)
    if not pairs:
        return None
    flat = "".join(a + b for a, b in pairs)
    norm = re.sub(r"[\s\u3000]", "", s)
    if flat != norm.replace("／", ""):
        return None
    return [(a.strip(), b.strip()) for a, b in pairs]


def _detect_limit_from_header(ov) -> Optional[str]:
    """從頭欄「較昨日 ▲／▼ x.xx（±y%）」＋收盤價推漲跌停。興櫃不判。"""
    try:
        from wayne_navigator import quote_limit_side
    except Exception:
        return None
    close = None
    pct = None
    for t in ov.texts:
        s = str(t.get_text() or "").strip()
        if re.fullmatch(r"[\d,.]+", s) and t.get_ha() == "right" and t.get_fontsize() >= 24:
            try:
                close = float(s.replace(",", ""))
            except Exception:
                pass
        if s.startswith("較昨日"):
            m = re.search(r"[（(]([+\-]?\d+(?:\.\d+)?)%?[）)]", s)
            if m:
                try:
                    pct = float(m.group(1))
                except Exception:
                    pct = None
    if close is None:
        return None
    prev = None
    if pct is not None and abs(pct) > 1e-9:
        prev = close / (1.0 + pct / 100.0)
    return quote_limit_side(close, prev, pct, emerging=False)


def struct_header(ink: Ink, ov, frames: List[FancyBboxPatch]) -> None:
    fig = ink.fig
    texts = {str(t.get_text()): t for t in ov.texts if t.get_visible()}
    hdr = max(frames, key=lambda p: p.get_window_extent(ink.ren).y1) if frames else None
    hb = hdr.get_window_extent(ink.ren) if hdr is not None else None
    name_t = next((t for t in ov.texts if t.get_fontsize() >= 28 and _hex(t.get_color()) == "#1f2933"), None)
    chips: List[Text] = []
    if name_t is not None:
        ne0 = ink.ext(name_t)
        for t in ov.texts:
            if t is name_t or t.get_bbox_patch() is None or not t.get_visible():
                continue
            ce = ink.shell_ext(t)
            if ne0.y0 - 2 <= 0.5 * (ce.y0 + ce.y1) <= ne0.y1 + 2 and ce.x0 >= ne0.x1 - 2:
                chips.append(t)
        chips.sort(key=lambda t: ink.shell_ext(t).x0)
    # 1) 反白名牌：黑墨塊貼頭欄頂，股名白字、產業黃標、龍頭橘標
    if name_t is not None and hb is not None:
        ne = ink.ext(name_t)
        right = ne.x1
        for c in chips:
            right = max(right, ink.shell_ext(c).x1)
        tab_x0 = hb.x0
        tab_x1 = right + ink.pt(9)
        tab_y0 = ne.y0 - ink.pt(4.5)
        tab_y1 = hb.y1
        ink.rect(ov, tab_x0, tab_y0, tab_x1, tab_y1, fc=INK, z=21.0, gid="ink:masthead")
        # 名牌右緣斜切一刀（墨線招牌）
        ink.poly(ov, [(tab_x1, tab_y1), (tab_x1 + ink.pt(12), tab_y1), (tab_x1, tab_y0)], fc=INK, z=21.0, gid="ink:masthead")
        # 升階：名牌底黃墨細線＝頭欄主層錨點
        ink.line(ov, [tab_x0, tab_x1 + ink.pt(6)], [tab_y0, tab_y0], color=YELLOW, lw=2.6, z=21.3)
        name_t.set_color(PAPER)
        name_t.set_fontproperties(fp(name_t.get_fontsize() + 1.5, heavy=True))
        name_t.set_zorder(22.5)
        ink.record(str(name_t.get_text()), [str(name_t.get_text())], "name", ne)
        for c in chips:
            c.set_zorder(22.6)
            if str(c.get_text()).strip() == "龍頭":
                ink.sticker(c, fc=CALL, tc=PAPER, ec=INK, pad=0.22, shadow=False, lw=1.1, role="leader")
            else:
                ink.sticker(c, fc=YELLOW, tc=INK, ec=INK, pad=0.22, shadow=False, lw=1.1, role="industry")
    # 2) 資料條：列首反白籤＋小灰標＋粗黑值
    rows = [t for t in ov.texts if t.get_visible() and _kv_pairs(str(t.get_text())) and t.get_fontsize() >= 13 and t.get_ha() == "left"]
    for t in rows:
        s = str(t.get_text())
        pairs = _kv_pairs(s)
        if not pairs:
            continue
        te = ink.ext(t)
        spike_row = s.startswith("爆大量")
        size = float(t.get_fontsize())
        lab_prop = fp(size * 0.78, heavy=False)
        val_prop = fp(size, heavy=True)
        tab_prop = fp(size * 0.8, heavy=True)
        _w, href, dref = ink.measure("撐9", val_prop)
        cy = 0.5 * (te.y0 + te.y1)
        base = cy - href / 2 + dref
        x = te.x0
        parts: List[str] = []
        first_lab, first_val = pairs[0]
        # 列首籤
        wtab, htab, dtab = ink.measure(first_lab, tab_prop)
        padx = ink.pt(3.2)
        pady = ink.pt(2.0)
        tab_fc = PRESS if spike_row else INK
        ink.rect(ov, x, cy - htab / 2 - pady, x + wtab + 2 * padx, cy + htab / 2 + pady, fc=tab_fc, z=21.5)
        ink.text(ov, x + padx + wtab / 2, cy - htab / 2 + dtab, first_lab, prop=tab_prop, color=PAPER, ha="center", z=22)
        parts.append(first_lab)
        x += wtab + 2 * padx + ink.pt(5)
        vcol = PRESS if spike_row else INK
        wv, _, _ = ink.measure(first_val, val_prop)
        ink.text(ov, x, base, first_val, prop=val_prop, color=vcol, ha="left", z=22)
        parts.append(first_val)
        x += wv
        for lab, val in pairs[1:]:
            x += ink.pt(12)
            # 欄間細墨線
            ink.line(ov, [x - ink.pt(6), x - ink.pt(6)], [cy - href * 0.42, cy + href * 0.42], color="#BDBDBD", lw=0.9, z=21.6)
            wl, _, _ = ink.measure(lab, lab_prop)
            ink.text(ov, x, base, lab, prop=lab_prop, color=MUTE, ha="left", z=22)
            x += wl + ink.pt(2.2)
            col = vcol
            if spike_row and val.endswith("＝撐"):
                col = HOLD
            elif spike_row and val.endswith("＝壓"):
                col = PRESS
            elif spike_row and val.endswith("張"):
                col = INK
            wv, _, _ = ink.measure(val, val_prop)
            ink.text(ov, x, base, val, prop=val_prop, color=col, ha="left", z=22)
            x += wv
            parts += [lab, val]
        t.set_visible(False)
        t.set_gid("ink:replaced")
        ink.record(s, parts, "kv_row", Bbox.from_extents(te.x0, te.y0, x, te.y1))
    # 3) 右側三行：價（大紅／綠）、漲跌（實心色塊反白）、時間（墨黑）
    for t in list(ov.texts):
        s = str(t.get_text())
        if not t.get_visible() or t.get_ha() != "right":
            continue
        col = _hex(t.get_color())
        if s.startswith("較昨日"):
            fc = UP if col == "#e53935" else (DN if col in ("#00897b", "#2e7d32", "#1b5e20", "#0a4d1c") else INK2)
            # 漲停／跌停：更深底＋字尾標（規則同源 quote_limit_side）
            limit_side = _detect_limit_from_header(ov)
            label = s
            if limit_side == "up":
                fc = LIMIT_UP
                if "漲停" not in label:
                    label = s + "　漲停"
            elif limit_side == "down":
                fc = LIMIT_DN
                if "跌停" not in label:
                    label = s + "　跌停"
            t.set_text(label)
            t.set_color(PAPER)
            t.set_fontproperties(fp(t.get_fontsize() - 0.5, heavy=True))
            t.set_bbox(dict(boxstyle="square,pad=0.28", facecolor=fc, edgecolor=INK, linewidth=1.2))
            if USE_SHADOW:
                t.get_bbox_patch().set_path_effects(ink.shadow_effect(2.0))
            ink.record(s, [label], "change", ink.shell_ext(t))
        elif re.search(r"\d{4}/\d{2}/\d{2}", s):
            t.set_color(MUTE)
            t.set_fontproperties(fp(max(9.0, t.get_fontsize() - 1.5), heavy=False))
            ink.record(s, [s], "stamp", ink.ext(t))
        elif re.fullmatch(r"[\d,.]+", s):
            limit_side = _detect_limit_from_header(ov)
            if limit_side == "up":
                t.set_color(LIMIT_UP)
            elif limit_side == "down":
                t.set_color(LIMIT_DN)
            else:
                t.set_color(UP if col == "#e53935" else (DN if col == "#00897b" else INK))
            # 升階：收盤價字級再抬，主次一眼分
            t.set_fontproperties(fp(t.get_fontsize() + 4.5, heavy=True))
            ink.record(s, [s], "price", ink.ext(t))
            # 硬鎖：縮圖 K 必須跟股價字同色（漲紅／跌綠，含漲跌停）
            sync_header_mini_candle(ov, _hex(t.get_color()) or UP)
        elif s in ("今", "K"):
            t.set_color(MUTE)
            t.set_fontproperties(fp(max(8.0, t.get_fontsize() - 1.0), heavy=False))
    for t in ov.texts:
        if str(t.get_text()) in ("收", "盤") and t.get_visible():
            t.set_color(MUTE)
            t.set_fontproperties(fp(max(9.0, t.get_fontsize() - 0.5), heavy=False))


def sync_header_mini_candle(ax, color: str) -> None:
    """頭欄今K／收盤縮圖：實體＋影線強制＝股價數字色。漲紅字紅K、跌綠字綠K。"""
    target = (color or UP).lower()
    if target in ("#d61f26", "#b71c1c"):
        target = UP.lower()
    elif target in ("#0a7a58", "#00695c", "#2e7d32", "#1b5e20", "#0a4d1c", "#045a2e"):
        target = DN.lower()
    elif target not in (UP.lower(), DN.lower()):
        # 非漲跌色就不動
        return
    body = {UP.lower(), DN.lower(), "#e53935", "#00897b", "#d61f26", "#0a7a58", "#b71c1c", "#00695c"}
    for p in ax.patches:
        if not isinstance(p, Rectangle):
            continue
        if _hex(p.get_facecolor()).lower() not in body:
            continue
        # 頭欄迷你 K：資料座標約寬 1、高 2（主圖 K 寬 0.7 不在 overlay）
        w, h = float(p.get_width()), float(p.get_height())
        if w > 8 or h > 20:
            continue
        p.set_facecolor(target)
        p.set_edgecolor(target)
        p.set_linewidth(0.0)
        p.set_alpha(1.0)
        try:
            p.set_antialiased(False)
        except Exception:
            pass
    for ln in ax.lines:
        if _hex(ln.get_color()).lower() not in body:
            continue
        xs = list(np.asarray(ln.get_xdata(), dtype=float).ravel())
        if len(xs) == 2 and abs(float(xs[0]) - float(xs[1])) < 1e-6:
            ln.set_color(target)


def struct_frames(ink: Ink, ov) -> List[FancyBboxPatch]:
    frames = [p for p in ov.patches if isinstance(p, FancyBboxPatch)]
    for p in frames:
        # 扁平墨框：方角、無陰影；外框線改細（frame-align）
        p.set_boxstyle("square,pad=0")
        p.set_edgecolor(INK)
        p.set_linewidth(1.2)
        p.set_path_effects([])
        # 透明填（或白底頭欄）— 不准灰影塊
        fc = _hex(p.get_facecolor())
        if fc not in ("#ffffff", "#fff"):
            p.set_facecolor("none")
    exts = sorted(((p, p.get_window_extent(ink.ren)) for p in frames), key=lambda pb: -pb[1].y1)
    if exts:
        panel_shadow(ink, exts[0][1])
    if len(exts) > 1:
        # 修訂 A：USE_SHADOW=False → 不加硬陰影；縫裡也不准出短直線雜訊
        panel_shadow(ink, Bbox.union([bb for _p, bb in exts[1:]]))
    for ln in list(ov.lines):
        col = _hex(ln.get_color())
        if col == "#90caf9":
            ln.set_color(INK)
            ln.set_linewidth(1.7)
        # 只刪「中／下匡縫」附近的灰短豎線；頭欄欄間細線保留
        xs = list(np.asarray(ln.get_xdata(), dtype=float).ravel())
        ys = list(np.asarray(ln.get_ydata(), dtype=float).ravel())
        if len(xs) == 2 and len(ys) == 2 and col in ("#bdbdbd", "#cfd8dc", "#e0e0e0", "#90a4ae"):
            ymid = 0.5 * (float(ys[0]) + float(ys[1]))
            if abs(float(xs[0]) - float(xs[1])) < 1e-6 and abs(float(ys[0]) - float(ys[1])) < 0.05 and 0.15 <= ymid <= 0.35:
                ln.set_visible(False)
    return frames


def struct_chips(ink: Ink, ov) -> None:
    for t in list(ov.texts):
        s = str(t.get_text())
        if not t.get_visible() or t.get_bbox_patch() is None:
            continue
        if t.get_fontsize() >= 12:
            continue
        col = _hex(t.get_color())
        fc = PRESS if col == "#ad1457" else (VIOLET if col == "#6a1b9a" else (HOLD if col in ("#1b5e20", "#0a4d1c") else INK))
        ink.sticker(t, fc=fc, tc=PAPER, pad=0.26, shadow=False, role="chip")


def lift_struct_header_gaps(ink: Ink, ov, frames, main, vol) -> None:
    """結構圖：chip 貼主圖頂改往圖內讓；爆大量說明離量圖頂框。"""
    if not frames:
        return
    ordered = sorted(frames, key=lambda p: -p.get_window_extent(ink.ren).y1)
    mid = ordered[1] if len(ordered) >= 2 else ordered[0]
    mid_bb = mid.get_window_extent(ink.ren)
    gap = ink.pt(16.0)
    # chip 若貼在主圖頂框內側／騎縫：往圖內下移，留出頂縫（不准上撞頭欄）
    for t in list(ov.texts):
        if not t.get_visible() or t.get_bbox_patch() is None:
            continue
        if t.get_fontsize() >= 12:
            continue
        bb = ink.shell_ext(t)
        if bb.y0 > mid_bb.y1 + ink.pt(8):
            continue  # 頭欄區，別動
        if bb.y1 < mid_bb.y1 - ink.pt(60):
            continue
        target_top = mid_bb.y1 - gap
        if bb.y1 > target_top:
            dy = bb.y1 - target_top
            cy = 0.5 * (bb.y0 + bb.y1) - dy
            ink.move_text_px(t, 0.5 * (bb.x0 + bb.x1), cy, ha="center", va="center")
    # 爆大量箭頭加粗（徽章縫距已在 badge clamp；此處補強箭頭）
    if vol is None:
        return
    for ax in (main, vol):
        if ax is None:
            continue
        for t in list(ax.texts):
            s = str(t.get_text() or "")
            if "爆大量" not in s and "下一層量日" not in s:
                continue
            if not isinstance(t, Annotation) or t.arrow_patch is None:
                continue
            t.arrow_patch.set_linewidth(2.3)
            try:
                t.arrow_patch.set_mutation_scale(max(float(t.arrow_patch.get_mutation_scale() or 12), 20.0))
            except Exception:
                pass


def sparse_right_ticks(ax, *, n_bins: int = 5, price: bool = True) -> None:
    """結構圖右軸疏刻度：參考正式量軸精神，價軸不要每 50 一格卡成一團。"""
    import matplotlib.ticker as mticker
    y0, y1 = ax.get_ylim()
    span = float(y1 - y0)
    if span <= 0:
        return
    if price:
        # 約 4～6 個標，步距對齊 50／100
        rough = span / max(n_bins, 3)
        for step in (50, 100, 200, 25, 20, 10, 5, 1):
            if step >= rough * 0.55:
                base = step
                break
        else:
            base = max(1.0, round(rough, 0) or 1.0)
        lo = int(np.floor(y0 / base) * base)
        hi = int(np.ceil(y1 / base) * base)
        ticks = list(np.arange(lo, hi + 0.5 * base, base, dtype=float))
        ticks = [t for t in ticks if y0 - 1e-6 <= t <= y1 + 1e-6]
        # 丟掉貼近上下緣的刻度，避免被中下縫橫線切字
        edge = span * 0.045
        ticks = [t for t in ticks if (y0 + edge) <= t <= (y1 - edge)]
        if len(ticks) > 7:
            ticks = ticks[::2]
        if len(ticks) < 3:
            ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=n_bins))
        else:
            ax.set_yticks(ticks)
    else:
        # 量軸：保留正式 sparse，只再保險 MaxNLocator
        labs = [t for t in ax.get_yticklabels() if t.get_visible() and str(t.get_text()).strip()]
        if len(labs) > 6:
            ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=5))
    # 右軸：更離框；量柱必須從底框長出（ymin＝0，不准負縫）
    ax.tick_params(axis="y", pad=14.0 if price else 12.0, length=3.6, width=1.1, labelsize=12.0)
    y0, y1 = ax.get_ylim()
    span = float(y1 - y0) or 1.0
    if not price:
        top = max(float(y1), float(span) * 0.02, 1.0)
        # 頂端略留空，避免最上量刻度壓價量分界框線；底仍 0
        ax.set_ylim(0.0, top * 1.06)
        ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=4))
        try:
            ax.set_ymargin(0.0)
        except Exception:
            pass
        # 0 貼底藏；貼頂（分界線）的刻度也丟掉
        ticks = [
            float(t)
            for t in ax.get_yticks()
            if float(t) > top * 0.05 and float(t) < top * 0.92
        ]
        if len(ticks) >= 2:
            ax.set_yticks(ticks)
        for lab in ax.get_yticklabels():
            try:
                if abs(float(lab.get_text().replace(",", "") or "nan")) < 1e-9:
                    lab.set_visible(False)
            except Exception:
                pass
    for lab in ax.get_yticklabels():
        lab.set_fontproperties(fp(12.0 if price else 11.0, heavy=True))
        lab.set_color(INK2)
        lab.set_clip_on(False)


def clear_vol_top_ytick(ax) -> None:
    """量軸最上刻度不准壓價量分界框線；以量柱高峰為準重算，丟掉貼頂刻度。

    2026-10-29：若有「爆大量／下一層量日」標，頂端多留空帶並把標釘在上緣下方。
    """
    import matplotlib.ticker as mticker

    if ax is None:
        return
    bar_peak = 0.0
    for p in ax.patches:
        if not isinstance(p, Rectangle):
            continue
        w = abs(float(p.get_width()))
        if w < 0.05 or w > 1.25:
            continue
        try:
            bar_peak = max(bar_peak, float(p.get_y()) + abs(float(p.get_height())))
        except Exception:
            pass
    if bar_peak < 1.0:
        bar_peak = max(float(ax.get_ylim()[1]), 1.0)
    has_vol_event = False
    for t in list(ax.texts):
        s = str(t.get_text() or "")
        if "爆大量" in s or "下一層量日" in s:
            has_vol_event = True
            break
    # 有量日標：柱區約 78%，上緣空帶掛標；否則維持舊 16% 頭
    head = (1.0 / 0.78) if has_vol_event else 1.16
    top = float(bar_peak) * float(head)
    ax.set_ylim(0.0, top)
    ax.yaxis.set_major_locator(mticker.MaxNLocator(nbins=4, prune="both"))
    # 不准在此整圖 draw：viewLim 已更新，get_yticks 不必重渲；外層 ink.redraw 一次收斂
    ticks = [
        float(t)
        for t in ax.get_yticks()
        if float(t) > bar_peak * 0.08 and float(t) < bar_peak * 0.90
    ]
    if len(ticks) >= 2:
        ax.yaxis.set_major_locator(mticker.FixedLocator(ticks))
    else:
        # 保底：三等分，仍避開頂／底
        ticks = [bar_peak * x for x in (0.25, 0.50, 0.75)]
        ax.yaxis.set_major_locator(mticker.FixedLocator(ticks))
    ax.tick_params(axis="y", pad=13.0, length=3.6, width=1.1)
    for lab in ax.get_yticklabels():
        lab.set_visible(True)
        lab.set_fontproperties(fp(11.0, heavy=True))
        lab.set_color(INK2)
        lab.set_clip_on(False)
    if has_vol_event:
        lab_y = float(top) * 0.972
        for t in list(ax.texts):
            s = str(t.get_text() or "")
            if "爆大量" not in s and "下一層量日" not in s:
                continue
            try:
                t.set_va("top")
                t.set_clip_on(False)
                if isinstance(t, Annotation):
                    x_pos = float(t.xyann[0]) if t.xyann is not None else float(t.get_position()[0])
                    t.set_position((x_pos, lab_y))
                else:
                    x_pos = float(t.get_position()[0])
                    t.set_position((x_pos, lab_y))
            except Exception:
                continue


def flush_data_left_xlim(*axes) -> None:
    """第一根 K／量柱貼 axes 左緣：只改 xlim，不准動 axes 幾何。"""
    axs = [a for a in axes if a is not None]
    lefts: List[float] = []
    for ax in axs:
        for p in ax.patches:
            if not isinstance(p, Rectangle):
                continue
            w = abs(float(p.get_width()))
            if 0.05 <= w <= 1.25:
                lefts.append(float(p.get_x()))
    if not lefts:
        return
    x_left = min(lefts)
    for ax in axs:
        lo, hi = ax.get_xlim()
        if float(lo) < x_left - 1e-9:
            ax.set_xlim(x_left, float(hi))


def flush_volume_bars_to_spine(ax) -> None:
    """量柱視覺貼底：AA 關＋微下伸（clip 關），消 1～2px 白縫；不准改 axes 位置。"""
    if ax is None:
        return
    y0, y1 = ax.get_ylim()
    top = max(float(y1), 1.0)
    ax.set_ylim(0.0, top)
    try:
        h_px = float(ax.bbox.height)
    except Exception:
        h_px = 120.0
    pix = (top / max(h_px, 1.0)) * 1.8
    for p in ax.patches:
        if not isinstance(p, Rectangle):
            continue
        w = abs(float(p.get_width()))
        if w < 0.05 or w > 1.25:
            continue
        try:
            p.set_antialiased(False)
        except Exception:
            pass
        try:
            p.set_clip_on(False)
        except Exception:
            pass
        y = float(p.get_y())
        if y >= -1e-9:
            p.set_y(y - pix)
            p.set_height(float(p.get_height()) + pix)


def apply_struct(fig) -> Ink:
    ink = Ink(fig, "struct", lazy=True)
    ov, main, vol = _struct_axes(fig)
    ink.redraw()
    frames = struct_frames(ink, ov)
    close_struct_frame_seam(frames)
    struct_header(ink, ov, frames)
    struct_chips(ink, ov)
    restyle_candles_and_bars(main)
    restyle_bands(main)
    restyle_levels(main)
    restyle_grid_ticks(main, ylab_size=11.25)
    sparse_right_ticks(main, n_bins=5, price=True)
    for ax in [a for a in (main, vol) if a is not None]:
        ax.spines["right"].set_visible(True)
        ax.spines["right"].set_edgecolor(INK)
        ax.spines["right"].set_linewidth(1.15)
    if vol is not None:
        restyle_candles_and_bars(vol, volume=True)
        restyle_grid_ticks(vol, ylab_size=10.75)
        sparse_right_ticks(vol, n_bins=4, price=False)
        flush_volume_bars_to_spine(vol)
        clear_vol_top_ytick(vol)
        for ln in vol.lines:
            if _hex(ln.get_color()) == "#b0bec5":
                ln.set_color("#8A8A8A")
        # 結構量軸：右脊外側再讓一點，0 不壓框
        vol.tick_params(axis="y", pad=13.0)
    flush_data_left_xlim(main, vol)
    badge_all_labels(ink, [main] + ([vol] if vol is not None else []), vol_ax=vol)
    lift_struct_header_gaps(ink, ov, frames, main, vol)
    # 最後才清縫刺／剝陰影，避免中段 restyle 又把刻度加回來
    kill_seam_ticks(main, vol)
    if vol is not None:
        flush_volume_bars_to_spine(vol)
        clear_vol_top_ytick(vol)
    flush_data_left_xlim(main, vol)
    ink._flat_scrub = scrub_flat(fig)
    return ink


# ====================================================================
# 大量區專圖
# ====================================================================

def _vol_axes(fig):
    """量圖＝最底下那框（用 y0 排序；主圖被縫壓縮後不可再靠 height 誤判）。"""
    header = None
    rest = []
    for ax in fig.axes:
        if not ax.axison:
            header = ax
        else:
            rest.append(ax)
    if not rest:
        return header, None, None, None
    by_y = sorted(rest, key=lambda a: a.get_position().y0)
    volume = by_y[0]
    upper = by_y[1:]
    if not upper:
        return header, None, None, volume
    if len(upper) == 1:
        return header, upper[0], None, volume
    sig = min(upper, key=lambda a: a.get_position().height)
    main = max((a for a in upper if a is not sig), key=lambda a: a.get_position().height, default=upper[0])
    return header, main, sig, volume


def _key_cats(legends: List[Legend]) -> List[str]:
    cats = []
    for L in legends:
        labs = [t.get_text() for t in L.get_texts()]
        if any("SMA" in x or "點線" in x for x in labs):
            cats.append("線・觀察")
        elif any(x.startswith("20高") or "接近" in x for x in labs):
            cats.append("導航箭頭")
        else:
            cats.append("訊號・買賣")
    return cats


KEY_TAB_PROP = 10.0


def _grow_legend_markers(legends: List[Legend]) -> None:
    """KEY 符號略加大＋符號↔字呼吸。

    一般列不重建 legend_box（免打爛錨點）。「線・觀察」列止穩◆／橘六角擠壓時，
    只對該列提高 columnspacing／handletextpad 後局部 _init_legend_box，再用右側空白排開；
    錨點仍由後續 vol_key_shift 重掛。
    """
    for L in legends:
        labs = [str(t.get_text()) for t in L.get_texts()]
        is_observe = any(
            ("SMA" in x) or ("點線" in x) or ("止穩" in x) or ("六角" in x) for x in labs
        )
        # 橘六角附註：與主標拉開全形空，不准黏
        if is_observe:
            for t in L.get_texts():
                s = str(t.get_text())
                if "六角" in s and "（" in s and "　（" not in s:
                    t.set_text(s.replace("（", "　（", 1))
        htpad = 1.35 if is_observe else 0.95
        colsp = 1.70 if is_observe else 0.95
        try:
            L.labelspacing = 1.55
        except Exception:
            pass
        try:
            L.borderpad = 0.75
        except Exception:
            pass
        try:
            L.handletextpad = htpad
        except Exception:
            pass
        try:
            L.columnspacing = max(float(getattr(L, "columnspacing", 0.8) or 0.8), colsp)
        except Exception:
            pass
        try:
            L.handlelength = 1.85
        except Exception:
            pass
        try:
            L.set_labelspacing(1.55)
            L.set_borderpad(0.75)
            L.set_handletextpad(htpad)
            L.set_handlelength(1.85)
            L.set_handleheight(1.45)
            L.set_columnspacing(colsp)
        except Exception:
            pass
        for t in L.get_texts():
            try:
                t.set_fontsize(max(float(t.get_fontsize()), 10.2))
                t.set_fontproperties(fp(max(10.2, float(t.get_fontsize())), heavy=False))
            except Exception:
                pass
        handles = getattr(L, "legend_handles", None) or getattr(L, "legendHandles", None) or []
        for h in handles:
            try:
                mk = ""
                try:
                    mk = str(h.get_marker() or "")
                except Exception:
                    mk = ""
                diamond_hex = mk in ("D", "d", "h", "H", "p")
                if hasattr(h, "set_markersize") and h.get_markersize() is not None:
                    ms = float(h.get_markersize() or 8)
                    # ◆／六角略收，避免壓到左右字；其餘維持加大
                    if diamond_hex:
                        h.set_markersize(min(max(ms * 1.12, 12.0), 16.5))
                    else:
                        h.set_markersize(min(max(ms * 1.28, 11.0), 20.0))
                if hasattr(h, "set_linewidth"):
                    try:
                        lw = float(h.get_linewidth() or 1.2)
                        if lw > 0:
                            h.set_linewidth(max(lw * 1.1, 1.7))
                    except Exception:
                        pass
                if hasattr(h, "set_sizes"):
                    sizes = list(h.get_sizes() or [36])
                    cap = 48.0 if diamond_hex else 58.0
                    h.set_sizes([min(max(float(s) * 1.12, 40.0), cap) for s in sizes])
                if isinstance(h, Rectangle):
                    try:
                        h.set_width(float(h.get_width()) * 1.15)
                        h.set_height(float(h.get_height()) * 1.15)
                    except Exception:
                        pass
            except Exception:
                pass
def breathe_observe_legend(ink: Ink, legends: List[Legend]) -> None:
    """線・觀察：拉開止穩◆／橘六角與字距（改 HPacker sep），不准 _init_legend_box。"""
    if not legends:
        return
    for L in legends:
        labs = [str(t.get_text()) for t in L.get_texts()]
        if not any(("止穩" in x) or ("六角" in x) for x in labs):
            continue
        box = getattr(L, "_legend_box", None)
        if box is None:
            continue
        # 結構：VPacker → HPacker(各欄) → 每欄 VPacker(符號+字)
        for ch in list(getattr(box, "get_children", lambda: [])()):
            kids = list(getattr(ch, "get_children", lambda: [])())
            # 欄間 HPacker：原 sep≈5.8 → 拉到 ~16，右側空白可吃
            if len(kids) >= 5 and hasattr(ch, "sep"):
                try:
                    ch.sep = max(float(getattr(ch, "sep", 0) or 0), 20.0)
                except Exception:
                    pass
            for sub in kids:
                # 符號↔字
                if hasattr(sub, "sep"):
                    try:
                        sub.sep = max(float(getattr(sub, "sep", 0) or 0), 5.5)
                    except Exception:
                        pass
        try:
            L.stale = True
        except Exception:
            pass
        break


def vol_key_shift(ink: Ink, legends: List[Legend], main) -> float:
    """三排圖例右移讓出列首分類籤；回傳 KEY 面板左緣（＝主圖左緣，整張左齊一條線）。"""
    panel_left = float(main.get_window_extent(ink.ren).x0)
    if not legends:
        return panel_left
    cats = _key_cats(legends)
    tab_prop = fp(KEY_TAB_PROP, heavy=True)
    tab_w = max(ink.measure(c, tab_prop)[0] for c in cats) + ink.pt(8)
    exts = [L.get_window_extent(ink.ren) for L in legends]
    dx = panel_left + tab_w + ink.pt(2.5) - min(e.x0 for e in exts)
    # 三排等距：大符號需要更高列；觀察列◆／六角再加一點高，免裁字
    order = sorted(range(len(legends)), key=lambda i: -exts[i].y1)
    row_boost = ink.pt(11.0)
    gap = ink.pt(11.5)
    span_top = max(e.y1 for e in exts)
    span_bot = min(e.y0 for e in exts)
    block = sum(e.height + row_boost for e in exts) + gap * (len(exts) - 1)
    first_top = span_top - max(0.0, (span_top - span_bot) - block) / 2.0
    anchors = [L.get_bbox_to_anchor() for L in legends]
    top = None
    for i in order:
        L = legends[i]
        bb = anchors[i]
        e = exts[i]
        offset = bb.y0 - e.y1
        y_top = first_top if top is None else top
        L.set_bbox_to_anchor(((bb.x0 + dx) / ink.W, (y_top + offset) / ink.H), transform=ink.fig.transFigure)
        top = y_top - e.height - row_boost - gap
    return panel_left


def vol_masthead(ink: Ink, header, legends: List[Legend], panel_left: float) -> None:
    """名牌＝結構圖同級（字級／高度／斜切黑標＋板上黃籤）；資料兩行右移騰位。"""
    fig = ink.fig
    title = next((t for t in header.texts if "專圖" in str(t.get_text())), None)
    sub = next((t for t in header.texts if str(t.get_text()).startswith("爆大量") or "最近" in str(t.get_text())), None)
    # 盤中＝「現xxxx」、收盤＝「收xxxx」；只認收會漏掉現價字，墨線重排後原字仍留在置中位壓住「低」
    close_t = next(
        (t for t in header.texts if re.fullmatch(r"[收現][\d,.]+", str(t.get_text()).strip())),
        None,
    )
    stamp = next((t for t in fig.texts if re.search(r"\d{4}/\d{2}/\d{2}", str(t.get_text()))), None)
    W, H = ink.W, ink.H
    # 右緣對齊結構外框（figure fraction 0.982）
    right_px = W * 0.982
    # 結構名牌參考：字級≈30、板高≈139px（≈45.5pt＠220dpi）
    NAME_FS = 30.0
    CHIP_FS = 14.5
    MAST_H = ink.pt(45.5)
    data_left = panel_left + ink.pt(280)
    mast_cy = H - ink.pt(22)
    mast_y0 = H - MAST_H
    if title is not None:
        s = str(title.get_text())
        m = re.match(r"^(\S+\s\S+)[\u3000 ]+(.+)$", s)
        # 貼頂、高度對齊結構名牌
        tab_y1 = H - ink.pt(1.5)
        tab_y0 = tab_y1 - MAST_H
        cy = 0.5 * (tab_y0 + tab_y1)
        mast_cy = cy
        mast_y0 = tab_y0
        x = panel_left
        parts: List[str] = []
        if m:
            name, rest = m.group(1), m.group(2)
            p1 = fp(NAME_FS, heavy=True)
            w1, h1, d1 = ink.measure(name, p1)
            m2 = re.match(r"^(\S+?)(（.+）)$", rest)
            chip = rest
            if m2:
                chip = m2.group(1)
                # 刪「(非買訊·…)」
            pa = fp(CHIP_FS, heavy=True)
            wa, ha_, da = ink.measure(chip, pa)
            chip_padx, chip_pady = ink.pt(5.5), ink.pt(3.2)
            # 黑板上：股名＋黃籤（結構同款），再斜切
            name_x = panel_left + ink.pt(6)
            chip_x0 = name_x + w1 + ink.pt(10)
            chip_x1 = chip_x0 + wa + 2 * chip_padx
            tab_x0 = panel_left - ink.pt(2)
            tab_x1 = chip_x1 + ink.pt(10)
            ink.rect(fig, tab_x0, tab_y0, tab_x1, tab_y1, fc=INK, z=25, gid="ink:masthead")
            ink.poly(
                fig,
                [(tab_x1, tab_y1), (tab_x1 + ink.pt(12), tab_y1), (tab_x1, tab_y0)],
                fc=INK, z=25, gid="ink:masthead",
            )
            ink.line(fig, [tab_x0, tab_x1 + ink.pt(6)], [tab_y0, tab_y0], color=YELLOW, lw=2.6, z=25.3)
            base = cy - h1 / 2 + d1
            ink.text(fig, name_x, base, name, prop=p1, color=PAPER, ha="left", z=26)
            parts.append(name)
            # 黃籤在黑板上（結構產業籤同級）
            ink.rect(
                fig,
                chip_x0, cy - ha_ / 2 - chip_pady,
                chip_x1, cy + ha_ / 2 + chip_pady,
                fc=YELLOW, ec=INK, lw=1.1, z=25.5,
            )
            ink.text(fig, chip_x0 + chip_padx, cy - ha_ / 2 + da, chip, prop=pa, color=INK, ha="left", z=26)
            parts.append(chip)
            # 資料兩行從斜切右側白底起，再多留縫
            data_left = tab_x1 + ink.pt(12) + ink.pt(18)
            title.set_visible(False)
            title.set_gid("ink:replaced")
            ink.record(s, parts, "title", Bbox.from_extents(tab_x0, tab_y0, tab_x1 + ink.pt(12), tab_y1))
        if stamp is not None:
            stamp.set_fontproperties(fp(10.5, heavy=False))
            stamp.set_color(INK2)
            stamp.set_bbox(dict(boxstyle="square,pad=0.28", facecolor=PAPER, edgecolor=RULE, linewidth=0.85))
            stamp.set_zorder(27)
            stamp.set_position((right_px / W - ink.pt(2) / W, cy / H))
            stamp.set_va("center")
            stamp.set_ha("right")
            ink.record(str(stamp.get_text()), [str(stamp.get_text())], "stamp", ink.shell_ext(stamp))
    # 資料列：名牌右側白底兩行加大、欄位對齊；用滿右側空間、不互壓名牌／時間戳
    if sub is not None:
        s = str(sub.get_text())
        # 固定大字級（原 sub≈13 太渺小）；行距加寬、用滿右側白底
        VAL_FS = 20.0
        LAB_FS = 15.0
        TAB_FS = 15.0
        CLOSE_FS = 20.0
        lab_prop = fp(LAB_FS, heavy=False)
        val_prop = fp(VAL_FS, heavy=True)
        tab_prop = fp(TAB_FS, heavy=True)
        fields = [f for f in re.split(r"[\u3000]+", s.strip()) if f.strip()]
        if len(fields) >= 3:
            row1_fields, row2_fields = fields[:2], fields[2:]
        elif len(fields) == 2:
            row1_fields, row2_fields = fields[:1], fields[1:]
        else:
            row1_fields, row2_fields = fields, []

        def _parse_row(fields_in: List[str]) -> Optional[List[Tuple[str, str]]]:
            out: List[Tuple[str, str]] = []
            for field in fields_in:
                prs = _kv_pairs(field)
                if not prs:
                    prs = _kv_pairs(field.replace("開", " 開").replace("高", " 高").replace("低", " 低"))
                if not prs:
                    return None
                out.extend(prs)
            return out

        row1 = _parse_row(row1_fields) or []
        row2 = _parse_row(row2_fields) or []
        ok = bool(row1 or row2)
        _w, href, dref = ink.measure("撐9", val_prop)
        x_data0 = data_left
        # 時間戳左緣預留，避免與收價籤互壓
        stamp_left = right_px - ink.pt(168)
        if stamp is not None:
            try:
                se = ink.shell_ext(stamp)
                stamp_left = min(stamp_left, float(se.x0) - ink.pt(10))
            except Exception:
                pass
        # 兩行垂直：加大行距，對齊名牌中帶
        row_gap = ink.pt(16)
        block_h = href * 2 + row_gap
        cy_mid = mast_cy
        cy1 = cy_mid + block_h / 4
        cy2 = cy_mid - block_h / 4
        if cy1 + href / 2 > H - ink.pt(3):
            cy1 = H - ink.pt(6) - href / 2
            cy2 = cy1 - href - row_gap

        # 欄位對齊：列首籤寬、日期欄對齊，其後單位欄等距
        def _lead_w(prs: List[Tuple[str, str]]) -> float:
            if not prs:
                return 0.0
            lab0 = prs[0][0]
            if lab0 == "爆大量":
                return ink.measure(lab0, tab_prop)[0] + ink.pt(10)
            return ink.measure(lab0, lab_prop)[0] + ink.pt(6)

        lead_w = max(_lead_w(row1), _lead_w(row2), ink.pt(52))
        date_w = ink.pt(78)  # 08/25／10/27 欄寬對齊

        def _paint_aligned(prs: List[Tuple[str, str]], cy: float) -> Tuple[float, List[str]]:
            x = x_data0
            base = cy - href / 2 + dref
            parts: List[str] = []
            if not prs:
                return x, parts
            # 列首
            lab0, val0 = prs[0]
            if lab0 == "爆大量":
                wtab, htab, dtab = ink.measure(lab0, tab_prop)
                ink.rect(
                    header,
                    x, cy - htab / 2 - ink.pt(2.4),
                    x + wtab + ink.pt(8), cy + htab / 2 + ink.pt(2.4),
                    fc=SPIKE, ec=INK, lw=0.95, z=21,
                )
                ink.text(header, x + ink.pt(4), cy - htab / 2 + dtab, lab0, prop=tab_prop, color=INK, ha="left", z=22)
            else:
                ink.text(header, x, base, lab0, prop=lab_prop, color=MUTE, ha="left", z=22)
            parts += [lab0, val0]
            # 日期對齊欄
            x_date = x_data0 + lead_w
            ink.text(header, x_date, base, val0, prop=val_prop, color=INK, ha="left", z=22)
            x = x_date + date_w
            # 其餘 kv
            rest = prs[1:]
            for j, (lab, val) in enumerate(rest):
                if j == 0:
                    ink.line(
                        header,
                        [x - ink.pt(8), x - ink.pt(8)],
                        [cy - href * 0.48, cy + href * 0.48],
                        color="#BDBDBD", lw=0.9, z=21,
                    )
                    x += ink.pt(4)
                else:
                    x += ink.pt(14)
                wl, _, _ = ink.measure(lab, lab_prop)
                ink.text(header, x, base, lab, prop=lab_prop, color=MUTE, ha="left", z=22)
                x += wl + ink.pt(3.0)
                col = INK
                if lab.endswith("壓"):
                    col = PRESS
                elif lab.endswith("撐"):
                    col = HOLD
                wv, _, _ = ink.measure(val, val_prop)
                ink.text(header, x, base, val, prop=val_prop, color=col, ha="left", z=22)
                # 字寬量測略偏窄時末位會貼紅底；欄尾多留一點呼吸
                x += wv + ink.pt(2.0)
                parts += [lab, val]
            return x, parts

        x1_end, p1 = _paint_aligned(row1, cy1) if row1 else (x_data0, [])
        x2_end, p2 = _paint_aligned(row2, cy2) if row2 else (x_data0, [])
        parts_all = list(p1) + list(p2)
        cy_close = cy2 if row2 else cy1
        # 「低」右緣＝row2 畫完；收／現字必須在此右側留缝，不准再為時間戳往左拉
        x_low_end = x2_end if row2 else x1_end
        # 萬元股「低 4,830」「現 5,008」字寬大；12pt 縫目測仍像壓字，改 20pt
        MIN_LOW_CLOSE_GAP = max(20.0, ink.pt(20))
        if ok:
            sub.set_visible(False)
            sub.set_gid("ink:replaced")
            y_bot = (cy2 if row2 else cy1) - href / 2 - ink.pt(3.5)
            y_top = cy1 + href / 2 + ink.pt(3.5)
            ink._data_strip_bot = y_bot
            ink._data_strip_top = y_top
            if close_t is not None:
                cs = str(close_t.get_text())
                pc = fp(CLOSE_FS, heavy=True)
                col = _hex(close_t.get_color())
                # 普通日＝紅漲／黑平／綠跌「字」；只有漲停／跌停才走色底白字
                move_tc = UP if col == "#e53935" else (DN if col == "#00897b" else INK)
                try:
                    raw_move = getattr(ink.fig, "_wayne_close_move_ink", None)
                    if raw_move:
                        rc = _hex(raw_move)
                        if rc == "#e53935":
                            move_tc = UP
                        elif rc in ("#00897b", "#2e7d32", "#1b5e20", "#0a4d1c"):
                            move_tc = DN
                        elif rc in ("#0b0b0b", "#000000", "#212121"):
                            move_tc = INK
                except Exception:
                    pass
                label = cs
                limit_side = _detect_limit_from_header(header)
                # 收／現：字級／位置鎖死原本（CLOSE_FS＋低右縫）；不准為塞昨比縮小或左移
                # 昨比：收右剩餘上下並排（上點數、下％），字加大仍 < 收；普通日不上色底
                move_plain = ""
                move_pts = ""
                move_pct_s = ""
                try:
                    move_plain = str(
                        getattr(ink.fig, "_wayne_close_move_plain", "") or ""
                    ).strip()
                    move_pts = str(
                        getattr(ink.fig, "_wayne_close_move_pts", "") or ""
                    ).strip()
                    move_pct_s = str(
                        getattr(ink.fig, "_wayne_close_move_pct", "") or ""
                    ).strip()
                except Exception:
                    move_plain = move_pts = move_pct_s = ""
                _move_re = re.compile(
                    r"^[▲▼]\s*[\d,.]+([\s]+)?[\(（][+\-]?\d+\.\d+%[\)）]$|^0\.00([\s]+)?[\(（]0\.00%[\)）]$"
                )
                for _mt in list(header.texts):
                    _ms = str(_mt.get_text() or "").strip()
                    if not _move_re.fullmatch(_ms) and not re.fullmatch(
                        r"^[▲▼]?[\d,.]+$", _ms
                    ) and not re.fullmatch(r"^[\(（][+\-]?\d+\.\d+%[\)）]$", _ms):
                        continue
                    if not move_plain:
                        move_plain = _ms
                    _mt.set_visible(False)
                    _mt.set_gid("ink:replaced")
                if not move_pts or not move_pct_s:
                    # 後備：從單行 plain 拆上下
                    _mp = (
                        (move_plain or "")
                        .replace("▲ ", "▲")
                        .replace("▼ ", "▼")
                        .replace("（", "(")
                        .replace("）", ")")
                        .strip()
                    )
                    _mm = re.match(
                        r"^([▲▼]?[\d,.]+)\s*(\([+\-]?\d+\.\d+%\))$", _mp
                    )
                    if _mm:
                        move_pts = move_pts or _mm.group(1)
                        move_pct_s = move_pct_s or _mm.group(2)
                pc = fp(CLOSE_FS, heavy=True)
                badge_pad_x = ink.pt(10)
                if limit_side == "up":
                    fc = LIMIT_UP
                    if "漲停" not in label:
                        label = cs + " 漲停"
                    wc, hc, dc = ink.measure(label, pc)
                    badge_w = wc + badge_pad_x
                    tc = PAPER
                elif limit_side == "down":
                    fc = LIMIT_DN
                    if "跌停" not in label:
                        label = cs + " 跌停"
                    wc, hc, dc = ink.measure(label, pc)
                    badge_w = wc + badge_pad_x
                    tc = PAPER
                else:
                    fc = None
                    wc, hc, dc = ink.measure(label, pc)
                    badge_w = wc + ink.pt(4)
                    tc = move_tc
                x_badge = x_low_end + MIN_LOW_CLOSE_GAP
                # 時間戳微讓：先按「收」右緣讓位（原本邏輯）；昨比再吃收右剩餘
                stamp_w = 0.0
                stamp_gap = ink.pt(10)
                if stamp is not None:
                    try:
                        sw, sh, sd = ink.measure(str(stamp.get_text()), fp(10.5, heavy=False))
                        stamp_w = sw + ink.pt(18)
                        stamp_right = right_px - ink.pt(2)
                        stamp_left_need = x_badge + badge_w + stamp_gap
                        if stamp_left_need + stamp_w > stamp_right:
                            stamp_right = right_px - ink.pt(1)
                        stamp.set_fontproperties(fp(10.5, heavy=False))
                        stamp.set_color(INK2)
                        stamp.set_bbox(
                            dict(boxstyle="square,pad=0.28", facecolor=PAPER, edgecolor=RULE, linewidth=0.85)
                        )
                        stamp.set_zorder(27)
                        stamp.set_position((stamp_right / W, mast_cy / H))
                        stamp.set_va("center")
                        stamp.set_ha("right")
                        ink.record(str(stamp.get_text()), [str(stamp.get_text())], "stamp", ink.shell_ext(stamp))
                    except Exception:
                        stamp_w = ink.pt(140)
                if fc is not None:
                    ink.rect(
                        header,
                        x_badge, cy_close - hc / 2 - ink.pt(3.2),
                        x_badge + badge_w, cy_close + hc / 2 + ink.pt(3.2),
                        fc=fc, z=21,
                    )
                    ink.text(
                        header,
                        x_badge + ink.pt(5),
                        cy_close - hc / 2 + dc,
                        label,
                        prop=pc,
                        color=tc,
                        ha="left",
                        z=22,
                    )
                    sync_col = fc
                else:
                    ink.text(
                        header,
                        x_badge,
                        cy_close - hc / 2 + dc,
                        label,
                        prop=pc,
                        color=tc,
                        ha="left",
                        z=22,
                    )
                    sync_col = tc
                move_right = x_badge + badge_w
                if move_pts and move_pct_s:
                    # 上下並排加大字（仍 < CLOSE_FS）；寬度吃收右剩餘，只縮昨比不縮收
                    close_right = x_badge + float(wc)
                    room = max(0.0, (right_px - ink.pt(4)) - close_right - ink.pt(3))
                    # 手機縮圖可讀：起點約 15.5（收＝20）
                    move_fs = min(15.5, float(CLOSE_FS) - 4.0)
                    move_prop = fp(move_fs, heavy=True)
                    wp = hp = dp = 0.0
                    wc2 = hc2 = dc2 = 0.0
                    for _ in range(12):
                        move_prop = fp(move_fs, heavy=True)
                        wp, hp, dp = ink.measure(move_pts, move_prop)
                        wc2, hc2, dc2 = ink.measure(move_pct_s, move_prop)
                        if max(wp, wc2) <= room or move_fs <= 11.0:
                            break
                        move_fs -= 0.5
                    if room > 0 and max(wp, wc2) <= room:
                        mx = close_right + ink.pt(4)
                        if limit_side == "up":
                            move_col = UP
                        elif limit_side == "down":
                            move_col = DN
                        else:
                            move_col = tc
                        # 兩行總高對齊收字垂直中心；行距略緊仍可讀
                        gap = ink.pt(1.2)
                        block_h = hp + hc2 + gap
                        y_top = cy_close + block_h / 2 - hp
                        y_bot = y_top - gap - hc2
                        ink.text(
                            header,
                            mx,
                            y_top + dp,
                            move_pts,
                            prop=move_prop,
                            color=move_col,
                            ha="left",
                            z=22,
                        )
                        ink.text(
                            header,
                            mx,
                            y_bot + dc2,
                            move_pct_s,
                            prop=move_prop,
                            color=move_col,
                            ha="left",
                            z=22,
                        )
                        move_right = mx + max(wp, wc2) + ink.pt(2)
                        ink.record(
                            f"{move_pts}\n{move_pct_s}",
                            [move_pts, move_pct_s],
                            "close_move",
                            Bbox.from_extents(
                                mx,
                                y_bot,
                                mx + max(wp, wc2),
                                y_top + hp,
                            ),
                        )
                close_t.set_visible(False)
                close_t.set_gid("ink:replaced")
                ink._low_end_x = float(x_low_end)
                ink._close_badge_x0 = float(x_badge)
                ink._low_close_gap = float(x_badge - x_low_end)
                ink.record(
                    cs, [label], "close",
                    Bbox.from_extents(x_badge, cy_close - hc / 2, x_badge + badge_w, cy_close + hc / 2),
                )
                ink.record(s, parts_all, "data_strip", Bbox.from_extents(x_data0, y_bot, x_low_end, y_top))
                sync_header_mini_candle(header, sync_col)
            else:
                ink.record(s, parts_all, "data_strip", Bbox.from_extents(x_data0, y_bot, x_low_end, y_top))
        else:
            sub.set_color(INK)


def vol_key_panel(ink: Ink, header, legends: List[Legend], panel_left: float) -> None:
    """三排圖例收成一個 KEY 面板：方框、列間細線、列首反白分類籤。符號原色。"""
    if not legends:
        return
    cats = _key_cats(legends)
    exts = []
    for L in legends:
        fr = L.get_frame()
        fr.set_boxstyle("square,pad=0")
        fr.set_facecolor(PAPER)
        fr.set_edgecolor("none")
        fr.set_linewidth(0)
        fr.set_alpha(1.0)
        for t in L.get_texts():
            t.set_fontproperties(fp(t.get_fontsize(), heavy=False))
            t.set_color(INK)
        exts.append(L.get_window_extent(ink.ren))
    tab_prop = fp(KEY_TAB_PROP, heavy=True)
    tab_w = max(ink.measure(c, tab_prop)[0] for c in cats) + ink.pt(8)
    x0 = panel_left
    # KEY 右緣與主圖／結構外框右齊（0.982）
    x1 = max(max(e.x1 for e in exts) + ink.pt(2), ink.W * 0.982)
    # 大符號／觀察列：外框多留上下，免第三排裁字
    y0 = min(e.y0 for e in exts) - ink.pt(7.0)
    y1 = max(e.y1 for e in exts) + ink.pt(5.5)
    if USE_SHADOW:
        off = ink.pt(2.6)
        ink.rect(header, x0 + off, y0 - off, x1 + off, y1 - off, fc=INK, z=-1, gid="ink:shadow")
    ink.rect(header, x0, y0, x1, y1, fc=PAPER, ec=INK, lw=1.05, z=-0.5, gid="ink:key")
    for L in legends:
        L.set_zorder(5)
    order = sorted(range(len(legends)), key=lambda i: -exts[i].y1)
    for k, i in enumerate(order):
        e = exts[i]
        cy = 0.5 * (e.y0 + e.y1)
        w, h, d = ink.measure(cats[i], tab_prop)
        row_y0 = e.y0 - ink.pt(1.6)
        row_y1 = e.y1 + ink.pt(1.6)
        if k == 0:
            row_y1 = y1
        if k == len(order) - 1:
            row_y0 = y0
        ink.rect(header, x0, row_y0, x0 + tab_w, row_y1, fc=INK, z=1, gid="ink:keytab")
        ink.text(header, x0 + tab_w / 2, cy - h / 2 + d, cats[i], prop=tab_prop, color=PAPER, ha="center", z=2, gid="ink:keytab")
        if k < len(order) - 1:
            nxt = exts[order[k + 1]]
            ymid = 0.5 * (e.y0 + nxt.y1)
            ink.line(header, [x0 + tab_w, x1], [ymid, ymid], color="#CFCFCF", lw=0.8, z=1)


def open_vol_vertical_gaps(ink: Ink, legends: List[Legend], main) -> None:
    """資料列／KEY／主圖縫：爆大量那排與下框、KEY 與主圖都要有清楚間距。"""
    if not legends or main is None:
        return
    # 沿用呼叫端剛同步的 renderer；位移用像素幾何推算，整段最多 redraw 一次
    exts = [L.get_window_extent(ink.ren) for L in legends]
    key_pad = ink.pt(7.0)
    key_y0 = min(e.y0 for e in exts) - key_pad
    key_y1 = max(e.y1 for e in exts) + key_pad
    main_bb = main.get_window_extent(ink.ren)
    main_top = float(main_bb.y1)
    need_main = ink.pt(18.0)
    moved = False
    # 資料列底 ↔ KEY 頂：先把 KEY 整塊下移，再處理主圖縫
    data_bot = getattr(ink, "_data_strip_bot", None)
    if data_bot is not None:
        need_data = ink.pt(14.0)
        gap_data = float(data_bot) - key_y1
        if gap_data < need_data:
            shift = need_data - gap_data
            # 用窗體像素重錨（upper-left）；不准把已是 figure 分數的 bbox 再 /W /H
            for L, e in zip(legends, exts):
                try:
                    L._loc = 2
                except Exception:
                    pass
                L.set_bbox_to_anchor(
                    (float(e.x0) / ink.W, (float(e.y1) - shift) / ink.H),
                    transform=ink.fig.transFigure,
                )
            # 幾何平移推估新盒，免中段整圖 draw
            exts = [
                Bbox.from_extents(
                    float(e.x0),
                    float(e.y0) - shift,
                    float(e.x1),
                    float(e.y1) - shift,
                )
                for e in exts
            ]
            key_y0 = min(e.y0 for e in exts) - key_pad
            key_y1 = max(e.y1 for e in exts) + key_pad
            moved = True
    # KEY 底 ↔ 主圖頂
    gap_main = key_y0 - main_top
    if gap_main < need_main:
        delta_px = need_main - gap_main
        p = main.get_position()
        delta = delta_px / ink.H
        new_h = max(0.12, p.height - delta)
        main.set_position([p.x0, p.y0, p.width, new_h])
        moved = True
    # 位移只改幾何；外層 apply_vol 在 KEY 面板前統一 redraw 一次


# 大量區三框：軸右緣內縮＝刻度溝；外框右緣對齊結構 FancyBbox（0.982）
VOL_AXES_X0 = 0.016
VOL_AXES_X1 = 0.905  # 對齊結構主圖右緣；刻度在軸脊～外框之間
VOL_OUTER_X1 = 0.982  # 外黑框右緣（使用者 2026-10-28 紅線示意→實作黑）


def align_vol_panel_margins(main, sig, volume) -> None:
    """大量圖上中下三框左緣對齊結構外框；軸右緣內縮留刻度溝。

    軸右緣不准拉到 0.982：刻度會畫在軸外，若無外框＝缺邊；若外框也在
    0.982 則數字出畫布只剩橫杠（#716／6213／6274）。軸＝0.905、外框＝0.982。
    """
    target_x0, target_x1 = float(VOL_AXES_X0), float(VOL_AXES_X1)
    target_w = target_x1 - target_x0
    for ax in (main, sig, volume):
        if ax is None:
            continue
        p = ax.get_position()
        ax.set_position([target_x0, p.y0, target_w, p.height])


def vol_frames(ink: Ink, main, sig, volume) -> None:
    for ax in [a for a in (main, sig, volume) if a is not None]:
        for sp in ax.spines.values():
            sp.set_visible(True)
            sp.set_edgecolor(INK)
            sp.set_linewidth(1.15)  # 外框改細，右脊封閉可見
        bb = ax.get_window_extent(ink.ren)
        if ax is sig:
            # 訊號列方框回來；刻度刺仍關，避免縫裡短豎
            ax.tick_params(axis="both", length=0, bottom=False, top=False, left=False, right=False)
            ax.set_facecolor("#F7F7F7")
        else:
            panel_shadow(ink, bb, off_pt=3.0)  # USE_SHADOW=False → no-op
    # 主圖底／量圖頂刻度刺：交給 kill_seam_ticks 統一清


def vol_close_right_outer_frame(ink: Ink, main, sig, volume) -> None:
    """三框外黑框：右緣封閉含刻度溝；刻度上下左右留距，不准卡／壓黑框。

    使用者註記（2026-10-28）：紅線僅示意範圍→實作黑色；缺右邊＝沒做完。
    """
    axes = [a for a in (main, sig, volume) if a is not None]
    if not axes:
        return
    if ink.ren is None:
        try:
            ink.redraw()
        except Exception:
            return
    bbs = [a.get_window_extent(ink.ren) for a in axes]
    y0 = min(float(bb.y0) for bb in bbs) / float(ink.H)
    y1 = max(float(bb.y1) for bb in bbs) / float(ink.H)
    x0 = float(VOL_AXES_X0)
    x1 = float(VOL_OUTER_X1)
    # 清舊外框（重套／二次呼叫只留一框）
    for p in list(ink.fig.patches):
        gid = ""
        try:
            gid = str(p.get_gid() or "")
        except Exception:
            gid = ""
        if gid == "ink:vol-outer-frame":
            try:
                p.remove()
            except Exception:
                pass
            try:
                if p in ink.fig.patches:
                    ink.fig.patches.remove(p)
            except Exception:
                pass
    frame = FancyBboxPatch(
        (x0, y0),
        x1 - x0,
        y1 - y0,
        boxstyle="square,pad=0",
        transform=ink.fig.transFigure,
        facecolor="none",
        edgecolor=INK,
        linewidth=1.25,
        zorder=18,
        clip_on=False,
        gid="ink:vol-outer-frame",
    )
    ink.fig.add_artist(frame)
    # 刻度不准壓外框：右緣留 ≥4pt；超出就略增 y pad 把字往左收
    outer_x1_px = float(ink.W) * x1
    pad_px = float(ink.pt(4.0))
    pad_hit = False
    for ax in axes:
        if ax is None:
            continue
        hit = False
        for t in list(ax.get_yticklabels()):
            s = str(t.get_text() or "").strip()
            if not s or not t.get_visible():
                continue
            try:
                bb = t.get_window_extent(renderer=ink.ren)
            except Exception:
                continue
            if float(bb.x1) > outer_x1_px - pad_px:
                hit = True
                break
        if hit:
            try:
                cur = float(ax.yaxis.get_tick_params().get("pad") or 12.0)
            except Exception:
                cur = 12.0
            ax.tick_params(axis="y", pad=max(6.0, cur - 4.0))
            pad_hit = True
    # 只在真的改 pad／加外框後再畫一次；外框本身靠後續 savefig 即可，但 pad 改了要刷新
    if pad_hit:
        try:
            ink.redraw()
        except Exception:
            pass


def lift_ex_div_off_press(ink: Ink, main) -> None:
    """除息／除權紫標不准壓「大量區壓／撐」；重疊就上移（仍鎖該根豎線 x）。"""
    if main is None:
        return
    if ink.ren is None:
        try:
            ink.redraw()
        except Exception:
            return
    blockers = [bb for role, bb in ink.shells if role in ("press", "hold")]
    if not blockers:
        for t in list(main.texts):
            s = str(t.get_text() or "")
            if label_role(s) in ("press", "hold"):
                try:
                    blockers.append(ink.shell_ext(t))
                except Exception:
                    pass
    if not blockers:
        return
    main_bb = main.get_window_extent(ink.ren)
    # clip_on=False：准許略超出主圖上緣，寧可冒出框也不准壓「大量區壓」
    top_cap = float(main_bb.y1) + ink.pt(22)
    moved: List[Tuple[Any, str]] = []
    for t in list(main.texts):
        s = str(t.get_text() or "")
        if not t.get_visible() or not (s.startswith("除息") or s.startswith("除權")):
            continue
        try:
            se = ink.shell_ext(t)
        except Exception:
            continue
        min_gap = ink.pt(12)
        hit = []
        for bb in blockers:
            xo = min(float(se.x1), float(bb.x1)) - max(float(se.x0), float(bb.x0))
            if xo <= 2.0:
                continue
            yo = min(float(se.y1), float(bb.y1)) - max(float(se.y0), float(bb.y0))
            gap_above = float(se.y0) - float(bb.y1)
            if yo > 2.0 or gap_above < min_gap:
                hit.append(bb)
        if not hit:
            continue
        need_up = max(float(bb.y1) + min_gap - float(se.y0) for bb in hit)
        h = float(se.y1) - float(se.y0)
        dy = min(need_up, max(0.0, top_cap - float(se.y1)))
        if dy <= 0.5:
            dy = min(float(bb.y0) for bb in hit) - min_gap - float(se.y1)
            if dy >= -0.5:
                continue
        cx = 0.5 * (float(se.x0) + float(se.x1))
        # 以中心點平移，保留原 ha／va，bbox 跟著走
        cy = 0.5 * (float(se.y0) + float(se.y1)) + dy
        ink.move_text_px(t, cx, cy, ha=str(t.get_ha() or "center"), va="center")
        moved.append((t, s))
    # 多標一次 redraw，不准每標整圖 Agg
    if moved:
        try:
            ink.redraw()
            for t, s in moved:
                ink.record(s, [s], "ex_div", ink.shell_ext(t))
        except Exception:
            pass


def vol_labels(ink: Ink, header, main, sig, volume) -> None:
    for t in list(main.texts):
        s = str(t.get_text())
        if not t.get_visible():
            continue
        if s.startswith("除息") or s.startswith("除權"):
            ink.sticker(t, fc=VIOLET, tc=PAPER, pad=0.24, shadow=False, role="ex_div")
    # 日況標（10月27日 撐為…）：字級／框略加大，仍靠主圖右內緣、不壓死最近 K
    for t in list(main.texts):
        s = str(t.get_text())
        if "\n" not in s or not t.get_visible() or t.get_bbox_patch() is None:
            continue
        if _hex(t.get_color()) not in ("#e65100", "#ef6c00", "#bf360c"):
            continue
        se = ink.shell_ext(t)
        l1, l2 = s.split("\n", 1)
        size = float(t.get_fontsize())
        # 比上一版明顯大一點（約 +2.4～+2.8pt）
        p1 = fp(size + 2.8, heavy=True)
        p2 = fp(size + 2.2, heavy=True)
        w1, h1, d1 = ink.measure(l1, p1)
        w2, h2, d2 = ink.measure(l2, p2)
        padx = ink.pt(6.0)
        pady = ink.pt(3.6)
        bw = max(w1, w2) + 2 * padx
        hh = h1 + 2 * pady
        bh = h2 + 2 * pady
        # 右齊主圖內緣，左移不得蓋最近 K（留約 1.2 根寬）
        main_bb = main.get_window_extent(ink.ren)
        x1 = float(main_bb.x1) - ink.pt(8)
        x0 = x1 - bw
        # 若原位偏左，仍靠右
        if se.x1 < x1 - ink.pt(12):
            pass
        cy = 0.5 * (se.y0 + se.y1)
        ytop = cy + (hh + bh) / 2
        ybot = ytop - hh - bh
        # 若頂穿主圖上緣，整塊下移
        if ytop > float(main_bb.y1) - ink.pt(4):
            dy = ytop - (float(main_bb.y1) - ink.pt(4))
            ytop -= dy
            ybot -= dy
        z = 30
        if USE_SHADOW:
            off = ink.pt(2.6)
            ink.rect(main, x0 + off, ybot - off, x1 + off, ytop - off, fc=INK, z=z, gid="ink:shadow")
        ink.rect(main, x0, ytop - hh, x1, ytop, fc=CALL, z=z + 0.1)
        ink.rect(main, x0, ybot, x1, ytop - hh, fc=PAPER, z=z + 0.1)
        ink.rect(main, x0, ybot, x1, ytop, fc="none", ec=INK, lw=1.35, z=z + 0.2)
        t.set_text(l1)
        t.set_fontproperties(p1)
        t.set_color(PAPER)
        t.set_bbox(None)
        t.set_zorder(z + 0.3)
        t.set_gid("ink:label")
        ink.move_text_px(t, x0 + padx, ytop - hh + pady + d1, ha="left", va="baseline")
        # 日框「收／現」：紅漲黑平綠跌（漲停特例仍走表頭 chip；框內字跟 move ink）
        close_col = INK
        try:
            raw_c = getattr(ink.fig, "_wayne_close_move_ink", None)
            if raw_c:
                close_col = str(raw_c)
        except Exception:
            close_col = INK
        m_close = re.search(r"((?:收|現)[\d,.]+)\s*$", l2)
        if m_close and m_close.start() > 0:
            pref = l2[: m_close.start()]
            bit = m_close.group(1)
            wp, _, _ = ink.measure(pref, p2)
            ink.text(main, x0 + padx, ybot + pady + d2, pref, prop=p2, color=INK, ha="left", z=z + 0.3)
            ink.text(
                main,
                x0 + padx + wp,
                ybot + pady + d2,
                bit,
                prop=p2,
                color=close_col,
                ha="left",
                z=z + 0.3,
            )
        else:
            ink.text(main, x0 + padx, ybot + pady + d2, l2, prop=p2, color=INK, ha="left", z=z + 0.3)
        ink.record(s, [l1, l2], "path_note", Bbox.from_extents(x0, ybot, x1, ytop))
    if sig is not None:
        # 點 2／7：量能訊號黑底白字框放回中間訊號列內（對齊主圖左緣），不准漂左外
        bb = sig.get_window_extent(ink.ren)
        for t in list(sig.texts):
            if "訊號" not in str(t.get_text()):
                continue
            raw = str(t.get_text())
            prop = fp(max(9.0, float(t.get_fontsize()) + 0.5), heavy=True)
            lines = [ln for ln in raw.replace("／", "\n").split("\n") if ln.strip()]
            if not lines:
                lines = ["量能", "訊號"]
            sizes = [ink.measure(ln, prop) for ln in lines]
            tw = max(s[0] for s in sizes)
            th = sum(s[1] for s in sizes) + ink.pt(2.0) * (len(lines) - 1)
            padx, pady = ink.pt(4.0), ink.pt(3.2)
            box_w = tw + 2 * padx
            box_h = max(th + 2 * pady, bb.height * 0.78)
            # 貼訊號列左內側，與主圖／量圖左緣齊
            x0 = bb.x0 + ink.pt(2.0)
            x1 = x0 + box_w
            cy = 0.5 * (bb.y0 + bb.y1)
            y0 = cy - box_h / 2
            y1 = cy + box_h / 2
            ink.rect(sig, x0, y0, x1, y1, fc=INK, ec=INK, lw=1.2, z=20, gid="ink:sigbox")
            # 逐行白字置中
            y = y1 - pady
            for ln, (lw_, lh, ld) in zip(lines, sizes):
                y -= lh
                ink.text(sig, 0.5 * (x0 + x1), y + ld, ln, prop=prop, color=PAPER, ha="center", z=21, gid="ink:siglab")
                y -= ink.pt(2.0)
            t.set_visible(False)
            t.set_gid("ink:replaced")
            ink.record(raw, lines, "sig_label", Bbox.from_extents(x0, y0, x1, y1))
    if volume is not None:
        for t in volume.texts:
            s = str(t.get_text())
            if re.fullmatch(r"\d{2}月|\d{2}/\d{2}", s.strip()):
                t.set_fontproperties(fp(t.get_fontsize() + 0.5, heavy=True))
                t.set_color(INK)


def vol_footer(ink: Ink) -> None:
    """底部說明只調色／字級；不准再畫日期軸上方分隔橫線（雙底框）。"""
    fig = ink.fig
    foot = [t for t in fig.texts if t.get_visible() and len(str(t.get_text())) > 40]
    if not foot:
        return
    for t in foot:
        t.set_color(INK2)
        t.set_fontproperties(fp(t.get_fontsize(), heavy=False))
    # 明確不畫橫線


def ma_under_candles(main) -> None:
    """均線壓在縮圖 K 下方（正式 paint 預設 z=4 會蓋住 z=3 的 K＝錯）。線仍在，只改 z。"""
    for ln in main.lines:
        if len(ln.get_xdata()) >= 20 and ln.get_linestyle() == "-":
            ln.set_zorder(2.0)
            # 細白描邊仍可，但 z 低於 K，不會蓋住實體
            lw = float(ln.get_linewidth())
            ln.set_path_effects([pe.Stroke(linewidth=lw + 1.2, foreground=PAPER), pe.Normal()])
    # 保險：K 實體／影線 z 必須 > 均線
    body = {UP.lower(), DN.lower(), "#e53935", "#00897b"}
    for p in main.patches:
        if isinstance(p, Rectangle) and _hex(p.get_facecolor()).lower() in body:
            if float(p.get_zorder()) < 3.0:
                p.set_zorder(3.0)
    for c in main.collections:
        if isinstance(c, LineCollection) and len(c.get_paths()) >= 20:
            if float(c.get_zorder()) < 3.0:
                c.set_zorder(3.0)


_MA_LINE = {
    "5": ("#ef6c00", "#e65100", "#ff6f00"),
    "10": ("#00838f", "#006064", "#00acc1"),
    "月": ("#f9a825", "#fbc02d", "#ffb300"),
    "季": ("#5c6bc0", "#3f51b5", "#7986cb"),
}


def force_ma_badges(ink: Ink, main) -> None:
    """正式版短標避讓略過時，四顆圓章都要補齊（5／10／月／季），字不准消失。"""
    have = {str(t.get_text()).strip() for t in main.texts if t.get_visible()}
    for lab, colors in _MA_LINE.items():
        if lab in have:
            continue
        target = None
        for ln in main.lines:
            if len(ln.get_xdata()) >= 20 and ln.get_linestyle() == "-" and _hex(ln.get_color()) in colors:
                target = ln
                break
        if target is None:
            continue
        xs = np.asarray(target.get_xdata(), dtype=float)
        ys = np.asarray(target.get_ydata(), dtype=float)
        ok = np.isfinite(xs) & np.isfinite(ys) & (ys > 0)
        if not ok.any():
            continue
        idx = np.where(ok)[0]
        frac = {"5": 0.32, "10": 0.48, "月": 0.22, "季": 0.18}[lab]
        i = idx[int(len(idx) * frac)]
        x, y = float(xs[i]), float(ys[i])
        face = colors[0]
        tc = INK if lab in ("月",) or face.lower() in ("#f9a825", "#ef6c00") else PAPER
        # 月線黃底墨字；其餘實心底白字
        if lab == "月":
            tc = INK
        elif lab == "5":
            tc = PAPER
        t = main.text(
            x, y, lab,
            color=tc,
            fontproperties=fp(12.0, heavy=True),
            ha="center", va="center", zorder=12.5, clip_on=False,
            bbox=dict(boxstyle="circle,pad=0.28", facecolor=face, edgecolor=INK, linewidth=1.45),
        )
        halo = PAPER if tc == INK else INK
        t.set_path_effects([pe.withStroke(linewidth=1.35, foreground=halo)])
        t.set_gid(f"ink:ma:{lab}")
        ink.record(lab, [lab], "ma_badge", ink.shell_ext(t))
        have.add(lab)


def knockout_halos(main, sig) -> None:
    """訊號符號加白色鏤空描邊；均線改走 ma_under_candles。"""
    for ax in [a for a in (main, sig) if a is not None]:
        for p in ax.patches:
            if isinstance(p, Polygon) and str(p.get_gid() or "") == "":
                p.set_path_effects([pe.Stroke(linewidth=1.6, foreground=PAPER), pe.Normal()])


def apply_vol(fig) -> Ink:
    ink = Ink(fig, "vol", lazy=True)
    header, main, sig, volume = _vol_axes(fig)
    # 大盤大量區 with_nav_signals=False：無 header／圖例／訊號列，仍要套墨線主圖＋量框
    if main is None:
        return ink
    legends: List[Legend] = []
    if header is not None:
        legends = [a for a in header.artists if isinstance(a, Legend)]
        if header.get_legend() is not None:
            legends.append(header.get_legend())
    align_vol_panel_margins(main, sig, volume)
    ink.redraw()  # 對齊 margins 後第一次 sync
    vol_frames(ink, main, sig, volume)
    restyle_candles_and_bars(main)
    restyle_bands(main)
    restyle_levels(main)
    restyle_grid_ticks(main, ylab_size=11.25)
    sparse_right_ticks(main, n_bins=5, price=True)
    if volume is not None:
        restyle_candles_and_bars(volume, volume=True)
        restyle_grid_ticks(volume, ylab_size=10.75)
        sparse_right_ticks(volume, n_bins=4, price=False)
        flush_volume_bars_to_spine(volume)
        clear_vol_top_ytick(volume)
    flush_data_left_xlim(main, sig, volume)
    if sig is not None:
        sig.tick_params(colors=INK, length=0, bottom=False, top=False, left=False, right=False)
    if header is not None:
        _grow_legend_markers(legends)
        ink.redraw()  # KEY 符號加大後量一次盒
        panel_left = vol_key_shift(ink, legends, main)
        vol_masthead(ink, header, legends, panel_left)
        open_vol_vertical_gaps(ink, legends, main)
        breathe_observe_legend(ink, legends)
        ink.redraw()  # 開縫／觀察列 sep 後一次，給 KEY 面板量盒
        vol_key_panel(ink, header, legends, panel_left)
    ma_under_candles(main)
    knockout_halos(main, sig)
    ma_badges(ink, main)
    force_ma_badges(ink, main)
    vol_labels(ink, header, main, sig, volume)
    badge_all_labels(ink, [main] + ([volume] if volume is not None else []), vol_ax=volume)
    lift_ex_div_off_press(ink, main)
    vol_footer(ink)
    kill_seam_ticks(main, sig, volume)
    if volume is not None:
        flush_volume_bars_to_spine(volume)
        clear_vol_top_ytick(volume)
    flush_data_left_xlim(main, sig, volume)
    # 刻度／縫處理後再封一次右外框，確保不缺邊、刻度不卡框
    vol_close_right_outer_frame(ink, main, sig, volume)
    ink._flat_scrub = scrub_flat(fig)
    return ink


def apply_ink(fig, kind: str) -> Ink:
    return apply_struct(fig) if kind == "struct" else apply_vol(fig)



def ink_chart_enabled() -> bool:
    v = str(_os.environ.get("WAYNE_INK_CHART", "1") or "1").strip().lower()
    return v not in ("0", "false", "off", "no", "disable", "disabled")


def maybe_apply_ink(fig, kind: str) -> bool:
    """查股結構／大量區 savefig 前套墨線。失敗只記 log，不准炸出圖／排程。"""
    if fig is None or not ink_chart_enabled():
        return False
    k = "struct" if str(kind or "").lower() in ("struct", "structure", "chart") else "vol"
    try:
        apply_ink(fig, k)
        return True
    except Exception:
        _log.exception("ink_chart_theme apply failed kind=%s", k)
        return False
