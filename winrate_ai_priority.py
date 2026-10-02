# -*- coding: utf-8 -*-
"""勝率買點名單：電子＋AI 用得到寬鏈（live 只推這組）。

使用者 2026-10-02 改口：推播／按鈕名單＝**AI 生態系 ONLY**（怕名單太多難讀）。
生技、醫療、傳產、非 AI 生態系 → **直接刪**，不是排後面。
不准改 leave_zero／黃金買點。

分類器（現有標籤；不限股名帶 AI）：
- 證交所／櫃買粗分產業 ∈ 電子族群（見 ELEC_INDUSTRIES）
- 或 CMoney／細項鏈、tags 命中「AI 用得到」供應鏈關鍵字
  （設備／材料／散熱／電力／PCB／先進封裝／伺服器／IC／記憶體／網通等）
- 刻意不含「電子商務-*」（零售／電商，不是算力供應鏈）

標籤誤差：細項缺檔時只靠粗分；粗分「電機機械」偏寬可能含非 AI 用得到；
「電子商務」若被標成其他電子粗分仍會進（粗分限制）。缺標＝不進名單（不准假標）。
非 AI 可靜默對照落檔，不准回寫買訊。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

# 證交所／櫃買粗分：電子＋數位＋電機機械＋光電（勝率名單入選＝AI 生態系 keep-set）
# 生技／醫療／傳產等不在此集合 → live 刪。
ELEC_INDUSTRIES: Set[str] = {
    "光電業",
    "光電",  # 別名／部分來源省略「業」
    "其他電子業",
    "半導體業",
    "數位雲端",
    "資訊服務業",
    "通信網路業",
    "電子通路業",
    "電子零組件業",
    "電腦及週邊設備業",
    "電機機械",
    "電機機械業",  # 別名
    "電器電纜",
}

# 正規化：來源標籤 → keep-set 鍵（缺＝原樣）
_INDUSTRY_ALIASES = {
    "光電": "光電業",
    "光電業": "光電業",
    "電機機械業": "電機機械",
    "電機機械": "電機機械",
}

# AI 用得到寬鏈：細項鏈／tags（設備／材料／散熱／電力／PCB／封裝／伺服器…）
# 不含「電子商務」；「電子上游／中游／下游」整鏈都算供應鏈寬母體。
_AI_WIDE_RE = re.compile(
    r"(?:電子上游|電子中游|電子下游|半導體|人工智慧|雲端運算|印刷電路板|資通訊)"
    r"|IP/ASIC|伺服器|Server|GPU|NPU|HPC|高效能運算|資料中心|數據中心"
    r"|矽光子|光通訊|CPO|CoWoS|HBM|高頻寬|先進封裝|液冷|散熱"
    r"|記憶體|晶圓|ABF|載板|PCB|銅箔|CCL|導線架|探針|測試介面"
    r"|IC-?代工|IC-?封測|IC-?設計|IC-?製造|IC-?通路|IC-?其他|半導體設備|半導體元件"
    r"|電源供應|變壓器與UPS|電力設備|網通|通訊設備|EMS|主機板|工業電腦"
    r"|連接元件|被動元件|PCB-材料|PCB-製造|二次電池|機殼|LCD|光學鏡片"
    r"|筆記型電腦|電腦周邊|消費電子|安全監控|顯示器",
    re.I,
)

_EXCLUDE_CHAIN_RE = re.compile(r"電子商務")


def _blob_from_fine(chain: Any, tags_json: Any) -> str:
    parts = [str(chain or "")]
    raw = tags_json
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                parts.extend(str(x) for x in parsed)
            else:
                parts.append(str(parsed))
        except Exception:
            parts.append(raw)
    elif isinstance(raw, (list, tuple)):
        parts.extend(str(x) for x in raw)
    return " ".join(parts)


def is_elec_industry(industry: Any) -> bool:
    raw = str(industry or "").strip()
    if not raw:
        return False
    if raw in ELEC_INDUSTRIES:
        return True
    canon = _INDUSTRY_ALIASES.get(raw, raw)
    return canon in ELEC_INDUSTRIES


def is_ai_wide_chain(chain_or_blob: Any, tags_json: Any = None) -> bool:
    """細項鏈／tags 是否像「AI 用得到」寬供應鏈。"""
    blob = (
        _blob_from_fine(chain_or_blob, tags_json)
        if tags_json is not None or not isinstance(chain_or_blob, str)
        else str(chain_or_blob or "")
    )
    if not blob.strip():
        return False
    if _EXCLUDE_CHAIN_RE.search(blob):
        return False
    return bool(_AI_WIDE_RE.search(blob))


def is_winrate_priority(
    industry: Any = "",
    *,
    chain: Any = "",
    tags_json: Any = None,
) -> bool:
    """電子粗分或 AI 寬鏈細項 → live 勝率名單可進（否則刪）。"""
    if is_elec_industry(industry):
        return True
    return is_ai_wide_chain(chain, tags_json)


def load_priority_flags(db_path: str, stock_ids: Sequence[str]) -> Dict[str, bool]:
    """批次查粗分＋細項，回傳 sid → 是否屬 AI／電子生態系。缺庫／缺列＝False。"""
    sids = [str(s).strip() for s in stock_ids if str(s or "").strip()]
    if not sids or not db_path or not os.path.isfile(db_path):
        return {s: False for s in sids}
    out: Dict[str, bool] = {s: False for s in sids}
    conn = sqlite3.connect(db_path)
    try:
        inds: Dict[str, str] = {}
        try:
            q = ",".join("?" * len(sids))
            for sid, ind in conn.execute(
                f"SELECT stock_id, industry FROM stock_universe WHERE stock_id IN ({q})",
                sids,
            ):
                inds[str(sid)] = str(ind or "")
        except Exception:
            inds = {}
        fines: Dict[str, tuple] = {}
        try:
            q = ",".join("?" * len(sids))
            for sid, chain, tags in conn.execute(
                f"SELECT stock_id, chain, tags_json FROM stock_fine_industry "
                f"WHERE stock_id IN ({q})",
                sids,
            ):
                fines[str(sid)] = (chain, tags)
        except Exception:
            fines = {}
    finally:
        conn.close()
    for sid in sids:
        chain, tags = fines.get(sid, ("", None))
        out[sid] = is_winrate_priority(inds.get(sid, ""), chain=chain, tags_json=tags)
    return out


def _row_is_ai(row: Dict[str, Any], flags: Dict[str, bool], *, db_path: str) -> bool:
    sid = str(row.get("stock_id") or row.get("code") or "").strip()
    if db_path:
        return bool(flags.get(sid))
    return is_winrate_priority(
        row.get("industry"),
        chain=row.get("fine_chain") or row.get("chain") or "",
        tags_json=row.get("tags_json"),
    )


def partition_winrate_ai_rows(
    rows: Sequence[Dict[str, Any]],
    db_path: str = "",
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """拆成（AI 生態系可推, 非 AI 對照／應刪）。同組內代號升冪。"""
    items = [r for r in (rows or []) if isinstance(r, dict)]
    if not items:
        return [], []
    sids = [str(r.get("stock_id") or r.get("code") or "").strip() for r in items]
    flags = load_priority_flags(db_path, sids) if db_path else {}
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for r in items:
        if _row_is_ai(r, flags, db_path=db_path):
            kept.append(r)
        else:
            dropped.append(r)
    kept.sort(key=lambda r: str(r.get("stock_id") or r.get("code") or ""))
    dropped.sort(key=lambda r: str(r.get("stock_id") or r.get("code") or ""))
    return kept, dropped


def filter_winrate_rows_ai_only(
    rows: Sequence[Dict[str, Any]],
    db_path: str = "",
) -> List[Dict[str, Any]]:
    """只留電子＋AI 寬鏈；生技／醫療／傳產／非 AI 生態系直接刪。"""
    kept, _dropped = partition_winrate_ai_rows(rows, db_path)
    return kept


def sort_winrate_rows_ai_first(
    rows: Sequence[Dict[str, Any]],
    db_path: str = "",
) -> List[Dict[str, Any]]:
    """相容舊名：現改為 AI-only（刪非 AI），組內代號升冪。"""
    return filter_winrate_rows_ai_only(rows, db_path)


def priority_mapping_zh() -> str:
    """給 PR／註解用的短對照說明。"""
    return (
        "勝率買點 live keep-set＝AI 生態系＋電機機械＋光電"
        "（證交所粗分：光電業／光電、電機機械／電機機械業、半導體、電子零組件、"
        "電腦週邊、通信網路、資訊服務、數位雲端、電子通路、其他電子、電器電纜；"
        "或細項鏈／tags 命中 AI 用得到寬鏈："
        "電子上中下游、半導體、人工智慧、雲端運算、PCB、散熱、電源、記憶體、"
        "IC 代工／封測／設計、伺服器／網通等；不含電子商務）。"
        "生技／醫療／傳產／非此範圍刪除不推；非 AI 可靜默對照。"
        "另刪訊號當天成交額＜500萬；live 不含 near_h20。"
    )
