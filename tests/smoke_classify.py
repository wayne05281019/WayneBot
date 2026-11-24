# -*- coding: utf-8 -*-
"""CI smoke 快篩分類：出圖／長測進 full-suite，其餘掛 smoke。

smoke job：``pytest -m smoke``（理想 ≤10–15 分）。
full-suite：不加 -m，仍跑含 render／slow／production_db 的全套。
"""
from __future__ import annotations

# 出圖／PNG／大盤渲圖／版面卡面：檔名含這些鍵 → render（smoke 排除）
_RENDER_KEYS: tuple[str, ...] = (
    "png",
    "chart",
    "kline",
    "vol_zone",
    "volzone",
    "layout",
    "face_audit",
    "card_face",
    "glance",
    "bijia",
    "decision_card",
    "teach_trio",
    "market_",
    "taiwan_market",
    "intraday_open_close",
    "compact_layout",
    "tg_layout",
    "tg_face",
    "help_plain",
    "morning_extra",
    "ex_gap",
    "flow_fine",
    "etf_card",
    "undervalue_",
    "lookup_image",
    "lookup_layout",
    "lookup_chart",
    "lookup_flagship",
    "lookup_struct",
    "lookup_hub",
    "lookup_industry",
    "lookup_cold",
    "lookup_intraday",
    "lookup_speed",
    "combo_glance",
    "value_fund",
    "pressure_support",
    "jiuha_",
    "ops_teach",
    "chart34",
    "smart_label",
    "quote_price_color",
    "card_session",
    "foreign_sell",
    "listing_close",
    "phone_same",
    "overnight_quality",
    "spoken_next",
    "query_time",
    "broker_points",
    "industry_fine",
    "industry_chain",
    "decade_lab_lookup",
    "sell_discipline",
    "winrate_",
    "biaoke_wave",
    "biaoke_next_support",
    "biaoke_level_learn",
    "biaoke_chart",
    "ft_render",
    "official_snapshots",
    "judge_tape",
    "fuse_and_screen",
    "btn_audit",
    "asof_invent",
    "huang_teach",
    "phone_narrative",
    "bot_ux",
    "scenario_forecast",
    "nav_chart",
    "index_kline",
    "structure_chart",
    "three_in_one",
    "ink_chart",
    "export_compare",
    "card_fixtures",
    "teach_vol",
    "health_endpoint",
    "industry_bijia",
    "combo_screen",
    "wave4_band",
    "target_350",
    "morning_winrate",
    "glance_fund",
    "png_layout",
    "nav_chart_render",
    "pressure_rank",
)

# 語意上是純語法／鎖版，檔名帶 render 仍留 smoke
_RENDER_ALLOW_SMOKE: frozenset[str] = frozenset(
    {
        "test_render_py311_syntax",
    }
)

_SLOW_NAME_KEYS: tuple[str, ...] = (
    "stress",
    "e2e",
    "spectrum",
    "concurrent",
    "audit50",
    "audit1000",
    "audit_oracle",
    "hotpath_speed",
    "nav180",
    "button_speed",
    "speed_quality",
    "loading_countdown",
    "carybot_user",
    "industry_tier",
    "live_data_cross",
    "persona_grid",
    "two_user",
    "cal60_encode",
    "system_correctness",
    "lookup_integration",
    "bot_ux",
    "full_spectrum",
    "cross_feature",
    "dual_user",
    "market_menu_e2e",
)

# 長 suite／重盤／默默對質：整模組 slow（smoke 排除，full 仍跑）
_SLOW_STEM_KEYS: tuple[str, ...] = (
    "main_runner_screen",
    "scheduler_ownership",
    "ops_watchdog",
    "telegram_menu_matrix",
    "bot_deep_audit",
    "leave_zero_live",
    "dc_scenario",
    "ai_evolve",
    "dongzhu_tape",
    "silent_verify",
    "wave_teach",
    "mine_wave",
    "hold_prior",
    "emerging_screen",
    "emerging_live",
    "live_quote",
    "red_arrow",
    "trade_journal",
    "trade_fast",
    "fear_composite",
    "watchlist_join",
    "morning_digest",
    "quote_lineage",
    "quote_integrity",
    "phone_update",
    "entry_stars",
    "busy_window",
    "button_silent",
    "fund_ensure",
    "fund_q",
    "screen_",
    "pipeline_",
    "schedule_",
    "runner_",
    "fuse_",
    "ingest_",
    "absorb_",
)


def module_stem(path_or_stem: str) -> str:
    name = path_or_stem.rsplit("/", 1)[-1]
    if name.endswith(".py"):
        name = name[:-3]
    return name


def is_render_module(stem: str) -> bool:
    stem = module_stem(stem)
    if stem in _RENDER_ALLOW_SMOKE:
        return False
    return any(k in stem for k in _RENDER_KEYS)


def is_slow_module(stem: str) -> bool:
    stem = module_stem(stem)
    if stem.startswith("test_biaoke_"):
        return True
    if stem.startswith("test_decade_lab"):
        return True
    if any(k in stem for k in _SLOW_NAME_KEYS):
        return True
    if any(k in stem for k in _SLOW_STEM_KEYS):
        return True
    return False


def smoke_bucket(stem: str) -> str:
    """回傳 production 以外的桶：render / slow / smoke。"""
    stem = module_stem(stem)
    if is_render_module(stem):
        return "render"
    if is_slow_module(stem):
        return "slow"
    return "smoke"
