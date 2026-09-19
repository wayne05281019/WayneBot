"""籌碼K公開個股頁的細項產業（JSON-LD 麵包屑），不是證交所產業別。

只讀 https://www.cmoney.tw/forum/stock/{代號}，不登入、不解驗證碼。
沒抓到就不畫細項，不准自造。
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

try:
    from config import get_db_path
except Exception:
    def get_db_path():
        return "data/wayne_market.db"

logger = logging.getLogger("WayneBot.IndustryFine")

SOURCE = "cmoney_forum"
CACHE_DAYS = 7
# 教過、對得上檔號才加最細標。比對只認這層。
# 自選截圖可歸錯；這裡只收籌碼K細項或本業對得上的，不准照抄錯桶。
# 籌碼K「通訊設備／半導體元件／網通／代工」太粗：成熟製程≠台積；低軌≠全部通訊設備。
# 代工只在光通訊／低軌這種化合物廠並存。封測、記憶體製造仍是準細項。
# 低軌衛星＝點名檔（昇達科 3491，不是建漢 3062）。不准發明軍工。
# 光通訊（矽光子）＝點名檔；IET＝IET-KY 4971。啞光＝亞光；啟基＝啟碁；耀華＝燿華。
# 通嘉 3588＝電源管理，不是記憶體控制。創見＝模組。晶豪科／鈺創＝記憶體IC設計，不是製造。
TAUGHT_GROUPS: Dict[str, tuple] = {
    "光通訊": (
        "3081",  # 聯亞
        "2455",  # 全新
        "3105",  # 穩懋
        "6442",  # 光聖
        "3163",  # 波若威
        "3234",  # 光環
        "4979",  # 華星光
        "4991",  # 環宇-KY
        "4971",  # IET-KY
        "3363",  # 上詮
        "4977",  # 眾達-KY
        "3450",  # 聯鈞（封測本業＋光通訊封裝）
    ),
    "低軌衛星": (
        "3491",  # 昇達科
        "3105",  # 穩懋
        "3178",  # 公準
        "3138",  # 耀登
        "3701",  # 大眾控
        "2367",  # 燿華
        "6285",  # 啟碁
        "2313",  # 華通
        "6443",  # 元晶
        "6271",  # 同欣電
    ),
    "成熟製程": ("2303", "6770", "5347"),  # 聯電、力積電、世界
    "機器人": (
        "2049",  # 上銀
        "4583",  # 台灣精銳
        "1597",  # 直得
        "4540",  # 全球傳動
        "4576",  # 大銀微系統
        "6188",  # 廣明
        "2359",  # 所羅門
        "3019",  # 亞光
        "2395",  # 研華
        "8234",  # 新漢
        "3088",  # 艾訊
        # 宇隆 2233＝汽車零組件，不收。工業電腦全鏈不灌。
    ),
    "記憶體製造": ("2408", "2344", "2337"),  # 南亞科、華邦電、旺宏；晶豪科／鈺創不收
    "記憶體控制": ("8299", "6485"),  # 群聯、點序；通嘉／祥碩／創惟／創見不收
    "記憶體模組": (
        "5289",  # 宜鼎
        "4973",  # 廣穎
        "8088",  # 品安
        "3260",  # 威剛
        "4967",  # 十銓
        "2451",  # 創見
        "8271",  # 宇瞻
        "8277",  # 商丞
    ),
    "記憶體通路": ("8112", "8096", "3033", "3028"),  # 至上、擎亞、威健、增你強
    "記憶體封測": ("6239", "8150", "8131", "2329", "8110"),  # 力成、南茂、福懋科、華泰、華東
    "高階測試": (
        "6223",  # 旺矽
        "6515",  # 穎崴
        "7769",  # 鴻勁
        "6510",  # 精測
        "2360",  # 致茂
        "6683",  # 雍智科技
        # 汎銓＝檢測驗證，不是探針卡
    ),
    "檢測驗證": ("6830", "3587", "3289"),  # 汎銓、閎康、宜特
    "ASIC": ("3443", "3661", "3035"),
    "散熱": ("3653", "3017", "3324"),  # 健策、奇鋐、雙鴻；富世達＝連接元件、竑騰＝半導體設備，不收
    "PCB": (
        "2383",  # 台光電
        "2368",  # 金像電
        "8021",  # 尖點
        "6274",  # 台燿
        "3044",  # 健鼎
        "4958",  # 臻鼎-KY
        "1815",  # 富喬
        "5475",  # 德宏
        "5498",  # 凱崴
        "4577",  # 達航科技
        # 台玻 1802＝玻璃陶瓷，不收
    ),
    "ABF": ("8046", "3037", "3189"),  # 南電、欣興、景碩；臻鼎是 PCB 製造不是載板
    "被動元件": ("2327",),
    "特用化學": ("4772", "4749", "4722"),  # 台特化、新應材、國精化
    "無塵室": ("5536", "2404", "6139", "6691", "6196", "6903", "3402"),  # 聖暉、漢唐、亞翔、洋基、帆宣、巨漢、漢科
    "太陽能": ("6443", "6244", "3576", "6477", "4934"),  # 元晶、茂迪、聯合再生、安集、太極
    "航空": ("2610", "6757", "2618", "2646"),  # 華航、台灣虎航、長榮航、星宇；不是海運
    "重電": ("1519", "1503", "1513", "2371", "1514", "4588"),  # 華城、士電、中興電、大同、亞力、玖鼎；台達電＝電源供應器，不收
}
_TAUGHT_CROSS = tuple(TAUGHT_GROUPS.items())
# 有跨族標時，這些籌碼K細項仍算同一條真鏈。代工要另外看是不是化合物廠。
_KEEP_FINEST = frozenset({"封測", "記憶體製造"})
_KEEP_FOUNDRY_WITH = frozenset({"光通訊", "低軌衛星"})
# 高階測試／記憶體封測是封測的更細拆，不能再跟矽格整桶比。
_SPLIT_FINEST = {"高階測試": "封測", "記憶體封測": "封測"}
SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cmoney_fine_industry.json")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}
_LD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)


def split_chain(chain: str) -> List[str]:
    return [p.strip() for p in str(chain or "").split("-") if p.strip()]


def extra_tags_for(stock_id: str) -> List[str]:
    """這檔除了籌碼K麵包屑，還被點名在哪個族。沒檔號就不加。穩懋可同時有光通訊＋低軌衛星。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return []
    out: List[str] = []
    for tag, members in _TAUGHT_CROSS:
        if sid in members and tag not in out:
            out.append(tag)
    return out


def membership_face(stock_id: str, finest: str = "", chain: str = "") -> str:
    """個股標題用的最細標。有跨族就跟產業卡同業括號同一句；沒有才寫籌碼K整條鏈。"""
    extras = extra_tags_for(stock_id)
    bits: List[str] = []
    fine = str(finest or "").strip()
    if not fine:
        parts = split_chain(chain)
        fine = parts[-1] if parts else ""
    extra_set = set(extras)
    if extras:
        split_away = {_SPLIT_FINEST[t] for t in extras if t in _SPLIT_FINEST}
        keep_fine = (fine in _KEEP_FINEST and fine not in split_away) or (
            fine == "代工" and (extra_set & _KEEP_FOUNDRY_WITH)
        )
        if keep_fine:
            if fine and fine not in bits:
                bits.append(fine)
        for t in extras:
            if t not in bits:
                bits.append(t)
        return "／".join(bits)
    raw = str(chain or "").strip()
    if raw:
        return raw
    return fine


def membership_keys(stock_id: str, finest: str = "") -> set:
    """最細標籤才拿來比。有光通訊／低軌衛星就用那層；代工／封測這種準細項可並存。"""
    extras = extra_tags_for(stock_id)
    keys = set()
    for tag in extras:
        keys.add(("x", tag))
    fine = str(finest or "").strip()
    if not fine:
        return keys
    if extras:
        extra_set = set(extras)
        split_away = {_SPLIT_FINEST[t] for t in extras if t in _SPLIT_FINEST}
        if fine in _KEEP_FINEST and fine not in split_away:
            keys.add(("fine", fine))
        elif fine == "代工" and (extra_set & _KEEP_FOUNDRY_WITH):
            keys.add(("fine", fine))
        return keys
    keys.add(("fine", fine))
    return keys


def display_tags(tags: List[str], stock_id: str) -> List[str]:
    """族群 → 次族群 → 產業鏈 → 跨族，全部留下。圖卡／HTML 不准再截最後三個。"""
    out: List[str] = []
    for t in list(tags or []) + extra_tags_for(stock_id):
        s = str(t or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def peer_chip_tags(tags: Iterable[str]) -> List[str]:
    """同業列小框：完整標籤。HTML 與 PNG 同一套。"""
    out: List[str] = []
    for t in list(tags or []):
        s = str(t or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def chain_peer_ids(db_path: str, stock_id: str) -> List[str]:
    """有同一最細標籤才算同業。封測對封測；光通訊對光通訊；穩懋跨族兩邊都進。上市／上櫃／興櫃同一套。"""
    sid = str(stock_id or "").strip()
    if not sid or not db_path:
        return []
    ensure_fine_industry_table(db_path)
    mine = load_cached_fine_industry(db_path, [sid]).get(sid) or {}
    mine_keys = membership_keys(sid, str(mine.get("finest") or ""))
    if not mine_keys:
        return []
    extra_sids = set()
    for tag, members in _TAUGHT_CROSS:
        if ("x", tag) in mine_keys:
            extra_sids.update(members)
    conn = sqlite3.connect(db_path, timeout=8.0)
    try:
        rows = conn.execute(
            """
            SELECT f.stock_id, f.chain, f.tags_json
            FROM stock_fine_industry f
            JOIN stock_universe u ON u.stock_id = f.stock_id
            WHERE u.is_active=1 AND length(f.stock_id)=4
              AND COALESCE(u.asset_type,'') NOT LIKE 'ETF%'
            """
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    out = set()
    for psid, chain, tags_json in rows:
        psid = str(psid or "").strip()
        if not psid:
            continue
        try:
            tags = json.loads(tags_json) if tags_json else split_chain(chain)
        except Exception:
            tags = split_chain(chain)
        finest = str(tags[-1] if tags else "")
        if mine_keys & membership_keys(psid, finest):
            out.add(psid)
    out.update(extra_sids)
    out.add(sid)
    return sorted(out)


def parse_cmoney_forum_industry(html: str) -> Optional[Dict[str, Any]]:
    """從籌碼K個股頁 JSON-LD 取出產業分類鏈，例如 電子上游-IC-代工。"""
    raw = str(html or "")
    if not raw:
        return None
    for block in _LD_RE.findall(raw):
        try:
            data = json.loads(block)
        except Exception:
            continue
        nodes: List[Any] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("@graph"):
                    nodes.extend(item.get("@graph") or [])
                elif isinstance(item, dict):
                    nodes.append(item)
        elif isinstance(data, dict):
            if data.get("@graph"):
                nodes.extend(data.get("@graph") or [])
            else:
                nodes.append(data)
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("@type") != "BreadcrumbList":
                continue
            chain = ""
            cat_id = ""
            for el in node.get("itemListElement") or []:
                if not isinstance(el, dict):
                    continue
                item = str(el.get("item") or "")
                name = str(el.get("name") or "").strip()
                if "/forum/category/" in item and name:
                    chain = name
                    cat_id = item.rstrip("/").split("/")[-1]
            if chain:
                tags = split_chain(chain)
                if tags:
                    return {
                        "chain": chain,
                        "tags": tags,
                        "cat_id": cat_id,
                        "source": SOURCE,
                    }
    return None


def _create_fine_industry_table(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_fine_industry (
            stock_id TEXT PRIMARY KEY,
            chain TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            cat_id TEXT DEFAULT '',
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_fine_industry_table(db_path: str) -> None:
    _create_fine_industry_table(db_path)
    conn = sqlite3.connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM stock_fine_industry").fetchone()[0]
    conn.close()
    if int(n or 0) == 0:
        seed_fine_industry_table(db_path)


def seed_fine_industry_table(db_path: str) -> int:
    """空表時灌進已抓好的籌碼K細項，查股不必等全市場現抓。"""
    if not os.path.isfile(SEED_PATH):
        return 0
    try:
        with open(SEED_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return 0
    recs = []
    for sid, rec in (data or {}).items():
        if not isinstance(rec, dict):
            continue
        recs.append(
            {
                "stock_id": str(sid),
                "chain": rec.get("chain") or "",
                "tags": rec.get("tags") or split_chain(rec.get("chain") or ""),
                "cat_id": rec.get("cat_id") or "",
                "source": rec.get("source") or SOURCE,
            }
        )
    return save_fine_industry_many(db_path, recs)


def _row_to_rec(stock_id: str, chain: str, tags: List[str], cat_id: str, source: str) -> Dict[str, Any]:
    return {
        "stock_id": stock_id,
        "chain": chain,
        "tags": list(tags),
        "finest": tags[-1] if tags else "",
        "cat_id": cat_id or "",
        "source": source or SOURCE,
    }


def peek_cached_fine_chain(
    db_path: str, stock_id: str, *, max_age_days: int = CACHE_DAYS
) -> str:
    """只讀庫裡已有細項鏈；表不在或過期就空。不准為了讀而去 seed／抓網。"""
    sid = str(stock_id or "").strip()
    if not sid or not db_path:
        return ""
    try:
        conn = sqlite3.connect(db_path)
        hit = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='stock_fine_industry'"
        ).fetchone()
        if not hit:
            conn.close()
            return ""
        row = conn.execute(
            "SELECT chain, fetched_at FROM stock_fine_industry WHERE stock_id=? LIMIT 1",
            (sid,),
        ).fetchone()
        conn.close()
    except Exception:
        return ""
    if not row:
        return ""
    chain = str(row[0] or "").strip()
    if not chain:
        return ""
    try:
        ts = datetime.fromisoformat(str(row[1] or ""))
    except Exception:
        return ""
    if ts < datetime.now() - timedelta(days=max(1, int(max_age_days))):
        return ""
    return chain


def load_cached_fine_industry(
    db_path: str, stock_ids: Iterable[str], *, max_age_days: int = CACHE_DAYS
) -> Dict[str, Dict[str, Any]]:
    ids = [str(s).strip() for s in stock_ids if str(s).strip()]
    if not ids:
        return {}
    ensure_fine_industry_table(db_path)
    qmarks = ",".join("?" * len(ids))
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        f"SELECT stock_id, chain, tags_json, cat_id, source, fetched_at FROM stock_fine_industry WHERE stock_id IN ({qmarks})",
        ids,
    ).fetchall()
    conn.close()
    cutoff = datetime.now() - timedelta(days=max(1, int(max_age_days)))
    out: Dict[str, Dict[str, Any]] = {}
    for sid, chain, tags_json, cat_id, source, fetched_at in rows:
        try:
            ts = datetime.fromisoformat(str(fetched_at))
        except Exception:
            continue
        if ts < cutoff:
            continue
        try:
            tags = json.loads(tags_json) if tags_json else split_chain(chain)
        except Exception:
            tags = split_chain(chain)
        if not tags:
            continue
        out[str(sid)] = _row_to_rec(str(sid), str(chain), [str(t) for t in tags], str(cat_id or ""), str(source or SOURCE))
    return out


def save_fine_industry(db_path: str, rec: Dict[str, Any]) -> None:
    sid = str(rec.get("stock_id") or "").strip()
    chain = str(rec.get("chain") or "").strip()
    tags = rec.get("tags") or split_chain(chain)
    if not sid or not chain or not tags:
        return
    ensure_fine_industry_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO stock_fine_industry(stock_id, chain, tags_json, cat_id, source, fetched_at)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(stock_id) DO UPDATE SET
            chain=excluded.chain,
            tags_json=excluded.tags_json,
            cat_id=excluded.cat_id,
            source=excluded.source,
            fetched_at=excluded.fetched_at
        """,
        (
            sid,
            chain,
            json.dumps(list(tags), ensure_ascii=False),
            str(rec.get("cat_id") or ""),
            str(rec.get("source") or SOURCE),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


def fetch_cmoney_fine_industry(stock_id: str, timeout: float = 8.0) -> Optional[Dict[str, Any]]:
    sid = str(stock_id or "").strip()
    if not sid or len(sid) > 8:
        return None
    try:
        import requests

        url = f"https://www.cmoney.tw/forum/stock/{sid}"
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        parsed = parse_cmoney_forum_industry(resp.text)
        if not parsed:
            return None
        parsed["stock_id"] = sid
        return parsed
    except Exception as exc:
        logger.info("籌碼K細項抓不到 %s：%s", sid, exc)
        return None


def load_or_fetch_fine_industry(
    db_path: str,
    stock_ids: Iterable[str],
    *,
    allow_fetch: bool = False,
    max_fetch: int = 5,
) -> Dict[str, Dict[str, Any]]:
    path = db_path or get_db_path()
    ids = []
    seen = set()
    for s in stock_ids:
        sid = str(s or "").strip()
        if sid and sid not in seen:
            seen.add(sid)
            ids.append(sid)
    out = load_cached_fine_industry(path, ids)
    if not allow_fetch:
        return out
    fetched = 0
    missing = [sid for sid in ids if sid not in out][: max(0, int(max_fetch))]
    if not missing:
        return out
    from concurrent.futures import ThreadPoolExecutor, as_completed

    workers = min(4, len(missing))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fetch_cmoney_fine_industry, sid): sid for sid in missing}
        for fut in as_completed(futs):
            sid = futs[fut]
            fetched += 1
            try:
                rec = fut.result()
            except Exception:
                rec = None
            if not rec:
                continue
            rec["stock_id"] = sid
            save_fine_industry(path, rec)
            out[sid] = _row_to_rec(
                sid, rec["chain"], rec["tags"], rec.get("cat_id") or "", rec.get("source") or SOURCE
            )
    return out


def chip_color(tag: str) -> tuple:
    """不同細項用不同框色。同類（記憶體／代工／LED）同一色系。"""
    t = str(tag or "").strip()
    palettes = {
        "memory": ((92, 52, 8), (242, 176, 64), (255, 236, 200)),
        "foundry": ((8, 72, 78), (64, 214, 196), (220, 255, 248)),
        "design": ((58, 28, 96), (186, 148, 255), (238, 228, 255)),
        "ic": ((16, 48, 112), (96, 168, 255), (220, 236, 255)),
        "upstream": ((42, 54, 72), (148, 168, 188), (226, 232, 240)),
        "led": ((12, 78, 40), (86, 210, 128), (220, 255, 230)),
        "pack": ((86, 32, 60), (230, 138, 186), (255, 230, 244)),
        "pcb": ((72, 48, 16), (214, 164, 82), (255, 232, 200)),
        "sat": ((18, 44, 92), (96, 168, 255), (214, 232, 255)),
        "other": ((48, 56, 70), (160, 176, 196), (230, 236, 242)),
    }
    if any(k in t for k in ("記憶體", "DRAM", "NAND", "Flash")):
        return palettes["memory"]
    if "代工" in t or "晶圓製造" in t:
        return palettes["foundry"]
    if "LED" in t or "光元件" in t or t.startswith("照明"):
        return palettes["led"]
    if "光通訊" in t or t in ("InP", "InP族"):
        return palettes["led"]
    if "低軌" in t or "衛星" in t:
        return palettes["sat"]
    if "機器人" in t or "工業電腦" in t:
        return palettes["design"]
    if "成熟製程" in t:
        return palettes["foundry"]
    if "記憶體控制" in t:
        return palettes["memory"]
    if "網通" in t:
        return palettes["ic"]
    if "封測" in t or "封裝" in t or "測試" in t:
        return palettes["pack"]
    if "PCB" in t:
        return palettes["pcb"]
    if "設計" in t or "IP" in t or "ASIC" in t:
        return palettes["design"]
    if t == "IC" or t.startswith("IC-") or t.startswith("IC／"):
        return palettes["ic"]
    if "電子上游" in t or "電子中游" in t or "電子下游" in t:
        return palettes["upstream"]
    h = sum(ord(c) for c in t) % 5
    return list(palettes.values())[h]


def parse_cmoney_category_index(html: str) -> Dict[str, str]:
    """產業總覽頁：C23020 → IC-代工。只作對照，個股細項仍以個股頁麵包屑為準。"""
    out: Dict[str, str] = {}
    for cid, name in re.findall(r'href="/forum/category/(C\d+)"[^>]*>([^<]+)', str(html or "")):
        n = re.sub(r"\s+", "", name)
        if cid and n:
            out[cid] = n
    return out


def active_equity_ids(db_path: str) -> List[str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        """
        SELECT stock_id FROM stock_universe
        WHERE is_active=1 AND length(stock_id)=4
          AND COALESCE(asset_type,'') NOT LIKE 'ETF%'
        ORDER BY stock_id
        """
    ).fetchall()
    conn.close()
    return [str(r[0]) for r in rows if r and r[0]]


def save_fine_industry_many(db_path: str, recs: List[Dict[str, Any]]) -> int:
    rows = []
    now = datetime.now().isoformat(timespec="seconds")
    for rec in recs:
        sid = str(rec.get("stock_id") or "").strip()
        chain = str(rec.get("chain") or "").strip()
        tags = rec.get("tags") or split_chain(chain)
        if not sid or not chain or not tags:
            continue
        rows.append(
            (
                sid,
                chain,
                json.dumps(list(tags), ensure_ascii=False),
                str(rec.get("cat_id") or ""),
                str(rec.get("source") or SOURCE),
                now,
            )
        )
    if not rows:
        return 0
    _create_fine_industry_table(db_path)
    conn = sqlite3.connect(db_path)
    conn.executemany(
        """
        INSERT INTO stock_fine_industry(stock_id, chain, tags_json, cat_id, source, fetched_at)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(stock_id) DO UPDATE SET
            chain=excluded.chain,
            tags_json=excluded.tags_json,
            cat_id=excluded.cat_id,
            source=excluded.source,
            fetched_at=excluded.fetched_at
        """,
        rows,
    )
    conn.commit()
    conn.close()
    return len(rows)


def sync_all_fine_industry(
    db_path: str = None,
    *,
    workers: int = 8,
    force: bool = False,
    limit: int = 0,
    ids: Optional[List[str]] = None,
) -> Dict[str, int]:
    """盤後一次抓全市場現股的籌碼K細項。查股只讀庫，不再一檔一檔等。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    path = db_path or get_db_path()
    ensure_fine_industry_table(path)
    want = list(ids) if ids is not None else active_equity_ids(path)
    if limit:
        want = want[: int(limit)]
    cached = {} if force else load_cached_fine_industry(path, want)
    missing = [sid for sid in want if sid not in cached]
    stats = {
        "total": len(want),
        "skip": len(want) - len(missing),
        "ok": 0,
        "fail": 0,
    }
    if not missing:
        return stats
    n_workers = max(1, min(int(workers or 8), 12))
    buf: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futs = {pool.submit(fetch_cmoney_fine_industry, sid): sid for sid in missing}
        for fut in as_completed(futs):
            sid = futs[fut]
            rec = None
            try:
                rec = fut.result()
            except Exception:
                rec = None
            if not rec:
                stats["fail"] += 1
                continue
            rec["stock_id"] = sid
            buf.append(rec)
            stats["ok"] += 1
            if len(buf) >= 40:
                save_fine_industry_many(path, buf)
                buf = []
    if buf:
        save_fine_industry_many(path, buf)
    logger.info("籌碼K細項全市場同步：%s", stats)
    return stats

