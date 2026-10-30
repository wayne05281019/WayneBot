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
    s = _CHART.sub("（有圖）", text or "")
    s = _SPACE.sub(" ", s).strip()
    n = max(40, int(limit))
    return s if len(s) <= n else s[: n - 1] + "…"


_NOISE = re.compile(
    r"(打錯|很有心|出書|90%\s*老師|碩哥和我|蕭明道|楊少凱)"
)
_BOARD = re.compile(
    r"(夜盤|47578|C\s*波|B\s*[-‐‑‒–—]?c|B\s*波|頭部型態|大盤要漲|加權|逃命|45398|"
    r"目前大盤|緩步上攻|推升脈動|早盤要買|尾盤再考慮|調節股票|"
    r"大盤|台指期|頭肩底|中繼站|做多安全|"
    r"台股|股王|股后|"
    r"主跌|止跌|抄底|空手|減碼|48066|45000|47729|48697|49239|"
    r"47000|47600|47300|反彈不過壓|下降軌道)"
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
    r"下星期[一二]|星期二絕對|不要再介入|撤出觀望)"
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


def _overlaps_shown(bit: str, shown: Sequence[str], *, min_chars: int = 20) -> bool:
    """句／段是否已在大盤／族群／PCB（或已收進他還說）出現過。"""
    n = _norm_focus(bit)
    if len(n) < min_chars:
        return False
    for s in shown:
        t = _norm_focus(s)
        if not t:
            continue
        if n in t or t in n:
            return True
        head = min(36, len(n), len(t))
        if head >= 20 and n[:head] == t[:head]:
            return True
    return False


def _strip_shown_sentences(bit: str, shown: Sequence[str]) -> str:
    """一則樓下前半複述大盤、後半才是新話 → 只留新句。"""
    s = str(bit or "").strip()
    if not s:
        return ""
    if not _overlaps_shown(s, shown):
        return s
    parts = [p.strip(" ，、") for p in re.split(r"[。！？；]", s) if p.strip()]
    keep: List[str] = []
    for p in parts:
        if len(p) < 8:
            continue
        if _overlaps_shown(p, shown) or _overlaps_shown(p, keep):
            continue
        keep.append(p)
    if not keep:
        return ""
    out = "。".join(keep)
    if not out.endswith("。"):
        out += "。"
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


def format_teach_brief(db_path: str = "") -> str:
    """空白鍵加一段消化過的白話結論（波浪／切割／型態／量價）；不是買訊。

    資料來自活畫 pack；失敗回空，不准擋主摘要。
    """
    if not db_path:
        return ""
    try:
        from biaoke_level_learn import _build_live_pack

        pack = _build_live_pack(db_path) or {}
    except Exception:
        return ""
    thesis = str(pack.get("thesis") or "").strip()
    morph = str(pack.get("morph_note") or "").strip()
    intent = str(pack.get("intent_note") or "").strip()
    fib = str(pack.get("fib_note") or "").strip()
    if not (thesis or intent or morph):
        return ""
    lines = ["<b>白話結論（消化過・非買訊）</b>"]
    if thesis:
        lines.append(html_escape(f"波浪：{thesis}"))
    if fib:
        lines.append(html_escape(f"黃金切割：{fib}"))
    if morph:
        lines.append(html_escape(f"型態：{morph}"))
    if intent:
        # 只取第一句故事，避免牆
        one = intent.split("；")[0].strip()
        lines.append(html_escape(f"量價／主力：{one}"))
    lines.append(html_escape("說明：這是彙整他公開說法＋官方柱，不是他本人即時口述。"))
    return "\n".join(lines)


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
    parts = re.split(r"(?:^|\s)\d+\.\s+", raw)
    bits = [p.strip().rstrip("。") for p in parts if p and len(p.strip()) >= 12]
    if len(bits) >= 2:
        return bits
    return [raw] if raw else []


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
    cleaned_mains: List[Dict[str, Any]] = []
    for p in mains:
        row = dict(p)
        row["text"] = _scrub_post_text(str(row.get("text") or ""))
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
        row["text"] = _scrub_post_text(str(row.get("text") or ""))
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
            board = _speak(bit, 260)
        elif not field and _FIELD.search(bit):
            field = _speak(bit, 140)
        elif not pcb and _PCB.search(bit):
            pcb = _speak(bit, 140)
        else:
            spare.append(_speak(bit, 140))
    # 大盤欄只認最新主文；舊主文不准回填把「現在在講」鎖在更早一天。
    if not board:
        board = _speak(str(latest.get("text") or ""), 260)
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
            pcb = _speak(t, 140)
            continue
        if not pcb and _PCB.search(t):
            pcb = _speak(t, 140)
            continue
        day = str(p.get("date") or "")
        if day and latest_day and day < latest_day:
            continue
        # 最新主文之後的自回：大盤／關卡／空手句要進口語，不准整段丟掉。
        if _row_key(p) >= _row_key(latest):
            if _BOARD_REPLY.search(t):
                bit = _speak(t, 120)
                if bit:
                    after_board.append(bit)
            continue
        extra.append(_speak(t, 100))
    if older_long and newer_short:
        pcb = (
            "前一天還說台光電至少整理三個月、PCB 全面減碼；"
            "晚上改口，整理時間會比 ABF 短很多，昨天錯殺居多，下波可能還是漲的主流。"
        )
    latest_t = str(latest.get("text") or "")
    if board and re.search(r"(否則|如果|一定要過)", board + latest_t) and "如果句" not in board:
        board = board.rstrip("。") + "。這句還是如果句，不是已確認主升。"
    # 主文後大盤自回併進大盤欄（口語一句接一句，國中生也讀得懂）
    if after_board:
        merged = _join_said([board] + after_board[:6], shown=[])
        if merged:
            board = merged
    shown = [x for x in (board, field, pcb) if x]
    # 他還說＝主文沒進上面三欄的補充＋樓下；已講過的大盤／族群／PCB 整段丟掉
    said = _join_said([preview] + spare[:2] + extra[:3], shown=shown)
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
            )
            if gates:
                blocks.append("")
                blocks.append(gates)
        except Exception:
            pass
    # 空白鍵：消化過的白話結論（波浪／切割／型態／量價），不准抄同學原話
    if (not stock_links) and db_path:
        try:
            brief = format_teach_brief(str(db_path))
            if brief:
                blocks.append("")
                blocks.append(brief)
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


def _gate_touch_line(level: float, bar: Optional[Dict[str, Any]]) -> str:
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
    if level > h:
        gap = level - h
        return f"高未到（差{_px_face(gap)}）　{face}"
    return f"低已破　{face}"


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
            how = _SPACE.sub(" ", ctx).strip()
            if len(how) > 72:
                how = how[:71] + "…"
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
) -> str:
    """他自己點過的加權／台指關 × 最新官方已收。一眼對：關、他怎麼說、柱有沒碰到。

    路人價不收；盤中未收不當印到。不是買訊、不是可點個股清單。
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
    lines: List[str] = ["<b>關卡 × 官方已收</b>"]
    note = str(bars.get("asof_note") or "").strip()
    if note:
        lines.append(html_escape(note))
    for g in gates:
        lv = float(g["level"])
        role = str(g.get("role") or "點位")
        how = str(g.get("how") or "")
        bar = _gate_bar_for_role(role, bars, how)
        touch = _gate_touch_line(lv, bar)
        head = f"{_px_face(lv)}（{role}）"
        lines.append("")
        lines.append(html_escape(head))
        if how:
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
    latest = list(reversed(mains[-max(1, int(n_main)) :]))
    root_ids = {_thread_root_id(p) for p in latest if _thread_root_id(p)}
    thread_replies = [
        p for p in replies if _thread_root_id(p) in root_ids
    ]
    # 兩串內按時間取最近 n_reply 則自回（含樓中樓）
    latest_replies = (
        list(reversed(thread_replies[-max(0, int(n_reply)) :])) if n_reply else []
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
