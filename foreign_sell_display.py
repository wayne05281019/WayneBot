# -*- coding: utf-8 -*-
"""外資／恐懼預警｜測試版話筒顯示（觀察／預警，不是買訊）。

使用者 2026-10-15「先做一版」＝測試版可上話筒（早報一句／大盤環境／查股觀察標）。
文案一律標「觀察／預警（測試）」；不准寫成可買；不准改 leave_zero／黃金買點／藍▲紅框。
正式過閘後再收文案（DISPLAY_MODE 之後可改 official）。
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dongzhu_tape import tape_store_path
from fear_composite import _ymd

# 測試版上話筒；正式過閘文案之後再收；靜默對質繼續
DISPLAY_MODE = "test"
DISPLAY_TAG = "觀察／預警（測試）"
BUY_SIGNAL = False  # 硬鎖：永遠不是買訊

# 查股觀察標視覺（須異於藍▲紅框、止穩◆）
OBSERVE_FACE = "#E65100"  # 琥珀橘
OBSERVE_EDGE = "#FF8F00"
OBSERVE_LABEL = "觀察"
OBSERVE_MARKER = "h"  # 六角形；◆＝止穩、▲＝買／60低

# 個股近窗：最近幾個交易日有升級／極端確認才標
STOCK_LOOKBACK_DAYS = 5
# 千金：收≥1000；絕對張數極端軌對這群不公平（平常量常不到門檻）
QIANJIN_PX = 1000.0
# lots_th* 極端軌：當日量至少達門檻才准當顯示（否則高價／小量股永不該靠張數亮）
LOTS_TRACK_MIN_VOL_MULT = 1.0  # 當日量 ≥ 張數門檻 × 此倍數

# 測試版先用、靜默續對（回測有 lift；賣側；買側未過關先不畫橘六角）
DISPLAY_SELL_SHARE_THR = 0.20  # 單日賣超佔量 ≥20% → 極端超比軌
DISPLAY_ESCALATE_THETA = 90.0  # 升級：爬向同日分位前約 10%
DISPLAY_INCLUDE_BUY_ESCALATE = False  # 買升級回測近平基線；測試版先不亮


@dataclass
class EnvObserveStatus:
    """大盤級環境觀察快照（Fear／Confirm／Calm）。"""

    as_of: str
    fear_lit: bool = False
    fear_evaluable: bool = False
    fear_votes: int = 0
    fear_lead_sync: str = ""
    fear_skip: str = ""
    confirm_n: int = 0  # 升級＋極端確認命中檔數（近窗摘要）
    confirm_tags: List[str] = field(default_factory=list)
    calm_lit: bool = False
    calm_note: str = ""
    buy_signal: bool = False  # 永遠 False

    @property
    def any_lit(self) -> bool:
        return bool(self.fear_lit or self.confirm_n > 0 or self.calm_lit)

    def fear_state(self) -> str:
        """中文狀態：恐懼亮／恐懼熄／恐懼未齊。"""
        if not self.fear_evaluable:
            return "恐懼未齊"
        return "恐懼亮" if self.fear_lit else "恐懼熄"

    def confirm_state(self) -> str:
        """中文狀態：確認亮／確認熄。"""
        return "確認亮" if self.confirm_n > 0 else "確認熄"

    def calm_state(self) -> str:
        """中文狀態：冷靜亮／冷靜熄。"""
        return "冷靜亮" if self.calm_lit else "冷靜熄"

    def status_line_zh(self) -> str:
        """大盤狀態一行：恐懼亮／確認熄／冷靜熄。"""
        return f"{self.fear_state()}／{self.confirm_state()}／{self.calm_state()}"


@dataclass
class StockObserveHit:
    """個股升級／確認命中（查股觀察標）。永遠不是買訊。"""

    sid: str
    as_of: str
    source: str  # escalate | extreme
    tag: str
    label: str
    buy_signal: bool = False


def _store(db_path: str) -> str:
    return tape_store_path(db_path)


def _conn_ro(path: str) -> Optional[sqlite3.Connection]:
    if not path or not os.path.isfile(path):
        return None
    try:
        return sqlite3.connect(path, timeout=5.0)
    except sqlite3.Error:
        return None


def _read_fear_tape(db_path: str, as_of: str) -> Dict[str, Any]:
    """讀 fear_preopen_tape；缺則即時 evaluate_day（不寫庫）。"""
    day = _ymd(as_of)
    out: Dict[str, Any] = {
        "lit": False,
        "evaluable": False,
        "votes": 0,
        "lead_sync": "",
        "skip_reason": "",
    }
    store = _store(db_path)
    conn = _conn_ro(store)
    if conn is not None:
        try:
            row = conn.execute(
                """
                SELECT lit, evaluable, votes, lead_sync, skip_reason
                FROM fear_preopen_tape
                WHERE kind=? AND as_of=?
                ORDER BY params_key LIMIT 1
                """,
                ("fear_preopen_warn", day),
            ).fetchone()
            if row:
                out["lit"] = bool(int(row[0] or 0))
                out["evaluable"] = bool(int(row[1] or 0))
                out["votes"] = int(row[2] or 0)
                out["lead_sync"] = str(row[3] or "")
                out["skip_reason"] = str(row[4] or "")
                return out
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    # 無靜默列 → 即時評估（早報盤前常見）
    try:
        from fear_preopen_verify import evaluate_day

        info = evaluate_day(db_path, day)
        res = info.get("result")
        if res is not None:
            out["lit"] = bool(res.lit)
            out["evaluable"] = bool(res.evaluable)
            out["votes"] = int(res.votes or 0)
            out["lead_sync"] = str(res.lead_sync or "")
            out["skip_reason"] = str(res.skip_reason or "")
    except Exception:
        pass
    return out


def _count_confirm(db_path: str, as_of: str) -> Tuple[int, List[str]]:
    """近窗升級／極端確認檔數（去重 sid）。"""
    day = _ymd(as_of)
    store = _store(db_path)
    conn = _conn_ro(store)
    if conn is None:
        return 0, []
    sids: set = set()
    tags: List[str] = []
    try:
        # escalate：當日命中
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT sid, tag FROM foreign_sell_escalate_tape
                WHERE kind=? AND as_of=? AND sid!='' AND sid NOT LIKE 'TWII%'
                """,
                ("foreign_sell_escalate", day),
            ).fetchall()
            for r in rows or []:
                sid = str(r[0] or "").strip()
                if sid:
                    sids.add(sid)
                    t = str(r[1] or "")
                    if t and t not in tags:
                        tags.append(t)
        except sqlite3.Error:
            pass
        # extreme：當日極端錨（張數軌對千金／量不足檔不計）
        try:
            rows = conn.execute(
                """
                SELECT sid, tag, track_key, volume, close
                FROM foreign_sell_extreme_tape
                WHERE kind=? AND as_of=? AND sid!='' AND sid NOT LIKE 'TWII%'
                """,
                ("foreign_sell_extreme_dplus", day),
            ).fetchall()
            for r in rows or []:
                sid = str(r[0] or "").strip()
                if not sid:
                    continue
                tkey = str(r[2] or "")
                try:
                    vol_t = float(r[3]) if r[3] is not None else None
                except (TypeError, ValueError):
                    vol_t = None
                try:
                    close_t = float(r[4]) if r[4] is not None else None
                except (TypeError, ValueError):
                    close_t = None
                if close_t is None or vol_t is None:
                    c2, v2 = _quote_close_vol(db_path, sid, day)
                    if close_t is None:
                        close_t = c2
                    if vol_t is None:
                        vol_t = v2
                if not lots_extreme_ok_for_display(
                    track_key=tkey, close=close_t, volume=vol_t
                ):
                    continue
                sids.add(sid)
                t = str(r[1] or "")
                if t and t not in tags:
                    tags.append(t)
        except sqlite3.Error:
            pass
    finally:
        conn.close()
    return len(sids), tags[:6]


def _read_calm(db_path: str, as_of: str) -> Tuple[bool, str]:
    day = _ymd(as_of)
    store = _store(db_path)
    conn = _conn_ro(store)
    if conn is None:
        return False, ""
    try:
        row = conn.execute(
            """
            SELECT note FROM foreign_sell_calm_tape
            WHERE kind=? AND as_of=? AND tag=?
            LIMIT 1
            """,
            ("foreign_sell_calm_env", day, "calm_fear_fade"),
        ).fetchone()
        if row:
            return True, str(row[0] or "")
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return False, ""


def load_env_status(db_path: str, as_of: str) -> EnvObserveStatus:
    """組大盤級環境觀察（測試版可顯示）。"""
    day = _ymd(as_of)
    fear = _read_fear_tape(db_path, day)
    n_c, tags = _count_confirm(db_path, day)
    calm_lit, calm_note = _read_calm(db_path, day)
    return EnvObserveStatus(
        as_of=day,
        fear_lit=bool(fear.get("lit")),
        fear_evaluable=bool(fear.get("evaluable")),
        fear_votes=int(fear.get("votes") or 0),
        fear_lead_sync=str(fear.get("lead_sync") or ""),
        fear_skip=str(fear.get("skip_reason") or ""),
        confirm_n=int(n_c),
        confirm_tags=list(tags),
        calm_lit=bool(calm_lit),
        calm_note=str(calm_note or ""),
        buy_signal=False,
    )


def _fear_plain(st: EnvObserveStatus) -> str:
    if not st.fear_evaluable:
        if "美股關鍵欄全空" in (st.fear_skip or ""):
            return "開盤前恐懼：美股沒資料，今天先不算"
        return "開盤前恐懼：資料未齊，今天先不算"
    if st.fear_lit:
        return "開盤前恐懼偏高"
    return "開盤前恐懼沒亮"


def _confirm_plain(st: EnvObserveStatus) -> str:
    if st.confirm_n <= 0:
        return "外資大賣升級：今天沒有"
    return f"外資大賣升級：約{st.confirm_n}檔"


def _calm_plain(st: EnvObserveStatus) -> str:
    if st.calm_lit:
        return "恐懼消退：有亮，仍不是買"
    return "恐懼消退：今天沒有"


def load_morning_status(
    db_path: str,
    as_of: str,
    *,
    fear_as_of: str = "",
) -> EnvObserveStatus:
    """早報用：恐懼看盤前日本（fear_as_of／今日）；籌碼確認／Calm 看 as_of（上一完整收）。"""
    chip = load_env_status(db_path, as_of)
    fear_day = _ymd(fear_as_of or as_of)
    if fear_day and fear_day != chip.as_of:
        fear = _read_fear_tape(db_path, fear_day)
        chip.fear_lit = bool(fear.get("lit"))
        chip.fear_evaluable = bool(fear.get("evaluable"))
        chip.fear_votes = int(fear.get("votes") or 0)
        chip.fear_lead_sync = str(fear.get("lead_sync") or "")
        chip.fear_skip = str(fear.get("skip_reason") or "")
        # as_of 仍標籌碼基準；恐懼日寫進 skip 旁註不另開欄
    return chip


def morning_observe_line_html(
    db_path: str,
    as_of: str,
    *,
    fear_as_of: str = "",
) -> str:
    """早報一句：有亮才寫主句；不亮寫「今無」短句。永遠標測試／非買。"""
    from tg_layout import html_escape

    st = load_morning_status(db_path, as_of, fear_as_of=fear_as_of)
    bits: List[str] = []
    if st.fear_lit:
        bits.append("恐懼預警")
    if st.confirm_n > 0:
        bits.append(f"外資升級約{st.confirm_n}檔")
    if st.calm_lit:
        bits.append("反向環境")
    tag = html_escape(DISPLAY_TAG)
    if not bits:
        return f"<b>{tag}</b>　今無"
    body = "／".join(bits)
    return f"<b>{tag}</b>　{html_escape(body)}　非買訊"


def market_env_section_lines(db_path: str, as_of: str) -> List[str]:
    """台股大盤頁頂部「環境觀察」一小段（HTML 行）。

    標題一行＋三句白話（恐懼／外資大賣升級／恐懼消退）＋非買訊一句（只留一次）。
    不印亮／熄／未齊狀態詞。
    """
    from tg_layout import html_escape

    st = load_env_status(db_path, as_of)
    return [
        f"<b>環境觀察｜{html_escape(DISPLAY_TAG)}</b>",
        html_escape(_fear_plain(st)),
        html_escape(_confirm_plain(st)),
        html_escape(_calm_plain(st)),
        html_escape("不是買訊；進場仍只認藍▲紅框"),
    ]


def _recent_as_ofs(conn: sqlite3.Connection, table: str, kind: str, limit: int) -> List[str]:
    try:
        rows = conn.execute(
            f"""
            SELECT DISTINCT as_of FROM {table}
            WHERE kind=? ORDER BY as_of DESC LIMIT ?
            """,
            (kind, int(limit)),
        ).fetchall()
        return [str(r[0]) for r in rows or [] if r and r[0]]
    except sqlite3.Error:
        return []


def _parse_lots_thr(track_key: str) -> Optional[float]:
    """lots_th5000 → 5000；非張數軌回 None。"""
    key = str(track_key or "").strip()
    if not key.startswith("lots_th"):
        return None
    try:
        return float(key.replace("lots_th", "", 1))
    except ValueError:
        return None


def _quote_close_vol(db_path: str, sid: str, day: str) -> Tuple[Optional[float], Optional[float]]:
    """讀該日官方收／量（張）。缺回 (None, None)。"""
    day = _ymd(day)
    if not day or not db_path or not os.path.isfile(db_path):
        return None, None
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            row = conn.execute(
                """
                SELECT close, volume FROM daily_quotes
                WHERE stock_id=? AND REPLACE(CAST(date AS TEXT),'-','')=?
                LIMIT 1
                """,
                (str(sid), day),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None, None
    if not row:
        return None, None
    try:
        close = float(row[0]) if row[0] is not None else None
    except (TypeError, ValueError):
        close = None
    try:
        vol = float(row[1]) if row[1] is not None else None
    except (TypeError, ValueError):
        vol = None
    return close, vol


def lots_extreme_ok_for_display(
    *,
    track_key: str,
    close: Optional[float],
    volume: Optional[float],
) -> bool:
    """絕對張數極端軌能不能上橘六角。

    千金（收≥1000）或當日量達不到該張數門檻 → 不准（高價股平常量常不到 5000 張）。
    超比／分位軌（非 lots_th*）→ 准。
    """
    thr = _parse_lots_thr(track_key)
    if thr is None:
        return True  # share／streak／cum10 等相對軌
    if close is not None and close >= float(QIANJIN_PX):
        return False
    if volume is None or volume < float(thr) * float(LOTS_TRACK_MIN_VOL_MULT):
        return False
    return True


def stock_observe_hit(
    db_path: str,
    sid: str,
    *,
    as_of: str = "",
    lookback: int = STOCK_LOOKBACK_DAYS,
) -> Optional[StockObserveHit]:
    """個股近窗有升級／極端確認 → 查股可畫觀察標。永遠不是買訊。

    顯示優先：超比／分位升級（escalate）→ 相對極端軌 → 張數極端（僅非千金且量夠）。
    千金不准靠 lots_th5000 亮燈。
    """
    sid = str(sid or "").strip()
    if not sid:
        return None
    store = _store(db_path)
    conn = _conn_ro(store)
    if conn is None:
        return None
    try:
        days: List[str] = []
        if as_of:
            days = [_ymd(as_of)]
        esc_days = _recent_as_ofs(
            conn, "foreign_sell_escalate_tape", "foreign_sell_escalate", lookback
        )
        ext_days = _recent_as_ofs(
            conn, "foreign_sell_extreme_tape", "foreign_sell_extreme_dplus", lookback
        )
        pool = sorted(set(days + esc_days + ext_days), reverse=True)[: max(1, lookback)]
        if not pool:
            return None
        placeholders = ",".join("?" * len(pool))

        # 1) 優先：超比／分位升級（對高價／低價都公平）
        try:
            row = conn.execute(
                f"""
                SELECT as_of, tag FROM foreign_sell_escalate_tape
                WHERE kind=? AND sid=? AND as_of IN ({placeholders})
                ORDER BY as_of DESC LIMIT 1
                """,
                ("foreign_sell_escalate", sid, *pool),
            ).fetchone()
            if row:
                return StockObserveHit(
                    sid=sid,
                    as_of=str(row[0]),
                    source="escalate",
                    tag=str(row[1] or ""),
                    label=OBSERVE_LABEL,
                    buy_signal=False,
                )
        except sqlite3.Error:
            pass

        # 2) 極端：先相對軌（share／streak／cum10），再張數軌（過濾千金／量不足）
        try:
            rows = conn.execute(
                f"""
                SELECT as_of, tag, track_key, volume, close
                FROM foreign_sell_extreme_tape
                WHERE kind=? AND sid=? AND as_of IN ({placeholders})
                ORDER BY as_of DESC
                """,
                ("foreign_sell_extreme_dplus", sid, *pool),
            ).fetchall()
        except sqlite3.Error:
            rows = []
        for r in rows or []:
            day_r = str(r[0] or "")
            tag = str(r[1] or "")
            tkey = str(r[2] or "")
            try:
                vol_t = float(r[3]) if r[3] is not None else None
            except (TypeError, ValueError):
                vol_t = None
            try:
                close_t = float(r[4]) if len(r) > 4 and r[4] is not None else None
            except (TypeError, ValueError):
                close_t = None
            # tape 缺 close 時回行情庫補（千金判定）
            if close_t is None or vol_t is None:
                c2, v2 = _quote_close_vol(db_path, sid, day_r)
                if close_t is None:
                    close_t = c2
                if vol_t is None:
                    vol_t = v2
            if not lots_extreme_ok_for_display(
                track_key=tkey, close=close_t, volume=vol_t
            ):
                continue
            return StockObserveHit(
                sid=sid,
                as_of=day_r,
                source="extreme",
                tag=tag,
                label=OBSERVE_LABEL,
                buy_signal=False,
            )

        # 3) 買升級：回測未過關；測試版預設不亮（DISPLAY_INCLUDE_BUY_ESCALATE）
        if DISPLAY_INCLUDE_BUY_ESCALATE:
            try:
                row = conn.execute(
                    f"""
                    SELECT as_of, tag FROM foreign_sell_calm_tape
                    WHERE kind=? AND sid=? AND tag=? AND as_of IN ({placeholders})
                    ORDER BY as_of DESC LIMIT 1
                    """,
                    ("foreign_sell_calm_env", sid, "buy_escalate_A", *pool),
                ).fetchone()
                if row:
                    return StockObserveHit(
                        sid=sid,
                        as_of=str(row[0]),
                        source="calm_buy",
                        tag=str(row[1] or ""),
                        label=OBSERVE_LABEL,
                        buy_signal=False,
                    )
            except sqlite3.Error:
                pass
    finally:
        conn.close()
    return None


def stock_observe_bar_index(
    dates: Sequence[Any], hit: Optional[StockObserveHit]
) -> List[int]:
    """把命中 as_of 對到圖上柱 index；對不到就畫最新柱。"""
    if not hit or not dates:
        return []
    target = _ymd(hit.as_of)
    for i, d in enumerate(dates):
        if _ymd(d) == target:
            return [int(i)]
    return [len(dates) - 1]


def is_buy_entry_path(fn_name: str) -> bool:
    """測試用：觀察標 paint 路徑名不准混進買訊函式名。"""
    buy_names = {
        "paint_buy_entry_indices",
        "paint_leave_zero_indices",
        "paint_ma60_lower_indices",
        "_nav_trade_marks",
        "_paint_nav_buy_arrows",
    }
    return str(fn_name or "") in buy_names


def display_mode_banner() -> str:
    return f"{DISPLAY_TAG}｜mode={DISPLAY_MODE}｜buy_signal={int(BUY_SIGNAL)}"
