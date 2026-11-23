# -*- coding: utf-8 -*-
"""DC／我估／飆大 三鍋分標不變式（DC-BOUND／MISSION_LOCK B6／B9）。"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mine_wave_rules import (
    check_w1_w4_overlap,
    detect_extension_1618,
    fib_retracement_levels,
    leading_diagonal_flags,
)
from wave_pot_boundary import (
    BIAOKE_FIB_REBOUND_RATIOS,
    CROSS_COMPARE_JSON,
    CROSS_COMPARE_MD,
    MINE_STRUCTURE_LEAK_TOKENS,
    OBSERVE_MANUAL_READ_ONLY_PREFIX,
    POT_BIAOKE,
    POT_DC,
    POT_MINE,
    assert_label_pot,
    cross_write_forbidden,
    forbid_auto_leading_diagonal_from_impulse_fail,
    fib_ratio_pots,
    label_looks_mixed,
    load_cross_compare,
    mine_phone_label,
    scan_text_for_pot_leaks,
    stamp_biaoke,
    stamp_dc_peer,
    stamp_mine,
    validate_cross_compare_rows,
)

ROOT = Path(__file__).resolve().parents[1]


def test_cross_compare_files_exist_and_three_columns():
    assert (ROOT / CROSS_COMPARE_JSON).is_file()
    assert (ROOT / CROSS_COMPARE_MD).is_file()
    data = load_cross_compare(str(ROOT / CROSS_COMPARE_JSON))
    rows = data["rows"]
    errs = validate_cross_compare_rows(rows)
    assert not errs, errs
    # md 必須有三欄表頭，不准「合鍋」欄
    md = (ROOT / CROSS_COMPARE_MD).read_text(encoding="utf-8")
    assert "他說" in md and "DC" in md and "我估" in md
    assert "合鍋" not in md and "三合一" not in md
    assert "observe_manual" in md


def test_pots_never_merge_keys():
    assert POT_BIAOKE != POT_DC != POT_MINE
    assert len({POT_BIAOKE, POT_DC, POT_MINE}) == 3


def test_stamp_and_phone_labels():
    m = stamp_mine({"pass": True})
    assert m["source"] == POT_MINE and m["not_biaoke"] is True
    d = stamp_dc_peer({"bubble": "x"})
    assert d["pot"] == POT_DC and d["phone_forbid_as_his"] is True
    b = stamp_biaoke({"level": 1})
    assert b["pot"] == POT_BIAOKE
    assert mine_phone_label("擴延1618").startswith("我估｜")
    assert_label_pot("我估｜前端傾斜", POT_MINE)
    with pytest.raises(ValueError):
        assert_label_pot("他說｜擴延1618", POT_MINE)
    with pytest.raises(ValueError):
        assert_label_pot("我估｜擴延1618", POT_BIAOKE)


def test_mixed_label_detector():
    assert label_looks_mixed("他說｜擴延1618") == "his_with_mine_structure"
    assert label_looks_mixed("我估｜近窗官方低") is None
    assert "dc_labeled_as_his" in scan_text_for_pot_leaks("他說DC同學句", claimed_pot=POT_DC)


def test_biaoke_fib_table_not_equal_mine_extension_gate():
    """飆大 Fib 反彈壓 ≠ mine 擴延閘；同數字不准混標。"""
    assert BIAOKE_FIB_REBOUND_RATIOS == (0.382, 0.618, 0.75)
    ext = detect_extension_1618({"1": 1000, "3": 1618, "5": 800})
    assert ext["source"] == POT_MINE
    assert ext.get("≠biaoke_fib_rebound_table") is True
    assert ext["phone_label"] == "我估｜擴延1618"
    fib = fib_retracement_levels(1000, 0, ratios=BIAOKE_FIB_REBOUND_RATIOS)
    assert fib["source"] == POT_MINE
    assert fib.get("≠biaoke_fib_rebound_table") is True
    pots = fib_ratio_pots()
    for key, cols in pots.items():
        assert set(cols) == {POT_BIAOKE, POT_DC, POT_MINE}
        vals = list(cols.values())
        assert len(set(vals)) == 3, key


def test_no_auto_promote_leading_diagonal_from_overlap_only():
    """標準 impulse 1–4 失敗不准自動前端傾斜。"""
    only = forbid_auto_leading_diagonal_from_impulse_fail(
        w1_w4_overlap=True, position_ok=None, structure_53535=None
    )
    assert only["candidate"] is True
    assert only["confirmed"] is False
    assert only["auto_promote_forbidden"] is True
    full = forbid_auto_leading_diagonal_from_impulse_fail(
        w1_w4_overlap=True, position_ok=True, structure_53535=True
    )
    assert full["confirmed"] is True
    ov = check_w1_w4_overlap(100, 200, 250, 150)
    assert ov["source"] == POT_MINE
    flags = leading_diagonal_flags(w1_w4_overlap=True)
    assert flags["confirmed"] is False
    assert flags["auto_promote_forbidden"] is True


def test_cross_write_forbidden_matrix():
    assert cross_write_forbidden(POT_MINE, POT_BIAOKE) is True
    assert cross_write_forbidden(POT_DC, POT_BIAOKE) is True
    assert cross_write_forbidden(POT_BIAOKE, POT_DC) is True  # observe／老師→DC 不准互寫
    assert cross_write_forbidden(POT_BIAOKE, POT_MINE) is False  # 可讀
    assert cross_write_forbidden(POT_DC, POT_MINE) is False


def test_dc_scenario_never_writes_biaoke_posts():
    src = (ROOT / "dc_scenario_silent_verify.py").read_text(encoding="utf-8")
    assert "INSERT INTO biaoke_posts" not in src
    assert "ingest_public_posts" not in src or "不准呼叫 ingest_public_posts" in src
    assert "run_absorb" not in src or "不准呼叫" in src
    # 只准寫 dc_sf_*
    assert "INSERT INTO dc_sf_" in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "INSERT INTO biaoke" in node.value:
                pytest.fail("dc_scenario SQL 寫入 biaoke 表")


def test_observe_manual_not_imported_into_dc_sources():
    """observe_manual 只讀；DC sources／digest 不准把飆大手冊當同學文。"""
    dc_dir = ROOT / "docs" / "expert_notes" / "dc_wave"
    for p in dc_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() in {".jpg", ".png", ".gif", ".webp"}:
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        # 允許邊界文件提到路徑政策；不准把手冊正文拷進來當 DC 來源
        if "observe_manual" in text and p.name not in {
            "cross_pot_compare.md",
            "cross_pot_compare.json",
            "vs-biaoke-boundary.md",
            "MISSION_LOCK_PARALLEL_20261123.md",
        }:
            assert "只讀" in text or "不准" in text
    # sources 目錄不准出現 observe_manual 檔名
    sources = dc_dir / "sources"
    if sources.is_dir():
        for p in sources.iterdir():
            assert "observe_manual" not in p.name


def test_phone_biaoke_paths_no_mine_structure_leak():
    """話筒／他說路徑不得把 leading_diagonal／擴延1618 當他說。"""
    # thesis 抽出與 digest「他說：」組句附近
    targets = [
        ROOT / "biaoke_digest.py",
        ROOT / "biaoke_alert.py",
    ]
    for path in targets:
        src = path.read_text(encoding="utf-8")
        # 允許註解／禁止句提到這些詞；不准組出「他說：…擴延1618」這類模板
        assert 'f"他說：{how}"' in src or "他說：" in src or path.name == "biaoke_alert.py"
        for tok in ("我估｜擴延1618", "我估｜前端傾斜", "leading_diagonal"):
            # 若出現，必須在禁止／分鍋語境
            if tok in src:
                idx = src.find(tok)
                window = src[max(0, idx - 80) : idx + 80]
                assert any(
                    k in window
                    for k in ("不准", "禁止", "≠", "分鍋", "我估", "mine", "POT")
                ), (path.name, tok, window)


def test_self_pred_label_rejects_his_basis():
    from biaoke_level_learn import _self_pred_label

    lab = _self_pred_label(40000.0, "他說擴延1618")
    assert lab.startswith("我估")
    assert "他說" not in lab
    assert_label_pot(lab, POT_MINE)


def test_self_pred_levels_keeps_mine_wave_out_of_pred_levels():
    from biaoke_level_learn import _build_self_pred_levels

    pack = {"pred_levels": {"tw": [{"level": 45546.0, "label": "錨"}]}}
    highs = [100.0 + i for i in range(20)]
    lows = [90.0 + i for i in range(20)]
    vols = [1.0] * 20
    bars = [{"date": f"2026-11-{i+1:02d}"} for i in range(20)]
    out = _build_self_pred_levels(
        pack,
        y_now=110.0,
        y5=120.0,
        y_alow=80.0,
        y_bhi=130.0,
        highs=highs,
        lows=lows,
        vols=vols,
        bars=bars,
    )
    assert out.get("source") == POT_MINE or out.get("pot") == POT_MINE
    assert "pred_levels" not in out
    for row in out.get("mine") or []:
        assert str(row.get("label") or "").startswith("我估")
        assert row.get("source") == "mine"
    for row in out.get("his_aux") or []:
        assert str(row.get("label") or "").startswith("他說")
        assert row.get("source") == "his"
    mw = out.get("mine_wave") or {}
    if mw:
        assert mw.get("source") == POT_MINE
        assert "extension" in mw
        assert mw["leading_diagonal"]["confirmed"] is False


def test_scenario_wave_pack_stamped_not_biaoke():
    from scenario_forecast_chart import infer_dc_wave_scenario

    # 最少柱不足以出浪時回空；有內容則必須帶 pot 戳
    rows = []
    for i in range(80):
        rows.append(
            {
                "date": f"202501{i%28+1:02d}",
                "open": 100 + i * 0.1,
                "high": 105 + i * 0.15,
                "low": 95 + i * 0.05,
                "close": 102 + i * 0.1,
                "volume": 1000,
            }
        )
    wave = infer_dc_wave_scenario(rows, [])
    if wave:
        assert wave.get("not_biaoke") is True
        assert wave.get("pot") == "dc_peer"
        assert wave.get("phone_forbid_as_his") is True
        bubble = str(wave.get("bubble") or "")
        assert not bubble.startswith("他說")
        assert "飆預測" not in bubble[:6]


def test_mine_wave_all_returns_stamped():
    for fn, args in (
        (detect_extension_1618, ({"1": 1, "3": 2},)),
        (check_w1_w4_overlap, (1, 2, 3, 4)),
        (leading_diagonal_flags, ()),
        (fib_retracement_levels, (10, 0)),
    ):
        if fn is leading_diagonal_flags:
            r = fn(w1_w4_overlap=False)
        elif fn is detect_extension_1618:
            r = fn(*args)
        else:
            r = fn(*args)
        assert r.get("source") == POT_MINE
        assert r.get("pot") == POT_MINE


def test_leak_token_list_covers_activate_checklist():
    for tok in ("leading_diagonal", "擴延1618", "我估｜前端傾斜"):
        assert tok in MINE_STRUCTURE_LEAK_TOKENS
    assert OBSERVE_MANUAL_READ_ONLY_PREFIX.endswith("observe_manual/")
