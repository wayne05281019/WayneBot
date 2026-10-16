# -*- coding: utf-8 -*-
"""外資／恐懼預警測試版顯示：早報／大盤／查股標；永遠不是買訊。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

from dongzhu_tape import tape_store_path
from foreign_sell_display import (
    BUY_SIGNAL,
    DISPLAY_ESCALATE_THETA,
    DISPLAY_INCLUDE_BUY_ESCALATE,
    DISPLAY_MODE,
    DISPLAY_SELL_SHARE_THR,
    DISPLAY_TAG,
    OBSERVE_LABEL,
    OBSERVE_MARKER,
    is_buy_entry_path,
    load_env_status,
    market_env_section_lines,
    morning_observe_line_html,
    stock_observe_bar_index,
    stock_observe_hit,
)
from foreign_sell_escalate_verify import ensure_tables as ensure_esc
from foreign_sell_extreme_verify import ensure_tables as ensure_ext
from foreign_sell_calm_verify import ensure_tables as ensure_calm
from fear_preopen_verify import ensure_tables as ensure_fear


def _mk_db() -> str:
    td = tempfile.mkdtemp()
    db = os.path.join(td, "wayne_market.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS index_daily(
            date TEXT NOT NULL, symbol TEXT NOT NULL DEFAULT 'TWII',
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            pct_change REAL, updated_at TEXT DEFAULT '',
            PRIMARY KEY(date, symbol)
        )
        """
    )
    conn.commit()
    conn.close()
    return db


def test_display_hard_locks():
    assert BUY_SIGNAL is False
    assert DISPLAY_MODE == "test"
    assert "測試" in DISPLAY_TAG
    assert "觀察" in DISPLAY_TAG
    assert OBSERVE_MARKER == "h"  # 異於止穩 D、買訊三角
    assert OBSERVE_LABEL == "觀察"
    assert DISPLAY_SELL_SHARE_THR == 0.20
    assert DISPLAY_ESCALATE_THETA == 90.0
    assert DISPLAY_INCLUDE_BUY_ESCALATE is False
    assert not is_buy_entry_path("_paint_foreign_sell_observe_marks")
    assert is_buy_entry_path("_paint_nav_buy_arrows")


def test_share_extreme_lights_qianjin():
    """超比 20% 軌：千金也可亮（不靠 5000 張）。"""
    db = _mk_db()
    ensure_ext(db)
    store = tape_store_path(db)
    conn = sqlite3.connect(store)
    conn.execute(
        """
        INSERT OR REPLACE INTO foreign_sell_extreme_tape(
            kind, as_of, track_key, sid, name, tag, volume, close
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            "foreign_sell_extreme_dplus",
            "20261013",
            "share_th0.2",
            "2330",
            "台積電",
            "anchor",
            2500.0,
            1150.0,
        ),
    )
    conn.commit()
    conn.close()
    hit = stock_observe_hit(db, "2330")
    assert hit is not None
    assert hit.source == "extreme"


def test_morning_line_none_and_lit():
    db = _mk_db()
    ensure_fear(db)
    store = tape_store_path(db)
    # 無 tape → 今無（evaluate 也可能因缺美股不亮）
    line = morning_observe_line_html(db, "20261014", fear_as_of="20261015")
    assert DISPLAY_TAG in line.replace("<b>", "").replace("</b>", "") or "觀察" in line
    assert "非買訊" in line or "今無" in line
    assert "買進" not in line and "可買" not in line

    conn = sqlite3.connect(store)
    conn.execute(
        """
        INSERT OR REPLACE INTO fear_preopen_tape(
            kind, as_of, params_key, lit, evaluable, votes, lead_sync,
            gap_open_pct, dump_day, twii_ret_d, vote_json, skip_reason
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "fear_preopen_warn",
            "20261015",
            "test",
            1,
            1,
            2,
            "lead",
            None,
            0,
            None,
            "[]",
            "",
        ),
    )
    conn.commit()
    conn.close()
    lit = morning_observe_line_html(db, "20261014", fear_as_of="20261015")
    assert "恐懼" in lit
    assert "非買訊" in lit
    assert "買進" not in lit


def test_market_env_section():
    db = _mk_db()
    ensure_fear(db)
    store = tape_store_path(db)
    conn = sqlite3.connect(store)
    conn.execute(
        """
        INSERT OR REPLACE INTO fear_preopen_tape(
            kind, as_of, params_key, lit, evaluable, votes, lead_sync,
            gap_open_pct, dump_day, twii_ret_d, vote_json, skip_reason
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "fear_preopen_warn",
            "20261014",
            "test",
            1,
            1,
            3,
            "lead",
            None,
            0,
            None,
            "[]",
            "",
        ),
    )
    conn.commit()
    conn.close()
    lines = market_env_section_lines(db, "20261014")
    blob = "\n".join(lines)
    assert "環境觀察｜" in blob or "環境觀察" in blob
    assert DISPLAY_TAG in blob.replace("<b>", "").replace("</b>", "")
    # 三句白話各一行；大盤頁不再印亮／熄／未齊
    assert "開盤前恐懼偏高" in lines
    assert "外資大賣升級：今天沒有" in lines
    assert "恐懼消退：今天沒有" in lines
    for banned in ("恐懼未齊", "恐懼亮", "恐懼熄", "確認亮", "確認熄", "冷靜亮", "冷靜熄"):
        assert banned not in blob
    assert "Fear" not in blob
    assert "Confirm" not in blob
    assert "Calm" not in blob
    assert "測試" in blob
    assert "不是買訊；進場仍只認藍▲紅框" not in blob
    assert "藍▲紅框" not in blob
    # 標題收成一行（有｜）
    assert any("環境觀察｜" in ln for ln in lines)


def _put_fear(store: str, *, lit: int, evaluable: int, skip: str) -> None:
    conn = sqlite3.connect(store)
    conn.execute("DELETE FROM fear_preopen_tape")
    conn.execute(
        """
        INSERT OR REPLACE INTO fear_preopen_tape(
            kind, as_of, params_key, lit, evaluable, votes, lead_sync,
            gap_open_pct, dump_day, twii_ret_d, vote_json, skip_reason
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "fear_preopen_warn",
            "20261014",
            "test",
            lit,
            evaluable,
            0,
            "",
            None,
            0,
            None,
            "[]",
            skip,
        ),
    )
    conn.commit()
    conn.close()


def test_market_env_plain_branches():
    """三句對旗標：恐懼 skip／沒亮、外資約 N 檔、恐懼消退有亮。"""
    db = _mk_db()
    ensure_fear(db)
    ensure_esc(db)
    ensure_calm(db)
    store = tape_store_path(db)
    _put_fear(store, lit=0, evaluable=0, skip="美股關鍵欄全空")
    lines = market_env_section_lines(db, "20261014")
    assert "開盤前恐懼：美股沒資料，今天先不算" in lines
    assert "不是買訊；進場仍只認藍▲紅框" not in lines

    _put_fear(store, lit=0, evaluable=0, skip="台股休市")
    lines = market_env_section_lines(db, "20261014")
    assert "開盤前恐懼：資料未齊，今天先不算" in lines

    _put_fear(store, lit=0, evaluable=1, skip="")
    lines = market_env_section_lines(db, "20261014")
    assert "開盤前恐懼沒亮" in lines

    conn = sqlite3.connect(store)
    for sid in ("2383", "2330"):
        conn.execute(
            """
            INSERT OR REPLACE INTO foreign_sell_escalate_tape(
                kind, as_of, params_key, sid, name, tag
            ) VALUES (?,?,?,?,?,?)
            """,
            ("foreign_sell_escalate", "20261014", "p", sid, sid, "escalate_pre_A"),
        )
    conn.execute(
        """
        INSERT OR REPLACE INTO foreign_sell_calm_tape(
            kind, as_of, params_key, sid, tag, note
        ) VALUES (?,?,?,?,?,?)
        """,
        ("foreign_sell_calm_env", "20261014", "", "", "calm_fear_fade", "fade"),
    )
    conn.commit()
    conn.close()
    lines = market_env_section_lines(db, "20261014")
    blob = "\n".join(lines)
    assert "外資大賣升級：約2檔" in lines
    assert "恐懼消退：有亮，仍不是買" in lines
    assert "不是買訊；進場仍只認藍▲紅框" not in blob
    for banned in ("恐懼未齊", "確認熄", "冷靜熄", "恐懼亮", "恐懼熄"):
        assert banned not in blob


def test_stock_observe_hit_escalate():
    db = _mk_db()
    ensure_esc(db)
    store = tape_store_path(db)
    conn = sqlite3.connect(store)
    conn.execute(
        """
        INSERT OR REPLACE INTO foreign_sell_escalate_tape(
            kind, as_of, params_key, sid, name, tag, lead_sync,
            sell_share, pctl, foreign_net, volume
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "foreign_sell_escalate",
            "20261013",
            "p",
            "2383",
            "台光電",
            "escalate_pre_A",
            "lead",
            0.2,
            90.0,
            -5000.0,
            20000.0,
        ),
    )
    conn.commit()
    conn.close()
    hit = stock_observe_hit(db, "2383")
    assert hit is not None
    assert hit.sid == "2383"
    assert hit.buy_signal is False
    assert hit.source == "escalate"
    idxs = stock_observe_bar_index(
        ["20261010", "20261013", "20261014"], hit
    )
    assert idxs == [1]


def test_stock_observe_prefers_escalate_over_lots():
    """顯示優先超比／分位升級，不先吃 5000 張極端。"""
    db = _mk_db()
    ensure_esc(db)
    ensure_ext(db)
    store = tape_store_path(db)
    conn = sqlite3.connect(store)
    conn.execute(
        """
        INSERT OR REPLACE INTO foreign_sell_escalate_tape(
            kind, as_of, params_key, sid, name, tag
        ) VALUES (?,?,?,?,?,?)
        """,
        ("foreign_sell_escalate", "20261012", "p", "2330", "台積電", "escalate_pre_A"),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO foreign_sell_extreme_tape(
            kind, as_of, track_key, sid, name, tag, volume, close
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            "foreign_sell_extreme_dplus",
            "20261013",
            "lots_th5000",
            "2330",
            "台積電",
            "anchor",
            3000.0,
            1200.0,
        ),
    )
    conn.commit()
    conn.close()
    hit = stock_observe_hit(db, "2330")
    assert hit is not None
    assert hit.source == "escalate"
    assert hit.buy_signal is False


def test_qianjin_skips_lots_th5000():
    """千金平常量常不到 5000 張 → lots_th5000 不准亮橘六角。"""
    from foreign_sell_display import lots_extreme_ok_for_display

    assert lots_extreme_ok_for_display(
        track_key="lots_th5000", close=1200.0, volume=3000.0
    ) is False
    assert lots_extreme_ok_for_display(
        track_key="lots_th5000", close=800.0, volume=3000.0
    ) is False  # 量也不足
    assert lots_extreme_ok_for_display(
        track_key="lots_th5000", close=800.0, volume=8000.0
    ) is True
    assert lots_extreme_ok_for_display(
        track_key="share_th0.15", close=1200.0, volume=2000.0
    ) is True

    db = _mk_db()
    ensure_ext(db)
    store = tape_store_path(db)
    conn = sqlite3.connect(store)
    conn.execute(
        """
        INSERT OR REPLACE INTO foreign_sell_extreme_tape(
            kind, as_of, track_key, sid, name, tag, volume, close
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            "foreign_sell_extreme_dplus",
            "20261013",
            "lots_th5000",
            "2330",
            "台積電",
            "anchor",
            2500.0,
            1150.0,
        ),
    )
    conn.commit()
    conn.close()
    assert stock_observe_hit(db, "2330") is None


def test_liquid_lots_extreme_can_show():
    """非千金且當日量≥門檻 → lots 極端可顯示。"""
    db = _mk_db()
    ensure_ext(db)
    store = tape_store_path(db)
    conn = sqlite3.connect(store)
    conn.execute(
        """
        INSERT OR REPLACE INTO foreign_sell_extreme_tape(
            kind, as_of, track_key, sid, name, tag, volume, close
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            "foreign_sell_extreme_dplus",
            "20261013",
            "lots_th5000",
            "2603",
            "長榮",
            "anchor",
            12000.0,
            180.0,
        ),
    )
    conn.commit()
    conn.close()
    hit = stock_observe_hit(db, "2603")
    assert hit is not None
    assert hit.source == "extreme"


def test_load_env_status_confirm_count():
    db = _mk_db()
    ensure_esc(db)
    store = tape_store_path(db)
    conn = sqlite3.connect(store)
    for sid in ("2383", "2330", "2454"):
        conn.execute(
            """
            INSERT OR REPLACE INTO foreign_sell_escalate_tape(
                kind, as_of, params_key, sid, name, tag
            ) VALUES (?,?,?,?,?,?)
            """,
            ("foreign_sell_escalate", "20261014", "p", sid, sid, "escalate_pre_A"),
        )
    conn.commit()
    conn.close()
    st = load_env_status(db, "20261014")
    assert st.confirm_n == 3
    assert st.buy_signal is False
    line = morning_observe_line_html(db, "20261014")
    assert "外資升級" in line
    assert "非買訊" in line


def test_foreign_hex_stacks_below_same_bar_arrow():
    """同柱上箭尾之下才放六角，中心不准落在箭身上。"""
    from wayne_navigator import _foreign_observe_anchor

    span = 1000.0
    gap = span * 0.034
    arrow_h = span * 0.048
    low = 4250.0
    tail = low - gap - arrow_h
    y = _foreign_observe_anchor(low, arrow_gap=gap, span=span, blocked_y=tail)
    mark_r = span * 0.028
    assert y <= tail - mark_r - span * 0.05
    plain = _foreign_observe_anchor(low, arrow_gap=gap, span=span, blocked_y=None)
    assert abs(plain - (low - gap * 2.15)) < 1e-6
    assert y < plain


def test_structure_hex_shares_occupy_with_stabilize():
    """結構圖與大量區／導航同一套：同柱六角排到止穩下方。不分代號。"""
    import inspect

    from biaoke_chart import _place_right_notes, render_biaoke_structure_png

    src = inspect.getsource(render_biaoke_structure_png)
    assert "mark_occupy" in src
    assert src.count("occupy=mark_occupy") >= 2
    assert 'sid == "2454"' not in src
    assert "_inset_today_close_inside" in inspect.getsource(_place_right_notes)
