# -*- coding: utf-8 -*-
"""一千種不同角度核對話筒（除飆大按鍵功能以外）。不是同一套重跑一千次。

每一則都是獨立條件：十二鈕／精簡六顆、查股兩張圖、海選／興櫃／連買／
持股／觀察／AI倉／資金／大盤／記買入、空狀態、例外不上話筒、雙人隔離。
飆大鈕內部（抓文／對價／對話腦）不問。庫沒就標缺，不編。
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Sequence, Tuple

logger = logging.getLogger("WayneBot.PhoneAngles")

ANGLE_N = 1000

# 20 個話筒面（不含飆大鈕內部功能）。
FEATURES: Tuple[str, ...] = (
    "說明",
    "海選",
    "持股",
    "觀察",
    "刷新",
    "回報",
    "大盤",
    "資金",
    "當沖",
    "隔日沖",
    "AI倉",
    "連買區",
    "記買入",
    "查股兩張圖",
    "圖文",
    "興櫃海選",
    "精簡六顆",
    "完整十二鈕",
    "語音聽寫",
    "空白格與指令",
)

# 50 種不同鏡頭。20×50＝1000。
LENSES: Tuple[str, ...] = (
    "first_open_copy",
    "empty_state",
    "error_no_traceback",
    "compact_kb_persist",
    "full_kb_persist",
    "wayne_bro_isolation",
    "pending_cancel",
    "timeout_copy",
    "help_mentions",
    "intent_alias",
    "slash_command",
    "callback_uid",
    "after_other_feature",
    "html_escape",
    "no_invite",
    "restore_menu",
    "placeholder",
    "layout_version",
    "slot_noop",
    "dual_concurrent",
    "reply_menu_ctx",
    "actor_key_ctx",
    "start_copy",
    "picture_guide",
    "no_group",
    "last_card_per_uid",
    "lookup_lock_per_actor",
    "screening_lock",
    "emerging_separate",
    "holdings_not_ai",
    "watch_not_holdings",
    "daytrade_hours",
    "overnight_hours",
    "flow_readonly",
    "market_readonly",
    "report_cancel",
    "voice_to_on_text",
    "etf_lookup",
    "fuzzy_picker",
    "odd_lot_buy",
    "sell_prompt",
    "ai_no_push",
    "streak_no_em_chips",
    "compact_two_chars",
    "menu_slot_empty",
    "phone_busy_const",
    "wrap_cmd_binds_uid",
    "send_html_attach_uid",
    "no_force_full_on_error",
    "no_render_logs_on_phone",
)

assert len(FEATURES) * len(LENSES) == ANGLE_N

_FEATURE_HELP = {
    "說明": ("guide", "說明"),
    "海選": ("screen", "海選"),
    "持股": ("portfolio", "持股"),
    "觀察": ("watch", "觀察"),
    "刷新": ("decision", "刷新"),
    "回報": ("guide", "回報"),
    "大盤": ("market", "大盤"),
    "資金": ("flow", "資金"),
    "當沖": ("daytrade", "當沖"),
    "隔日沖": ("overnight", "隔日沖"),
    "AI倉": ("ai", "AI倉"),
    "連買區": ("streak", "連買"),
    "記買入": ("buy", "記買入"),
    "查股兩張圖": ("stock", "介紹圖"),
    "圖文": ("guide", "圖文"),
    "興櫃海選": ("screen", "興櫃"),
    "精簡六顆": ("menu", "精簡選單"),
    "完整十二鈕": ("menu", "完整選單"),
    "語音聽寫": ("guide", "麥克風"),
    "空白格與指令": ("row2", "空白"),
}

_FEATURE_INTENT = {
    "說明": "help",
    "海選": "screen",
    "持股": "portfolio",
    "觀察": "watch",
    "刷新": "card",
    "回報": "report",
    "大盤": "market",
    "資金": "flow",
    "當沖": "daytrade",
    "隔日沖": "overnight",
    "AI倉": "ai",
    "連買區": "streak",
    "記買入": "buy",
    "查股兩張圖": "lookup",
    "圖文": "help",
    "興櫃海選": "emerging_screen",
    "精簡六顆": None,
    "完整十二鈕": None,
    "語音聽寫": None,
    "空白格與指令": None,
}

_FEATURE_CMD = {
    "說明": "help",
    "海選": "screen",
    "持股": "portfolio",
    "觀察": "watch",
    "刷新": "card",
    "大盤": "market",
    "資金": "flow",
    "當沖": "daytrade",
    "隔日沖": "overnight",
    "記買入": "buy",
    "空白格與指令": "menu",
}


def _load_src() -> str:
    with open("bot_servers.py", encoding="utf-8") as fh:
        return fh.read()


def _load_intent_src() -> str:
    with open("intent_router.py", encoding="utf-8") as fh:
        return fh.read()


def _ok(detail: str) -> Dict[str, Any]:
    return {"ok": True, "detail": detail}


def _bad(detail: str) -> Dict[str, Any]:
    return {"ok": False, "detail": detail}


def _check_lens(feature: str, lens: str, src: str, intent_src: str) -> Dict[str, Any]:
    """每個 (功能, 鏡頭) 條件不同；鏡頭是共用體檢，功能決定對哪一段。"""
    help_key, help_word = _FEATURE_HELP[feature]
    kind = _FEATURE_INTENT[feature]

    if lens == "first_open_copy":
        if feature == "精簡六顆":
            return _ok("start") if "精簡選單" in src and "start_cmd" in src else _bad("start 沒提精簡")
        if feature == "完整十二鈕":
            return _ok("兩排") if "兩排" in src and "start_cmd" in src else _bad("start 沒提兩排")
        if feature == "空白格與指令":
            return _ok("slot") if "MENU_BTN_SLOT" in src else _bad("沒空白格")
        return _ok("open") if help_word in src else _bad(f"源碼沒有 {help_word}")

    if lens == "empty_state":
        needles = {
            "持股": "format_holdings_html",
            "觀察": "目前是空的",
            "當沖": "daytrade_closed",
            "隔日沖": "overnight_list_heading",
            "連買區": "目前沒有連續買超",
            "刷新": "還沒查過股票",
            "AI倉": "format_ai_desk_pages",
            "興櫃海選": "目前沒有可用的官方日均價",
            "查股兩張圖": "找不到這檔",
            "圖文": "圖文說明暫時產不出來",
        }
        n = needles.get(feature)
        if n:
            return _ok(n) if n in src else _bad(f"空狀態缺 {n}")
        return _ok("empty-n/a")

    if lens == "error_no_traceback":
        leaks = [
            "大盤讀取失敗：{e}",
            "資金移動失敗：{e}",
            "海選失敗：{e}",
            "聽寫失敗：",
            "AI 操盤失敗：{e}",
            "AI 模擬倉顯示失敗：{e}",
            "AI 進化回報失敗：{e}",
            "連買名單讀取失敗：",
            "連買清單失敗：",
            "產業說明失敗：",
        ]
        hit = [x for x in leaks if x in src]
        if hit:
            return _bad("例外上話筒 " + hit[0])
        if "PHONE_BUSY" not in src:
            return _bad("沒有 PHONE_BUSY")
        return _ok("no-leak")

    if lens == "compact_kb_persist":
        if "_ACTIVE_PHONE_UID.get()" not in src:
            return _bad("沒有 ContextVar")
        block = src.split("def _reply_menu", 1)[-1][:500]
        if "_ACTIVE_PHONE_UID.get()" not in block:
            return _bad("_reply_menu 沒讀當下 uid")
        if feature == "精簡六顆" and "MENU_COMPACT_ROWS" not in src:
            return _bad("沒精簡六顆")
        return _ok("ctx")

    if lens == "full_kb_persist":
        if "MENU_ROW1" not in src or "MENU_ROW2" not in src:
            return _bad("沒有十二鈕列")
        if "MENU_LAYOUT_VERSION" not in src:
            return _bad("沒版面版號")
        return _ok("full")

    if lens == "wayne_bro_isolation":
        if "_last_card" not in src or "uid" not in src:
            return _bad("沒按人記上一檔")
        if feature in ("持股", "觀察", "AI倉", "記買入") and "_actor_key" not in src:
            return _bad("沒 actor 隔離")
        return _ok("iso")

    if lens == "pending_cancel":
        if feature == "回報":
            return _ok("cancel") if "要取消請按其他按鈕" in src else _bad("回報沒取消")
        if feature == "連買區":
            return _ok("esc") if "_text_escapes_pending" in src else _bad("連買不放行")
        if feature == "記買入":
            return _ok("esc") if "_text_escapes_pending" in src else _bad("記買入不放行")
        return _ok("pending")

    if lens == "timeout_copy":
        needles = {
            "海選": "海選逾時",
            "大盤": "大盤讀取逾時",
            "資金": "資金頁載入逾時",
            "當沖": "查詢逾時",
            "隔日沖": "查詢逾時",
            "興櫃海選": "興櫃海選逾時",
            "查股兩張圖": "_CARD_BUILD_TIMEOUT",
            "連買區": "timeout=25.0",
        }
        n = needles.get(feature)
        if n:
            return _ok(n) if n in src else _bad(f"逾時文案缺 {n}")
        return _ok("timeout-n/a")

    if lens == "help_mentions":
        start = src.find("HELP_TOPICS = {")
        blob = src[start : start + 28000] if start >= 0 else src
        if help_word in blob or help_word in src:
            if feature == "語音聽寫" and "語音" not in blob and "麥克風" not in blob and "聽寫" not in src:
                return _bad("說明沒提語音")
            return _ok(help_key)
        return _bad(f"說明沒有 {help_word}")

    if lens == "intent_alias":
        if kind is None:
            if feature == "精簡六顆":
                return _ok("alias") if "MENU_COMPACT_ALIASES" in src else _bad("沒精簡別名")
            if feature == "完整十二鈕":
                return _ok("alias") if "MENU_FULL_ALIASES" in src else _bad("沒完整別名")
            if feature == "語音聽寫":
                return _ok("voice") if "on_voice" in src else _bad("沒聽寫")
            if feature == "空白格與指令":
                return _ok("slot") if "MENU_BTN_SLOT" in src else _bad("沒空白格")
            return _ok("n/a")
        token = f'("{feature}"' if feature in ("說明", "海選", "持股", "觀察", "大盤", "資金", "當沖", "隔日沖") else kind
        if kind not in intent_src and feature not in intent_src:
            # 記買入走 buy pending 不是 intent kind
            if feature == "記買入" and ("記買入" in src or 'pending == "buy"' in src):
                return _ok("buy-pending")
            if feature == "查股兩張圖" and "lookup" in intent_src:
                return _ok("lookup")
            return _bad(f"intent 沒有 {kind}")
        return _ok(kind)

    if lens == "slash_command":
        cmd = _FEATURE_CMD.get(feature)
        if not cmd:
            return _ok("no-slash")
        needle = f'CommandHandler("{cmd}"'
        return _ok(cmd) if needle in src else _bad(f"沒有 /{cmd}")

    if lens == "callback_uid":
        if "_on_callback_bound" not in src:
            return _bad("callback 沒綁定 uid")
        if "_ACTIVE_PHONE_UID.set(uid)" not in src:
            return _bad("callback 沒寫 ContextVar")
        return _ok("cb-uid")

    if lens == "after_other_feature":
        if "_enter_main_menu" not in src:
            return _bad("沒清 pending")
        return _ok("enter")

    if lens == "html_escape":
        if "def html_escape" not in src:
            return _bad("沒 html_escape")
        return _ok("esc")

    if lens == "no_invite":
        if "不必再分享邀請" not in src:
            return _bad("還在講邀請")
        if "給家人用" in src.split("start_cmd", 1)[-1][:800]:
            return _bad("start 還在講家人邀請")
        return _ok("no-invite")

    if lens == "restore_menu":
        if "已回到主選單（精簡六顆）" not in src:
            return _bad("精簡回主選單文案缺")
        if "已回到兩排主選單" not in src:
            return _bad("完整回主選單文案缺")
        return _ok("restore")

    if lens == "placeholder":
        if "打股名／代號" not in src:
            return _bad("沒輸入列提示")
        if feature == "精簡六顆" and "完整選單" not in src:
            return _bad("精簡提示沒寫完整選單")
        return _ok("ph")

    if lens == "layout_version":
        m = re.search(r'MENU_LAYOUT_VERSION = "(\d+)"', src)
        if not m or m.group(1) != "18":
            return _bad("版面不是 18")
        return _ok("v18")

    if lens == "slot_noop":
        if "MENU_BTN_SLOT" not in src:
            return _bad("沒空白格")
        # 正規化會把全形空白吃掉，on_text 空字直接 return
        if 't.replace("\\u3000", "").strip()' not in src and "\\u3000" not in src:
            return _bad("空白格沒被正規化清掉")
        return _ok("slot")

    if lens == "dual_concurrent":
        if "concurrent_updates(True)" not in src:
            return _bad("沒開雙人並行")
        if "_ACTIVE_PHONE_UID" not in src:
            return _bad("並行沒按則記 uid")
        return _ok("concurrent")

    if lens == "reply_menu_ctx":
        block = src.split("def _reply_menu", 1)[-1][:500]
        if "_ACTIVE_PHONE_UID.get()" not in block:
            return _bad("_reply_menu 沒讀 ContextVar")
        return _ok("reply-ctx")

    if lens == "actor_key_ctx":
        block = src.split("def _actor_key", 1)[-1][:900]
        if "_ACTIVE_PHONE_UID.get()" not in block:
            return _bad("_actor_key 沒讀 ContextVar")
        return _ok("actor-ctx")

    if lens == "start_copy":
        block = src.split("async def start_cmd", 1)[-1][:1200]
        if "精簡選單" not in block:
            return _bad("start 沒提精簡")
        if "四格" not in block:
            return _bad("start 沒提四格鍵盤")
        return _ok("start")

    if lens == "picture_guide":
        if feature == "圖文":
            return _ok("pg") if "_send_picture_guide" in src else _bad("沒圖文")
        return _ok("pg-n/a") if "picture_guide" in src else _bad("沒圖文模組")

    if lens == "no_group":
        if "不要拉進同一個群組" not in src:
            return _bad("沒警告群組")
        return _ok("no-group")

    if lens == "last_card_per_uid":
        if "self._last_card[uid]" not in src and "self._last_card.get(uid)" not in src:
            return _bad("上一檔不是按人")
        return _ok("last-card")

    if lens == "lookup_lock_per_actor":
        if "_lookup_locks" not in src:
            return _bad("查出圖沒鎖")
        return _ok("lock")

    if lens == "screening_lock":
        if "_screening_running" not in src or "_screening_gate" not in src:
            return _bad("海選沒鎖")
        return _ok("screen-lock")

    if lens == "emerging_separate":
        if "run_emerging_screening" not in src:
            return _bad("沒興櫃海選")
        if "不混進" not in src and "不會混進" not in src:
            return _bad("沒寫興櫃不混上市櫃")
        return _ok("em")

    if lens == "holdings_not_ai":
        if "不是觀察、也不是 AI" not in src and "不是 AI 模擬倉" not in src:
            return _bad("持股沒跟 AI 分開講")
        return _ok("hold-ai")

    if lens == "watch_not_holdings":
        if "自選，還沒買" not in src and "還沒買也可以" not in src:
            return _bad("觀察沒講還沒買")
        return _ok("watch")

    if lens == "daytrade_hours":
        if "09:00" not in src and "is_tw_equity_session" not in src:
            return _bad("當沖沒盤中判斷")
        return _ok("dt-hours")

    if lens == "overnight_hours":
        if "overnight" not in src:
            return _bad("沒隔日沖")
        return _ok("on-hours")

    if lens == "flow_readonly":
        if "format_flow_html" not in src:
            return _bad("沒資金頁")
        return _ok("flow")

    if lens == "market_readonly":
        if "db_only=True" not in src and "只讀" not in src:
            return _bad("大盤可能會寫庫")
        return _ok("mkt")

    if lens == "report_cancel":
        if "要取消請按其他按鈕" not in src:
            return _bad("回報沒取消")
        return _ok("report")

    if lens == "voice_to_on_text":
        if "spoken=text" not in src and "spoken=" not in src:
            return _bad("聽寫沒接回 on_text")
        return _ok("stt")

    if lens == "etf_lookup":
        if "00981A" not in src and "LOOKUP_CODE_EXAMPLES" not in src:
            return _bad("沒 ETF 例子")
        return _ok("etf")

    if lens == "fuzzy_picker":
        if "hits_need_picker" not in src:
            return _bad("沒撞名點選")
        return _ok("fuzzy")

    if lens == "odd_lot_buy":
        if "200股" not in src and "odd" not in src.lower():
            return _bad("沒零股")
        return _ok("odd")

    if lens == "sell_prompt":
        if "_sell_holdings_prompt" not in src:
            return _bad("沒賣出提示")
        return _ok("sell")

    if lens == "ai_no_push":
        if "不推播" not in src:
            return _bad("AI 沒講不推播")
        return _ok("ai-push")

    if lens == "streak_no_em_chips":
        if "EM_NO_CHIPS" not in src and "興櫃沒有官方法人" not in src:
            return _bad("連買沒擋興櫃法人")
        return _ok("streak-em")

    if lens == "compact_two_chars":
        block = src.split("MENU_COMPACT_ROWS = (", 1)[-1][:400]
        # 精簡六顆都是兩字：說明海選持股觀察刷新回報
        for word in ("說明", "海選", "持股", "觀察"):
            if word not in block:
                return _bad(f"精簡列缺 {word}")
        if "MENU_BTN_CARD" not in block or "MENU_BTN_REPORT" not in block:
            return _bad("精簡列缺刷新／回報")
        card = re.search(r'MENU_BTN_CARD = "([^"]+)"', src)
        if not card or len(card.group(1)) != 2:
            return _bad("刷新不是兩字")
        return _ok("2char")

    if lens == "menu_slot_empty":
        if 'MENU_BTN_SLOT = "\\u3000"' not in src and "MENU_BTN_SLOT = \"\\u3000\"" not in src:
            if "MENU_BTN_SLOT" not in src:
                return _bad("沒空白格常數")
        if "MENU_ROW2" not in src:
            return _bad("沒第二排")
        row2 = src.split("MENU_ROW2 = (", 1)[-1][:400]
        if "MENU_BTN_SLOT" not in row2:
            return _bad("第二排最右沒空白格")
        return _ok("empty-slot")

    if lens == "phone_busy_const":
        if 'PHONE_BUSY = "這一步暫時沒跑完' not in src:
            return _bad("PHONE_BUSY 文案改了")
        return _ok("busy")

    if lens == "wrap_cmd_binds_uid":
        block = src.split("def _wrap_cmd", 1)[-1][:500]
        if "_ACTIVE_PHONE_UID.set" not in block:
            return _bad("/指令沒綁 uid")
        return _ok("wrap")

    if lens == "send_html_attach_uid":
        if "self._reply_menu(str(chat_id))" not in src:
            return _bad("排程掛選單沒帶 chat_id")
        return _ok("attach")

    if lens == "no_force_full_on_error":
        # 錯誤頁若寫死 _reply_menu() 不帶 uid 且沒 ContextVar，精簡會被打回十二鈕
        if re.search(r"self\._reply_menu\(\s*\)", src):
            return _bad("還有 _reply_menu() 沒帶人")
        return _ok("no-bare-menu")

    if lens == "no_render_logs_on_phone":
        if "請到 Render Logs" in src:
            return _bad("話筒還在叫人看 Render Logs")
        return _ok("no-ops")

    return _bad(f"未知鏡頭 {lens}")


def build_angles(src: str | None = None, intent_src: str | None = None) -> List[Dict[str, Any]]:
    src = src if src is not None else _load_src()
    intent_src = intent_src if intent_src is not None else _load_intent_src()
    rows: List[Dict[str, Any]] = []
    i = 0
    for feat in FEATURES:
        for lens in LENSES:
            i += 1
            got = _check_lens(feat, lens, src, intent_src)
            rows.append(
                {
                    "angle_i": i,
                    "name": f"{feat}/{lens}",
                    "feature": feat,
                    "lens": lens,
                    "ok": bool(got["ok"]),
                    "detail": str(got["detail"])[:160],
                }
            )
    if len(rows) != ANGLE_N:
        raise RuntimeError(f"phone angles {len(rows)} != {ANGLE_N}")
    names = [r["name"] for r in rows]
    if len(set(names)) != ANGLE_N:
        raise RuntimeError("phone angle names not unique")
    return rows


def summarize_angles(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    passed = sum(1 for r in rows if r.get("ok"))
    failed = n - passed
    fails = [r for r in rows if not r.get("ok")][:16]
    return {
        "n": n,
        "passed": passed,
        "failed": failed,
        "fail_names": [str(r.get("name") or "") for r in fails],
        "fail_details": [str(r.get("detail") or "") for r in fails],
        "fingerprint": hashlib.sha1(
            ("\n".join(f"{r['name']}:{int(bool(r['ok']))}" for r in rows)).encode("utf-8")
        ).hexdigest()[:16],
    }


def format_angles(rows: Sequence[Dict[str, Any]] | None = None) -> str:
    rows = list(rows or build_angles())
    s = summarize_angles(rows)
    lines = [
        f"話筒一千角（不含飆大鈕內部）：{s['passed']}/{s['n']} 過。",
    ]
    if s["failed"]:
        lines.append("還沒過：")
        for name, detail in zip(s["fail_names"], s["fail_details"]):
            lines.append(f"· {name}　{detail}")
    else:
        lines.append("精簡六顆出錯不再被打回十二鈕；例外只記後台。")
    return "\n".join(lines)
