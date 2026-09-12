# -*- coding: utf-8 -*-
"""四路對質：加權／台積電量價／費半／台指期，核他確認句對不對。

主音（波浪）不夠。這裡不數 15 分段、不發明「某金融商品」。
缺官方序列就現抓（Yahoo 日 K、期交所日／夜）。不是買訊、不進海選。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote as url_quote

import requests

from biaoke_alert import confirm_stack
from tg_layout import html_escape

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "expert_notes", "飆客")
SNAPSHOT_JSON = os.path.join(_DIR, "witness.json")
SNAPSHOT_MD = os.path.join(_DIR, "witness.md")

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
_RETRACT = re.compile(r"(已經沒了|改口|更正|今天最低|不破\s*40000|講錯|看錯了)")
_ENTER = re.compile(r"(抄底|第一次抄|差不多到底|A\s*波低|開始介入)")
_ASK = re.compile(
    r"(四路|對質|現在確認|確認了沒|輔助現在|量價現在|官方對不對|"
    r"能不能確認|疊得上|證人)"
)

Bar = Dict[str, Any]


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _dash(ymd: str) -> str:
    t = _ymd(ymd)
    return f"{t[:4]}-{t[4:6]}-{t[6:8]}" if len(t) == 8 else str(ymd or "")


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _clip(text: str, n: int) -> str:
    s = _plain(text)
    return s if len(s) <= n else s[: n - 1] + "…"


def is_witness_query(ask: str) -> bool:
    return bool(_ASK.search(ask or ""))


def classify_post(text: str) -> str:
    """confirm / prelim / retract / enter / ''。沿用推播那套主音＋輔助，不另發明。"""
    blob = text or ""
    st = confirm_stack(blob)
    if st.get("confirmed"):
        return "confirm"
    if _RETRACT.search(blob):
        return "retract"
    if st.get("veto"):
        return "prelim"
    if _ENTER.search(blob):
        return "enter"
    return ""


def fetch_yahoo_ohlcv(symbol: str, *, range_: str = "2y", interval: str = "1d") -> List[Bar]:
    """Yahoo 日 K／近 5 日分鐘。失敗回空，不編。"""
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{url_quote(symbol, safe='^')}?interval={interval}&range={range_}"
    )
    try:
        resp = requests.get(url, headers=_UA, timeout=30)
        resp.raise_for_status()
        result = (resp.json().get("chart") or {}).get("result") or []
    except Exception:
        return []
    if not result:
        return []
    block = result[0]
    stamps = block.get("timestamp") or []
    q = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    out: List[Bar] = []
    for i, ts in enumerate(stamps):
        try:
            c = q.get("close")[i]
            if c is None:
                continue
            day = datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(
                timezone(timedelta(hours=8))
            )
            out.append(
                {
                    "date": day.strftime("%Y%m%d"),
                    "ts": int(ts),
                    "open": float(q.get("open")[i] if q.get("open")[i] is not None else c),
                    "high": float(q.get("high")[i] if q.get("high")[i] is not None else c),
                    "low": float(q.get("low")[i] if q.get("low")[i] is not None else c),
                    "close": float(c),
                    "volume": float((q.get("volume") or [0])[i] or 0),
                }
            )
        except (TypeError, ValueError, IndexError):
            continue
    out.sort(key=lambda r: (r["date"], r.get("ts") or 0))
    return out


def fetch_tx_range(start: str, end: str) -> Dict[str, Dict[str, Bar]]:
    """期交所歷史：一般＝日盤、盤後＝夜盤。單次約 31 日。"""
    from taiwan_market import _download_taifex_history_chunk

    a, b = _ymd(start), _ymd(end)
    if len(a) != 8 or len(b) != 8:
        return {}
    s = f"{a[:4]}/{a[4:6]}/{a[6:8]}"
    e = f"{b[:4]}/{b[4:6]}/{b[6:8]}"
    try:
        chunk = _download_taifex_history_chunk(s, e)
    except Exception:
        return {}
    out: Dict[str, Dict[str, Bar]] = {}
    for d, sess in (chunk or {}).items():
        row: Dict[str, Bar] = {}
        for key in ("regular", "night"):
            one = (sess or {}).get(key) or {}
            if not one.get("close"):
                continue
            row[key] = {
                "date": _ymd(d),
                "open": float(one.get("open") or 0),
                "high": float(one.get("high") or 0),
                "low": float(one.get("low") or 0),
                "close": float(one.get("close") or 0),
                "volume": float(one.get("volume") or 0),
                "session": key,
            }
        if row:
            out[_ymd(d)] = row
    return out


def fetch_tx_months(months: Sequence[str]) -> Dict[str, Dict[str, Bar]]:
    """months 形如 202607。缺哪月抓哪月。"""
    merged: Dict[str, Dict[str, Bar]] = {}
    for ym in months:
        y = str(ym).replace("-", "")[:6]
        if len(y) != 6 or not y.isdigit():
            continue
        start = y + "01"
        yyyy, mm = int(y[:4]), int(y[4:6])
        if mm == 12:
            end = f"{yyyy}1231"
        else:
            nxt = datetime(yyyy, mm + 1, 1) - timedelta(days=1)
            end = nxt.strftime("%Y%m%d")
        merged.update(fetch_tx_range(start, end))
    return merged


def _idx(series: Sequence[Bar], day: str) -> Optional[int]:
    d = _ymd(day)
    if not d:
        return None
    for i, row in enumerate(series):
        if _ymd(row.get("date")) >= d:
            return i
    return None


def tsmc_witness(bars: Sequence[Bar], day: str) -> Dict[str, Any]:
    """低檔爆量＋收近低／假跌破站回。沒量就不裝。"""
    i = _idx(bars, day)
    empty = {"fire": False, "vol_ratio": None, "close_eq_low": False, "false_break": False}
    if i is None or i < 6:
        return empty
    cur = bars[i]
    win = [float(b.get("volume") or 0) for b in bars[max(0, i - 20) : i] if float(b.get("volume") or 0) > 0]
    if not win:
        return empty
    win_s = sorted(win)
    med = win_s[len(win_s) // 2]
    vol = float(cur.get("volume") or 0)
    ratio = (vol / med) if med else 0.0
    lo, cl = float(cur.get("low") or 0), float(cur.get("close") or 0)
    close_eq_low = bool(cl > 0 and (cl - lo) / cl <= 0.004)
    prev_lo = min(float(b.get("low") or 0) for b in bars[max(0, i - 5) : i])
    false_break = bool(prev_lo > 0 and lo < prev_lo * 0.998 and cl > prev_lo)
    fire = bool(false_break or (ratio >= 1.55 and close_eq_low) or ratio >= 1.95)
    return {
        "fire": fire,
        "vol_ratio": round(ratio, 2),
        "close_eq_low": close_eq_low,
        "false_break": false_break,
        "close": cl,
        "low": lo,
        "volume": vol,
        "date": _ymd(cur.get("date")),
    }


def sox_witness(bars: Sequence[Bar], day: str) -> Dict[str, Any]:
    """當根不是 20 日新低，或後 3 根不破當根低。"""
    i = _idx(bars, day)
    empty = {"fire": False, "new20_low": None, "hold3": None}
    if i is None or i < 20:
        return empty
    cur = bars[i]
    lo = float(cur.get("low") or 0)
    prev20 = min(float(b.get("low") or 0) for b in bars[i - 20 : i])
    new20 = bool(lo > 0 and lo < prev20)
    nxt = bars[i + 1 : i + 4]
    hold3 = None
    if nxt:
        hold3 = all(float(b.get("low") or 0) >= lo * 0.995 for b in nxt)
    fire = (not new20) or (hold3 is True)
    return {
        "fire": bool(fire),
        "new20_low": new20,
        "hold3": hold3,
        "low": lo,
        "date": _ymd(cur.get("date")),
    }


def tx_witness(tx: Dict[str, Dict[str, Bar]], day: str) -> Dict[str, Any]:
    """夜盤低點先印出來＝夜盤領先。庫沒那日就空。"""
    d = _ymd(day)
    empty = {"fire": False, "night_first": None, "have": False}
    row = tx.get(d) or {}
    if not row:
        # 夜盤常掛前一日日期
        prev = (datetime.strptime(d, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d") if len(d) == 8 else ""
        row = tx.get(prev) or {}
        d = prev or d
    night = row.get("night") or {}
    regular = row.get("regular") or {}
    if not night or not regular:
        return empty
    nlo = float(night.get("low") or 0)
    rlo = float(regular.get("low") or 0)
    night_first = bool(nlo > 0 and rlo > 0 and nlo <= rlo + 5)
    return {
        "fire": night_first,
        "night_first": night_first,
        "have": True,
        "night_low": nlo,
        "regular_low": rlo,
        "date": d,
    }


def follow_twii(bars: Sequence[Bar], day: str, *, n: int = 20) -> Dict[str, Any]:
    i = _idx(bars, day)
    empty = {"hold": None, "ret": None, "n": 0, "low": None}
    if i is None:
        return empty
    cur = bars[i]
    lo = float(cur.get("low") or 0)
    cl = float(cur.get("close") or 0)
    nxt = bars[i + 1 : i + 1 + n]
    if not nxt or lo <= 0 or cl <= 0:
        return {**empty, "low": lo, "date": _ymd(cur.get("date"))}
    hold = all(float(b.get("low") or 0) >= lo * 0.995 for b in nxt)
    last = float(nxt[-1].get("close") or 0)
    ret = (last / cl - 1.0) * 100.0 if last else None
    return {
        "hold": hold,
        "ret": round(ret, 2) if ret is not None else None,
        "n": len(nxt),
        "low": lo,
        "date": _ymd(cur.get("date")),
    }


def score_day(
    day: str,
    *,
    twii: Sequence[Bar],
    tsmc: Sequence[Bar],
    sox: Sequence[Bar],
    tx: Dict[str, Dict[str, Bar]],
) -> Dict[str, Any]:
    t = tsmc_witness(tsmc, day)
    d0 = _ymd(day)
    if d0 and len(d0) == 8 and not t.get("fire"):
        for delta in (1, 2):
            try:
                prev = (datetime.strptime(d0, "%Y%m%d") - timedelta(days=delta)).strftime("%Y%m%d")
            except ValueError:
                break
            w = tsmc_witness(tsmc, prev)
            if w.get("fire"):
                t = {**w, "lead_days": delta}
                break
    s = sox_witness(sox, day)
    x = tx_witness(tx, day)
    f5 = follow_twii(twii, day, n=5)
    f20 = follow_twii(twii, day, n=20)
    fires = [k for k, w in (("tsmc", t), ("sox", s), ("tx", x)) if w.get("fire")]
    return {
        "date": _ymd(day),
        "aux_n": len(fires),
        "aux": fires,
        "tsmc": t,
        "sox": s,
        "tx": x,
        "twii5": f5,
        "twii20": f20,
    }


def claim_posts(posts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for p in posts or []:
        kind = classify_post(str(p.get("text") or ""))
        if not kind:
            continue
        day = _ymd(p.get("date"))
        aid = str(p.get("id") or "")
        key = (day, kind, aid)
        if not day or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "id": aid,
                "date": _dash(day),
                "kind": kind,
                "club": bool(p.get("club")),
                "snip": _clip(p.get("text") or "", 110),
            }
        )
    out.sort(key=lambda r: (r["date"], r["id"]))
    return out


def run_witness(
    posts: Sequence[Dict[str, Any]],
    *,
    twii: Optional[Sequence[Bar]] = None,
    tsmc: Optional[Sequence[Bar]] = None,
    sox: Optional[Sequence[Bar]] = None,
    tx: Optional[Dict[str, Dict[str, Bar]]] = None,
    fetch: bool = True,
    db_path: str = "",
) -> Dict[str, Any]:
    claims = [c for c in claim_posts(posts) if not c.get("club")]
    if fetch:
        twii = list(twii or []) or fetch_yahoo_ohlcv("^TWII", range_="2y")
        tsmc = list(tsmc or []) or fetch_yahoo_ohlcv("2330.TW", range_="2y")
        sox = list(sox or []) or fetch_yahoo_ohlcv("^SOX", range_="5y")
        tx = dict(tx or {})
        if db_path and not tx:
            tx.update(load_tx_from_db(db_path))
        months = sorted({_ymd(c["date"])[:6] for c in claims if _ymd(c["date"]) >= "20250201"})
        missing = [m for m in months if not any(str(k).startswith(m) for k in tx)]
        if missing:
            tx.update(fetch_tx_months(missing))
        if db_path:
            persist_tx_to_db(db_path, tx)
    twii, tsmc, sox = list(twii or []), list(tsmc or []), list(sox or [])
    tx = dict(tx or {})
    rows: List[Dict[str, Any]] = []
    for c in claims:
        scored = score_day(c["date"], twii=twii, tsmc=tsmc, sox=sox, tx=tx)
        rows.append({**c, **scored})

    def _agg(kind: str, pred) -> Dict[str, Any]:
        hit = [r for r in rows if r["kind"] == kind and pred(r)]
        with20 = [r for r in hit if r.get("twii20", {}).get("hold") is not None]
        hold = [r for r in with20 if r["twii20"]["hold"]]
        rets = [r["twii20"]["ret"] for r in with20 if r["twii20"].get("ret") is not None]
        return {
            "n": len(with20),
            "hold_pct": round(100.0 * len(hold) / len(with20), 1) if with20 else None,
            "mean_ret": round(sum(rets) / len(rets), 2) if rets else None,
        }

    stacked = _agg("confirm", lambda r: int(r.get("aux_n") or 0) >= 2)
    confirm_any = _agg("confirm", lambda r: True)
    prelim = _agg("prelim", lambda r: True)
    tsmc_fire = _agg("confirm", lambda r: bool((r.get("tsmc") or {}).get("fire")))
    gaps = {
        "twii": len(twii),
        "tsmc": len(tsmc),
        "sox": len(sox),
        "tx_days": len(tx),
        "tx_night": sum(1 for v in tx.values() if v.get("night")),
    }
    return {
        "source": "witness-4way",
        "n_claims": len(rows),
        "gaps": gaps,
        "confirm": confirm_any,
        "confirm_aux2": stacked,
        "confirm_tsmc": tsmc_fire,
        "prelim": prelim,
        "rows": rows[-80:],
        "now": live_from_series(twii, tsmc, sox, tx),
    }


def live_from_series(
    twii: Sequence[Bar],
    tsmc: Sequence[Bar],
    sox: Sequence[Bar],
    tx: Dict[str, Dict[str, Bar]],
) -> Dict[str, Any]:
    """用最新一根官方 K 推論：現在疊不疊得上確認。不准數沒有的 15 分。"""
    if not twii:
        return {"ok": False}
    last = twii[-1]
    day = _ymd(last.get("date"))
    scored = score_day(day, twii=twii, tsmc=tsmc, sox=sox, tx=tx)
    levels = {
        "45839": float(last.get("low") or 0) >= 45839,
        "46506": None,
        "47578": float(last.get("high") or 0) >= 47578,
    }
    # 46506 是台指期日盤低，不是加權
    tx_last = tx.get(day) or {}
    reg = tx_last.get("regular") or {}
    if reg.get("high"):
        levels["46506"] = float(reg.get("high") or 0) >= 46506
    return {
        "ok": True,
        "date": _dash(day),
        "twii_close": round(float(last.get("close") or 0), 2),
        "twii_low": round(float(last.get("low") or 0), 2),
        "aux_n": scored.get("aux_n"),
        "aux": scored.get("aux"),
        "tsmc": scored.get("tsmc"),
        "sox": scored.get("sox"),
        "tx": scored.get("tx"),
        "levels": levels,
        "infer": (
            "輔助疊得上、比較像確認窗"
            if int(scored.get("aux_n") or 0) >= 2
            else "官方四路還沒疊滿，主音不夠、還不到確認"
        ),
    }


def save_snapshot(blob: Dict[str, Any], path: str = "") -> str:
    dest = path or SNAPSHOT_JSON
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    slim = dict(blob)
    # 明細只留日期／種類／輔助數，正文不進 git 長檔
    slim["rows"] = [
        {
            "id": r.get("id"),
            "date": r.get("date"),
            "kind": r.get("kind"),
            "aux_n": r.get("aux_n"),
            "aux": r.get("aux"),
            "hold20": (r.get("twii20") or {}).get("hold"),
            "ret20": (r.get("twii20") or {}).get("ret"),
            "tsmc_fire": (r.get("tsmc") or {}).get("fire"),
            "sox_fire": (r.get("sox") or {}).get("fire"),
            "tx_have": (r.get("tx") or {}).get("have"),
        }
        for r in (blob.get("rows") or [])
    ]
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(slim, fh, ensure_ascii=False, indent=2)
    return dest


def write_md(blob: Dict[str, Any], path: str = "") -> str:
    dest = path or SNAPSHOT_MD
    g = blob.get("gaps") or {}
    c, c2, ct, p = blob.get("confirm") or {}, blob.get("confirm_aux2") or {}, blob.get("confirm_tsmc") or {}, blob.get("prelim") or {}
    now = blob.get("now") or {}
    lines = [
        "# 四路對質（加權／台積電量價／費半／台指期）",
        "",
        "新角度：不掃「向上」當確認。把他寫確認／初步／改口的日子，拿官方四路當證人。",
        "缺序列就抓 Yahoo 日 K＋期交所日／夜。夜盤 15 分用期交所成交聚柱，有柱只報高低仍不數段。某金融商品沒點名，不准寫死。不是買訊。",
        "",
        f"- 抓到：加權 {g.get('twii')} 根、台積電 {g.get('tsmc')} 根、費半 {g.get('sox')} 根、台指期 {g.get('tx_days')} 日（夜盤 {g.get('tx_night')}）",
        f"- 公開確認句樣本 {blob.get('n_claims')}（主文＋自回，社團不算）",
        f"- 確認句後 20 根加權沒再破低：{c.get('hold_pct')}%（n={c.get('n')}，均 {c.get('mean_ret')}%）",
        f"- 確認句且輔助≥2：{c2.get('hold_pct')}%（n={c2.get('n')}，均 {c2.get('mean_ret')}%）",
        f"- 確認句且台積電量價有火：{ct.get('hold_pct')}%（n={ct.get('n')}，均 {ct.get('mean_ret')}%）",
        f"- 初步／右肩觀盤後 20 根沒再破低：{p.get('hold_pct')}%（n={p.get('n')}，均 {p.get('mean_ret')}%）",
        "",
        "## 現在（最新官方日）",
        "",
        f"- 加權 {now.get('date')} 收 {now.get('twii_close')} 低 {now.get('twii_low')}",
        f"- 輔助點火 {now.get('aux_n')}：{', '.join(now.get('aux') or []) or '無'}",
        f"- 推論：{now.get('infer')}",
        "",
        "45839＝右肩低（加權）；46506＝台指期日盤低才算穿越；47578＝近波前高。沒過就不要升浪。",
        "",
        "**不進海選。**",
        "",
    ]
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return dest


def load_snapshot() -> Dict[str, Any]:
    if not os.path.isfile(SNAPSHOT_JSON):
        return {}
    with open(SNAPSHOT_JSON, encoding="utf-8") as fh:
        return json.load(fh) or {}


def format_witness_html(ask: str = "") -> str:
    blob = load_snapshot()
    now = blob.get("now") or {}
    c2 = blob.get("confirm_aux2") or {}
    p = blob.get("prelim") or {}
    bits = [
        "四路對質＝加權、台積電量價、費半、台指期夜盤。主音（波浪）他自己說不是 100%。"
        "確認句且輔助≥2 時，後 20 根加權沒再破低 "
        f"{c2.get('hold_pct')}%（n={c2.get('n')}）。"
        f"初步／右肩觀盤只有 {p.get('hold_pct')}%，不能當確認。"
    ]
    if now.get("ok"):
        bits.append(
            f"最新官方 {now.get('date')} 加權收 {now.get('twii_close')}，"
            f"輔助點火 {now.get('aux_n')}（{', '.join(now.get('aux') or []) or '無'}）。"
            f"{now.get('infer')}。46506 要用台指期日盤，不是加權。不是買訊。"
        )
    else:
        bits.append("官方四路這次還沒抓齊，不准假裝現在已確認。不是買訊。")
    return html_escape("".join(bits))


def load_tx_from_db(db_path: str) -> Dict[str, Dict[str, Bar]]:
    if not db_path or not os.path.isfile(db_path):
        return {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
    out: Dict[str, Dict[str, Bar]] = {}
    try:
        rows = conn.execute(
            "SELECT date, session, open, high, low, close, volume FROM futures_daily "
            "WHERE symbol='TX'"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for d, sess, o, h, lo, c, v in rows:
        day = _ymd(d)
        key = "night" if str(sess) == "night" else "regular"
        out.setdefault(day, {})[key] = {
            "date": day,
            "open": float(o or 0),
            "high": float(h or 0),
            "low": float(lo or 0),
            "close": float(c or 0),
            "volume": float(v or 0),
            "session": key,
        }
    return out


def persist_tx_to_db(db_path: str, tx: Dict[str, Dict[str, Bar]]) -> int:
    """把抓到的期貨日／夜寫進庫。pytest 不寫。失敗不編。"""
    if not db_path or os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    if not tx:
        return 0
    from taiwan_market import ensure_futures_daily_table

    ensure_futures_daily_table(db_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        for d, sess in tx.items():
            for key, row in (sess or {}).items():
                if not row.get("close"):
                    continue
                conn.execute(
                    """
                    INSERT INTO futures_daily(
                        date, symbol, session, open, high, low, close, volume, source, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(date, symbol, session) DO UPDATE SET
                        open=excluded.open, high=excluded.high, low=excluded.low,
                        close=excluded.close, volume=excluded.volume, updated_at=excluded.updated_at
                    """,
                    (
                        _ymd(d),
                        "TX",
                        key,
                        row.get("open") or 0,
                        row.get("high") or 0,
                        row.get("low") or 0,
                        row.get("close") or 0,
                        int(row.get("volume") or 0),
                        "taifex",
                        now,
                    ),
                )
                n += 1
        conn.commit()
    except sqlite3.Error:
        return n
    finally:
        conn.close()
    return n
