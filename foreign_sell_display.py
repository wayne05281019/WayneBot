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

# 測試版上話筒；正式過閘文案之後再收
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
        if not self.fear_evaluable:
            return "n/a"
        return "Fear" if self.fear_lit else "Off"

    def confirm_state(self) -> str:
        if self.confirm_n > 0:
            return "Confirm"
        return "Off"

    def calm_state(self) -> str:
        return "Calm" if self.calm_lit else "Off"


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
        # extreme：當日極端錨
        try:
            rows = conn.execute(
                """
                SELECT DISTINCT sid, tag FROM foreign_sell_extreme_tape
                WHERE kind=? AND as_of=? AND sid!='' AND sid NOT LIKE 'TWII%'
                """,
                ("foreign_sell_extreme_dplus", day),
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
        skip = st.fear_skip or "資料未齊"
        return f"恐懼複合暫無法評估（{skip}）"
    if st.fear_lit:
        sync = "同步" if st.fear_lead_sync == "sync" else "領先"
        return f"開盤前恐懼偏高（{st.fear_votes}票・{sync}）；只觀察，不是買訊"
    return "開盤前恐懼複合未亮"


def _confirm_plain(st: EnvObserveStatus) -> str:
    if st.confirm_n <= 0:
        return "外資升級／極端確認今無"
    return f"外資升級／確認近窗約{st.confirm_n}檔；只觀察，不是買訊"


def _calm_plain(st: EnvObserveStatus) -> str:
    if st.calm_lit:
        return "恐懼消退／反向環境亮（佈局環境觀察，不是買訊）"
    return "反向 Calm 未亮"


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
    """台股大盤頁頂部「環境觀察」一小段（HTML 行）。"""
    from tg_layout import html_escape

    st = load_env_status(db_path, as_of)
    # 白話一句：優先恐懼→確認→反向→全無
    if st.fear_lit:
        plain = _fear_plain(st)
    elif st.confirm_n > 0:
        plain = _confirm_plain(st)
    elif st.calm_lit:
        plain = _calm_plain(st)
    elif not st.fear_evaluable and st.fear_skip:
        plain = _fear_plain(st)
    else:
        plain = "今日環境無預警亮燈；進場仍只認藍▲紅框"

    fear_s = st.fear_state()
    conf_s = st.confirm_state()
    calm_s = st.calm_state()
    state_line = (
        f"Fear　{html_escape(fear_s)}　"
        f"Confirm　{html_escape(conf_s)}　"
        f"Calm　{html_escape(calm_s)}"
    )
    return [
        f"<b>環境觀察</b>　{html_escape(DISPLAY_TAG)}",
        state_line,
        html_escape(plain),
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


def stock_observe_hit(
    db_path: str,
    sid: str,
    *,
    as_of: str = "",
    lookback: int = STOCK_LOOKBACK_DAYS,
) -> Optional[StockObserveHit]:
    """個股近窗有升級／極端確認 → 查股可畫觀察標。永遠不是買訊。"""
    sid = str(sid or "").strip()
    if not sid or sid.startswith("00") and len(sid) == 4:
        # ETF 等仍可標；不過濾代號格式，只擋空
        pass
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
        # 近窗：escalate／extreme 各自最近 as_of
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
        # 優先極端確認，其次升級
        try:
            row = conn.execute(
                f"""
                SELECT as_of, tag FROM foreign_sell_extreme_tape
                WHERE kind=? AND sid=? AND as_of IN ({placeholders})
                ORDER BY as_of DESC LIMIT 1
                """,
                ("foreign_sell_extreme_dplus", sid, *pool),
            ).fetchone()
            if row:
                return StockObserveHit(
                    sid=sid,
                    as_of=str(row[0]),
                    source="extreme",
                    tag=str(row[1] or ""),
                    label=OBSERVE_LABEL,
                    buy_signal=False,
                )
        except sqlite3.Error:
            pass
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
        # 小買升級（反向個股）也可標觀察——仍非買
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
