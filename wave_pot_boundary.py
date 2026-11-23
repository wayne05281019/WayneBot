# -*- coding: utf-8 -*-
"""DC／我估／飆大 三鍋分標邊界（DC-BOUND）。

MISSION_LOCK B6／B9：永遠分開標；對照不互寫。
對齊 ``docs/expert_notes/dc_wave/vs-biaoke-boundary.md``。

- 飆大＝老師（他說／飆預測）
- DC＝同學頂標教材（原文不准當他說；消化後進我估）
- 我估＝self／mine（可讀前兩鍋；不准回寫成他的）

不是買訊。時區 Asia/Taipei。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# --- 鍋鍵（機器可判；永不准合併成一鍋） ---
POT_BIAOKE = "biaoke"  # 他說／飆預測
POT_DC = "dc_peer"  # D.C直流變頻同學原文／視覺臉
POT_MINE = "mine"  # 我估（含 DC 消化後工具）

PHONE_TAG = {
    POT_BIAOKE: ("他說", "飆預測"),
    POT_DC: ("DC同學", "DC原文"),
    POT_MINE: ("我估",),
}

# 飆大公開反彈壓價表（課綱）；≠ mine 擴延閘、≠ mine Fib 工具語意
BIAOKE_FIB_REBOUND_RATIOS: Tuple[float, ...] = (0.382, 0.618, 0.75)

# 話筒／他說路徑禁止出現的我估／DC 結構詞（洩漏＝混標）
MINE_STRUCTURE_LEAK_TOKENS: Tuple[str, ...] = (
    "leading_diagonal",
    "擴延1618",
    "我估｜擴延1618",
    "我估｜前端傾斜",
    "前端傾斜1-4重疊",
    "ending_diagonal=termination",
)

# 不准把觀察手冊產出寫進 DC 同學表／digest 來源
OBSERVE_MANUAL_READ_ONLY_PREFIX = "docs/expert_notes/飆客/observe_manual/"
DC_WRITE_PREFIXES: Tuple[str, ...] = (
    "docs/expert_notes/dc_wave/",
    "dc_sf_",
)

CROSS_COMPARE_JSON = (
    "docs/expert_notes/dc_wave/cross_pot_compare.json"
)
CROSS_COMPARE_MD = "docs/expert_notes/dc_wave/cross_pot_compare.md"


def stamp_mine(payload: Mapping[str, Any], *, basis_extra: str = "") -> Dict[str, Any]:
    """給 mine／DC→我估 結果蓋鍋戳；不改呼叫端既有欄。"""
    out = dict(payload or {})
    out["source"] = POT_MINE
    out["pot"] = POT_MINE
    out["pot_zh"] = "我估"
    out["not_biaoke"] = True
    out["not_buy_signal"] = True
    if basis_extra and "basis" in out and isinstance(out["basis"], str):
        if basis_extra not in out["basis"]:
            out["basis"] = f"{out['basis']}; {basis_extra}"
    return out


def stamp_dc_peer(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """DC 同學原文／視覺臉戳；不准當他說。"""
    out = dict(payload or {})
    out["source"] = POT_DC
    out["pot"] = POT_DC
    out["pot_zh"] = "DC同學"
    out["not_biaoke"] = True
    out["phone_forbid_as_his"] = True
    out["not_buy_signal"] = True
    return out


def stamp_biaoke(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """他說／飆預測戳；不准被 DC／我估覆寫。"""
    out = dict(payload or {})
    out["source"] = POT_BIAOKE
    out["pot"] = POT_BIAOKE
    out["pot_zh"] = "他說"
    out["not_buy_signal"] = True
    return out


def mine_phone_label(topic_zh: str) -> str:
    """話筒我估標：固定「我估｜…」前綴。"""
    t = str(topic_zh or "").strip()
    if not t:
        return "我估｜（缺依據＝不准）"
    if t.startswith("我估"):
        return t
    return f"我估｜{t}"


def assert_label_pot(label: str, pot: str) -> None:
    """標籤字面必須符合鍋；混鍋立刻 raise。"""
    s = str(label or "")
    if pot == POT_MINE:
        if s.startswith("他說") or "飆預測" in s[:8]:
            raise ValueError(f"mine 標混成他說：{s!r}")
        if s.startswith("DC原文") or s.startswith("DC同學｜他說"):
            raise ValueError(f"mine 標混成 DC／他說：{s!r}")
    elif pot == POT_DC:
        if s.startswith("他說") or s.startswith("飆預測"):
            raise ValueError(f"DC 標混成他說：{s!r}")
    elif pot == POT_BIAOKE:
        if s.startswith("我估｜") or "leading_diagonal" in s or "擴延1618" in s:
            raise ValueError(f"他說標混進我估結構詞：{s!r}")


def label_looks_mixed(label: str) -> Optional[str]:
    """若同一標同時冒充兩鍋，回混因；乾淨回 None。"""
    s = str(label or "")
    his = s.startswith("他說") or s.startswith("飆預測")
    mine = s.startswith("我估") or "我估｜" in s
    dc = s.startswith("DC原文") or s.startswith("DC同學")
    hits = sum(1 for x in (his, mine, dc) if x)
    if hits >= 2:
        return "multi_pot_prefix"
    if his and any(tok in s for tok in MINE_STRUCTURE_LEAK_TOKENS):
        return "his_with_mine_structure"
    if dc and (his or "飆預測" in s):
        return "dc_as_his"
    return None


def forbid_auto_leading_diagonal_from_impulse_fail(
    *,
    w1_w4_overlap: Optional[bool],
    position_ok: Optional[bool],
    structure_53535: Optional[bool],
) -> Dict[str, Any]:
    """標準 impulse 1–4 失敗不准自動改標前端傾斜（缺位置＋結構＝假陽性）。

    回傳可 JSON 化的閘結果；confirmed 只在三件齊。
    """
    from mine_wave_rules import leading_diagonal_flags

    flags = leading_diagonal_flags(
        w1_w4_overlap=w1_w4_overlap,
        position_ok=position_ok,
        structure_53535=structure_53535,
    )
    stamped = stamp_mine(flags, basis_extra="≠biaoke_14_forbid_auto_promote")
    stamped["auto_promote_forbidden"] = True
    if w1_w4_overlap is True and not (
        position_ok is True and structure_53535 is True
    ):
        stamped["confirmed"] = False
        stamped["reason_zh"] = "僅重疊≠前端傾斜；缺位置或5-3-5-3-5不准升格"
    return stamped


def fib_ratio_pots() -> Dict[str, Any]:
    """同數字三鍋語意對照（永不合併）。"""
    return {
        "0.382_0.618_0.75": {
            POT_BIAOKE: "公開反彈壓價位表（課綱；可修訂版價）",
            POT_DC: "同學教材若講 Fib＝消化進我估工具，原文不准寫成他說",
            POT_MINE: "fib_retracement_levels 結構／回撤工具；≠他公開反彈壓表",
        },
        "1.618": {
            POT_BIAOKE: "戰術用語「可能擴延／第五波擴延」；9波擴延敘事",
            POT_DC: "教學圖：擴延＝L_max≥1.618×L_2nd（消化來源）",
            POT_MINE: "detect_extension_1618 結構閘；≠ C 段 1.618 目標價投影",
        },
    }


def cross_write_forbidden(src_pot: str, dst_pot: str) -> bool:
    """B9：可對照不互寫。True＝禁止寫入。"""
    if src_pot == dst_pot:
        return False
    # 單向允許：biaoke／dc → 可被 mine「讀」；不准 mine／dc 回寫 biaoke
    if dst_pot == POT_BIAOKE and src_pot in (POT_MINE, POT_DC):
        return True
    # 飆大 observe_manual 不准寫進 DC 同學鍋當原文
    if src_pot == POT_BIAOKE and dst_pot == POT_DC:
        return True
    return False


def scan_text_for_pot_leaks(
    text: str,
    *,
    claimed_pot: str,
) -> List[str]:
    """掃描一段輸出字是否對 claimed_pot 洩漏他鍋結構詞。"""
    s = str(text or "")
    leaks: List[str] = []
    mix = label_looks_mixed(s)
    if mix:
        leaks.append(mix)
    if claimed_pot == POT_BIAOKE:
        for tok in MINE_STRUCTURE_LEAK_TOKENS:
            if tok in s:
                leaks.append(f"biaoke_leak:{tok}")
    if claimed_pot == POT_DC:
        if s.startswith("他說") or "｜他說" in s:
            leaks.append("dc_labeled_as_his")
    if claimed_pot == POT_MINE:
        if s.startswith("他說") and "我估" not in s[:4]:
            leaks.append("mine_labeled_as_his")
    return leaks


def validate_cross_compare_rows(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    """對照表列必須有他說／DC／我估三欄且內容互異、不准合併欄。"""
    errs: List[str] = []
    if not rows:
        errs.append("empty_rows")
        return errs
    for i, row in enumerate(rows):
        topic = str(row.get("topic") or row.get("id") or i)
        his = str(row.get("biaoke_zh") or row.get("他說") or "").strip()
        dc = str(row.get("dc_zh") or row.get("DC") or "").strip()
        mine = str(row.get("mine_zh") or row.get("我估") or "").strip()
        if not his or not dc or not mine:
            errs.append(f"{topic}:missing_column")
            continue
        if his == dc or his == mine or dc == mine:
            errs.append(f"{topic}:merged_identical")
        # 合併成一鍋的顯性欄名
        for bad in ("merged", "all_in_one", "合鍋", "三合一"):
            if bad in row:
                errs.append(f"{topic}:forbidden_merge_key:{bad}")
        if "他說" in dc and "不准" not in dc and "不是" not in dc:
            # DC 欄若敘述「寫成他說」且無禁止語＝危險；有禁止語 OK
            if "寫成他說" in dc or "當他說" in dc:
                if "不准" not in dc:
                    errs.append(f"{topic}:dc_column_claims_his")
    return errs


def load_cross_compare(path: Optional[str] = None) -> Dict[str, Any]:
    import json
    from pathlib import Path

    p = Path(path or CROSS_COMPARE_JSON)
    return json.loads(p.read_text(encoding="utf-8"))
