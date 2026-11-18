# -*- coding: utf-8 -*-
"""公司指引／法說書面收集。

來源優先序（不准影音）：
1) 觀測站重大訊息說明欄（公司自述）
2) 法說中文簡報 PDF（mops /nas/STR/…M001.pdf）→ 抽文字
3) 法說當日～隔日新聞／廣編標題摘要（第二層備註；％須像公司展望句才升級）

澄清稿「不作財務預測」→ 不收。抽出的％／EPS 可覆蓋 MoM 剩餘季遞推。
原文摘要進低估卡備註。不是買訊。
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

logger = logging.getLogger("wayne.guidance")
TAIPEI = ZoneInfo("Asia/Taipei")

TWSE_MATERIAL = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
TPEX_MATERIAL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O"

_DDL = """
CREATE TABLE IF NOT EXISTS company_guidance (
    stock_id TEXT NOT NULL,
    published_ymd TEXT NOT NULL,
    kind TEXT NOT NULL,
    value REAL,
    unit TEXT NOT NULL DEFAULT '',
    excerpt TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (stock_id, published_ymd, kind, source)
)
"""

# 下一季／本季相對％（營收或 EPS）
_QOQ = re.compile(
    r"(?:下一?[季季]|下季|第[四4]季|Q4)"
    r".{0,24}?"
    r"(?:營收|EPS|獲利|稅後淨利)?"
    r".{0,16}?"
    r"(?:較|比)?"
    r"(?:本季|上一?季|第[三3]季|Q3)?"
    r".{0,12}?"
    r"(?:成長|增加|上修|成長約|約|達|上看)?"
    r"\s*([+\-]?\d+(?:\.\d+)?)\s*%",
    re.I | re.S,
)
_YOY = re.compile(
    r"(?:下一?[季季]|下季|第[四4]季|Q4|明年|全年)"
    r".{0,24}?"
    r"(?:營收|EPS|獲利)?"
    r".{0,16}?"
    r"(?:年增|較去年|YoY|YOY)"
    r".{0,12}?"
    r"(?:成長|約|達)?"
    r"\s*([+\-]?\d+(?:\.\d+)?)\s*%",
    re.I | re.S,
)
_EPS_ABS = re.compile(
    r"(?:全年|今年|明年)?\s*EPS\s*(?:上看|挑戰|目標|預估|約)\s*([+\-]?\d+(?:\.\d+)?)\s*元?",
    re.I,
)
_REJECT = re.compile(r"不作財務預測|未公佈財務預測|並未發布財務預測|媒體報導與事實不符")


def ensure_schema(db_path: str) -> None:
    conn = sqlite3.connect(str(db_path or ""), timeout=30.0)
    try:
        conn.execute(_DDL)
        conn.commit()
    finally:
        conn.close()


def _get_json(url: str, *, timeout: float = 45.0) -> List[Dict[str, Any]]:
    req = Request(url, headers={"User-Agent": "WayneBot/1.0", "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    data = json.loads(raw.decode("utf-8", errors="replace"))
    return list(data) if isinstance(data, list) else []


def roc_or_ymd_to_ymd(raw: str) -> str:
    s = re.sub(r"\D", "", str(raw or ""))
    if len(s) == 7:  # 1151118
        y, m, d = int(s[:3]) + 1911, int(s[3:5]), int(s[5:7])
    elif len(s) == 8:
        y, m, d = int(s[:4]), int(s[4:6]), int(s[6:8])
    else:
        return ""
    try:
        datetime(y, m, d)
    except ValueError:
        return ""
    return f"{y:04d}{m:02d}{d:02d}"


def _subject_key(row: Dict[str, Any]) -> str:
    for k in row:
        if "主旨" in str(k):
            return str(k)
    return "主旨"


def extract_guidance_from_text(blob: str) -> List[Dict[str, Any]]:
    """從單一公告正文抽出可量化指引。無％／無絕對 EPS → 空。"""
    text = str(blob or "")
    if not text.strip():
        return []
    if _REJECT.search(text):
        return []
    out: List[Dict[str, Any]] = []
    m = _QOQ.search(text)
    if m:
        out.append(
            {
                "kind": "next_q_qoq_pct",
                "value": float(m.group(1)),
                "unit": "pct",
                "excerpt": m.group(0).replace("\n", " ")[:160],
            }
        )
    m = _YOY.search(text)
    if m:
        out.append(
            {
                "kind": "next_q_yoy_pct",
                "value": float(m.group(1)),
                "unit": "pct",
                "excerpt": m.group(0).replace("\n", " ")[:160],
            }
        )
    m = _EPS_ABS.search(text)
    if m:
        out.append(
            {
                "kind": "eps_year_abs",
                "value": float(m.group(1)),
                "unit": "eps",
                "excerpt": m.group(0).replace("\n", " ")[:160],
            }
        )
    return out


def _ir_summary_note(blob: str) -> Optional[str]:
    """無法量化時，仍留法說擇要一句備註（有官方句才留）。"""
    m = re.search(r"法人說明會擇要訊息[：:]\s*(.+?)(?:\n|5\.|完整財務|$)", blob, re.S)
    if not m:
        return None
    s = re.sub(r"\s+", " ", m.group(1)).strip(" 。;；")
    if len(s) < 6:
        return None
    if _REJECT.search(s):
        return None
    return s[:120]


def parse_material_row(row: Dict[str, Any], *, source: str) -> List[Dict[str, Any]]:
    sid = str(row.get("公司代號") or row.get("SecuritiesCompanyCode") or "").strip()
    if not sid:
        return []
    sub_k = _subject_key(row)
    title = str(row.get(sub_k) or "").strip()
    note = str(row.get("說明") or "").strip()
    blob = f"{title}\n{note}"
    ymd = roc_or_ymd_to_ymd(
        str(row.get("發言日期") or row.get("Date") or row.get("事實發生日") or "")
    )
    if not ymd:
        return []
    hits = extract_guidance_from_text(blob)
    out = []
    for h in hits:
        out.append(
            {
                "stock_id": sid,
                "published_ymd": ymd,
                "kind": h["kind"],
                "value": h["value"],
                "unit": h["unit"],
                "excerpt": h["excerpt"],
                "title": title[:200],
                "source": source,
                "raw_json": json.dumps(
                    {"title": title[:200], "excerpt": h["excerpt"]},
                    ensure_ascii=False,
                ),
            }
        )
    # 無法量化：法說擇要仍可當備註（kind=ir_note，value 空）
    if not hits:
        ir = _ir_summary_note(blob)
        if ir and ("展望" in ir or "Q4" in ir or "營運" in ir or "成長" in ir):
            out.append(
                {
                    "stock_id": sid,
                    "published_ymd": ymd,
                    "kind": "ir_note",
                    "value": None,
                    "unit": "",
                    "excerpt": ir,
                    "title": title[:200],
                    "source": source,
                    "raw_json": json.dumps({"title": title[:200], "excerpt": ir}, ensure_ascii=False),
                }
            )
    return out


def upsert_rows(db_path: str, rows: Sequence[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    ensure_schema(db_path)
    stamp = datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    n = 0
    try:
        for r in rows:
            conn.execute(
                "INSERT OR REPLACE INTO company_guidance "
                "(stock_id, published_ymd, kind, value, unit, excerpt, title, source, raw_json, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(r["stock_id"]),
                    str(r["published_ymd"]),
                    str(r["kind"]),
                    r.get("value"),
                    str(r.get("unit") or ""),
                    str(r.get("excerpt") or "")[:240],
                    str(r.get("title") or "")[:200],
                    str(r.get("source") or ""),
                    str(r.get("raw_json") or "")[:2000],
                    stamp,
                ),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def sync_material_guidance(db_path: str) -> Dict[str, Any]:
    """拉上市＋上櫃當日重大訊息快照，抽出指引寫庫。"""
    ensure_schema(db_path)
    out: Dict[str, Any] = {"ok": False, "n": 0, "sources": {}}
    all_rows: List[Dict[str, Any]] = []
    for url, src in ((TWSE_MATERIAL, "t187ap04_L"), (TPEX_MATERIAL, "t187ap04_O")):
        try:
            raw = _get_json(url)
            parsed: List[Dict[str, Any]] = []
            for row in raw:
                parsed.extend(parse_material_row(row, source=src))
            out["sources"][src] = {"raw": len(raw), "parsed": len(parsed)}
            all_rows.extend(parsed)
        except Exception as exc:
            logger.exception("guidance sync %s", src)
            out["sources"][src] = {"error": type(exc).__name__}
    out["n"] = upsert_rows(db_path, all_rows)
    out["ok"] = True
    return out


def load_latest_guidance(
    db_path: str, stock_id: str, *, within_days: int = 120
) -> Dict[str, Any]:
    """該股最近指引：優先 next_q_qoq_pct → next_q_yoy_pct → eps_year_abs；備註可附 ir_note。"""
    ensure_schema(db_path)
    sid = str(stock_id or "").strip()
    out: Dict[str, Any] = {"ok": False}
    if not sid:
        return out
    conn = sqlite3.connect(str(db_path), timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT stock_id, published_ymd, kind, value, unit, excerpt, title, source "
            "FROM company_guidance WHERE stock_id=? ORDER BY published_ymd DESC LIMIT 40",
            (sid,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return out
    # within_days 以最新列日期粗切
    latest = str(rows[0]["published_ymd"] or "")
    by_kind: Dict[str, Dict[str, Any]] = {}
    notes: List[str] = []
    for r in rows:
        d = dict(r)
        k = str(d.get("kind") or "")
        if k == "ir_note":
            ex = str(d.get("excerpt") or "").strip()
            if ex and ex not in notes:
                notes.append(ex)
            continue
        if k not in by_kind:
            by_kind[k] = d
    pick = (
        by_kind.get("next_q_qoq_pct")
        or by_kind.get("next_q_yoy_pct")
        or by_kind.get("eps_year_abs")
    )
    if pick:
        out.update(pick)
        out["ok"] = True
    if notes:
        out["ir_note"] = notes[0]
        out.setdefault("ok", True)
        out.setdefault("kind", out.get("kind") or "ir_note")
        out.setdefault("excerpt", notes[0])
        out.setdefault("published_ymd", latest)
    out["as_of_guidance"] = latest
    _ = within_days
    return out


def guidance_step_g(guidance: Dict[str, Any]) -> Optional[float]:
    """可直接當剩餘季遞推的步進 g（小數）。僅 QoQ％。"""
    if not guidance or not guidance.get("ok"):
        return None
    if str(guidance.get("kind") or "") != "next_q_qoq_pct":
        return None
    try:
        return float(guidance["value"]) / 100.0
    except (TypeError, ValueError, KeyError):
        return None


def format_guidance_note(guidance: Dict[str, Any]) -> str:
    if not guidance:
        return ""
    ymd = str(guidance.get("published_ymd") or guidance.get("as_of_guidance") or "")
    mmdd = f"{ymd[4:6]}/{ymd[6:8]}" if len(ymd) == 8 else ""
    kind = str(guidance.get("kind") or "")
    ex = str(guidance.get("excerpt") or "").strip()
    if kind == "next_q_qoq_pct" and guidance.get("value") is not None:
        head = f"公告QoQ {float(guidance['value']):g}%"
    elif kind == "next_q_yoy_pct" and guidance.get("value") is not None:
        head = f"公告YoY {float(guidance['value']):g}%"
    elif kind == "eps_year_abs" and guidance.get("value") is not None:
        head = f"公告EPS {float(guidance['value']):g}元"
    else:
        head = "法說擇要"
    bit = f"{mmdd} {head}".strip()
    if ex and ex not in bit:
        bit = f"{bit}：{ex}"
    return bit[:80]


# ----- 法說書面（PDF／擇要）；不准抓影音 -----
MOPS_IR_AJAX = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb07_1"
MOPS_HOST = "https://mopsov.twse.com.tw"
_IR_DOC_DDL = """
CREATE TABLE IF NOT EXISTS company_ir_docs (
    stock_id TEXT NOT NULL,
    ir_ymd TEXT NOT NULL,
    doc_kind TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    text_excerpt TEXT NOT NULL DEFAULT '',
    text_chars INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (stock_id, ir_ymd, doc_kind, url)
)
"""
_PDF_HREF = re.compile(r"href=['\"]([^'\"]+\.pdf)['\"]", re.I)
_IR_DATE = re.compile(r"召開法人說明會日期[：:]\s*([0-9]{2,4}[/.\-年][0-9]{1,2}[/.\-月][0-9]{1,2})")
_YEAR_GROWTH = re.compile(
    r"(?:全年|今年|明年|年度)?(?:美元)?(?:合併)?營收成長(?:大約|約|達)?\s*([+\-]?\d+(?:\.\d+)?)\s*%",
    re.I,
)


def ensure_ir_doc_schema(db_path: str) -> None:
    ensure_schema(db_path)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        conn.execute(_IR_DOC_DDL)
        conn.commit()
    finally:
        conn.close()


def _market_typek(stock_id: str, db_path: str = "") -> str:
    sid = str(stock_id or "").strip()
    if not db_path:
        return "sii"
    try:
        conn = sqlite3.connect(str(db_path), timeout=10.0)
        try:
            row = conn.execute(
                "SELECT market_type FROM stock_universe WHERE stock_id=? LIMIT 1",
                (sid,),
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT market FROM stock_directory WHERE stock_id=? LIMIT 1",
                    (sid,),
                ).fetchone()
        finally:
            conn.close()
        m = str(row[0] if row else "").upper()
        if m in ("TWO", "OTC", "TPEX", "上櫃"):
            return "otc"
        if m in ("ROTC", "EM", "興櫃", "EMERGING"):
            return "rot"
    except Exception:
        pass
    return "sii"


def list_mops_ir_pdfs(stock_id: str, *, year: int, db_path: str = "") -> List[Dict[str, str]]:
    """觀測站法說一覽：只收 PDF 簡報連結，影音／vimeo／youtube 一律丢掉。"""
    sid = str(stock_id or "").strip()
    if not sid:
        return []
    roc_y = int(year) - 1911
    typek = _market_typek(sid, db_path)
    body = (
        f"encodeURIComponent=1&step=1&firstin=1&off=1&TYPEK={typek}"
        f"&year={roc_y}&co_id={sid}&month="
    )
    req = Request(
        MOPS_IR_AJAX,
        data=body.encode(),
        headers={
            "User-Agent": "WayneBot/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://mopsov.twse.com.tw/mops/web/t100sb07_1",
        },
        method="POST",
    )
    with urlopen(req, timeout=45) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    out: List[Dict[str, str]] = []
    for href in _PDF_HREF.findall(html):
        if "vimeo" in href.lower() or "youtube" in href.lower():
            continue
        url = href if href.startswith("http") else (MOPS_HOST + href)
        # 只要中文簡報碼 …M001.pdf；E001 英文可略（省額度／碟）
        name = url.rsplit("/", 1)[-1]
        if re.search(r"E00\d\.pdf$", name, re.I):
            continue
        out.append({"url": url, "name": name, "title": "法人說明會簡報"})
    return out


def download_pdf_bytes(url: str, *, timeout: float = 120.0, min_bytes: int = 50_000) -> bytes:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 WayneBot/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if len(data) < min_bytes or not data.startswith(b"%PDF"):
        raise RuntimeError(f"pdf_too_small_or_not_pdf len={len(data)}")
    if b"%%EOF" not in data[-2048:]:
        raise RuntimeError("pdf_truncated_no_eof")
    return data


def extract_pdf_text(data: bytes, *, max_pages: int = 40) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data), strict=False)
    parts: List[str] = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            break
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def extract_guidance_from_text(blob: str) -> List[Dict[str, Any]]:
    """從公告／PDF／廣編正文抽可量化句。"""
    text = str(blob or "")
    if not text.strip():
        return []
    if _REJECT.search(text):
        return []
    out: List[Dict[str, Any]] = []
    seen = set()

    def _add(kind: str, value: float, unit: str, excerpt: str) -> None:
        key = (kind, round(value, 4))
        if key in seen:
            return
        seen.add(key)
        out.append(
            {
                "kind": kind,
                "value": float(value),
                "unit": unit,
                "excerpt": excerpt.replace("\n", " ")[:160],
            }
        )

    m = _QOQ.search(text)
    if m:
        _add("next_q_qoq_pct", float(m.group(1)), "pct", m.group(0))
    m = _YOY.search(text)
    if m:
        _add("next_q_yoy_pct", float(m.group(1)), "pct", m.group(0))
    m = _EPS_ABS.search(text)
    if m:
        _add("eps_year_abs", float(m.group(1)), "eps", m.group(0))
    m = _YEAR_GROWTH.search(text)
    if m:
        _add("year_rev_growth_pct", float(m.group(1)), "pct", m.group(0))
    return out


# 覆蓋先前同名函式（檔案末尾定義優先生效於 import 後的綁定；
# 為免雙定義混淆，測試只走模組屬性。）


def collect_ir_pdf_for_stock(
    db_path: str, stock_id: str, *, ir_ymd: str = "", year: Optional[int] = None
) -> Dict[str, Any]:
    """法說後收中文簡報 PDF→抽文字→寫指引／文件列。不抓影音。"""
    ensure_ir_doc_schema(db_path)
    sid = str(stock_id or "").strip()
    out: Dict[str, Any] = {"ok": False, "stock_id": sid, "n_pdf": 0, "n_guide": 0}
    if not sid:
        return out
    y = int(year or (int(ir_ymd[:4]) if len(str(ir_ymd)) >= 4 else datetime.now(TAIPEI).year))
    try:
        pdfs = list_mops_ir_pdfs(sid, year=y, db_path=db_path)
    except Exception as exc:
        out["error"] = type(exc).__name__
        logger.exception("list_mops_ir_pdfs %s", sid)
        return out
    out["n_pdf"] = len(pdfs)
    stamp = datetime.now(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")
    ymd = str(ir_ymd or f"{y}0101")[:8]
    guides: List[Dict[str, Any]] = []
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        for doc in pdfs[:3]:
            url = doc["url"]
            status = "ok"
            excerpt = ""
            chars = 0
            try:
                raw = download_pdf_bytes(url)
                text = extract_pdf_text(raw)
                chars = len(text)
                excerpt = re.sub(r"\s+", " ", text)[:1200]
                for h in extract_guidance_from_text(text):
                    guides.append(
                        {
                            "stock_id": sid,
                            "published_ymd": ymd,
                            "kind": h["kind"],
                            "value": h["value"],
                            "unit": h["unit"],
                            "excerpt": h["excerpt"],
                            "title": doc.get("title") or "法說簡報",
                            "source": f"mops_pdf:{doc.get('name')}",
                            "raw_json": json.dumps(
                                {"url": url, "excerpt": h["excerpt"]},
                                ensure_ascii=False,
                            ),
                        }
                    )
            except Exception as exc:
                status = type(exc).__name__
                logger.warning("ir pdf %s %s: %s", sid, url, status)
            conn.execute(
                "INSERT OR REPLACE INTO company_ir_docs "
                "(stock_id, ir_ymd, doc_kind, url, title, text_excerpt, text_chars, status, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    sid,
                    ymd,
                    "pdf_brief",
                    url,
                    str(doc.get("title") or "")[:200],
                    excerpt,
                    int(chars),
                    status,
                    stamp,
                ),
            )
        conn.commit()
    finally:
        conn.close()
    out["n_guide"] = upsert_rows(db_path, guides)
    out["ok"] = True
    return out


def collect_due_ir_pdfs(db_path: str, *, as_of: str = "", limit: int = 12) -> Dict[str, Any]:
    """company_events 法說日≤as_of、尚無成功 PDF 的標的，排程收書面。"""
    ensure_ir_doc_schema(db_path)
    day = str(as_of or datetime.now(TAIPEI).strftime("%Y%m%d")).replace("-", "")[:8]
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        rows = conn.execute(
            "SELECT stock_id, event_date FROM company_events "
            "WHERE kind='法說' AND event_date<=? "
            "ORDER BY event_date DESC LIMIT 80",
            (day,),
        ).fetchall()
        done = {
            str(r[0])
            for r in conn.execute(
                "SELECT DISTINCT stock_id FROM company_ir_docs "
                "WHERE status='ok' AND text_chars>200"
            ).fetchall()
        }
    finally:
        conn.close()
    todo = []
    seen = set()
    for sid, ymd in rows:
        sid = str(sid or "").strip()
        if not sid or sid in done or sid in seen:
            continue
        seen.add(sid)
        todo.append((sid, str(ymd)))
        if len(todo) >= int(limit):
            break
    results = []
    for sid, ymd in todo:
        results.append(collect_ir_pdf_for_stock(db_path, sid, ir_ymd=ymd, year=int(ymd[:4])))
    return {"ok": True, "as_of": day, "n": len(results), "results": results}


def collect_post_ir_news_notes(
    db_path: str, stock_id: str, stock_name: str = "", *, ir_ymd: str = ""
) -> Dict[str, Any]:
    """法說當日～隔日：Google 新聞標題／摘要當第二層備註（廣編常有重點）。

    只寫 media_note；％要有「公司／展望／法說」字樣才升級成可引用句。
    不准影音、不准當唯一買訊來源。
    """
    from urllib.parse import quote
    from email.utils import parsedate_to_datetime
    from datetime import timedelta, timezone
    import xml.etree.ElementTree as ET

    sid = str(stock_id or "").strip()
    out: Dict[str, Any] = {"ok": False, "n": 0}
    if not sid:
        return out
    q = quote(f"{sid} {stock_name} 法說 OR 法人說明會 OR 展望".strip())
    url = f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 WayneBot/1.0"})
        with urlopen(req, timeout=12) as resp:
            xml_text = resp.read().decode("utf-8", errors="replace")
        root = ET.fromstring(xml_text)
    except Exception as exc:
        out["error"] = type(exc).__name__
        return out
    anchor = None
    if len(str(ir_ymd)) == 8:
        try:
            anchor = datetime.strptime(str(ir_ymd), "%Y%m%d").replace(tzinfo=TAIPEI)
        except ValueError:
            anchor = None
    notes: List[Dict[str, Any]] = []
    for item in root.findall(".//item")[:15]:
        title = (item.findtext("title") or "").strip()
        desc = re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        try:
            dt = parsedate_to_datetime(pub)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(TAIPEI)
        except Exception:
            continue
        if anchor is not None:
            if dt < anchor - timedelta(hours=6) or dt > anchor + timedelta(days=2):
                continue
        blob = f"{title}。{desc}"
        if not any(k in blob for k in ("法說", "法人說明", "展望", "業績", "營收", "EPS")):
            continue
        ymd = dt.strftime("%Y%m%d")
        # 媒體％僅在像「公司展望／法說指出」時才抽
        scored = []
        if re.search(r"(公司|法說|展望|指出|預期|預估)", blob):
            scored = extract_guidance_from_text(blob)
        if scored:
            for h in scored:
                notes.append(
                    {
                        "stock_id": sid,
                        "published_ymd": ymd,
                        "kind": h["kind"],
                        "value": h["value"],
                        "unit": h["unit"],
                        "excerpt": h["excerpt"][:160],
                        "title": title[:200],
                        "source": "news_post_ir",
                        "raw_json": json.dumps({"title": title[:200]}, ensure_ascii=False),
                    }
                )
        else:
            notes.append(
                {
                    "stock_id": sid,
                    "published_ymd": ymd,
                    "kind": "media_note",
                    "value": None,
                    "unit": "",
                    "excerpt": title[:120],
                    "title": title[:200],
                    "source": "news_post_ir",
                    "raw_json": json.dumps({"title": title[:200]}, ensure_ascii=False),
                }
            )
    out["n"] = upsert_rows(db_path, notes)
    out["ok"] = True
    return out
