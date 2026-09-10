# ==============================================================================
# 官方 ISIN 標的母體：保留現股／KY／ETF，剔除權證、牛熊、特別股、債券
# ==============================================================================
from __future__ import annotations

import io
import logging
import os
import re
import sqlite3
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"

logger = logging.getLogger("WayneBot.Universe")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

EXCLUDE_NAME_TOKENS = (
    "權證", "認購", "認售", "牛證", "熊證", "展權",
    "特別股", "甲特", "乙特",
    "債券", "公司債", "可轉債", "轉換公司債", "次順位",
    "附認股權",
)

WARRANT_CODE = re.compile(r"^(0[3-8]\d{4}|7\d{5}|\d{4,6}[PQCFX])$", re.I)
DIRTY_NAME = re.compile(r"^\[|<p\s|style=", re.I)
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_YAHOO_EN_TOKENS = re.compile(
    r"\b(limited|ltd\.?|inc\.?|corp\.?|corporation|holdings|company|manufacturing)\b",
    re.I,
)


def clean_stock_name(name: str) -> str:
    s = str(name or "").replace("\u3000", " ").strip()
    if DIRTY_NAME.search(s) or s.startswith("['"):
        return ""
    return s


def has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def looks_like_yahoo_english_name(name: str) -> bool:
    """Yahoo chart longName（Taiwan Semiconductor Manufacturing Company Limited）。

    官方拉丁股名（LINEPAY、M31、IKKA-KY、Q BURGER）不是這種公司全名。
    """
    s = clean_stock_name(name)
    if not s or has_cjk(s):
        return False
    if _YAHOO_EN_TOKENS.search(s):
        return True
    return len(s.split()) >= 3


def prefer_display_stock_name(existing: str, incoming: str = "", sid: str = "") -> str:
    """卡面／圖說用官方中文股名。Yahoo 英文長名不准蓋掉。

    ETF 官方名可含 S&P／NASDAQ，但一定有漢字；純英文公司全名不當股名。
    """
    ex = clean_stock_name(existing)
    inc = clean_stock_name(incoming)
    code = str(sid or "").strip()
    if looks_like_yahoo_english_name(ex):
        ex = ""
    if looks_like_yahoo_english_name(inc):
        inc = ""
    if has_cjk(ex):
        return ex
    if has_cjk(inc):
        return inc
    if ex and ex != code:
        return ex
    if inc and inc != code:
        return inc
    return code or ex or inc


def official_stock_name(stock_id: str, db_path: str = None) -> str:
    """母體／最新日 K 的官方名。Yahoo 英文長名當沒有。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    path = db_path or get_db_path()
    name = ""
    try:
        conn = sqlite3.connect(path, timeout=10.0)
        for sql in (
            "SELECT stock_name FROM stock_universe WHERE stock_id=? LIMIT 1",
            "SELECT stock_name FROM daily_quotes WHERE stock_id=? ORDER BY date DESC LIMIT 1",
        ):
            row = conn.execute(sql, (sid,)).fetchone()
            cand = clean_stock_name(row[0] if row else "")
            if cand and not looks_like_yahoo_english_name(cand):
                name = cand
                break
        conn.close()
    except Exception:
        name = ""
    if looks_like_yahoo_english_name(name):
        return sid
    return name or sid


def classify_target(stock_id: str, stock_name: str = "") -> Tuple[str, bool]:
    sid = str(stock_id or "").strip().upper()
    name = clean_stock_name(stock_name)

    if not sid or len(sid) < 4:
        return "INVALID", False
    if sid in ("TWA00", "TWO00", "TWII"):
        return "INDEX", True
    if any(tok in name for tok in EXCLUDE_NAME_TOKENS):
        return "JUNK", False
    if "牛" in name and "證" in name:
        return "JUNK", False
    if "熊" in name and "證" in name:
        return "JUNK", False
    if WARRANT_CODE.match(sid):
        return "WARRANT", False
    if sid[-1] == "B" and sid[0].isdigit():
        return "BOND", False
    if sid[-1] in ("C", "D", "E") and len(sid) == 5 and not sid.startswith("00"):
        return "PREFERRED", False
    if "KY" in name or sid.endswith("KY"):
        if len(sid) == 4 and sid.isdigit():
            return "KY", True
        if sid.endswith("KY") and sid[:4].isdigit():
            return "KY", True
    if sid.startswith("00") or sid.startswith("01"):
        if sid.endswith("L"):
            return "ETF_LEVERAGED", True
        if sid.endswith("R"):
            return "ETF_INVERSE", True
        if sid[-1].isalpha():
            return "ETF_ACTIVE", True
        return "ETF_PASSIVE", True
    if len(sid) == 4 and sid.isdigit():
        return "STOCK", True
    return "OTHER", False


# 查股代號：2330／0050／00878／00631L／00990A。海選仍不收 ETF。
# 至少四碼：不要把「100 天」這種三位數當代號。
_LOOKUP_TICKER_RE = re.compile(r"^(?:\d{4,6}|[0-9]{4,6}[A-Za-z])$", re.I)


def is_lookup_ticker(query: str) -> bool:
    q = unicodedata.normalize("NFKC", (query or "").strip())
    return bool(_LOOKUP_TICKER_RE.fullmatch(q))


_ETF_KIND_ALIASES = {
    "兩倍槓桿": ("ETF_LEVERAGED",),
    "二倍槓桿": ("ETF_LEVERAGED",),
    "2倍槓桿": ("ETF_LEVERAGED",),
    "兩倍": ("ETF_LEVERAGED",),
    "二倍": ("ETF_LEVERAGED",),
    "2倍": ("ETF_LEVERAGED",),
    "槓桿": ("ETF_LEVERAGED",),
    "槓桿etf": ("ETF_LEVERAGED",),
    "正2etf": ("ETF_LEVERAGED",),
    "反向": ("ETF_INVERSE",),
    "反向etf": ("ETF_INVERSE",),
    "反1": ("ETF_INVERSE",),
    "反1etf": ("ETF_INVERSE",),
    "主動etf": ("ETF_ACTIVE",),
    "主動型": ("ETF_ACTIVE",),
    "主動型etf": ("ETF_ACTIVE",),
    "主动": ("ETF_ACTIVE",),
    "主动etf": ("ETF_ACTIVE",),
    "主动型": ("ETF_ACTIVE",),
    "主動": ("ETF_ACTIVE",),
    "被動etf": ("ETF_PASSIVE",),
    "被動型": ("ETF_PASSIVE",),
    "被動型etf": ("ETF_PASSIVE",),
    "被动": ("ETF_PASSIVE",),
    "被动etf": ("ETF_PASSIVE",),
    "被动型": ("ETF_PASSIVE",),
    "被動": ("ETF_PASSIVE",),
    "主被動etf": ("ETF_ACTIVE", "ETF_PASSIVE"),
    "主被動": ("ETF_ACTIVE", "ETF_PASSIVE"),
    "主動被動etf": ("ETF_ACTIVE", "ETF_PASSIVE"),
    "主動被動": ("ETF_ACTIVE", "ETF_PASSIVE"),
    "etf": ("ETF_PASSIVE", "ETF_ACTIVE", "ETF_LEVERAGED", "ETF_INVERSE"),
}

_ETF_ALL_KINDS = ("ETF_PASSIVE", "ETF_ACTIVE", "ETF_LEVERAGED", "ETF_INVERSE")
_ETF_SPOT_KINDS = ("ETF_PASSIVE", "ETF_ACTIVE")
_ETF_CADENCE_ALIASES = {
    "月配": "月配",
    "月配etf": "月配",
    "月配息": "月配",
    "季配": "季配",
    "季配etf": "季配",
    "季配息": "季配",
    "半年配": "半年配",
    "半年配etf": "半年配",
}
_ETF_NAME_ALIASES = {
    "高股息": ("高股息", "高息"),
    "高股息etf": ("高股息", "高息"),
    "高息etf": ("高股息", "高息"),
    "高息": ("高股息", "高息"),
}
_ETF_DIV_ALIASES = {
    "配息型",
    "配息型etf",
    "配息etf",
    "配息",
}


def _norm_etf_lookup_key(query: str) -> str:
    q = unicodedata.normalize("NFKC", (query or "").strip())
    q = re.sub(r"[\s\u3000]+", "", q)
    key = q.replace("槓杆", "槓桿").replace("ＥＴＦ", "ETF").replace("Etf", "ETF")
    return key.lower()


def parse_etf_lookup_spec(query: str) -> Optional[Dict[str, Any]]:
    """對話框分類詞：官方 asset_type、官方除息日距、或官股名含高息。不走讀音撞現股。"""
    key = _norm_etf_lookup_key(query)
    if not key or is_lookup_ticker(key):
        return None
    kinds = _ETF_KIND_ALIASES.get(key)
    if kinds:
        return {
            "kinds": kinds,
            "cadence": "",
            "needles": (),
            "has_div": False,
            "label": etf_kind_label(kinds),
        }
    cadence = _ETF_CADENCE_ALIASES.get(key)
    if cadence:
        return {
            "kinds": _ETF_ALL_KINDS,
            "cadence": cadence,
            "needles": (),
            "has_div": False,
            "label": f"{cadence} ETF",
        }
    needles = _ETF_NAME_ALIASES.get(key)
    if needles:
        return {
            "kinds": _ETF_SPOT_KINDS,
            "cadence": "",
            "needles": needles,
            "has_div": False,
            "label": "高股息 ETF",
        }
    if key in _ETF_DIV_ALIASES:
        return {
            "kinds": _ETF_ALL_KINDS,
            "cadence": "",
            "needles": (),
            "has_div": True,
            "label": "配息型 ETF",
        }
    return None


_BOPO_TONES = "ˉˊˇˋ˙"
_BOPO_RE = re.compile(r"[\u3105-\u312f]")
_ETF_SUGGEST_SKIP = {"型", "etf", "式", "的", "類"}


def _cjk_only_key(s: str) -> str:
    return "".join(ch for ch in (s or "") if "\u4e00" <= ch <= "\u9fff")


def _has_bopomofo(s: str) -> bool:
    return bool(_BOPO_RE.search(s or "")) or any(ch in _BOPO_TONES for ch in (s or ""))


def _fold_bopomofo(s: str) -> str:
    text = unicodedata.normalize("NFKC", s or "")
    text = re.sub(r"[\s\u3000]+", "", text)
    for mark in _BOPO_TONES:
        text = text.replace(mark, "")
    return text


def _pinyin_compact(s: str) -> str:
    core = _cjk_only_key(s)
    if not core:
        return ""
    try:
        from pypinyin import Style, lazy_pinyin

        return "".join(str(x or "").lower() for x in lazy_pinyin(core, style=Style.NORMAL))
    except Exception:
        return ""


def _bopo_compact(s: str) -> str:
    if _has_bopomofo(s):
        return _fold_bopomofo(s)
    core = _cjk_only_key(s)
    if not core:
        return ""
    try:
        from pypinyin import Style, lazy_pinyin

        return _fold_bopomofo("".join(str(x or "") for x in lazy_pinyin(core, style=Style.BOPOMOFO)))
    except Exception:
        return ""


def etf_lookup_catalog() -> List[Dict[str, Any]]:
    """分類詞去重：給打不完整／注音對。"""
    grouped: Dict[tuple, Dict[str, Any]] = {}
    aliases: List[str] = []
    aliases.extend(_ETF_KIND_ALIASES.keys())
    aliases.extend(_ETF_CADENCE_ALIASES.keys())
    aliases.extend(_ETF_NAME_ALIASES.keys())
    aliases.extend(_ETF_DIV_ALIASES)
    for alias in aliases:
        spec = parse_etf_lookup_spec(alias)
        if not spec:
            continue
        sig = (
            tuple(spec.get("kinds") or ()),
            str(spec.get("cadence") or ""),
            tuple(spec.get("needles") or ()),
            bool(spec.get("has_div")),
        )
        slot = grouped.get(sig)
        cand = _cjk_only_key(alias) or alias
        if slot is None:
            slot = {
                "kinds": spec["kinds"],
                "cadence": spec.get("cadence") or "",
                "needles": tuple(spec.get("needles") or ()),
                "has_div": bool(spec.get("has_div")),
                "label": spec.get("label") or "",
                "pick": cand,
                "aliases": [],
            }
            grouped[sig] = slot
        slot["aliases"].append(alias)
        cur = str(slot.get("pick") or "")
        cur_cjk = _cjk_only_key(cur)
        if cand and (not cur_cjk or (2 <= len(cand) < len(cur_cjk) or (not cur_cjk and cand))):
            slot["pick"] = cand
    return list(grouped.values())


def suggest_etf_lookup_specs(query: str) -> List[Dict[str, Any]]:
    """打不完整、注音沒轉完時，列出可能的 ETF 分類。不是個股讀音。"""
    exact = parse_etf_lookup_spec(query)
    if exact:
        exact = dict(exact)
        exact["pick"] = _cjk_only_key(query) or _norm_etf_lookup_key(query)
        return [exact]
    raw = unicodedata.normalize("NFKC", (query or "").strip())
    key = _norm_etf_lookup_key(query)
    if not key or is_lookup_ticker(key) or key in _ETF_SUGGEST_SKIP:
        return []
    q_cjk = _cjk_only_key(key)
    if len(q_cjk) == 1 and not _has_bopomofo(raw) and q_cjk not in {"主", "被", "配", "槓", "反", "月", "季"}:
        return []
    q_bopo = _fold_bopomofo(raw) if _has_bopomofo(raw) else ""
    q_py = _pinyin_compact(key) if q_cjk else ""
    scored: List[tuple] = []
    for item in etf_lookup_catalog():
        names = list(item.get("aliases") or []) + [str(item.get("label") or ""), str(item.get("pick") or "")]
        best = 0
        for name in names:
            n = _norm_etf_lookup_key(name)
            n_cjk = _cjk_only_key(n)
            if not n:
                continue
            if q_cjk and (n.startswith(key) or n_cjk.startswith(q_cjk)):
                best = max(best, 94 if len(q_cjk) >= 2 else 88)
            elif key and n.startswith(key):
                best = max(best, 90)
            elif q_cjk and len(q_cjk) >= 2 and q_cjk in n_cjk:
                best = max(best, 80)
            n_py = _pinyin_compact(n)
            if q_py and n_py and n_py.startswith(q_py) and len(q_cjk) >= 2:
                best = max(best, 92 if len(q_py) >= 4 else 84)
            n_bopo = _bopo_compact(n)
            if q_bopo and n_bopo and n_bopo.startswith(q_bopo):
                best = max(best, 92 if len(q_bopo) >= 2 else 86)
        if q_bopo:
            pick_bopo = _bopo_compact(str(item.get("pick") or item.get("label") or ""))
            if pick_bopo and pick_bopo.startswith(q_bopo):
                best = max(best, 90)
        if best >= 80:
            scored.append((best, str(item.get("label") or ""), item))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out: List[Dict[str, Any]] = []
    seen = set()
    for _score, _lab, item in scored:
        pick = str(item.get("pick") or "")
        if not pick or pick in seen:
            continue
        seen.add(pick)
        out.append(dict(item))
    return out


def parse_etf_lookup_kinds(query: str) -> Optional[Tuple[str, ...]]:
    """對話框打「兩倍槓桿／主被動ETF」對到官方分類。代號查詢不走這裡。"""
    spec = parse_etf_lookup_spec(query)
    if not spec or spec.get("cadence") or spec.get("needles") or spec.get("has_div"):
        return None
    return spec["kinds"]


def etf_kind_label(kinds) -> str:
    s = {str(k) for k in (kinds or ())}
    if s == {"ETF_LEVERAGED"}:
        return "兩倍槓桿 ETF"
    if s == {"ETF_INVERSE"}:
        return "反向 ETF"
    if s == {"ETF_ACTIVE"}:
        return "主動 ETF"
    if s == {"ETF_PASSIVE"}:
        return "被動 ETF"
    if s == {"ETF_ACTIVE", "ETF_PASSIVE"}:
        return "主動／被動 ETF"
    return "ETF"


ETF_CARD_KIND = {
    "ETF_PASSIVE": "被動",
    "ETF_ACTIVE": "主動",
    "ETF_LEVERAGED": "正2",
    "ETF_INVERSE": "反1",
}


def is_etf_asset(asset_type: str = "", stock_id: str = "", stock_name: str = "") -> bool:
    """查股／圖下鈕用：有 universe.asset_type 就認官方；沒有就用代號規則。"""
    at = str(asset_type or "").strip().upper()
    if at:
        return at.startswith("ETF")
    if stock_id:
        kind, _ok = classify_target(stock_id, stock_name)
        return str(kind).startswith("ETF")
    return False


def etf_card_kind_label(asset_type: str = "", stock_id: str = "", stock_name: str = "") -> str:
    """查股標題旁：被動／主動／正2／反1。不是清單用的長名。"""
    at = str(asset_type or "").strip().upper()
    if not at.startswith("ETF") and stock_id:
        kind, _ok = classify_target(stock_id, stock_name)
        at = str(kind or "").strip().upper()
    return ETF_CARD_KIND.get(at, "")


def card_asset_type(stock_id: str, db_path: str = None) -> str:
    """查股讀母體分類；庫沒列再退回代號規則。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    path = db_path or get_db_path()
    try:
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT asset_type FROM stock_universe WHERE stock_id=?",
            (sid,),
        ).fetchone()
        conn.close()
        if row and str(row[0] or "").strip():
            return str(row[0]).strip().upper()
    except Exception:
        pass
    kind, _ok = classify_target(sid)
    return str(kind or "").strip().upper()


def canonical_lookup_ticker(query: str) -> str:
    """查股用代號：全形轉半形、槓桿／主動後綴大寫。"""
    q = unicodedata.normalize("NFKC", (query or "").strip())
    if not _LOOKUP_TICKER_RE.fullmatch(q):
        return ""
    return q.upper() if q[-1:].isalpha() else q


def default_industry(asset_type: str, industry: str = "") -> str:
    """ISIN 對 ETF 常沒產業欄；空白就標 ETF，避免輪動／產業頁變成未分類。"""
    ind = str(industry or "").strip()
    if ind and ind.lower() not in ("nan", "none"):
        return ind
    if str(asset_type or "").upper().startswith("ETF"):
        return "ETF"
    return ""


def card_industry_label(stock_id: str, db_path: str = None) -> str:
    """查股圖卡用的官方細部產業（公開資訊觀測站產業別）。沒有真值就空字串。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return ""
    path = db_path or get_db_path()
    try:
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT industry, asset_type FROM stock_universe WHERE stock_id=?",
            (sid,),
        ).fetchone()
        conn.close()
    except Exception:
        return ""
    if not row:
        return ""
    return default_industry(row[1] or "", row[0] or "")


def is_tradable(stock_id: str, stock_name: str = "") -> bool:
    _atype, keep = classify_target(stock_id, stock_name)
    return keep


SCREEN_EQUITY_TYPES = frozenset({"STOCK", "KY"})


def is_screen_equity(stock_id: str, stock_name: str = "", asset_type: Optional[str] = None) -> bool:
    """海選／當沖快取只收現股與 KY。ETF（含槓桿、反向、主動）一律排除。

    有 universe.asset_type 就認官方分類；沒有就用代號規則（00／01 開頭＝ETF）。
    """
    at = str(asset_type or "").strip().upper()
    if at:
        return at in SCREEN_EQUITY_TYPES
    kind, ok = classify_target(stock_id, stock_name)
    return bool(ok and kind in SCREEN_EQUITY_TYPES)


def name_or_sid(name: str, sid: str) -> str:
    n = clean_stock_name(name)
    return n if n else sid


def decode_isin_bytes(raw: bytes) -> str:
    """ISIN 頁：utf-8 優先。硬解 cp950 會把 utf-8 的「台積電」解成亂碼。"""
    if not raw:
        return ""
    last = ""
    for enc in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            text = raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
        last = text
        if "有價證券" in text or "台積電" in text or "國際證券辨識" in text:
            return text
    return last or raw.decode("utf-8", errors="replace")


def _parse_isin_html(html: str) -> List[Tuple[str, str, str]]:
    rows: List[Tuple[str, str, str]] = []
    try:
        import pandas as pd
        dfs = pd.read_html(io.StringIO(html))
        if dfs:
            df = dfs[0]
            for i in range(len(df)):
                raw0 = str(df.iloc[i, 0]).strip()
                industry = ""
                if df.shape[1] > 4:
                    industry = str(df.iloc[i, 4]).strip()
                    if industry in ("nan", "None"):
                        industry = ""
                m = re.match(r"^([0-9A-Za-z]{4,8})[\s\u3000\xa0\t]+(.+)$", raw0)
                if not m:
                    continue
                rows.append((m.group(1).strip(), m.group(2).strip(), industry))
            if rows:
                return rows
    except Exception as e:
        logger.info("pandas.read_html 失敗，改用 regex：%s", e)

    pattern = re.compile(r">([0-9A-Za-z]{4,8})[\s\u3000]+([^<]{1,40})<", re.U)
    for m in pattern.finditer(html):
        rows.append((m.group(1).strip(), m.group(2).strip(), ""))
    return rows


def fetch_isin_universe() -> List[Dict]:
    universe: List[Dict] = []
    urls = [
        ("TW", "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"),
        ("TWO", "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"),
        ("EM", "https://isin.twse.com.tw/isin/C_public.jsp?strMode=5"),
    ]
    session = requests.Session()
    session.headers.update(HEADERS)
    for market, url in urls:
        try:
            resp = session.get(url, timeout=25)
            text = decode_isin_bytes(resp.content or b"")
            rows = _parse_isin_html(text)
            for sid, sname, industry in rows:
                atype, keep = classify_target(sid, sname)
                if not keep:
                    continue
                universe.append({
                    "stock_id": sid,
                    "stock_name": name_or_sid(sname, sid),
                    "market_type": market,
                    "asset_type": atype,
                    "industry": industry or "",
                    "is_active": 1,
                })
            logger.info("ISIN %s 解析保留 %s 檔", market, sum(1 for u in universe if u["market_type"] == market))
        except Exception as e:
            logger.warning("ISIN %s 擷取失敗: %s", market, e)
    seen = {}
    for u in universe:
        seen[u["stock_id"]] = u
    return list(seen.values())


def ensure_universe_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stock_universe (
        stock_id TEXT PRIMARY KEY,
        stock_name TEXT NOT NULL,
        market_type TEXT NOT NULL,
        asset_type TEXT NOT NULL,
        industry TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        updated_at TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()


def restore_universe_if_wiped(db_path: str = None) -> int:
    """母體列還在但全被 is_active=0：重新打開。空 ISIN 抓失敗時大盤 sample_n 才不會變 0。"""
    path = db_path or get_db_path()
    if not path or not os.path.isfile(path):
        return 0
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        hit = cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_universe'"
        ).fetchone()
        if not hit:
            return 0
        active = int(
            cur.execute(
                "SELECT COUNT(*) FROM stock_universe WHERE is_active=1"
            ).fetchone()[0]
            or 0
        )
        total = int(cur.execute("SELECT COUNT(*) FROM stock_universe").fetchone()[0] or 0)
        if active > 0 or total == 0:
            return 0
        cur.execute("UPDATE stock_universe SET is_active=1 WHERE COALESCE(is_active,0)=0")
        n = int(cur.rowcount or 0)
        conn.commit()
        logger.warning("母體全被關掉，已重新打開 %s 檔", n)
        return n
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _universe_counts(db_path: str) -> Tuple[int, int]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        active = int(
            cur.execute("SELECT COUNT(*) FROM stock_universe WHERE is_active=1").fetchone()[0]
            or 0
        )
        total = int(cur.execute("SELECT COUNT(*) FROM stock_universe").fetchone()[0] or 0)
        return active, total
    except sqlite3.OperationalError:
        return 0, 0
    finally:
        conn.close()


def sync_universe(db_path: str = None, items: Optional[List[Dict]] = None) -> Dict[str, Any]:
    path = db_path or get_db_path()
    ensure_universe_table(path)
    items = items if items is not None else fetch_isin_universe()
    if not items:
        restored = restore_universe_if_wiped(path)
        active_n, total = _universe_counts(path)
        logger.warning(
            "ISIN 空清單，不關掉現有母體 active=%s total=%s restored=%s",
            active_n,
            total,
            restored,
        )
        return {
            "universe": 0,
            "active": active_n,
            "quotes_ids": 0,
            "deleted_junk_rows": 0,
            "industry_from_monthly": 0,
            "skipped": "empty_isin",
            "restored": restored,
        }
    now = datetime.now().isoformat(timespec="seconds")
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("UPDATE stock_universe SET is_active = 0;")
    rows = [
        (
            str(u.get("stock_id") or "").strip(),
            u.get("stock_name") or "",
            u.get("market_type") or "",
            u.get("asset_type") or "",
            default_industry(u.get("asset_type") or "", u.get("industry") or ""),
            now,
        )
        for u in items
        if str(u.get("stock_id") or "").strip()
    ]
    if rows:
        cur.executemany(
            """
            INSERT INTO stock_universe (stock_id, stock_name, market_type, asset_type, industry, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(stock_id) DO UPDATE SET
                stock_name=excluded.stock_name,
                market_type=excluded.market_type,
                asset_type=excluded.asset_type,
                industry=excluded.industry,
                is_active=1,
                updated_at=excluded.updated_at;
            """,
            rows,
        )
    active_n = int(
        cur.execute("SELECT COUNT(*) FROM stock_universe WHERE is_active=1").fetchone()[0] or 0
    )
    if active_n == 0:
        conn.rollback()
        conn.close()
        restored = restore_universe_if_wiped(path)
        logger.error("母體同步後 0 檔，已回滾 restored=%s", restored)
        active_n, _total = _universe_counts(path)
        return {
            "universe": len(items),
            "active": active_n,
            "quotes_ids": 0,
            "deleted_junk_rows": 0,
            "industry_from_monthly": 0,
            "skipped": "zero_active",
            "restored": restored,
        }
    conn.commit()
    cur.execute("""
    UPDATE daily_quotes
    SET stock_name = (
        SELECT u.stock_name FROM stock_universe u
        WHERE u.stock_id = daily_quotes.stock_id AND u.is_active = 1
    )
    WHERE EXISTS (
        SELECT 1 FROM stock_universe u
        WHERE u.stock_id = daily_quotes.stock_id AND u.is_active = 1
    );
    """)
    all_ids = [r[0] for r in cur.execute("SELECT DISTINCT stock_id FROM daily_quotes")]
    deleted = 0
    active = {r[0] for r in cur.execute("SELECT stock_id FROM stock_universe WHERE is_active=1")}
    for sid in all_ids:
        if sid in active:
            continue
        row = cur.execute("SELECT stock_name FROM daily_quotes WHERE stock_id=? LIMIT 1", (sid,)).fetchone()
        name = row[0] if row else ""
        _atype, keep = classify_target(sid, name)
        if keep:
            continue
        cur.execute("DELETE FROM daily_quotes WHERE stock_id = ?", (sid,))
        deleted += cur.rowcount
        try:
            cur.execute("DELETE FROM technical_indicators WHERE stock_id = ?", (sid,))
        except sqlite3.OperationalError:
            pass
    filled = 0
    try:
        cur.execute(
            """
            UPDATE stock_universe
            SET industry = (
                SELECT m.industry FROM monthly_revenue m
                WHERE m.stock_id = stock_universe.stock_id
                  AND TRIM(COALESCE(m.industry,'')) != ''
                LIMIT 1
            )
            WHERE TRIM(COALESCE(industry,'')) = ''
              AND EXISTS (
                SELECT 1 FROM monthly_revenue m
                WHERE m.stock_id = stock_universe.stock_id
                  AND TRIM(COALESCE(m.industry,'')) != ''
              );
            """
        )
        filled = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    except sqlite3.OperationalError:
        filled = 0
    conn.commit()
    stats = {
        "universe": len(items),
        "active": active_n,
        "quotes_ids": len(all_ids),
        "deleted_junk_rows": deleted,
        "industry_from_monthly": filled,
    }
    conn.close()
    logger.info("母體同步完成 %s", stats)
    return stats


def get_active_ids(db_path: str = None) -> set:
    path = db_path or get_db_path()
    ensure_universe_table(path)
    restore_universe_if_wiped(path)
    conn = sqlite3.connect(path)
    ids = {r[0] for r in conn.execute("SELECT stock_id FROM stock_universe WHERE is_active=1")}
    conn.close()
    return ids


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    path = get_db_path()
    print("同步母體 →", path)
    print(sync_universe(path))
