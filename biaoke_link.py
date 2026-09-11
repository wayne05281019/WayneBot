# -*- coding: utf-8 -*-
"""飆大公開文 ↔ 同一顆行情庫：檔名對代號、樓中樓、時間線。

底圖是 Drive 那一千七百多則，不是 520 篇種子。連到 daily_quotes 才寫收盤。
不進海選、不是買訊。社團 72 不進公開庫。
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger("WayneBot.BiaokeLink")

_MENTIONS_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_mentions (
    post_id TEXT NOT NULL,
    stock_id TEXT NOT NULL,
    stock_name TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (post_id, stock_id)
);
"""
_MENTIONS_SID_IX = (
    "CREATE INDEX IF NOT EXISTS idx_biaoke_mentions_sid ON biaoke_mentions(stock_id);"
)

# 兩個字又是口語／量價用詞，不准當成股票。
_DENY = {
    "大量",
    "三星",
    "開發",
    "工業",
    "電子",
    "金控",
    "銀行",
    "壽險",
    "建設",
    "食品",
    "百貨",
    "控股",
    "科技",
    "國際",
    "企業",
    "集團",
    "汽車",
    "鋼鐵",
    "水泥",
    "化工",
    "製藥",
    "生技",
    "幸福",
    "統一",
    "動能",
    "成長",
    "創新",
    "展望",
    "先進",
    "主流",
    "指標",
    "類股",
}

_ALIASES = {
    "發哥": ("2454", "聯發科"),
    "台積": ("2330", "台積電"),
    "穎葳": ("6515", "穎崴"),
    "泛銓": ("6830", "汎銓"),
}

_TICKER = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_YEARISH = re.compile(r"^(19|20)\d{2}$")


def ensure_biaoke_mentions_table(db_path: str) -> None:
    if not db_path:
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(_MENTIONS_DDL)
        conn.execute(_MENTIONS_SID_IX)
        conn.commit()
    finally:
        conn.close()


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _load_universe(db_path: str) -> List[Tuple[str, str]]:
    if not db_path or not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        try:
            rows = conn.execute(
                "SELECT stock_id, stock_name FROM stock_universe"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if not rows:
            try:
                rows = conn.execute(
                    "SELECT stock_id, stock_name FROM stock_directory"
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
    finally:
        conn.close()
    out: List[Tuple[str, str]] = []
    seen = set()
    for sid, name in rows:
        sid_s = str(sid or "").strip().upper()
        name_s = str(name or "").strip()
        if not sid_s or not name_s or name_s in _DENY:
            continue
        key = (name_s, sid_s)
        if key in seen:
            continue
        seen.add(key)
        out.append((name_s, sid_s))
    return out


@lru_cache(maxsize=4)
def name_index(db_path: str = "") -> Tuple[Tuple[str, str], ...]:
    """最長檔名優先，南亞科先於南亞。"""
    pairs = list(_load_universe(str(db_path or "")))
    by_name = {n: sid for n, sid in pairs}
    for alias, (sid, name) in _ALIASES.items():
        by_name.setdefault(alias, sid)
        by_name.setdefault(name, sid)
    extra = [
        ("智原", "3035"),
        ("廣達", "2382"),
        ("技嘉", "2376"),
        ("緯創", "3231"),
        ("光聖", "6442"),
        ("志聖", "2467"),
        ("欣興", "3037"),
        ("台積電", "2330"),
        ("奇鋐", "3017"),
        ("健策", "3653"),
        ("聯亞", "3081"),
        ("南亞科", "2408"),
        ("群聯", "8299"),
        ("勤誠", "8210"),
        ("金像電", "2368"),
        ("台光電", "2383"),
        ("富喬", "1815"),
        ("穎崴", "6515"),
        ("致茂", "2360"),
        ("川湖", "2059"),
        ("汎銓", "6830"),
        ("聯發科", "2454"),
        ("華邦電", "2344"),
        ("均豪", "5443"),
        ("雷科", "6207"),
        ("萬海", "2615"),
        ("原相", "3227"),
        ("高技", "5439"),
        ("鴻海", "2317"),
        ("貿聯", "3036"),
        ("雍智", "6683"),
        ("金居", "8358"),
        ("台燿", "6274"),
        ("聯茂", "6213"),
        ("正崴", "2392"),
        ("尖點", "8021"),
        ("辛耘", "3583"),
        ("台虹", "8039"),
        ("弘塑", "3131"),
        ("旺矽", "6223"),
        ("萬潤", "6187"),
        ("長榮", "2603"),
        ("陽明", "2609"),
        ("華碩", "2357"),
        ("宏碁", "2353"),
        ("南亞", "1303"),
        ("飛捷", "6206"),
        ("漢唐", "2404"),
        ("穩懋", "3105"),
        ("信音", "6126"),
        ("蔚華科", "3055"),
        ("東捷", "8064"),
        ("聖暉", "5536"),
        ("創意", "3443"),
        ("AES-KY", "6781"),
        ("台達電", "2308"),
        ("富世達", "6805"),
        ("建暐", "8092"),
        ("均華", "6640"),
        ("事欣科", "4916"),
        ("新漢", "8234"),
        ("威強電", "3022"),
        ("華星光", "4979"),
        ("眾達", "4977"),
        ("聯鈞", "3450"),
        ("新應材", "4749"),
        ("藝舍", "2724"),
    ]
    for n, sid in extra:
        by_name.setdefault(n, sid)
    ranked = sorted(by_name.items(), key=lambda x: (-len(x[0]), x[0]))
    return tuple((n, sid) for n, sid in ranked if n and n not in _DENY)


def _name_re(index: Sequence[Tuple[str, str]]) -> Optional[re.Pattern[str]]:
    names = [n for n, _sid in index if n]
    if not names:
        return None
    return re.compile("|".join(re.escape(n) for n in names))


@lru_cache(maxsize=4)
def _compiled(db_path: str = "") -> Tuple[Tuple[str, str], Optional[re.Pattern[str]]]:
    idx = name_index(db_path)
    return idx, _name_re(idx)


def extract_mentions(
    text: str,
    *,
    tags: Optional[Sequence[str]] = None,
    db_path: str = "",
) -> List[Dict[str, str]]:
    """一段正文／標籤 → 代號。南亞科≠南亞；爆大量≠大量。"""
    idx, pat = _compiled(str(db_path or ""))
    by_name = {n: sid for n, sid in idx}
    blob = str(text or "")
    found: List[Dict[str, str]] = []
    seen_sid = set()
    seen_name = set()

    def add(name: str, sid: str) -> None:
        name = str(name or "").strip()
        sid = str(sid or "").strip().upper()
        if not name or name in _DENY:
            return
        if sid and sid in seen_sid:
            return
        if not sid and name in seen_name:
            return
        if sid:
            seen_sid.add(sid)
        seen_name.add(name)
        found.append({"stock_id": sid, "stock_name": name})

    for tag in tags or []:
        t = str(tag or "").strip()
        if t in by_name:
            add(t, by_name[t])
    if pat and blob:
        for m in pat.finditer(blob):
            name = m.group(0)
            add(name, by_name.get(name) or "")
    for m in _TICKER.finditer(blob):
        sid = m.group(1)
        if _YEARISH.match(sid):
            continue
        name = next((n for n, s in idx if s == sid), "")
        if sid in {s for _n, s in idx} or name:
            add(name or sid, sid)
    return found


def _children_map(posts: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for p in posts:
        parent = str(p.get("parent") or "")
        if not parent:
            continue
        out.setdefault(parent, []).append(p)
    return out


class MentionGraph:
    """公開文節點：代號／樓中樓／日期。問句只走鄰近，不掃成講義。"""

    def __init__(
        self,
        posts: Sequence[Dict[str, Any]],
        *,
        db_path: str = "",
    ) -> None:
        self.posts = list(posts)
        self.by_id = {str(p.get("id") or ""): p for p in self.posts if p.get("id")}
        self.children = _children_map(self.posts)
        self.db_path = str(db_path or "")
        self.sids: Dict[str, List[str]] = {}
        self.by_sid: Dict[str, List[str]] = {}
        self.by_date: Dict[str, List[str]] = {}
        for p in self.posts:
            aid = str(p.get("id") or "")
            if not aid:
                continue
            hits = extract_mentions(
                str(p.get("text") or ""),
                tags=list(p.get("tags") or []),
                db_path=self.db_path,
            )
            sids = [str(h.get("stock_id") or "") for h in hits if h.get("stock_id")]
            names = [str(h.get("stock_name") or "") for h in hits if h.get("stock_name")]
            p["_sids"] = sids
            p["_snames"] = names
            self.sids[aid] = sids
            day = str(p.get("date") or "")
            if day:
                self.by_date.setdefault(day, []).append(aid)
            for sid in sids:
                self.by_sid.setdefault(sid, []).append(aid)
        for sid, ids in self.by_sid.items():
            ids.sort(
                key=lambda i: (
                    str((self.by_id.get(i) or {}).get("date") or ""),
                    str((self.by_id.get(i) or {}).get("time") or ""),
                )
            )

    def sids_of(self, posts: Iterable[Dict[str, Any]]) -> List[str]:
        out: List[str] = []
        seen = set()
        for p in posts:
            for sid in p.get("_sids") or self.sids.get(str(p.get("id") or ""), []):
                if sid and sid not in seen:
                    seen.add(sid)
                    out.append(sid)
        return out

    def oldest(self, sids: Sequence[str]) -> Optional[Dict[str, Any]]:
        ids: List[str] = []
        for sid in sids:
            ids.extend(self.by_sid.get(sid) or [])
        if not ids:
            return None
        aid = min(
            ids,
            key=lambda i: (
                str((self.by_id.get(i) or {}).get("date") or "9999"),
                str((self.by_id.get(i) or {}).get("time") or ""),
            ),
        )
        return self.by_id.get(aid)

    def newest(self, sid: str, *, skip: Optional[set] = None, limit: int = 3) -> List[Dict[str, Any]]:
        skip = skip or set()
        out: List[Dict[str, Any]] = []
        for aid in reversed(self.by_sid.get(sid) or []):
            if aid in skip:
                continue
            p = self.by_id.get(aid)
            if p:
                out.append(p)
            if len(out) >= limit:
                break
        return out


@lru_cache(maxsize=2)
def mention_graph(
    n_posts: int,
    stamp: str,
    db_path: str = "",
) -> MentionGraph:
    from biaoke_desk import load_corpus

    blob = load_corpus(db_path if db_path else None)
    posts = list(blob.get("posts") or [])
    return MentionGraph(posts, db_path=db_path)


def graph_for(posts: Sequence[Dict[str, Any]], db_path: str = "") -> MentionGraph:
    if not posts:
        return MentionGraph([], db_path=db_path)
    stamp = (
        str(posts[0].get("id") or "")
        + ":"
        + str(posts[-1].get("id") or "")
        + ":"
        + str(len(posts))
    )
    try:
        cached = mention_graph(len(posts), stamp, str(db_path or ""))
        if len(cached.posts) == len(posts):
            return cached
    except Exception:
        pass
    return MentionGraph(posts, db_path=db_path)


def link_biaoke_db(db_path: str) -> Dict[str, int]:
    """把 1709 底圖對到行情庫代號，寫進 biaoke_mentions。缺的才對官方日 K。"""
    stats = {"posts": 0, "mentions": 0, "stocks": 0}
    if not db_path:
        return stats
    from biaoke_desk import ensure_biaoke_posts_table, load_corpus

    ensure_biaoke_posts_table(db_path)
    ensure_biaoke_mentions_table(db_path)
    blob = load_corpus(db_path)
    posts = list(blob.get("posts") or [])
    g = MentionGraph(posts, db_path=db_path)
    rows: List[Tuple[str, str, str]] = []
    for aid, sids in g.sids.items():
        names = (g.by_id.get(aid) or {}).get("_snames") or []
        for i, sid in enumerate(sids):
            name = names[i] if i < len(names) else sid
            rows.append((aid, sid, str(name or "")))
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute("DELETE FROM biaoke_mentions")
        conn.executemany(
            "INSERT OR REPLACE INTO biaoke_mentions(post_id, stock_id, stock_name) VALUES (?,?,?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    try:
        mention_graph.cache_clear()
        name_index.cache_clear()
        _compiled.cache_clear()
    except Exception:
        pass
    stats["posts"] = sum(
        1 for p in posts if (p.get("kind") or "post") != "reply"
    )
    stats["mentions"] = len(rows)
    stats["stocks"] = len(g.by_sid)
    logger.info(
        "飆大連線 posts=%s mentions=%s stocks=%s",
        stats["posts"],
        stats["mentions"],
        stats["stocks"],
    )
    return stats


def bar_on(db_path: str, sid: str, date_s: str) -> Optional[Dict[str, Any]]:
    """當日官方日 K。庫沒這天就空，不編。"""
    ymd = _ymd(date_s)
    if not db_path or not os.path.isfile(db_path) or not sid or not ymd:
        return None
    conn = sqlite3.connect(db_path, timeout=15.0)
    try:
        if sid == "TWII":
            try:
                row = conn.execute(
                    "SELECT date, high, low, close, open, volume, pct_change "
                    "FROM index_daily WHERE symbol='TWII' AND date=?",
                    (ymd,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = conn.execute(
                    "SELECT date, high, low, close FROM index_daily "
                    "WHERE symbol='TWII' AND date=?",
                    (ymd,),
                ).fetchone()
                if row:
                    row = tuple(row) + (None, None, None)
        else:
            try:
                row = conn.execute(
                    "SELECT date, high, low, close, open, volume, pct_change "
                    "FROM daily_quotes WHERE stock_id=? AND date=?",
                    (sid, ymd),
                ).fetchone()
            except sqlite3.OperationalError:
                row = conn.execute(
                    "SELECT date, high, low, close FROM daily_quotes "
                    "WHERE stock_id=? AND date=?",
                    (sid, ymd),
                ).fetchone()
                if row:
                    row = tuple(row) + (None, None, None)
    except sqlite3.OperationalError:
        row = None
    finally:
        conn.close()
    if not row:
        return None
    if row[1] is None or row[2] is None or row[3] is None:
        return None

    def _f(i: int) -> Optional[float]:
        if i >= len(row) or row[i] is None:
            return None
        try:
            return float(row[i])
        except (TypeError, ValueError):
            return None

    vol = None
    if len(row) > 5 and row[5] is not None:
        try:
            vol = int(float(row[5]))
        except (TypeError, ValueError):
            vol = None
    return {
        "date": str(row[0]),
        "high": float(row[1]),
        "low": float(row[2]),
        "close": float(row[3]),
        "open": _f(4),
        "volume": vol,
        "pct_change": _f(6),
    }


def _px(val: Any) -> str:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return ""
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def format_link_notes(
    posts: Sequence[Dict[str, Any]],
    *,
    db_path: str = "",
    limit: int = 3,
) -> str:
    """給對話腦看：這則連到哪一檔、當日官方收盤（有才寫）。"""
    lines: List[str] = []
    seen = set()
    for p in posts:
        aid = str(p.get("id") or "")
        sids = list(p.get("_sids") or [])
        names = list(p.get("_snames") or [])
        day = str(p.get("date") or "")
        for i, sid in enumerate(sids[:2]):
            name = names[i] if i < len(names) else sid
            key = (sid, day)
            if not sid or key in seen:
                continue
            seen.add(key)
            bar = bar_on(db_path, sid, day) if db_path else None
            bit = f"連線 {sid}{name} 他{day}寫過"
            if bar:
                bit += f" 當日收 {_px(bar.get('close'))} 低 {_px(bar.get('low'))}"
            lines.append(bit)
            if len(lines) >= limit:
                return "\n".join(lines)
        if aid and not sids and day:
            lines.append(f"連線 他{day}寫過")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def link_cache_clear() -> None:
    try:
        mention_graph.cache_clear()
    except Exception:
        pass
    try:
        name_index.cache_clear()
    except Exception:
        pass
    try:
        _compiled.cache_clear()
    except Exception:
        pass
