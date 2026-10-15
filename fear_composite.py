# -*- coding: utf-8 -*-
"""FearComposite₀｜開盤前恐懼複合（只觀察，不是買訊）。

票池（缺鍵不投票、不編造）：
  1. 美股大跌／regime∈{caution,risk_off} 且電子鏈夜側＝跌
  2. TX 或 TE 夜盤相對前一交易日日盤結算 ≤ night_thr%
  3. 外圍池一票：USD/TWD Δ≥usdtwd_thr 或 DXY Δ≥dxy_thr 或 |Brent Δ|≥brent_abs

濾：台股休市不計；美股關鍵欄（那指／費半／VIX）全空 → 整包不亮。
不准改 leave_zero／黃金買點。Asia/Taipei。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple  # Sequence：單位檢查用

# 草稿門檻（離線網格可覆寫；預設＝計畫稿）
DEFAULT_MIN_VOTES = 2
DEFAULT_NIGHT_THR = -0.8
DEFAULT_USDTWD_THR = 0.3
DEFAULT_DXY_THR = 0.4
DEFAULT_BRENT_ABS_THR = 3.0
# 開盤相對昨收 ≤ 此值＝Sync（跳空已殺，不是盤前偷跑）
DEFAULT_SYNC_GAP_PCT = -1.0
# 當日加權大跌混淆閾（分表用，不混進主勝率）
DEFAULT_DUMP_DAY_PCT = -1.5

VOTE_US = "us_risk"
VOTE_NIGHT = "tx_te_night"
VOTE_OUTER = "outer_fx_oil"

GRID_MIN_VOTES: Tuple[int, ...] = (2, 3)
GRID_NIGHT_THR: Tuple[float, ...] = (-0.5, -0.8, -1.2)
GRID_USDTWD_THR: Tuple[float, ...] = (0.3,)
GRID_DXY_THR: Tuple[float, ...] = (0.4,)
GRID_BRENT_ABS: Tuple[float, ...] = (3.0,)


def _f(val: Any) -> Optional[float]:
    try:
        if val is None or val == "":
            return None
        n = float(val)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN
        return None
    return n


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


@dataclass(frozen=True)
class FearParams:
    min_votes: int = DEFAULT_MIN_VOTES
    night_thr: float = DEFAULT_NIGHT_THR
    usdtwd_thr: float = DEFAULT_USDTWD_THR
    dxy_thr: float = DEFAULT_DXY_THR
    brent_abs_thr: float = DEFAULT_BRENT_ABS_THR
    sync_gap_pct: float = DEFAULT_SYNC_GAP_PCT
    dump_day_pct: float = DEFAULT_DUMP_DAY_PCT

    def key(self) -> str:
        return (
            f"v{self.min_votes}"
            f"_n{self.night_thr:g}"
            f"_twd{self.usdtwd_thr:g}"
            f"_dx{self.dxy_thr:g}"
            f"_br{self.brent_abs_thr:g}"
        )

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def iter_fear_param_grid() -> List[FearParams]:
    """全網格：每組門檻都要跑，不准只抽一組交差。"""
    out: List[FearParams] = []
    for mv in GRID_MIN_VOTES:
        for nt in GRID_NIGHT_THR:
            for twd in GRID_USDTWD_THR:
                for dx in GRID_DXY_THR:
                    for br in GRID_BRENT_ABS:
                        out.append(
                            FearParams(
                                min_votes=int(mv),
                                night_thr=float(nt),
                                usdtwd_thr=float(twd),
                                dxy_thr=float(dx),
                                brent_abs_thr=float(br),
                            )
                        )
    return out


@dataclass
class FearVoteDetail:
    name: str
    lit: bool
    reason: str = ""
    value: Optional[float] = None
    available: bool = True


@dataclass
class FearCompositeResult:
    as_of: str
    lit: bool
    evaluable: bool
    votes: int
    min_votes: int
    vote_details: List[FearVoteDetail] = field(default_factory=list)
    lead_sync: str = ""  # "lead" | "sync" | ""（未亮或不估值）
    gap_open_pct: Optional[float] = None
    params_key: str = ""
    skip_reason: str = ""

    def lit_vote_names(self) -> List[str]:
        return [v.name for v in self.vote_details if v.lit]


def us_keys_present(snap: Dict[str, Any]) -> bool:
    """美股關鍵欄：那指／費半／VIX 至少有一欄有數才算「有美股包」。

    計畫濾＝三者皆空才整包不亮。任一有數即可評估美股票（仍可能投不亮）。
    """
    snap = snap or {}
    for k in ("ixic_pct", "sox_pct", "vix"):
        if _f(snap.get(k)) is not None:
            return True
    return False


def vote_us_risk(snap: Dict[str, Any]) -> FearVoteDetail:
    """票 1：should_alert_us_drop 或 regime∈caution/risk_off 且電子鏈＝跌。"""
    snap = snap or {}
    if not us_keys_present(snap):
        return FearVoteDetail(
            name=VOTE_US, lit=False, available=False, reason="美股關鍵欄全空"
        )
    try:
        from us_overnight import (
            electronics_night_side,
            should_alert_us_drop,
        )
    except Exception:
        return FearVoteDetail(
            name=VOTE_US, lit=False, available=False, reason="us_overnight 不可用"
        )
    alert = bool(should_alert_us_drop(snap))
    regime = str(snap.get("regime") or "").strip() or "unknown"
    side = electronics_night_side(snap)
    chain_risk = regime in ("caution", "risk_off") and side == "跌"
    lit = alert or chain_risk
    worst = None
    for k in ("ixic_pct", "sox_pct", "spx_pct", "dji_pct"):
        v = _f(snap.get(k))
        if v is None:
            continue
        worst = v if worst is None else min(worst, v)
    reason = (
        f"alert={int(alert)} regime={regime} elec={side or '—'}"
    )
    return FearVoteDetail(
        name=VOTE_US, lit=lit, available=True, reason=reason, value=worst
    )


def night_vs_prior_settle_pct(
    night_close: Any, prior_settle: Any
) -> Optional[float]:
    nc = _f(night_close)
    ps = _f(prior_settle)
    if nc is None or ps is None or ps <= 0:
        return None
    return (nc / ps - 1.0) * 100.0


def vote_tx_te_night(
    *,
    tx_night_pct: Optional[float],
    te_night_pct: Optional[float],
    night_thr: float = DEFAULT_NIGHT_THR,
) -> FearVoteDetail:
    """票 2：TX 或 TE 夜盤相對前日日盤結算 ≤ thr。缺者不投該側。"""
    vals = [v for v in (tx_night_pct, te_night_pct) if v is not None]
    if not vals:
        return FearVoteDetail(
            name=VOTE_NIGHT,
            lit=False,
            available=False,
            reason="TX／TE 夜盤皆缺",
        )
    worst = min(vals)
    lit = worst <= float(night_thr)
    parts = []
    if tx_night_pct is not None:
        parts.append(f"TX={tx_night_pct:.3f}%")
    else:
        parts.append("TX=缺")
    if te_night_pct is not None:
        parts.append(f"TE={te_night_pct:.3f}%")
    else:
        parts.append("TE=缺")
    return FearVoteDetail(
        name=VOTE_NIGHT,
        lit=lit,
        available=True,
        reason=";".join(parts) + f" thr={night_thr:g}",
        value=worst,
    )


def vote_outer(
    snap: Dict[str, Any],
    *,
    usdtwd_thr: float = DEFAULT_USDTWD_THR,
    dxy_thr: float = DEFAULT_DXY_THR,
    brent_abs_thr: float = DEFAULT_BRENT_ABS_THR,
) -> FearVoteDetail:
    """票 3：外圍池任一條件（缺者不構成該子條件）。三子皆無 → available=False。"""
    snap = snap or {}
    twd = _f(snap.get("usdtwd_pct"))
    dxy = _f(snap.get("dx_f_pct"))
    brent = _f(snap.get("brent_pct"))
    if twd is None and dxy is None and brent is None:
        return FearVoteDetail(
            name=VOTE_OUTER,
            lit=False,
            available=False,
            reason="油匯欄全空",
        )
    hits: List[str] = []
    if twd is not None and twd >= float(usdtwd_thr):
        hits.append(f"TWD={twd:.3f}%")
    if dxy is not None and dxy >= float(dxy_thr):
        hits.append(f"DXY={dxy:.3f}%")
    if brent is not None and abs(brent) >= float(brent_abs_thr):
        hits.append(f"Brent={brent:.3f}%")
    lit = bool(hits)
    return FearVoteDetail(
        name=VOTE_OUTER,
        lit=lit,
        available=True,
        reason=(";".join(hits) if hits else "外圍未達門檻"),
        value=twd if twd is not None else (dxy if dxy is not None else brent),
    )


def classify_lead_sync(
    lit: bool,
    gap_open_pct: Optional[float],
    *,
    sync_gap_pct: float = DEFAULT_SYNC_GAP_PCT,
) -> str:
    if not lit:
        return ""
    if gap_open_pct is not None and gap_open_pct <= float(sync_gap_pct):
        return "sync"
    return "lead"


def evaluate_fear_composite(
    *,
    as_of: str,
    us_snap: Optional[Dict[str, Any]] = None,
    tx_night_pct: Optional[float] = None,
    te_night_pct: Optional[float] = None,
    gap_open_pct: Optional[float] = None,
    params: Optional[FearParams] = None,
    tw_closed: bool = False,
) -> FearCompositeResult:
    """評估一日恐懼複合。tw_closed／美股全空 → evaluable=False、不亮。"""
    day = _ymd(as_of)
    p = params or FearParams()
    if tw_closed:
        return FearCompositeResult(
            as_of=day,
            lit=False,
            evaluable=False,
            votes=0,
            min_votes=p.min_votes,
            params_key=p.key(),
            skip_reason="台股休市",
            gap_open_pct=gap_open_pct,
        )
    snap = dict(us_snap or {})
    if not us_keys_present(snap):
        return FearCompositeResult(
            as_of=day,
            lit=False,
            evaluable=False,
            votes=0,
            min_votes=p.min_votes,
            params_key=p.key(),
            skip_reason="美股關鍵欄全空",
            gap_open_pct=gap_open_pct,
        )
    details = [
        vote_us_risk(snap),
        vote_tx_te_night(
            tx_night_pct=tx_night_pct,
            te_night_pct=te_night_pct,
            night_thr=p.night_thr,
        ),
        vote_outer(
            snap,
            usdtwd_thr=p.usdtwd_thr,
            dxy_thr=p.dxy_thr,
            brent_abs_thr=p.brent_abs_thr,
        ),
    ]
    votes = sum(1 for d in details if d.lit)
    lit = votes >= int(p.min_votes)
    return FearCompositeResult(
        as_of=day,
        lit=lit,
        evaluable=True,
        votes=votes,
        min_votes=p.min_votes,
        vote_details=details,
        lead_sync=classify_lead_sync(lit, gap_open_pct, sync_gap_pct=p.sync_gap_pct),
        gap_open_pct=gap_open_pct,
        params_key=p.key(),
    )


# 台股：1 張＝1000 股。WayneBot ``daily_quotes.volume``／``foreign_net`` 一律為**張**
# （見 data_fetcher 欄位註；TWSE 成交股數入庫前 ÷1000）。不准把張當股或股當張。
LOTS_PER_SHARE = 1000
VOLUME_UNIT = "張"
FOREIGN_NET_UNIT = "張"
SELL_SHARE_UNIT = "比率（張/張）"


def sell_share(foreign_net: Any, volume: Any) -> Optional[float]:
    """外資賣超佔量＝(−foreign_net張)/volume張；僅 foreign_net<0 且 volume>0。

    分子分母同為張 → 無量綱比率；若誤用股當張會差 1000 倍。
    """
    fn = _f(foreign_net)
    vol = _f(volume)
    if fn is None or vol is None or vol <= 0 or fn >= 0:
        return 0.0 if (vol is not None and vol > 0 and fn is not None and fn >= 0) else None
    return max(0.0, -fn) / vol


def unit_consistency_report(
    rows: Sequence[Dict[str, Any]],
    *,
    foreign_key: str = "foreign_net",
    volume_key: str = "volume",
) -> Dict[str, Any]:
    """單位一致性檢查（非整檔抽測）：同列 foreign_net／volume 皆視為張。

    若誤把法人股數配成交張，|賣超|/量 常出現大量 ≫1 的極端；此檢查報比率分布。
    """
    n = 0
    n_sell = 0
    n_share_gt1 = 0
    n_share_gt10 = 0
    n_share_gt100 = 0
    for r in rows or []:
        fn = _f(r.get(foreign_key))
        vol = _f(r.get(volume_key))
        if fn is None or vol is None or vol <= 0:
            continue
        n += 1
        if fn >= 0:
            continue
        n_sell += 1
        ss = (-fn) / vol
        if ss > 1.0:
            n_share_gt1 += 1
        if ss > 10.0:
            n_share_gt10 += 1
        if ss > 100.0:
            n_share_gt100 += 1
    # 通過：有樣本且 ≫10 的比例極低（允許少數錯價／特殊日）
    frac_gt10 = (n_share_gt10 / n_sell) if n_sell else 0.0
    ok = n_sell == 0 or frac_gt10 < 0.05
    return {
        "volume_unit": VOLUME_UNIT,
        "foreign_net_unit": FOREIGN_NET_UNIT,
        "sell_share_unit": SELL_SHARE_UNIT,
        "lots_per_share": LOTS_PER_SHARE,
        "n_rows_checked": n,
        "n_sell_rows": n_sell,
        "n_sell_share_gt1": n_share_gt1,
        "n_sell_share_gt10": n_share_gt10,
        "n_sell_share_gt100": n_share_gt100,
        "frac_sell_share_gt10": frac_gt10,
        "units_ok": ok,
        "note": "foreign_net 與 volume 皆張；sell_share＝張/張。若 units_ok=False 疑單位混用。",
    }


def is_dump_day(index_ret_pct: Optional[float], thr: float = DEFAULT_DUMP_DAY_PCT) -> bool:
    return index_ret_pct is not None and index_ret_pct <= float(thr)
