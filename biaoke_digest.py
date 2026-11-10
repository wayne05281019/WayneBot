# -*- coding: utf-8 -*-
"""飆大未讀：定時抓到的新文／樓下自回，未讀前重疊的只留最新，按進去看一口重點。

Telegram 鍵盤不能閃；未讀改寫在按鈕旁「飆大 3」。兩人分開計。
不進海選、不改黃金買點。社團不進。
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from tg_layout import html_escape

TAIPEI = ZoneInfo("Asia/Taipei")
_BTN = "飆大"
_CHART = re.compile(r"https://image\.cmoney\.tw/attachment/\S+", re.I)
_SPACE = re.compile(r"\s+")

_DDL = """
CREATE TABLE IF NOT EXISTS biaoke_inbox (
    post_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'post',
    date TEXT NOT NULL DEFAULT '',
    time TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    fetched_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS biaoke_reader (
    user_id TEXT PRIMARY KEY,
    last_read_at TEXT NOT NULL DEFAULT ''
);
"""


def taipei_now() -> datetime:
    return datetime.now(TAIPEI)


def _iso(now: Optional[datetime] = None) -> str:
    dt = now or taipei_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    return dt.astimezone(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S")


def ensure_biaoke_digest_tables(db_path: str) -> None:
    if not db_path:
        return
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()


def record_ingest_events(
    db_path: str,
    events: Sequence[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> int:
    """同一篇只留最新正文。沒改到的不寫，才不會把舊文當成未讀。"""
    if not db_path or not events:
        return 0
    ensure_biaoke_digest_tables(db_path)
    stamp = _iso(now)
    n = 0
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        for ev in events:
            pid = str(ev.get("post_id") or ev.get("id") or "").strip()
            text = _scrub_post_text(str(ev.get("text") or "")).strip()
            if not pid or not text:
                continue
            kind = str(ev.get("kind") or "post")
            date = str(ev.get("date") or "")
            time_s = str(ev.get("time") or "")
            body = text[:4000]
            prev = conn.execute(
                "SELECT text, kind, date, time FROM biaoke_inbox WHERE post_id=?",
                (pid,),
            ).fetchone()
            if prev and (
                str(prev[0] or "") == body
                and str(prev[1] or "") == kind
                and str(prev[2] or "") == date
                and str(prev[3] or "") == time_s
            ):
                continue
            conn.execute(
                """
                INSERT INTO biaoke_inbox(post_id, kind, date, time, text, fetched_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(post_id) DO UPDATE SET
                    kind=excluded.kind,
                    date=excluded.date,
                    time=excluded.time,
                    text=excluded.text,
                    fetched_at=excluded.fetched_at
                """,
                (pid, kind, date, time_s, body, stamp),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def unread_events(
    user_id: str,
    db_path: str,
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    uid = str(user_id or "").strip()
    if not uid or not db_path:
        return []
    ensure_biaoke_digest_tables(db_path)
    clock = now if now is not None else taipei_now()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=TAIPEI)
    else:
        clock = clock.astimezone(TAIPEI)
    floor = (clock - timedelta(days=14)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        row = conn.execute(
            "SELECT last_read_at FROM biaoke_reader WHERE user_id=?",
            (uid,),
        ).fetchone()
        last = str(row[0] or "") if row else ""
        if last:
            rows = conn.execute(
                """
                SELECT post_id, kind, date, time, text, fetched_at
                FROM biaoke_inbox
                WHERE fetched_at > ?
                ORDER BY date DESC, time DESC, post_id DESC
                """,
                (last,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT post_id, kind, date, time, text, fetched_at
                FROM biaoke_inbox
                ORDER BY date DESC, time DESC, post_id DESC
                """
            ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    out = []
    for r in rows:
        day = str(r[2] or "")
        if day and day < floor:
            continue
        out.append(
            {
                "post_id": r[0],
                "kind": r[1],
                "date": r[2],
                "time": r[3],
                "text": r[4],
                "fetched_at": r[5],
            }
        )
    return out


def unread_count(
    user_id: str,
    db_path: str,
    *,
    now: Optional[datetime] = None,
) -> int:
    return len(unread_events(user_id, db_path, now=now))


def mark_biaoke_read(user_id: str, db_path: str, *, now: Optional[datetime] = None) -> None:
    uid = str(user_id or "").strip()
    if not uid or not db_path:
        return
    ensure_biaoke_digest_tables(db_path)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            """
            INSERT INTO biaoke_reader(user_id, last_read_at) VALUES (?,?)
            ON CONFLICT(user_id) DO UPDATE SET last_read_at=excluded.last_read_at
            """,
            (uid, _iso(now)),
        )
        conn.commit()
    finally:
        conn.close()


def biaoke_button_label(user_id: str, db_path: str) -> str:
    """Telegram 鍵盤不能閃；未讀寫在兩個字後面。"""
    n = unread_count(user_id, db_path) if user_id else 0
    if n <= 0:
        return _BTN
    return f"{_BTN} {n}"


def normalize_biaoke_button(text: str) -> str:
    t = str(text or "").strip()
    if t == _BTN or t.startswith(_BTN + " ") or t.startswith(_BTN + "·"):
        rest = t[len(_BTN) :].strip(" ·")
        if not rest or rest.isdigit():
            return _BTN
    return t


def _oral_body(text: str, limit: int = 280) -> str:
    """口語裁切：優先在句號／問嘆號收束，不准半句「接下來會去測8…」這種斷字。"""
    s = _CHART.sub("（有圖）", text or "")
    s = _SPACE.sub(" ", s).strip()
    n = max(40, int(limit))
    if len(s) <= n:
        return s
    window = s[:n]
    best = -1
    for sep in ("。", "！", "？", "；", "…"):
        i = window.rfind(sep)
        if i >= max(24, n // 3):
            best = max(best, i)
    if best >= 0:
        return window[: best + 1]
    # 沒句號才退到頓號／空白，仍不准中間切開數字
    for sep in ("，", "、", " "):
        i = window.rfind(sep)
        if i >= max(24, n // 3):
            cut = window[:i].rstrip("，、 ")
            return cut + "…"
    return s[: n - 1] + "…"


_FWD_WEEKDAY = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}
_FWD_REL = re.compile(
    r"(下星期|下週|這星期|這週)?([一二三四五六日天])"
    r"|(明天|後天|今晚|明天晚上|明天早盤|明早)"
)


def _post_dt(date_s: str, time_s: str = "") -> Optional[datetime]:
    d = str(date_s or "").strip()
    t = str(time_s or "").strip() or "12:00"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", d)
    if not m:
        digits = re.sub(r"\D", "", d)
        if len(digits) >= 8:
            m = re.match(r"(\d{4})(\d{2})(\d{2})", digits)
    if not m:
        return None
    try:
        hh, mm = 12, 0
        tm = re.match(r"(\d{1,2}):(\d{2})", t)
        if tm:
            hh, mm = int(tm.group(1)), int(tm.group(2))
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)), hh, mm, tzinfo=TAIPEI
        )
    except ValueError:
        return None


def _forward_target_date(post_dt: datetime, sentence: str) -> Optional[datetime]:
    """從「下周一／周一／明天」推他當時指的日；推不出就不判過期。"""
    s = sentence or ""
    if "明天" in s or "明早" in s or "明天早" in s or "明天晚" in s:
        return (post_dt + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if "後天" in s:
        return (post_dt + timedelta(days=2)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if "今晚" in s:
        return post_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    # 周一／週一／下星期一／這週二…（「周」「週」都認）
    m = re.search(
        r"(下星期|下個星期|下週|下個週|這星期|這個星期|這週|這個週)?"
        r"(星期|週|周)?([一二三四五六日天])",
        s,
    )
    if not m:
        return None
    wd = _FWD_WEEKDAY.get(m.group(3))
    if wd is None:
        return None
    prefix = m.group(1) or ""
    base = post_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    delta = (wd - base.weekday()) % 7
    if prefix.startswith("下"):
        # 下週X＝下一個該曜日（不含當天）
        if delta == 0:
            delta = 7
    elif not prefix.startswith("這"):
        # 裸「周一」：盤後再講＝下一個該曜
        if delta == 0 and post_dt.hour >= 15:
            delta = 7
    return base + timedelta(days=delta)


_FWD_TRIGGER = re.compile(
    r"下星期|下個星期|下週|下個週|這星期|這週|"
    r"明天|後天|今晚|明早|"
    r"下周一|下週一|下周二|下週二|下周三|下週三|下周四|下週四|下周五|下週五|"
    r"星期[一二三四五六日天]|週[一二三四五六日天]|周[一二三四五六日天]"
)


def _forward_expired(
    target: Optional[datetime],
    today,
    clock: datetime,
    *,
    sentence: str = "",
) -> bool:
    if target is None:
        return False
    if target.date() < today:
        return True
    if target.date() != today:
        return False
    # 「今晚」＝當日夜盤窗，盤後到深夜仍有效；隔日才過期
    if "今晚" in (sentence or ""):
        return False
    # 其他「今天／周一＝今天」：過午盤（13:30）前瞻窗關閉
    if clock.hour > 13 or (clock.hour == 13 and clock.minute >= 30):
        return True
    return False


def _scrub_expired_forward(
    text: str,
    *,
    post_date: str = "",
    post_time: str = "",
    now: Optional[datetime] = None,
) -> str:
    """過期的「下周一／明天…」前瞻子句拿掉；同句裡仍有效的判斷要留。"""
    s = _SPACE.sub(" ", text or "").strip()
    if not s:
        return ""
    clock = now or taipei_now()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=TAIPEI)
    else:
        clock = clock.astimezone(TAIPEI)
    today = clock.date()
    post_dt = _post_dt(post_date, post_time) or clock

    def _keep_clause(bit: str) -> bool:
        bit = bit.strip()
        if not bit:
            return False
        # 「上星期／上週四」＝回顧已發生，不是前瞻；不准當過期句整段刪掉
        if re.search(r"上(星期|個星期|週|個週|周|個周)", bit):
            return True
        if not _FWD_TRIGGER.search(bit):
            return True
        return not _forward_expired(
            _forward_target_date(post_dt, bit),
            today,
            clock,
            sentence=bit,
        )

    # 先按句號切；句內若夾過期前瞻，再按逗號只丟過期子句
    sentences = re.split(r"(?<=[。！？；])", s)
    keep: List[str] = []
    for sent in sentences:
        bit = sent.strip()
        if not bit:
            continue
        if not _FWD_TRIGGER.search(bit):
            keep.append(bit)
            continue
        if ("，" in bit or "、" in bit) and len(bit) >= 12:
            clauses = re.split(r"(?<=[，、])", bit)
            kept_c = [c for c in clauses if _keep_clause(c)]
            if not kept_c:
                continue
            merged = "".join(kept_c).strip(" ，、")
            # 原句有句號結尾就補回，避免後面黏成一團
            if bit[-1] in "。！？；" and merged and merged[-1] not in "。！？；":
                merged += bit[-1]
            if merged:
                keep.append(merged)
            continue
        if _keep_clause(bit):
            keep.append(bit)
    out = "".join(keep).strip(" ，、")
    return _SPACE.sub(" ", out).strip()


def _reply_answer_line(
    text: str,
    reply_to: str = "",
    *,
    limit: int = 220,
) -> str:
    """自回要講清楚在答什麼；同學問句只留短引，不准整段蓋過他的判斷。"""
    spoken = _speak(text, limit)
    if not spoken:
        return ""
    ask = _SPACE.sub(" ", str(reply_to or "")).strip()
    ask = _CLASSMATE_QUOTE.sub("", ask)
    ask = _SPACE.sub(" ", ask).strip(" 「」\"“”")
    if not ask or len(ask) < 4:
        return spoken
    # 他文裡已引同學句就不再加「回」
    if ask[:12] in (text or ""):
        return spoken
    # 引號內不准留問嘆號：後面 _join_said／句切會被「？」切開，變成上文不接下文
    short = _oral_body(ask, 36).rstrip("…。？！?")
    short = re.sub(r"[？！?]", "", short).strip(" ，、")
    if not short:
        return spoken
    return f"回「{short}」：{spoken}"


_NOISE = re.compile(
    r"(打錯|很有心|出書|90%\s*老師|碩哥和我|蕭明道|楊少凱)"
)
_BOARD = re.compile(
    r"(夜盤|47578|C\s*波|B\s*[-‐‑‒–—]?c|B\s*波|頭部型態|大盤要漲|加權|逃命|45398|"
    r"目前大盤|緩步上攻|推升脈動|早盤要買|尾盤再考慮|調節股票|"
    r"大盤|台指期|頭肩底|中繼站|做多安全|"
    r"台股|股王|股后|"
    r"主跌|止跌|抄底|空手|減碼|48066|45000|47729|48697|49239|"
    r"47000|47600|47300|反彈不過壓|下降軌道|"
    r"下降壓力線|不可能假跌破|清洗籌碼|C\s*3)"
    # 不准用「回測／前波高點／主升段」當大盤鍵：個股（智邦回測季線）會誤吸進大盤欄
)
_FIELD = re.compile(
    r"(ASIC|散熱|光通訊|記憶體|多頭格局的族群|創意|健策|奇鋐|風向)"
)
_PCB = re.compile(r"(PCB|台光電|金像電|台燿|富喬|金居|ABF)")
_PREVIEW = re.compile(r"(星期[日天]晚上|技術分析看法)")
# 主文之後自回：做法／關卡／位階句才併進大盤口語（不准整段丟掉；也不准把閒聊全吸進來）
_BOARD_REPLY = re.compile(
    r"(C\s*波|B\s*[-‐‑‒–—]?c|B\s*波|主跌|止跌|抄底|空手|減碼|逃命|"
    r"下降軌道|反彈不過|做多安全|無止跌|破前低|"
    r"48066|45000|47729|48697|49239|47000|47600|47300|"
    r"下星期[一二]|星期二絕對|不要再介入|撤出觀望|"
    r"要去休息|反向下殺|不要亂下單|夜盤前|盈虧自負|洗盤|震盪往下)"
)
_NOISE_ONLY = re.compile(r"(出書|90%\s*老師|我自己都沒|說實話|看盤當下寫|很有心)")
# CMoney 頁面「加入 google 偏好」宣傳；不是他正文（他真講去 google 查型態另算）
_CMONEY_CHROME = re.compile(
    r"(?i)加入\s*google\s*偏好|google\s*偏好搜尋|將網站加入你的\s*google|"
    r"更容易搜尋到喜愛的內容"
)


# 同學問句常被他用引號包起來回；話筒只要他的判斷，不准把同學原話整段抄給使用者
_CLASSMATE_QUOTE = re.compile(
    r"[「\"“][^」\"”]{3,240}[」\"”]"
)
_CLASSMATE_LEAD = re.compile(
    r"^(請問|想請教|老師[，,]?|飆大[，,]?|學長[，,]?|這檔|那檔).{0,40}[？?]"
)


def _strip_classmate_echo(text: str) -> str:
    """去掉引號裡的同學問句／複述；只留他自己的答。"""
    s = str(text or "")
    if not s:
        return ""
    s = _CLASSMATE_QUOTE.sub(" ", s)
    kept: List[str] = []
    for ln in re.split(r"[\n]+", s):
        t = ln.strip()
        if not t:
            continue
        if _CLASSMATE_LEAD.search(t) and not re.search(
            r"(我認為|我覺得|目前|大盤|台指|波浪|量價|主跌|反彈)", t
        ):
            continue
        kept.append(t)
    return _SPACE.sub(" ", " ".join(kept)).strip()


def _scrub_post_text(text: str) -> str:
    try:
        from biaoke_ingest import scrub_cmoney_chrome

        raw = scrub_cmoney_chrome(text)
    except Exception:
        s = str(text or "")
        if not s:
            return ""
        kept = []
        for ln in s.splitlines():
            if _CMONEY_CHROME.search(ln):
                continue
            kept.append(ln)
        raw = "\n".join(kept).strip()
    return _strip_classmate_echo(raw)


def _norm_focus(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _drop_stale_sox_distance(text: str) -> str:
    """已改口「9865會破」後，拿掉同欄「還有一段距離」舊句，避免按鍵自相矛盾。"""
    s = str(text or "").strip()
    if not s:
        return ""
    # 句級清：同句同時講 9865＋還有一段距離
    parts = re.split(r"(?<=[。！？；])", s)
    kept: List[str] = []
    for part in parts:
        if re.search(r"9865", part) and re.search(r"還有一段距離|連9865都沒到", part):
            continue
        kept.append(part)
    out = _SPACE.sub(" ", "".join(kept)).strip(" ，,")
    return out


def _overlaps_shown(bit: str, shown: Sequence[str], *, min_chars: int = 10) -> bool:
    """句／段是否已在大盤／族群／PCB（或已收進他還說）出現過。

    短句（「要去休息了…」約 17 字）也要算重疊；舊門檻 20 會漏掉，話筒就重複貼。
    """
    n = _norm_focus(bit)
    if len(n) < max(6, int(min_chars)):
        return False
    for s in shown:
        t = _norm_focus(s)
        if not t:
            continue
        if n == t or n in t or t in n:
            return True
        head = min(28, len(n), len(t))
        if head >= 10 and n[:head] == t[:head]:
            return True
    return False


def _strip_shown_sentences(bit: str, shown: Sequence[str]) -> str:
    """一則樓下前半複述大盤、後半才是新話 → 只留新句。

    整段已是大盤／已示欄子集 → 直接空（不准再把開頭短句貼進「他還說」）。
    """
    s = str(bit or "").strip()
    if not s:
        return ""
    n = _norm_focus(s)
    for raw in shown:
        t = _norm_focus(raw)
        if not t:
            continue
        # 完全相同、或這段已整包出現在已示欄 → 不重複
        if n == t or (len(n) >= 10 and n in t):
            return ""
    if not _overlaps_shown(s, shown, min_chars=10):
        return s
    parts = [p.strip(" ，、") for p in re.split(r"[。！？；]", s) if p.strip()]
    keep: List[str] = []
    for p in parts:
        if len(_norm_focus(p)) < 8:
            continue
        if _overlaps_shown(p, shown, min_chars=8) or _overlaps_shown(
            p, keep, min_chars=8
        ):
            continue
        keep.append(p)
    if not keep:
        return ""
    out = "。".join(keep)
    if not out.endswith("。"):
        out += "。"
    # 掐完若仍只是已示欄的開頭複述，丟掉
    if _overlaps_shown(out, shown, min_chars=10) and len(_norm_focus(out)) <= max(
        (len(_norm_focus(x)) for x in shown if x), default=0
    ):
        on = _norm_focus(out)
        for raw in shown:
            t = _norm_focus(raw)
            if t and (on in t or on == t):
                return ""
    return out


def _join_said(parts: Sequence[str], *, shown: Sequence[str]) -> str:
    keep: List[str] = []
    seen = list(shown)
    for x in parts:
        s = _strip_shown_sentences(str(x or "").strip(), seen)
        if not s:
            continue
        keep.append(s)
        seen.append(s)
    return " ".join(x.rstrip("。") + "。" for x in keep).strip()


def _speak(text: str, limit: int = 220) -> str:
    """口語重述：像教沒底子的人講一遍；只留他的判斷，不抄同學原話。"""
    s = _scrub_post_text(text or "")
    s = _CHART.sub("（有圖）", s)
    s = _SPACE.sub(" ", s).strip()
    s = s.replace("2024/10~2025/02", "2024年10月到2025年2月")
    s = s.replace("2024/10～2025/02", "2024年10月到2025年2月")
    s = re.sub(r"我這周末比較忙", "這周末比較忙", s)
    s = re.sub(r"星期[日天]晚上我發一篇", "星期天晚上會發一篇", s)
    s = re.sub(r"^從夜盤反彈", "夜盤已經彈", s)
    s = re.sub(r"不過這次大盤要漲到目標點位一定要過", "不過要漲到他講的目標，一定要過", s)
    s = re.sub(r"目前唯一在多頭格局的族群就是", "現在唯一還在多頭的是", s)
    s = re.sub(
        r"因為現在追蹤我的人數過多，我已經無法像以前那樣公開點名",
        "追的人太多就不再公開點名",
        s,
    )
    s = re.sub(r"未來不是再一次出現這一次大修正，或者走", "後面不是再來一次大修正，就是走出", s)
    s = re.sub(r"做一個大的頭部型態出來", "那種大頭部", s)
    # 他回同學時常先寫 Yes／對，後面才是重點
    s = re.sub(r"^(Yes|YES|yes|對|是的|正確)[，,\s]+", "", s)
    s = _SPACE.sub(" ", s).strip()
    s = re.sub(r"^我+", "", s)
    parts = [p.strip(" ，、") for p in re.split(r"[。！？；]", s) if p.strip()]
    keep: List[str] = []
    for p in parts:
        if _CMONEY_CHROME.search(p):
            continue
        if _NOISE_ONLY.search(p) and not re.search(r"(47578|ASIC|PCB|台光電|夜盤|頭部)", p):
            continue
        if _CLASSMATE_LEAD.search(p):
            continue
        if len(p) < 6:
            continue
        keep.append(p)
        if len(keep) >= 4:
            break
    out = "。".join(keep)
    if out and not out.endswith("。"):
        out += "。"
    return _oral_body(out or s, limit)


def _plain_wave_now_phrase(now: str) -> str:
    """波浪位階『目前落在』一句人話；不准只丟代號讓人猜。"""
    n = str(now or "").strip()
    if not n:
        return ""
    if n == "C內橫台中繼":
        return "大C下跌裡的橫盤中繼（暫時橫著，還沒宣告止跌）"
    if n == "C內主跌":
        return "大C裡的主跌段"
    if n == "C3-3主跌":
        return "大C裡的 C3-3 主跌"
    if re.match(r"C3-3-\d$", n):
        return f"大C細浪 {n}（超近窗那張）"
    if n == "C3-5":
        return "大C裡的 C3-5（第二組下跌脈動）"
    if n == "C3":
        return "大C 的 C3 段"
    if n == "大C進行中":
        return "大C下跌進行中"
    if n == "9波擴延":
        return "大C第二段下殺・9波擴延"
    if n in ("C-7轉C-8", "C-7走完→C-8", "C-8"):
        return "9波擴延：目前最有可能 C-7轉C-8；還有最後一小段 C-9"
    if n == "C-7":
        return "9波擴延：C-7（接著八先上，後面還有九）"
    if n == "C-9":
        return "9波擴延最後一小段 C-9（跌完＝這段下殺完）"
    if n in ("第二隻腳", "等第二隻腳"):
        return "夜盤跌完居多；低點最多 37000~37500；等反彈後拉回 1-2轉1-3-1 第二隻腳"
    if n in ("主B-b／備九波", "B-b雙軌", "主B-b"):
        return "主線五波跌完走 B-b（假跌破 37837 觀察）；備線若九波擴延 → 35579→31705"
    if n in ("止跌確認・已過C3下降壓", "已過C3下降壓"):
        return (
            "他說已過 C3 下降壓（口述斜線・圖上未標 C3／無報價）；"
            "週五低不再假跌破；水平台指壓 41760 另計（≠那條口述下降壓）"
        )
    if n in ("止跌確認・再測週五低", "止跌確認"):
        return "C3-5＋1 4重疊・確認上週五低＝最低；接下來再測週五低／假跌破觀察"
    return n


def format_teach_brief(db_path: str = "") -> str:
    """波浪位階開場敘述：現在走到哪／怎麼看／盯著的價。給人讀，不准術語叠句。

    只服務「波浪位階」鍵。飆大空白鍵走 format_focus_oral。
    重點＝他最新講的走勢與點位（後文壓前文）；非買訊。
    失敗回空，不准擋主摘要。不准寫英文 as_of。
    """
    if not db_path:
        return ""
    try:
        from biaoke_level_learn import _build_live_pack, _wave_now_ladder

        pack = _build_live_pack(db_path) or {}
    except Exception:
        return ""
    thesis = str(pack.get("thesis") or "").strip()
    morph = str(pack.get("morph_note") or "").strip()
    intent = str(pack.get("intent_note") or "").strip()
    fib = str(pack.get("fib_note") or "").strip()
    wait = str(pack.get("wait_struct") or "").strip()
    if not (thesis or intent or morph or pack.get("pred_note")):
        return ""
    try:
        ladder = _wave_now_ladder(pack)
    except Exception:
        ladder = {}
    lines: List[str] = ["<b>波浪位階・預估・非買訊</b>", ""]
    now = str(ladder.get("now") or "").strip()
    day_zh = str(ladder.get("day_zh") or "").strip()
    lines.append("<b>現在</b>")
    _pressure_break = (
        "不再假跌破" in thesis
        or "過C3下降壓" in thesis
        or "已過C3下降壓" in now
        or "回測下降壓力線" in wait
        or "清洗籌碼" in wait
    )
    _stop_confirm = (not _pressure_break) and (
        "確認上週五低" in thesis
        or "1 4重疊" in thesis
        or "止跌確認" in thesis
        or "止跌確認" in now
        or "再測週五" in now
        or "台指壓41760" in wait
        or "一定再測週五低" in wait
    )
    _bb_dual = (not _pressure_break) and (not _stop_confirm) and (
        "B-b" in thesis
        or "五波跌完" in thesis
        or "備線九波" in thesis
        or "假跌破37837" in wait
        or "35579→31705" in wait
    )
    _foot2_brief = (not _pressure_break) and (not _stop_confirm) and (
        "第二隻腳" in thesis
        or "等第二隻腳" in thesis
        or "37000~37500" in wait
        or "37000-37500" in wait
        or "看不到37000" in wait
    )
    # 一條路＋目前落在哪；不准再叠「大A→大B→…→落在」兩段重複
    if _pressure_break:
        lines.append(
            html_escape("大盤：大A底（7/29）→ 大B反彈 → 大C進行中（他已講止跌・下降壓改口）。")
        )
        lines.append(
            html_escape(
                "他最新：夜盤過第二組 C3 下降壓（他口述的斜線；圖上沒單獨標 C3、也無報價），"
                "上週五低不再假跌破；拉回再測那條下降壓／清洗籌碼。"
                "水平台指壓 41760 另計（≠那條口述下降壓；非買訊）。"
            )
        )
    elif _stop_confirm:
        lines.append(
            html_escape("大盤：大A底（7/29）→ 大B反彈 → 大C進行中（他已講止跌確認）。")
        )
        lines.append(
            html_escape(
                "他最新：C3-5＋1 4重疊，確認上週五低＝最低；"
                "一定再測週五低，破＝假跌破觀察（非買訊）。"
            )
        )
    else:
        lines.append(html_escape("大盤：大A底（7/29）→ 大B反彈 → 大C下跌中。"))
    if _bb_dual:
        lines.append(
            html_escape(
                "主線：五波跌完走 B-b（假跌破 37837 觀察）；"
                "備線：若九波擴延 → 35579→31705。未定案前雙軌並陳（非買訊）。"
            )
        )
    elif _foot2_brief:
        lines.append(
            html_escape(
                "夜盤來看跌完居多；目前應該看不到 37000 以下；"
                "低點最多 37000~37500；等反彈後拉回 1-2轉1-3-1 第二隻腳（他口語路徑・非買訊）。"
            )
        )
    elif (not _stop_confirm) and (not _pressure_break) and (
        "9波擴延" in thesis
        or "C-7轉C-8" in thesis
        or "C-7走完" in thesis
        or "準備往八" in thesis
    ):
        lines.append(
            html_escape(
                "第二段下殺走 9 波擴延：目前最有可能 C-7轉C-8；"
                "還有最後一小段下跌 C-9，要跌就全部跌完；低點約會落在 35500~37300。"
            )
        )
    if now:
        sit = f"目前落在：{_plain_wave_now_phrase(now)}"
        if day_zh:
            sit += f"（題旨 {day_zh}）"
        lines.append(html_escape(sit))
    elif thesis:
        lines.append(html_escape(thesis))
    struct_bits: List[str] = []
    if fib and not (_stop_confirm or _pressure_break):
        # 止跌／下降壓當令時，反彈壓舊句不准蓋最新點位
        fib_s = re.sub(r"^黃金切割反彈壓\s*", "", fib).strip() or fib
        struct_bits.append(f"· 反彈壓：{fib_s}")
    elif fib and (_stop_confirm or _pressure_break):
        pass
    if morph and not (_stop_confirm or _pressure_break):
        morph_s = morph.replace("；", "；").strip()
        struct_bits.append(f"· 型態：{morph_s}")
    if intent:
        one = intent.split("；")[0].strip()
        if one and "還不清楚" not in one:
            struct_bits.append(f"· 量：{one}")
    if wait:
        one_w = re.split(r"[；。]", wait)[0].strip()
        if one_w:
            # 「中繼後原方向」補一句人話
            if one_w in ("中繼後原方向", "中繼後走原方向"):
                one_w = "中繼結束後，多半續走原來的下跌方向"
            elif re.search(r"低點區\s*37000", one_w):
                one_w = "低點最多 37000~37500；看不到 37000 以下；等第二隻腳"
            elif re.search(r"低點區\s*35500", one_w):
                one_w = "低點約會落在 35500~37300；C-9 跌完＝這段下殺完"
            elif re.search(r"C-7(?:轉|走完).{0,8}C-8→C-9|C-7走完→C-8→C-9", one_w):
                one_w = "七走完≠整段完；八先上、再九最後下；九跌完＝這段下殺完"
            elif _pressure_break or re.search(
                r"回測下降壓力線|清洗籌碼|資金可\s*5\s*~\s*6\s*成", wait
            ):
                # 整段 wait：斜線回測 ≠ 水平41760；不准誤寫回「再測假跌破」
                one_w = (
                    "拉回回測下降壓力線（口述斜線・圖上未標C3／無報價）；"
                    "清洗籌碼；資金可 5~6 成"
                )
                if re.search(r"41760", wait):
                    one_w = "水平台指壓 41760（≠那條口述下降壓）；" + one_w
            elif re.search(r"台指壓\s*41760|一定再測週五低", one_w):
                one_w = "台指壓 41760；一定再測週五低；破＝假跌破觀察"
            struct_bits.append(f"· 下一步：{one_w}")
    if struct_bits:
        lines.append("")
        lines.append("<b>怎麼看</b>")
        for bit in struct_bits:
            lines.append(html_escape(bit))
    pred_note = str(pack.get("pred_note") or "").strip()
    pred = pack.get("pred_levels") or {}
    if not pred_note:
        bits = []
        for row in (pred.get("tw") or []) + (pred.get("sox") or []):
            lab = str((row or {}).get("label") or "").strip()
            if lab:
                bits.append(lab)
            if len(bits) >= 6:
                break
        pred_note = "｜".join(bits)
    # 改口／C9 低點區優先寫成看得懂的區間句（兩端都是他原文；改口壓 C9）
    foot_hi = foot_lo = c9_hi = c9_lo = None
    for row in pred.get("tw") or []:
        role = str((row or {}).get("role") or "")
        try:
            lv = float((row or {}).get("level"))
        except (TypeError, ValueError):
            continue
        if role == "改口低上沿" or abs(lv - 37500.0) < 1.0:
            foot_hi = lv
        elif role == "改口低下沿" or abs(lv - 37000.0) < 1.0:
            foot_lo = lv
        elif role == "C9低上沿" or abs(lv - 37300.0) < 1.0:
            c9_hi = lv
        elif role == "C9低下沿" or abs(lv - 35500.0) < 1.0:
            c9_lo = lv
    if _stop_confirm or _pressure_break:
        # 止跌／下降壓當令：不准再用舊改口／C9 區間句蓋最新盯價
        foot_lo = foot_hi = c9_lo = c9_hi = None
    if foot_lo is not None and foot_hi is not None:
        c9_lo = c9_hi = None  # 改口壓 C9 區間句
    zone_lo, zone_hi = (
        (foot_lo, foot_hi)
        if foot_lo is not None and foot_hi is not None
        else (c9_lo, c9_hi)
    )
    if pred_note or (zone_lo is not None and zone_hi is not None):
        bits = []
        if zone_lo is not None and zone_hi is not None:
            if foot_lo is not None:
                bits.append(f"改口低點區 {int(zone_lo)}~{int(zone_hi)}")
            else:
                bits.append(f"C-9低點區 {int(zone_lo)}~{int(zone_hi)}")
        for raw in re.split(r"[｜|]", pred_note):
            bit = raw.strip()
            if not bit:
                continue
            if re.search(r"周一破|週一破|明日|明天", bit):
                bit = re.sub(r"(周一|週一)破", "破", bit)
                bit = re.sub(r"(明日|明天)", "", bit).strip(" ・")
            # 「飆預測45,546」保留數字，拿掉重複前綴堆叠可讀性
            bit = re.sub(r"^飆預測\s*", "", bit).strip() or bit
            # 舊劇本一 38000 上沿：有修訂低點區時改寫成已破
            if zone_lo is not None and re.search(r"38000.*劇本一上沿|38000$", bit):
                bit = "38000已破"
            if re.search(r"改口低|37000|37500", bit) and (
                foot_lo is not None or _stop_confirm or _pressure_break
            ):
                continue
            if re.search(r"C9低|35500|37300", bit) and (
                foot_lo is not None
                or c9_lo is not None
                or _stop_confirm
                or _pressure_break
            ):
                continue
            # 止跌／下降壓當令：舊雙軌深殺備線不准蓋最新盯價
            if (_stop_confirm or _pressure_break) and re.search(
                r"35579|31705|AI結束", bit
            ):
                continue
            # 下降壓改口當令：舊「再測週五低／假跌破」標不准再掛
            # 但「不再假跌破」是新標，要留
            if _pressure_break and re.search(r"再測週五|假跌破", bit):
                if "不再假跌破" not in bit:
                    continue
            if bit and bit not in bits:
                bits.append(bit)
            if len(bits) >= 5:
                break
        if bits:
            lines.append("")
            lines.append("<b>盯著的價（他講過）</b>")
            lines.append(html_escape("｜".join(bits)))
    return "\n".join(lines)


def format_wave_level_one_liner(db_path: str = "") -> str:
    """飆大空白鍵用：只附一層級對照句，細節請按波浪位階。"""
    if not db_path:
        return ""
    try:
        from biaoke_level_learn import _build_live_pack, _wave_now_ladder

        pack = _build_live_pack(db_path) or {}
        ladder = _wave_now_ladder(pack)
    except Exception:
        return ""
    now = str(ladder.get("now") or "").strip()
    if not now:
        return ""
    plain = _plain_wave_now_phrase(now) or now
    return html_escape(f"大盤現在落在「{plain}」（細節按「波浪位階」・非買訊）")


def _when_short(date: str, time_s: str) -> str:
    d = str(date or "").strip()
    t = str(time_s or "").strip()
    day = d
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", d)
    if m:
        day = f"{int(m.group(2))}/{int(m.group(3))}"
    if not t:
        return day
    try:
        h = int(t[:2])
    except ValueError:
        h = -1
    if h >= 18:
        tod = "晚上"
    elif h >= 12:
        tod = "下午"
    elif h >= 5:
        tod = "早上"
    elif h >= 0:
        tod = "凌晨"
    else:
        tod = ""
    clock = t[:5] if len(t) >= 5 else t
    bits = [x for x in (day, tod, clock) if x]
    return " ".join(bits)


def _row_key(p: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(p.get("date") or ""),
        str(p.get("time") or ""),
        str(p.get("post_id") or p.get("id") or ""),
    )


def _noise_reply(text: str) -> bool:
    s = _SPACE.sub(" ", text or "").strip()
    if len(s) < 6:
        return True
    # 名字本身不是整則作廢。同一則裡有部位、空方、波浪，仍然是他的回文。
    if _NOISE.search(s) and not re.search(
        r"(PCB|台光電|夜盤|47578|ASIC|整理|錯殺|空股票|出清|波浪|修正|台指|持股)",
        s,
    ):
        return True
    return False


def _numbered_bits(text: str) -> List[str]:
    raw = _SPACE.sub(" ", text or "").strip()
    raw = re.sub(r"^重要留言看法分享\s*", "", raw)
    # 「1. …。2. …」句號後常直接接下一號；用 lookbehind 保住前句句號
    parts = re.split(r"(?:(?<=^)|(?<=[\s。；]))\d+\.\s+", raw)
    bits = [p.strip().rstrip("。") for p in parts if p and len(p.strip()) >= 6]
    if len(bits) >= 2:
        return bits
    return [raw] if raw else []


def _scrub_stale_fake_break_retest(text: str) -> str:
    """下降壓改口之後：拿掉過期「再測週五低／假跌破」子句，留其餘仍有效句。"""
    s = _SPACE.sub(" ", str(text or "")).strip()
    if not s:
        return ""
    # 整句若主軸就是再測假跌破，整句丟
    drop = re.compile(
        r"(?:接下來)?還會再去測星期五低點一次|"
        r"一定再測週五低|"
        r"頂多在測一次低破星期五低點假跌破|"
        r"破不破，跌破上星期五低點是假跌破|"
        r"跌破上星期五低點是假跌破|"
        r"破＝假跌破觀察|"
        r"再測一次假跌破"
    )
    parts = re.split(r"(?<=[。！？；])", s)
    keep: List[str] = []
    for part in parts:
        bit = part.strip()
        if not bit:
            continue
        if drop.search(bit) and not re.search(
            r"不可能假跌破|不再假跌破|下降壓力線", bit
        ):
            # 句內若還有其他大盤判斷，只剁過期子句
            if "，" in bit or "、" in bit:
                clauses = re.split(r"(?<=[，、])", bit)
                kept_c = [
                    c
                    for c in clauses
                    if c.strip()
                    and not drop.search(c)
                ]
                if kept_c:
                    merged = "".join(kept_c).strip(" ，、")
                    if bit[-1] in "。！？；" and merged and merged[-1] not in "。！？；":
                        merged += bit[-1]
                    if merged:
                        keep.append(merged)
                continue
            continue
        keep.append(bit)
    return _SPACE.sub(" ", "".join(keep)).strip(" ，、")


def _apply_pressure_break_oral_to_board(
    board: str,
    *,
    blob: str = "",
    db_path: str = "",
    now: Optional[datetime] = None,
) -> str:
    """飆大欄：下降壓改口當令時，壓過期假跌破句並補最新第4點（只認他文／口頭）。"""
    try:
        from biaoke_level_learn import (
            _PRESSURE_BREAK_ORAL_AS_OF,
            _PRESSURE_BREAK_ORAL_SNIP,
            _ensure_pressure_break_oral_thesis_snap,
            _find_pressure_break_snip,
            _text_has_c3_pressure_break,
        )
    except Exception:
        return board
    clock = now or taipei_now()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=TAIPEI)
    else:
        clock = clock.astimezone(TAIPEI)
    day = clock.strftime("%Y%m%d")
    if day < _PRESSURE_BREAK_ORAL_AS_OF:
        return board
    pb = ""
    if _text_has_c3_pressure_break(blob) or _text_has_c3_pressure_break(board):
        pb = board if _text_has_c3_pressure_break(board) else ""
        if not pb and _text_has_c3_pressure_break(blob):
            # 從 blob 抽含下降壓的那段
            for sent in re.split(r"(?<=[。！？；\n])", blob):
                if _text_has_c3_pressure_break(sent):
                    pb = _SPACE.sub(" ", sent).strip()
                    break
            if not pb:
                pb = _PRESSURE_BREAK_ORAL_SNIP
    if db_path and not pb:
        try:
            _ensure_pressure_break_oral_thesis_snap(db_path, as_of=day)
            pb = _find_pressure_break_snip(db_path, day) or ""
        except Exception:
            pb = ""
    if not pb and day >= _PRESSURE_BREAK_ORAL_AS_OF:
        pb = _PRESSURE_BREAK_ORAL_SNIP
    if not pb or not _text_has_c3_pressure_break(pb):
        return board
    cleaned = _scrub_stale_fake_break_retest(board)
    # 大盤欄開頭先講改口，再接其餘仍有效句（不准重複贴同一段）
    lead = _speak(pb, 280)
    if not lead:
        return cleaned
    if cleaned and lead[:24] in cleaned:
        return cleaned
    if cleaned:
        return f"{lead} {cleaned}".strip()
    return lead


def format_focus_oral(
    mains: Sequence[Dict[str, Any]],
    replies: Sequence[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    db_path: str = "",
    stock_links: bool = True,
    include_gates: bool = False,
) -> str:
    """空白按飆大：口語重述最新重點＋智囊團活用。不准倒原文、不准時間跳來跳去。

    stock_links=False（話筒空白鍵）：不准文內個股藍字／可點清單。
    include_gates=True：附他自己點過的加權／台指關 × 最新官方已收對照。
    """
    clock = now
    if clock is not None:
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=TAIPEI)
        else:
            clock = clock.astimezone(TAIPEI)
    else:
        clock = taipei_now()
    cleaned_mains: List[Dict[str, Any]] = []
    for p in mains:
        row = dict(p)
        raw = _scrub_post_text(str(row.get("text") or ""))
        row["text"] = _scrub_expired_forward(
            raw,
            post_date=str(row.get("date") or ""),
            post_time=str(row.get("time") or ""),
            now=clock,
        )
        if str(row.get("text") or "").strip():
            cleaned_mains.append(row)
    if not cleaned_mains:
        return ""
    mains = sorted(cleaned_mains, key=_row_key, reverse=True)
    cleaned_replies: List[Dict[str, Any]] = []
    for p in replies:
        if str(p.get("kind") or "") == "bystander":
            continue
        row = dict(p)
        raw = _scrub_post_text(str(row.get("text") or ""))
        row["text"] = _scrub_expired_forward(
            raw,
            post_date=str(row.get("date") or ""),
            post_time=str(row.get("time") or ""),
            now=clock,
        )
        # reply_to＝同學／樓問句，要留著標「回什麼」；不准走 _scrub_post_text
        # （那條會依 _CLASSMATE_LEAD 把「老師…？」整段清掉）
        ask_raw = _SPACE.sub(" ", str(row.get("reply_to_text") or "")).strip()
        try:
            from biaoke_ingest import scrub_cmoney_chrome

            ask_raw = scrub_cmoney_chrome(ask_raw)
        except Exception:
            ask_raw = _CMONEY_CHROME.sub(" ", ask_raw)
        row["reply_to_text"] = _SPACE.sub(" ", ask_raw).strip()
        t = str(row.get("text") or "").strip()
        if t and not _noise_reply(t):
            cleaned_replies.append(row)
    replies = sorted(cleaned_replies, key=_row_key, reverse=True)
    latest = mains[0]
    when_p = latest
    if replies and _row_key(replies[0]) > _row_key(latest):
        when_p = replies[0]
    when = _when_short(str(when_p.get("date") or ""), str(when_p.get("time") or ""))
    board = ""
    field = ""
    pcb = ""
    preview = ""
    spare: List[str] = []
    extra: List[str] = []
    after_board: List[str] = []
    older_long = False
    newer_short = False
    for bit in _numbered_bits(str(latest.get("text") or "")):
        if not board and _BOARD.search(bit):
            board = _speak(bit, 420)
        elif not field and _FIELD.search(bit):
            field = _speak(bit, 200)
        elif not pcb and _PCB.search(bit):
            pcb = _speak(bit, 200)
        else:
            spare.append(_speak(bit, 200))
    # 大盤欄只認最新主文；舊主文不准回填把「現在在講」鎖在更早一天。
    if not board:
        board = _speak(str(latest.get("text") or ""), 420)
    for p in mains[1:]:
        t = str(p.get("text") or "")
        if re.search(r"整理三個月|全面減碼", t):
            older_long = True
        # 最近兩則都要對齊：前一則主文重點進「他還說」，不准整則丟掉。
        prior = _speak(t, 140)
        if prior:
            spare.append(prior)
        if not field:
            for bit in _numbered_bits(t):
                if _FIELD.search(bit) and not _BOARD.search(bit):
                    field = _speak(bit, 120)
                    break
    latest_day = str(latest.get("date") or "")
    for p in replies:
        t = str(p.get("text") or "")
        if _PREVIEW.search(t) and not preview:
            preview = _speak(t, 140)
            continue
        if "閱讀障礙" in t:
            continue
        if re.search(r"比ABF短|錯殺", t):
            newer_short = True
            pcb = _reply_answer_line(
                t, str(p.get("reply_to_text") or ""), limit=160
            ) or _speak(t, 140)
            continue
        if not pcb and _PCB.search(t):
            pcb = _reply_answer_line(
                t, str(p.get("reply_to_text") or ""), limit=160
            ) or _speak(t, 140)
            continue
        day = str(p.get("date") or "")
        if day and latest_day and day < latest_day:
            continue
        # 最新主文之後的自回：大盤／關卡／空手句併大盤欄；其餘自回（含回別人）進「他還說」。
        # 有 reply_to 要標他在回什麼，不准上文不接下文。
        if _row_key(p) >= _row_key(latest):
            bit = _reply_answer_line(
                t, str(p.get("reply_to_text") or ""), limit=220
            )
            if not bit:
                continue
            if _BOARD_REPLY.search(t):
                after_board.append(bit)
            else:
                extra.append(bit)
            continue
        extra.append(
            _reply_answer_line(t, str(p.get("reply_to_text") or ""), limit=160)
        )
    if older_long and newer_short:
        pcb = (
            "前一天還說台光電至少整理三個月、PCB 全面減碼；"
            "晚上改口，整理時間會比 ABF 短很多，昨天錯殺居多，下波可能還是漲的主流。"
        )
    latest_t = str(latest.get("text") or "")
    if board and re.search(r"(否則|如果|一定要過)", board + latest_t) and "如果句" not in board:
        board = board.rstrip("。") + "。這句還是如果句，不是已確認主升。"
    # 下降壓改口：庫／口頭已確認時，壓掉過期「再測週五低假跌破」，並補進最新第4點
    _pb_blob = " ".join(
        x
        for x in (
            board,
            latest_t,
            *(str(p.get("text") or "") for p in mains[:3]),
            *(str(p.get("text") or "") for p in replies[:6]),
        )
        if x
    )
    board = _apply_pressure_break_oral_to_board(
        board,
        blob=_pb_blob,
        db_path=str(db_path or ""),
        now=clock,
    )
    # 主文後大盤自回併進大盤欄（口語一句接一句；同義短句不准另開「他還說」）
    if after_board:
        merged = _join_said([board] + after_board[:6], shown=[])
        if merged:
            board = merged
    shown = [x for x in (board, field, pcb) if x]
    # 他還說＝主文沒進上面三欄的補充＋樓下；已講過的大盤／族群／PCB 整段丟掉
    said = _join_said([preview] + spare[:2] + extra[:3], shown=shown)
    # 下降壓當令：他還說／備援句也不准再留過期再測假跌破
    try:
        from biaoke_level_learn import _text_has_c3_pressure_break

        if _text_has_c3_pressure_break(board) or _text_has_c3_pressure_break(_pb_blob):
            said = _scrub_stale_fake_break_retest(said)
            # 黃金脈絡用的主文也同步清過期句，不准又把假跌破貼回來
            for row in cleaned_mains:
                row["text"] = _scrub_stale_fake_break_retest(str(row.get("text") or ""))
    except Exception:
        pass
    # 再保險：他還說若只是大盤欄開頭複述，整欄拿掉（智慧融合，不重複唸）
    if said and board and _overlaps_shown(said, [board], min_chars=10):
        said2 = _strip_shown_sentences(said, [board])
        said = said2
    # 後句改口壓前：已說「9865會破」就不准再留「還有一段距離」（開盤按鍵不准自相矛盾）
    blob_all = " ".join(x for x in (board, said, *(extra or []), *(after_board or [])) if x)
    if re.search(r"9865\s*會破|會破.{0,6}9865", blob_all):
        board = _drop_stale_sox_distance(board)
        said = _drop_stale_sox_distance(said)
    blocks: List[str] = [
        "<b>飆大現在在講</b>",
        html_escape(f"最新　{when}" if when else "最新"),
    ]
    # 文內藍字僅非空白鍵路徑；空白鍵只出口語＋關卡表（2026-10-24）
    match_pack: Dict[str, Any] = {}
    if stock_links:
        try:
            if db_path:
                from biaoke_live_match import refresh_live_match

                match_pack = refresh_live_match(str(db_path)) or {}
        except Exception:
            match_pack = {}

    def _add(title: str, body: str) -> None:
        if not body:
            return
        blocks.append("")
        blocks.append(f"<b>{html_escape(title)}</b>")
        if stock_links and db_path:
            try:
                from biaoke_live_match import linkify_spoken_html

                blocks.append(
                    linkify_spoken_html(body, str(db_path), pack=match_pack)
                )
                return
            except Exception:
                pass
        blocks.append(html_escape(body))

    _add("大盤", board)
    _add("族群", field)
    _add("PCB", pcb)
    _add("他還說", said)
    # 黃金脈絡只跟這次拿進來的最新主文＋他自己的回文，對過已收官方柱。
    # 不准再套近四月雙箭頭稿，也不准在空白鍵後面接「可接」。
    try:
        from biaoke_reweave import voice_gold_lines

        shown_txt = [x for x in (board, field, pcb, said) if x]
        gold_lines = voice_gold_lines(
            list(cleaned_mains) + list(replies),
            str(db_path or ""),
            shown=shown_txt,
        )
        if gold_lines:
            blocks.append("")
            blocks.append("<b>脈絡黃金</b>")
            for x in gold_lines:
                if stock_links and db_path:
                    try:
                        from biaoke_live_match import linkify_spoken_html

                        blocks.append(
                            linkify_spoken_html(x, str(db_path), pack=match_pack)
                        )
                        continue
                    except Exception:
                        pass
                blocks.append(html_escape(x))
    except Exception:
        pass
    if include_gates and db_path:
        try:
            gates = format_index_gates_confront_html(
                str(db_path),
                posts=list(cleaned_mains) + list(cleaned_replies),
                now=now,
                skip_how_shown=[x for x in (board, field, pcb, said) if x],
            )
            if gates:
                blocks.append("")
                blocks.append(gates)
        except Exception:
            pass
    # 空白飆大：口語為主；波浪整段敘述歸「波浪位階」鍵，這裡只附一層級對照句
    if (not stock_links) and db_path:
        try:
            one = format_wave_level_one_liner(str(db_path))
            if one:
                blocks.append("")
                blocks.append(one)
        except Exception:
            pass
    # 還能問只跟最新主文＋當天以後的自回，不准拿更早一篇的夜盤價來出題。
    latest_day = str(mains[0].get("date") or "")
    ask_rows = [mains[0]] + [
        r for r in replies if not latest_day or str(r.get("date") or "") >= latest_day
    ]
    if stock_links:
        asks = _likely_asks(ask_rows[:9])
        if asks:
            blocks.append("")
            blocks.append("<b>還能問</b>")
            blocks.extend(html_escape(a) for a in asks[:3])
    else:
        # 空白鍵：不准一排可點股名；改純文字入口說明
        blocks.append("")
        blocks.append(
            html_escape(
                "想問某一檔他怎麼看，直接打股號或股名即可（這裡不掛可點清單）。"
            )
        )
    clock = ""
    if now is not None:
        dt = now if now.tzinfo else now.replace(tzinfo=TAIPEI)
        clock = dt.astimezone(TAIPEI).strftime("%H:%M")
    tail = "直接打字或語音。"
    if clock:
        tail = f"看到這裡是 {clock}。{tail}"
    blocks.append("")
    blocks.append(html_escape(tail))
    return "\n".join(blocks)


def _ymd8(raw: Any) -> str:
    s = str(raw or "").strip()
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 8:
        return digits[:8]
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return ""


def _fmt_ymd_slash(ymd: str) -> str:
    d = _ymd8(ymd)
    if len(d) != 8:
        return str(ymd or "")
    return f"{int(d[4:6])}/{int(d[6:8])}"


def _bar_px(val: Any) -> Optional[float]:
    try:
        if val is None or val == "":
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _latest_closed_index_bars(
    db_path: str, *, now: Optional[datetime] = None
) -> Dict[str, Any]:
    """最新已收官方柱：加權／台指日盤／台指夜盤；盤中未收不當印到。"""
    out: Dict[str, Any] = {"twii": None, "tx": None, "txn": None, "asof_note": ""}
    path = str(db_path or "").strip()
    if not path:
        return out
    clock = now if now is not None else taipei_now()
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=TAIPEI)
    else:
        clock = clock.astimezone(TAIPEI)
    try:
        from trading_calendar import is_official_daily_bar
    except Exception:
        def is_official_daily_bar(ymd, *, now=None):  # type: ignore
            return True

    conn = sqlite3.connect(path, timeout=30.0)
    try:
        tw_rows = conn.execute(
            """
            SELECT date, open, high, low, close FROM index_daily
            WHERE symbol='TWII' OR symbol='^TWII' OR symbol='' OR symbol IS NULL
            ORDER BY date DESC LIMIT 12
            """
        ).fetchall()
        for date, o, h, l, c in tw_rows:
            ymd = _ymd8(date)
            if not ymd or not is_official_daily_bar(ymd, now=clock):
                continue
            out["twii"] = {
                "date": ymd,
                "open": _bar_px(o),
                "high": _bar_px(h),
                "low": _bar_px(l),
                "close": _bar_px(c),
                "label": "加權",
            }
            break
        try:
            tx_rows = conn.execute(
                """
                SELECT date, session, open, high, low, close FROM futures_daily
                WHERE symbol='TX' AND (session='regular' OR session='day' OR session='' OR session IS NULL)
                ORDER BY date DESC LIMIT 12
                """
            ).fetchall()
        except sqlite3.Error:
            tx_rows = []
        for date, _sess, o, h, l, c in tx_rows:
            ymd = _ymd8(date)
            if not ymd or not is_official_daily_bar(ymd, now=clock):
                continue
            out["tx"] = {
                "date": ymd,
                "open": _bar_px(o),
                "high": _bar_px(h),
                "low": _bar_px(l),
                "close": _bar_px(c),
                "label": "台指日盤",
            }
            break
        try:
            txn_rows = conn.execute(
                """
                SELECT date, session, open, high, low, close FROM futures_daily
                WHERE symbol='TX' AND session='night'
                ORDER BY date DESC LIMIT 12
                """
            ).fetchall()
        except sqlite3.Error:
            txn_rows = []
        for date, _sess, o, h, l, c in txn_rows:
            ymd = _ymd8(date)
            # 夜盤：交易日當天白天不算「已收」；用同一把官方日收閘（過 13:30 才認當日）
            if not ymd or not is_official_daily_bar(ymd, now=clock):
                continue
            out["txn"] = {
                "date": ymd,
                "open": _bar_px(o),
                "high": _bar_px(h),
                "low": _bar_px(l),
                "close": _bar_px(c),
                "label": "台指夜盤",
            }
            break
    finally:
        conn.close()

    bits: List[str] = []
    for key in ("twii", "tx", "txn"):
        bar = out.get(key) or {}
        if not bar:
            continue
        hi = bar.get("high")
        lo = bar.get("low")
        cl = bar.get("close")
        bits.append(
            f"{bar.get('label')} {_fmt_ymd_slash(str(bar.get('date') or ''))}"
            f" 高{_px_face(hi)} 低{_px_face(lo)} 收{_px_face(cl)}"
        )
    today = clock.strftime("%Y%m%d")
    closed_note = ""
    try:
        from trading_calendar import is_tw_market_holiday

        if clock.weekday() >= 5 or is_tw_market_holiday(today):
            closed_note = "今日休市／未開盤；"
    except Exception:
        if clock.weekday() >= 5:
            closed_note = "今日休市／未開盤；"
    if bits:
        out["asof_note"] = (
            f"{closed_note}截至（台北）" + "；".join(bits) + "。盤中未收不當印到。"
        )
    elif closed_note:
        out["asof_note"] = f"{closed_note}尚無已收官方柱。"
    return out


def _px_face(val: Optional[float]) -> str:
    if val is None:
        return "—"
    if abs(val - round(val)) < 1e-6:
        return f"{int(round(val))}"
    return f"{val:.2f}".rstrip("0").rstrip(".")


def _gate_touch_line(
    level: float,
    bar: Optional[Dict[str, Any]],
    *,
    ctx: str = "",
) -> str:
    """關卡 vs 已收柱：區間碰到／高未到／低未到／低已破。不准把「還沒跌到」標成已破。"""
    if not bar:
        return "尚無對應已收柱"
    hi = bar.get("high")
    lo = bar.get("low")
    cl = bar.get("close")
    if hi is None or lo is None:
        return "尚無對應已收柱"
    try:
        h, l = float(hi), float(lo)
    except (TypeError, ValueError):
        return "尚無對應已收柱"
    face = (
        f"{bar.get('label') or ''} {_fmt_ymd_slash(str(bar.get('date') or ''))}"
        f" 高{_px_face(h)} 低{_px_face(l)} 收{_px_face(cl)}"
    ).strip()
    if l <= level <= h:
        return f"區間碰到　{face}"
    if level < l:
        # 整根都在關卡上方＝還沒跌到
        gap = l - level
        return f"低未到（差{_px_face(gap)}）　{face}"
    # level > h：整根在關卡下方。下檔目標＝已破；上檔壓力＝高未到
    blob = str(ctx or "")
    if re.search(r"(必破|破底|下測|下看|支撐|低點|末跌|主跌)", blob):
        return f"低已破　{face}"
    gap = level - h
    return f"高未到（差{_px_face(gap)}）　{face}"


def _gate_bar_for_role(
    role: str, bars: Dict[str, Any], ctx: str = ""
) -> Optional[Dict[str, Any]]:
    r = str(role or "")
    blob = f"{r} {ctx}"
    if "夜盤" in blob:
        return bars.get("txn") or bars.get("tx") or bars.get("twii")
    if "台指" in blob:
        return bars.get("tx") or bars.get("txn") or bars.get("twii")
    if "加權" in blob or "大盤" in blob:
        return bars.get("twii") or bars.get("tx")
    # 點位：依上下文；沒寫清楚先對加權（他常混用時表頭會標來源）
    return bars.get("twii") or bars.get("tx")


def _collect_open_index_gates(
    posts: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """只收他自己文內的指數關；路人正文不進 posts。同價留最新一句。"""
    try:
        from biaoke_walk import extract_index_levels
    except Exception:
        return []
    by_lv: Dict[float, Dict[str, Any]] = {}
    for p in sorted(posts or [], key=_row_key):
        if str(p.get("kind") or "") == "bystander":
            continue
        text = _scrub_post_text(str(p.get("text") or ""))
        if not text.strip():
            continue
        for hit in extract_index_levels(text):
            try:
                lv = float(hit.get("level"))
            except (TypeError, ValueError):
                continue
            if lv < 15000:
                continue
            key = round(lv, 2)
            ctx = str(hit.get("ctx") or "").strip()
            role = str(hit.get("role") or "點位")
            blob = f"{text} {ctx}"
            # 他最新題旨鎖定角色：反彈穿刺／轉震盪／劇本一，不准全叫「點位」
            if abs(key - 45546.0) < 1.0 and re.search(r"穿刺|反彈", blob):
                role = "反彈穿刺"
            elif abs(key - 46292.0) < 1.0 and re.search(r"轉震盪|震盪整理", blob):
                role = "轉震盪"
            elif abs(key - 38000.0) < 1.0 and re.search(r"35000|劇本", blob):
                role = "劇本一上沿"
            elif abs(key - 35000.0) < 1.0 and re.search(r"38000|劇本", blob):
                role = "劇本一下沿"
            how = _SPACE.sub(" ", ctx).strip()
            # 關卡「他說」只留短上下文；長洗盤敘述留給大盤欄，不准每關重貼一次
            how = _oral_body(how, 56)
            by_lv[key] = {
                "level": key,
                "role": role,
                "how": how or role,
                "date": str(p.get("date") or ""),
                "time": str(p.get("time") or ""),
            }
    rows = sorted(by_lv.values(), key=lambda r: float(r["level"]), reverse=True)
    return rows[:14]


def format_index_gates_confront_html(
    db_path: str = "",
    *,
    posts: Optional[Sequence[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    days: int = 21,
    skip_how_shown: Optional[Sequence[str]] = None,
) -> str:
    """他自己點過的加權／台指關 × 最新官方已收。一眼對：關、他怎麼說、柱有沒碰到。

    路人價不收；盤中未收不當印到。不是買訊、不是可點個股清單。
    skip_how_shown：大盤／他還說已唸過的敘述，關卡列不再貼「他說：」長複誦。
    """
    path = str(db_path or "").strip()
    rows_in = list(posts or [])
    if not rows_in and path:
        try:
            from biaoke_desk import load_corpus
            from biaoke_ingest import is_biaoke_voice
        except Exception:
            return ""
        blob = load_corpus(path)
        all_posts = list((blob or {}).get("posts") or [])
        clock = now if now is not None else taipei_now()
        if clock.tzinfo is None:
            clock = clock.replace(tzinfo=TAIPEI)
        else:
            clock = clock.astimezone(TAIPEI)
        floor = (clock - timedelta(days=max(7, int(days)))).strftime("%Y-%m-%d")
        for p in all_posts:
            day = str(p.get("date") or "")
            if day and day < floor:
                continue
            text = _scrub_post_text(str(p.get("text") or ""))
            if not text.strip():
                continue
            if str(p.get("kind") or "") == "bystander":
                continue
            try:
                if not is_biaoke_voice(text):
                    continue
            except Exception:
                pass
            rows_in.append(dict(p, text=text))
    gates = _collect_open_index_gates(rows_in)
    if not gates:
        return ""
    bars = _latest_closed_index_bars(path, now=now) if path else {
        "twii": None,
        "tx": None,
        "txn": None,
        "asof_note": "",
    }
    shown_how = [str(x) for x in (skip_how_shown or []) if str(x or "").strip()]
    lines: List[str] = ["<b>關卡 × 官方已收</b>"]
    note = str(bars.get("asof_note") or "").strip()
    if note:
        lines.append(html_escape(note))
    for g in gates:
        lv = float(g["level"])
        role = str(g.get("role") or "點位")
        how = str(g.get("how") or "")
        bar = _gate_bar_for_role(role, bars, how)
        touch = _gate_touch_line(lv, bar, ctx=f"{role} {how}")
        head = f"{_px_face(lv)}（{role}）"
        lines.append("")
        lines.append(html_escape(head))
        # 大盤欄已講過的洗盤長句，關卡只留官方對照，不准每關再貼一次「他說」
        if how and not (
            shown_how and _overlaps_shown(how, shown_how, min_chars=10)
        ):
            lines.append(html_escape(f"他說：{how}"))
        lines.append(html_escape(f"官方：{touch}"))
    return "\n".join(lines)


def format_unread_digest(
    events: Sequence[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    db_path: str = "",
) -> str:
    """未讀期間同一篇抓很多次，只留最新再口語重述。按飆大才看。

    顯示對齊最新兩則主文＋這兩串自回；更早未讀不拿來組「現在在講」。
    空白鍵路徑：無個股藍字、附關卡對官方已收。
    """
    uniq: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        pid = str(ev.get("post_id") or "")
        if pid:
            row = dict(ev)
            row["text"] = _scrub_post_text(str(row.get("text") or ""))
            uniq[pid] = row
    rows = list(uniq.values())
    mains = [
        r
        for r in rows
        if str(r.get("kind") or "post") not in ("reply", "bystander")
    ]
    replies = [r for r in rows if str(r.get("kind") or "") == "reply"]
    if not mains and replies:
        mains = [replies[0]]
        replies = replies[1:]
    if not mains:
        return ""
    mains = sorted(mains, key=_row_key, reverse=True)[:2]
    root_ids = {_thread_root_id(p) for p in mains if _thread_root_id(p)}
    if root_ids:
        replies = [r for r in replies if _thread_root_id(r) in root_ids]
    return format_focus_oral(
        mains,
        replies,
        now=now,
        db_path=db_path or "",
        stock_links=False,
        include_gates=True,
    )


_ASK_SKIP = {
    "飆客",
    "飆大",
    "AI飆客",
    "夜盤",
    "大盤",
    "加權",
    "台指期",
    "細微波",
}


def _likely_asks(posts: Sequence[Dict[str, Any]]) -> List[str]:
    asks: List[str] = []
    blob = " ".join(str(p.get("text") or "") for p in posts)
    tags: List[str] = []
    for p in posts:
        tags.extend(str(t) for t in (p.get("tags") or []) if t)
    if "逃命波" in blob or "C-2" in blob:
        asks.insert(0, "現在是逃命波嗎")
    if "夜盤" in blob or "46506" in blob:
        asks.append("夜盤過了沒")
    if "波浪" in blob or "位階" in blob or "細微波" in blob or "右肩" in blob:
        asks.insert(0, "現在波浪位階")
    if "45839" in blob:
        asks.append("45839有沒有守")
    if "47578" in blob:
        asks.append("47578過了沒")
    if "長線" in blob or "龍頭" in blob:
        asks.append("長線龍頭現在怎麼抱")
    for tag in tags:
        if tag in _ASK_SKIP or tag in asks:
            continue
        if "TWA" in tag or "指數" in tag:
            continue
        if tag.isdigit() and len(tag) == 4:
            continue
        asks.append(tag)
        if len(asks) >= 4:
            break
    if not any("大盤" in a for a in asks):
        asks.insert(0, "大盤現在怎樣")
    out: List[str] = []
    for a in asks:
        if a not in out:
            out.append(a)
        if len(out) >= 4:
            break
    return out


def _thread_root_id(post: Dict[str, Any]) -> str:
    """主文 id，或回文所屬主文（parent／id 冒號前）。"""
    parent = str(post.get("parent") or "").strip()
    if parent:
        return parent.split(":", 1)[0]
    aid = str(post.get("id") or post.get("post_id") or "").strip()
    return aid.split(":", 1)[0] if aid else ""


def format_latest_focus(db_path: str = "", *, n_main: int = 2, n_reply: int = 24) -> str:
    """按飆大空白進去：口語重述最新重點。不准倒原文、不念課綱、不疊舊位階。

    只認最新兩則主文＋這兩串他自己的回文（含樓中樓自回）；路人不当判斷。
    空白鍵：無個股藍字／選股狀態；附關卡 × 官方已收對照。
    """
    try:
        from biaoke_desk import load_corpus
    except Exception:
        return ""
    blob = load_corpus(db_path if db_path else None)
    posts = list((blob or {}).get("posts") or [])
    try:
        from biaoke_ingest import is_biaoke_voice
    except Exception:
        is_biaoke_voice = lambda _t: True  # noqa: E731
    mains = [
        p
        for p in posts
        if (p.get("kind") or "post") not in ("reply", "bystander")
        and is_biaoke_voice(_scrub_post_text(str(p.get("text") or "")))
    ]
    replies = [
        p
        for p in posts
        if p.get("kind") == "reply"
        and is_biaoke_voice(_scrub_post_text(str(p.get("text") or "")))
    ]
    if not mains:
        return ""
    # 主文／自回一律先依時間序排；最新兩則主文＋兩串自回（含樓中樓）
    mains_chrono = sorted(mains, key=_row_key)
    latest = list(reversed(mains_chrono[-max(1, int(n_main)) :]))
    root_ids = {_thread_root_id(p) for p in latest if _thread_root_id(p)}
    thread_replies = sorted(
        [p for p in replies if _thread_root_id(p) in root_ids],
        key=_row_key,
    )
    # 兩串內取最近 n_reply 則；傳入 oral 時維持時間由舊到新，改口才壓得住
    latest_replies = (
        thread_replies[-max(0, int(n_reply)) :] if n_reply else []
    )
    return format_focus_oral(
        latest,
        latest_replies,
        now=taipei_now(),
        db_path=db_path or "",
        stock_links=False,
        include_gates=True,
    )


def take_unread_digest(user_id: str, db_path: str, *, now: Optional[datetime] = None) -> str:
    """讀出未讀彙整。不在這裡標記已讀，等訊息真的送出。"""
    events = unread_events(user_id, db_path, now=now)
    if not events:
        return ""
    return format_unread_digest(events, now=now, db_path=db_path or "")
