"""智能標籤基本評測套件（可回歸）。

2026-10-26 鎖：
- 底線（任一 fail＝整張不合格）：不壓 K／量／他標／關鍵數字；不裁切；不孤字斷數字。
- 協調與平衡（計分）：同帶對齊、視覺重心、邊距、疏密、層級、縮圖可讀。
- 功能／底線不過＝不准合；美感／協調低＝改策略再渲。
不准改買訊／假 OHLC。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# —— 底線閘（硬 fail）——
GATE_K_HIT_BARS = 0
GATE_VOL_HIT_LABELS = 0
GATE_LABEL_OVERLAP = 0
GATE_KEY_NUMBER_HIT = 0  # 壓右軸刻度／關鍵價數字
GATE_CLIPPED_OR_ORPHAN = 0
GATE_CHANNEL_X_FRAC = 0.12
GATE_CHANNEL_X_BARS = 10.0
GATE_RAIL_OFF_FRAC = 0.06

# —— 協調／平衡合成分（0–100）；低分＝needs_restyle ——
GATE_AESTHETIC_MIN = 70.0
# 權重合計 100；報告必須列同一套
AESTHETIC_WEIGHTS: Dict[str, float] = {
    "overlap_clear": 18.0,  # 殘餘重疊壓力（底線過後仍量）
    "parallel_pair_x_gap": 14.0,
    "alignment": 10.0,
    "visual_balance": 14.0,  # 面積重心不過偏一角
    "edge_margin": 12.0,  # 邊距／呼吸感
    "crowding_density": 12.0,  # 局部疏密
    "hierarchy": 10.0,  # 主／輔不搶
    "thumbnail_readable": 10.0,  # 縮圖可讀代理
}
assert abs(sum(AESTHETIC_WEIGHTS.values()) - 100.0) < 1e-6

# 標籤層級：主標權重大、輔標可讓
KIND_TIER: Dict[str, str] = {
    "channel_u": "primary",
    "channel_l": "primary",
    "layer": "primary",
    "path": "primary",
    "key": "primary",  # 壓／撐角標、今收
    "ma": "secondary",
    "vol": "secondary",
    "other": "secondary",
}


@dataclass
class LabelBox:
    kind: str
    text: str
    x0: float
    x1: float
    y0: float
    y1: float
    rail_y: Optional[float] = None
    clipped: bool = False
    orphan: bool = False  # 孤字／數字被切斷
    hits_key_number: bool = False  # 壓右軸刻度／關鍵數字

    @property
    def cx(self) -> float:
        return 0.5 * (float(self.x0) + float(self.x1))

    @property
    def cy(self) -> float:
        return 0.5 * (float(self.y0) + float(self.y1))

    @property
    def area(self) -> float:
        return max(0.0, float(self.x1) - float(self.x0)) * max(
            0.0, float(self.y1) - float(self.y0)
        )

    @property
    def tier(self) -> str:
        return KIND_TIER.get(self.kind, "secondary")


@dataclass
class ChartGeom:
    n: int
    highs: Sequence[float]
    lows: Sequence[float]
    labels: List[LabelBox] = field(default_factory=list)
    vol_heights: Optional[Sequence[float]] = None
    ymin: float = 0.0
    ymax: float = 1.0
    xmin: float = -0.5
    xmax: Optional[float] = None
    chart: str = ""
    sid: str = ""


@dataclass
class AestheticParts:
    overlap_clear: float
    parallel_pair_x_gap: float
    alignment: float
    visual_balance: float
    edge_margin: float
    crowding_density: float
    hierarchy: float
    thumbnail_readable: float

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class MetricScore:
    sid: str
    chart: str
    bucket: str
    k_hit_bars: int
    k_hit_labels: int
    label_overlaps: int
    vol_hit_labels: int
    key_number_hits: int
    clipped_or_orphan: int
    channel_pair_dx: Optional[float]
    channel_pair_dx_frac: Optional[float]
    rail_off_max_frac: Optional[float]
    n_labels: int
    aesthetic_score: float
    aesthetic_parts: Dict[str, float]
    baseline_pass: bool  # 底線
    functional_pass: bool  # 底線＋通道同帶／貼線（合主硬閘）
    aesthetic_pass: bool
    pass_gate: bool
    needs_restyle: bool
    fail_reasons: List[str] = field(default_factory=list)
    restyle_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


BUCKET_STRATEGIES: Dict[str, str] = {
    "dual_parallel": "通道雙標鎖同垂直帶；硬拒蓋 K；同帶無淨空→略過",
    "crowded_near": "近端擁擠：說明／橘框改右軸旁或中右空白；撞 K→略過",
    "mid_clear": "中段空窗：沿線／沿軌貼空窗；仍硬拒蓋 K",
    "right_edge_k": "右緣近期 K 密：禁右下硬壓；改上緣內側或右溝",
    "layer_pair": "下一層壓／撐共享 x 帶；代價高→右溝或略過",
    "ma_short": "均線短標只貼己線；淨空不足不畫",
    "vol_pane": "量標抬離柱頂＋避右軸；互壓則錯開或略過",
    "sparse": "標少：沿線預設；仍走整套評測",
    "imbalanced": "重心偏一角：把次要標挪對側空窗或略過輔標",
}


def _boxes_overlap(
    a: LabelBox, b: LabelBox, *, pad_x: float = 0.15, pad_y: float = 0.0
) -> bool:
    return not (
        a.x1 + pad_x < b.x0
        or b.x1 + pad_x < a.x0
        or a.y1 + pad_y < b.y0
        or b.y1 + pad_y < a.y0
    )


def _label_k_hit_bars(
    lab: LabelBox,
    *,
    n: int,
    highs: Sequence[float],
    lows: Sequence[float],
    bar_half: float = 0.42,
) -> int:
    hits = 0
    i0 = max(0, int(lab.x0 - bar_half))
    i1 = min(int(n) - 1, int(lab.x1 + bar_half))
    for i in range(i0, i1 + 1):
        try:
            hk = float(highs[i])
            lk = float(lows[i])
        except (TypeError, ValueError, IndexError):
            continue
        if hk <= 0 or lk <= 0:
            continue
        if lk <= lab.y1 and hk >= lab.y0:
            hits += 1
    return int(hits)


def _label_vol_hit(
    lab: LabelBox, *, n: int, vol_heights: Sequence[float], vol_y0: float = 0.0
) -> bool:
    if lab.kind != "vol":
        return False
    i0 = max(0, int(lab.x0 - 0.5))
    i1 = min(int(n) - 1, int(lab.x1 + 0.5))
    for i in range(i0, i1 + 1):
        try:
            h = float(vol_heights[i])
        except (TypeError, ValueError, IndexError):
            continue
        if h <= 0:
            continue
        if lab.y0 < h and lab.y1 > vol_y0:
            return True
    return False


def classify_bucket(geom: ChartGeom) -> str:
    n = max(int(geom.n), 1)
    labels = list(geom.labels or [])
    if not labels:
        return "sparse"
    # 重心極偏先分桶
    xmax = float(geom.xmax) if geom.xmax is not None else float(n - 1) + 0.8
    xmin = float(geom.xmin)
    x_span = max(xmax - xmin, 1e-6)
    y_span = max(float(geom.ymax) - float(geom.ymin), 1e-6)
    areas = [max(L.area, 1e-6) for L in labels]
    wsum = sum(areas)
    cx = sum(L.cx * a for L, a in zip(labels, areas)) / wsum
    cy = sum(L.cy * a for L, a in zip(labels, areas)) / wsum
    nx = (cx - xmin) / x_span
    ny = (cy - float(geom.ymin)) / y_span
    if nx < 0.22 or nx > 0.78 or ny < 0.18 or ny > 0.82:
        if len(labels) >= 3:
            return "imbalanced"

    ch_u = [L for L in labels if L.kind == "channel_u"]
    ch_l = [L for L in labels if L.kind == "channel_l"]
    if ch_u and ch_l:
        return "dual_parallel"
    layers = [L for L in labels if L.kind == "layer"]
    if len(layers) >= 2:
        return "layer_pair"
    paths = [L for L in labels if L.kind == "path"]
    recent_lo = float(n) * 0.78
    if paths and any(L.cx >= recent_lo for L in paths):
        return "right_edge_k"
    near = [L for L in labels if L.cx >= recent_lo]
    if len(near) >= 3:
        return "crowded_near"
    mas = [L for L in labels if L.kind == "ma"]
    if mas and not ch_u and not layers:
        return "ma_short"
    vols = [L for L in labels if L.kind == "vol"]
    if vols and len(labels) <= len(vols) + 1:
        return "vol_pane"
    mid = [L for L in labels if 0.25 * n <= L.cx <= 0.75 * n]
    if mid:
        return "mid_clear"
    return "sparse"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _score_from_penalty(penalty: float) -> float:
    return 100.0 * (1.0 - _clamp01(penalty))


def compute_aesthetic_parts(
    geom: ChartGeom,
    *,
    k_hit_bars: int,
    label_overlaps: int,
    vol_hits: int,
    pair_frac: Optional[float],
    pair_dx: Optional[float],
) -> AestheticParts:
    n = max(int(geom.n), 1)
    labels = list(geom.labels or [])
    y_span = max(float(geom.ymax) - float(geom.ymin), 1.0)
    xmax = float(geom.xmax) if geom.xmax is not None else float(n - 1) + 0.8
    xmin = float(geom.xmin)
    x_span = max(xmax - xmin, 1.0)

    # overlap_clear：底線過後殘餘壓力
    p_ov = _clamp01(
        float(k_hit_bars) * 0.35 + float(vol_hits) * 0.4 + float(label_overlaps) * 0.4
    )

    if pair_frac is None:
        p_gap = 0.0
    else:
        soft = max(
            float(pair_dx or 0) / max(GATE_CHANNEL_X_BARS, 1e-6),
            float(pair_frac) / max(GATE_CHANNEL_X_FRAC, 1e-6),
        )
        p_gap = _clamp01(soft)

    # alignment
    align_pen = 0.0
    ch_u = [L for L in labels if L.kind == "channel_u"]
    ch_l = [L for L in labels if L.kind == "channel_l"]
    if ch_u and ch_l:
        align_pen = max(
            align_pen,
            _clamp01(abs(ch_u[0].cx - ch_l[0].cx) / max(GATE_CHANNEL_X_BARS, 1e-6)),
        )
    layers = [L for L in labels if L.kind == "layer"]
    if len(layers) >= 2:
        align_pen = max(
            align_pen,
            _clamp01(
                abs(layers[0].cx - layers[1].cx) / max(GATE_CHANNEL_X_BARS, 1e-6)
            ),
        )

    # visual_balance：面積加權重心離圖心
    bal = 0.0
    if labels:
        areas = [max(L.area, 1e-6) for L in labels]
        wsum = sum(areas)
        cx = sum(L.cx * a for L, a in zip(labels, areas)) / wsum
        cy = sum(L.cy * a for L, a in zip(labels, areas)) / wsum
        nx = (cx - xmin) / x_span
        ny = (cy - float(geom.ymin)) / y_span
        # 離 (0.5,0.5) 的 L∞；>0.18 開始罰
        dev = max(abs(nx - 0.5), abs(ny - 0.5))
        bal = _clamp01((dev - 0.18) / 0.32)

    # edge_margin
    edge_pen = 0.0
    margin_x = max(x_span * 0.02, 0.35)
    margin_y = max(y_span * 0.02, 1.0)
    if labels:
        tight = 0
        for L in labels:
            if L.x0 < xmin + margin_x or L.x1 > xmax - margin_x:
                tight += 1
            if L.y0 < float(geom.ymin) + margin_y or L.y1 > float(geom.ymax) - margin_y:
                tight += 1
        edge_pen = min(1.0, tight / max(len(labels), 1) * 0.85)

    # crowding 4×3
    crowding = 0.0
    if labels:
        gx, gy = 4, 3
        cells: Dict[Tuple[int, int], int] = {}
        for L in labels:
            ix = min(gx - 1, max(0, int((L.cx - xmin) / x_span * gx)))
            iy = min(
                gy - 1,
                max(0, int((L.cy - float(geom.ymin)) / y_span * gy)),
            )
            cells[(ix, iy)] = cells.get((ix, iy), 0) + 1
        peak = max(cells.values()) if cells else 0
        crowding = _clamp01((peak - 2) / 4.0)

    # hierarchy：主標互壓或主標面積被輔標蓋過
    hier = 0.0
    prim = [L for L in labels if L.tier == "primary"]
    sec = [L for L in labels if L.tier == "secondary"]
    if prim and sec:
        for p in prim:
            for s in sec:
                if _boxes_overlap(p, s, pad_x=0.05, pad_y=0.0):
                    hier += 0.35
                # 輔標盒幾乎蓋住主標中心
                if p.x0 <= s.cx <= p.x1 and p.y0 <= s.cy <= p.y1:
                    hier += 0.25
        hier = _clamp01(hier)

    # thumbnail_readable：標相對圖幅過小或過密→縮圖糊
    thumb = 0.0
    if labels:
        chart_area = x_span * y_span
        mean_a = sum(max(L.area, 1e-9) for L in labels) / len(labels)
        # 單標面積佔圖 < 0.0015 → 縮圖難讀；>0.04 則擋 K
        frac = mean_a / max(chart_area, 1e-9)
        if frac < 0.0012:
            thumb += (0.0012 - frac) / 0.0012
        if frac > 0.045:
            thumb += min(1.0, (frac - 0.045) / 0.05)
        # 近端標太多
        near = sum(1 for L in labels if L.cx >= n * 0.8)
        if near >= 4:
            thumb += 0.35
        thumb = _clamp01(thumb)

    return AestheticParts(
        overlap_clear=_score_from_penalty(p_ov),
        parallel_pair_x_gap=_score_from_penalty(p_gap),
        alignment=_score_from_penalty(align_pen),
        visual_balance=_score_from_penalty(bal),
        edge_margin=_score_from_penalty(edge_pen),
        crowding_density=_score_from_penalty(crowding),
        hierarchy=_score_from_penalty(hier),
        thumbnail_readable=_score_from_penalty(thumb),
    )


def aesthetic_score_from_parts(parts: AestheticParts) -> float:
    d = parts.to_dict()
    total = 0.0
    for k, w in AESTHETIC_WEIGHTS.items():
        total += float(d.get(k, 100.0)) * (w / 100.0)
    return round(max(0.0, min(100.0, total)), 2)


def score_chart(geom: ChartGeom) -> MetricScore:
    n = max(int(geom.n), 1)
    highs = list(geom.highs)
    lows = list(geom.lows)
    labels = list(geom.labels or [])
    y_span = max(float(geom.ymax) - float(geom.ymin), 1.0)

    k_hit_bars = 0
    k_hit_labels = 0
    for lab in labels:
        if lab.kind == "vol":
            continue
        hb = _label_k_hit_bars(lab, n=n, highs=highs, lows=lows)
        if hb > 0:
            k_hit_labels += 1
            k_hit_bars += hb

    overlaps = 0
    for i, a in enumerate(labels):
        for b in labels[i + 1 :]:
            if _boxes_overlap(a, b):
                overlaps += 1

    vol_hits = 0
    if geom.vol_heights is not None:
        for lab in labels:
            if lab.kind == "vol" and _label_vol_hit(
                lab, n=n, vol_heights=list(geom.vol_heights)
            ):
                vol_hits += 1

    key_hits = sum(1 for L in labels if L.hits_key_number)
    clipped_or_orphan = sum(1 for L in labels if L.clipped or L.orphan)

    ch_u = [L for L in labels if L.kind == "channel_u"]
    ch_l = [L for L in labels if L.kind == "channel_l"]
    pair_dx: Optional[float] = None
    pair_frac: Optional[float] = None
    if ch_u and ch_l:
        pair_dx = abs(float(ch_u[0].cx) - float(ch_l[0].cx))
        pair_frac = float(pair_dx) / float(n)

    rail_offs: List[float] = []
    for lab in labels:
        if lab.rail_y is None:
            continue
        rail_offs.append(abs(float(lab.cy) - float(lab.rail_y)) / y_span)
    rail_off_max = max(rail_offs) if rail_offs else None

    parts = compute_aesthetic_parts(
        geom,
        k_hit_bars=k_hit_bars,
        label_overlaps=overlaps,
        vol_hits=vol_hits,
        pair_frac=pair_frac,
        pair_dx=pair_dx,
    )
    aest = aesthetic_score_from_parts(parts)
    bucket = classify_bucket(geom)

    # —— 底線 ——
    baseline_fails: List[str] = []
    if k_hit_bars > GATE_K_HIT_BARS:
        baseline_fails.append(f"k_hit_bars={k_hit_bars}>{GATE_K_HIT_BARS}")
    if vol_hits > GATE_VOL_HIT_LABELS:
        baseline_fails.append(f"vol_hit_labels={vol_hits}>{GATE_VOL_HIT_LABELS}")
    if overlaps > GATE_LABEL_OVERLAP:
        baseline_fails.append(f"label_overlaps={overlaps}>{GATE_LABEL_OVERLAP}")
    if key_hits > GATE_KEY_NUMBER_HIT:
        baseline_fails.append(f"key_number_hits={key_hits}>{GATE_KEY_NUMBER_HIT}")
    if clipped_or_orphan > GATE_CLIPPED_OR_ORPHAN:
        baseline_fails.append(
            f"clipped_or_orphan={clipped_or_orphan}>{GATE_CLIPPED_OR_ORPHAN}"
        )

    # —— 功能（底線＋通道／貼線）——
    func_fails = list(baseline_fails)
    if pair_frac is not None:
        if pair_frac > GATE_CHANNEL_X_FRAC and float(pair_dx or 0) > GATE_CHANNEL_X_BARS:
            func_fails.append(
                f"channel_dx_frac={pair_frac:.3f}>{GATE_CHANNEL_X_FRAC}"
                f" dx={pair_dx:.1f}>{GATE_CHANNEL_X_BARS}"
            )
    if rail_off_max is not None and rail_off_max > GATE_RAIL_OFF_FRAC:
        func_fails.append(f"rail_off={rail_off_max:.3f}>{GATE_RAIL_OFF_FRAC}")

    baseline_pass = not baseline_fails
    functional_pass = not func_fails
    aesthetic_pass = aest >= GATE_AESTHETIC_MIN
    restyle: List[str] = []
    if functional_pass and not aesthetic_pass:
        restyle.append(f"aesthetic_score={aest}<{GATE_AESTHETIC_MIN}")
        weak = sorted(parts.to_dict().items(), key=lambda kv: kv[1])[:3]
        for name, val in weak:
            if val < 80.0:
                restyle.append(f"weak:{name}={val:.0f}")

    return MetricScore(
        sid=str(geom.sid or ""),
        chart=str(geom.chart or ""),
        bucket=bucket,
        k_hit_bars=int(k_hit_bars),
        k_hit_labels=int(k_hit_labels),
        label_overlaps=int(overlaps),
        vol_hit_labels=int(vol_hits),
        key_number_hits=int(key_hits),
        clipped_or_orphan=int(clipped_or_orphan),
        channel_pair_dx=pair_dx,
        channel_pair_dx_frac=pair_frac,
        rail_off_max_frac=rail_off_max,
        n_labels=len(labels),
        aesthetic_score=float(aest),
        aesthetic_parts=parts.to_dict(),
        baseline_pass=baseline_pass,
        functional_pass=functional_pass,
        aesthetic_pass=aesthetic_pass,
        pass_gate=functional_pass,
        needs_restyle=bool(restyle),
        fail_reasons=func_fails,
        restyle_reasons=restyle,
    )


def strategy_for_bucket(bucket: str) -> str:
    return BUCKET_STRATEGIES.get(str(bucket), BUCKET_STRATEGIES["sparse"])


def summarize_scores(scores: Sequence[MetricScore]) -> Dict[str, Any]:
    rows = list(scores)
    by_bucket: Dict[str, List[MetricScore]] = {}
    for s in rows:
        by_bucket.setdefault(s.bucket, []).append(s)
    aests = [s.aesthetic_score for s in rows]
    return {
        "n": len(rows),
        "baseline_pass": sum(1 for s in rows if s.baseline_pass),
        "functional_pass": sum(1 for s in rows if s.functional_pass),
        "functional_fail": sum(1 for s in rows if not s.functional_pass),
        "aesthetic_pass": sum(1 for s in rows if s.aesthetic_pass),
        "needs_restyle": sum(1 for s in rows if s.needs_restyle),
        "aesthetic_mean": round(sum(aests) / len(aests), 2) if aests else None,
        "aesthetic_min": round(min(aests), 2) if aests else None,
        "by_bucket": {
            b: {
                "n": len(v),
                "functional_pass": sum(1 for x in v if x.functional_pass),
                "aesthetic_mean": round(
                    sum(x.aesthetic_score for x in v) / max(len(v), 1), 2
                ),
                "strategy": strategy_for_bucket(b),
            }
            for b, v in sorted(by_bucket.items())
        },
        "gate_baseline": {
            "k_hit_bars": GATE_K_HIT_BARS,
            "vol_hit_labels": GATE_VOL_HIT_LABELS,
            "label_overlaps": GATE_LABEL_OVERLAP,
            "key_number_hits": GATE_KEY_NUMBER_HIT,
            "clipped_or_orphan": GATE_CLIPPED_OR_ORPHAN,
        },
        "gate_functional_extra": {
            "channel_x_frac": GATE_CHANNEL_X_FRAC,
            "channel_x_bars": GATE_CHANNEL_X_BARS,
            "rail_off_frac": GATE_RAIL_OFF_FRAC,
        },
        "gate_aesthetic_min": GATE_AESTHETIC_MIN,
        "aesthetic_weights": dict(AESTHETIC_WEIGHTS),
    }


def collect_labels_from_ax(
    ax,
    *,
    n: int,
    highs: Sequence[float],
    lows: Sequence[float],
    ymin: float,
    ymax: float,
    sid: str = "",
    chart: str = "",
) -> ChartGeom:
    labels: List[LabelBox] = []
    arts = list(getattr(ax, "_wayne_channel_label_artists", None) or [])
    for art in arts:
        try:
            txt = str(art.get_text() or "")
            x, y = art.get_position()
        except Exception:
            continue
        kind = "channel_u"
        if any(k in txt for k in ("平行撐", "上昇軌", "上升軌", "下軌")):
            kind = "channel_l"
        if any(k in txt for k in ("下降壓", "平行壓", "上軌")):
            kind = "channel_u"
        clipped = False
        try:
            ax.figure.canvas.draw()
            ren = ax.figure.canvas.get_renderer()
            bb = art.get_window_extent(renderer=ren)
            inv = ax.transData.inverted()
            (x0, y0) = inv.transform((bb.x0, bb.y0))
            (x1, y1) = inv.transform((bb.x1, bb.y1))
            try:
                abb = ax.get_window_extent(renderer=ren)
                if (
                    bb.x0 < abb.x0 - 2
                    or bb.x1 > abb.x1 + 2
                    or bb.y0 < abb.y0 - 2
                    or bb.y1 > abb.y1 + 2
                ):
                    clipped = True
            except Exception:
                pass
            labels.append(
                LabelBox(
                    kind=kind,
                    text=txt,
                    x0=min(x0, x1),
                    x1=max(x0, x1),
                    y0=min(y0, y1),
                    y1=max(y0, y1),
                    rail_y=float(y),
                    clipped=clipped,
                )
            )
            continue
        except Exception:
            pass
        dx, dy = 4.0, max((ymax - ymin) * 0.025, 1.0)
        labels.append(
            LabelBox(
                kind=kind,
                text=txt,
                x0=float(x) - dx / 2,
                x1=float(x) + dx / 2,
                y0=float(y) - dy / 2,
                y1=float(y) + dy / 2,
                rail_y=float(y),
            )
        )
    extra = list(getattr(ax, "_wayne_smart_label_boxes", None) or [])
    for raw in extra:
        try:
            labels.append(
                LabelBox(
                    kind=str(raw.get("kind") or "other"),
                    text=str(raw.get("text") or ""),
                    x0=float(raw["x0"]),
                    x1=float(raw["x1"]),
                    y0=float(raw["y0"]),
                    y1=float(raw["y1"]),
                    rail_y=(
                        float(raw["rail_y"])
                        if raw.get("rail_y") is not None
                        else None
                    ),
                    clipped=bool(raw.get("clipped") or False),
                    orphan=bool(raw.get("orphan") or False),
                    hits_key_number=bool(raw.get("hits_key_number") or False),
                )
            )
        except Exception:
            continue
    return ChartGeom(
        n=int(n),
        highs=highs,
        lows=lows,
        labels=labels,
        ymin=float(ymin),
        ymax=float(ymax),
        chart=chart,
        sid=sid,
    )


def record_smart_label(ax, **box_kw: Any) -> None:
    try:
        lst = getattr(ax, "_wayne_smart_label_boxes", None)
        if lst is None:
            lst = []
            ax._wayne_smart_label_boxes = lst  # type: ignore[attr-defined]
        lst.append(dict(box_kw))
    except Exception:
        pass
