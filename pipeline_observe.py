# -*- coding: utf-8 -*-
"""今日流水線觀測：分層真相＋節點對質（不是買訊、不准合成總分榜）。

層級固定：環境 → 主題 → 候選池 → 進場閘 → 帳簿／核心軌健康。
每一層標資料日、筆數、齊／空／過期／缺／失真；失真＝標題日與內容日不一致或兩套閘門對不上。
時區 Asia/Taipei。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# 觀測頁狀態（給話筒一眼）
ST_OK = "齊"
ST_EMPTY = "空"
ST_STALE = "過期"
ST_MISSING = "缺"
ST_BAD = "失真"


@dataclass
class LayerIssue:
    node: str
    detail: str


@dataclass
class Layer:
    id: str
    title: str
    status: str
    as_of: str = ""
    content_as_of: str = ""
    lines: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == ST_OK


def _ymd(raw: Any) -> str:
    t = str(raw or "").replace("-", "")[:8]
    return t if len(t) == 8 and t.isdigit() else ""


def _zh(day: str) -> str:
    d = _ymd(day)
    if not d:
        return "—"
    try:
        from trading_calendar import format_trading_date_zh

        return format_trading_date_zh(d)
    except Exception:
        return f"{d[:4]}/{d[4:6]}/{d[6:8]}"


def _twii_bar(db_path: str, as_of: str) -> Optional[Dict[str, Any]]:
    day = _ymd(as_of)
    if not day:
        return None
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            row = conn.execute(
                "SELECT date, close, regime FROM index_daily "
                "WHERE symbol='TWII' AND REPLACE(CAST(date AS TEXT),'-','')=? "
                "LIMIT 1",
                (day,),
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT date, close, regime FROM index_daily "
                    "WHERE symbol='TWII' ORDER BY date DESC LIMIT 1"
                ).fetchone()
                if not row:
                    return None
                return {
                    "date": _ymd(row[0]),
                    "close": row[1],
                    "regime": row[2] or "",
                    "exact": _ymd(row[0]) == day,
                }
            return {
                "date": _ymd(row[0]),
                "close": row[1],
                "regime": row[2] or "",
                "exact": True,
            }
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _chip_count(db_path: str, as_of: str) -> int:
    day = _ymd(as_of)
    if not day:
        return 0
    try:
        conn = sqlite3.connect(db_path, timeout=10.0)
        try:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM daily_quotes
                WHERE REPLACE(CAST(date AS TEXT),'-','')=?
                  AND (ABS(COALESCE(foreign_net,0))+ABS(COALESCE(trust_net,0))
                       +ABS(COALESCE(dealer_net,0)))>0
                """,
                (day,),
            ).fetchone()
            return int(row[0] or 0) if row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _bucket_n(results: Dict[str, Any], key: str) -> int:
    rows = results.get(key) or []
    return len(rows) if isinstance(rows, (list, tuple)) else 0


def _ids_from_bucket(results: Dict[str, Any], key: str) -> List[str]:
    out: List[str] = []
    for r in results.get(key) or []:
        if isinstance(r, dict):
            sid = str(r.get("stock_id") or r.get("code") or "").strip()
        else:
            sid = str(r or "").strip()
        if sid:
            out.append(sid)
    return out


def build_pipeline_observe(
    db_path: str,
    *,
    uid: str = "",
    now=None,
) -> Dict[str, Any]:
    """組觀測 payload：分層＋issues。uid 只影響帳簿段（持股／觀察）。"""
    from config import taipei_now
    from trading_calendar import fuse_end_trading_date, resolve_screen_as_of

    path = str(db_path or "").strip()
    press = now or taipei_now()
    today = press.strftime("%Y%m%d")
    desk = _ymd(resolve_screen_as_of(path)) if path else ""
    fuse = _ymd(fuse_end_trading_date(press))
    issues: List[LayerIssue] = []
    layers: List[Layer] = []

    # —— 0 基準日 ——
    if not desk:
        issues.append(LayerIssue("基準日", "無法解析海選／完整日 as_of"))
    elif fuse and desk < fuse:
        issues.append(
            LayerIssue(
                "基準日",
                f"話筒基準 { _zh(desk) } 落後 fuse 上限 { _zh(fuse) }（現貨／融合未齊）",
            )
        )

    # —— 1 環境 ——
    env = Layer(id="env", title="環境", status=ST_MISSING, as_of=desk)
    tw = _twii_bar(path, desk) if path and desk else None
    if not tw:
        env.status = ST_MISSING
        env.lines = ["加權柱缺"]
        issues.append(LayerIssue("環境", "index_daily TWII 無資料"))
    else:
        env.content_as_of = tw["date"]
        env.as_of = desk
        close = tw.get("close")
        regime = str(tw.get("regime") or "")
        risk = "關" if regime == "bear" else ("開" if regime == "bull" else "半")
        env.lines = [
            f"加權 {_zh(tw['date'])} 收 {close:,.0f}" if isinstance(close, (int, float)) else f"加權 {_zh(tw['date'])}",
            f"regime={regime or '—'} → 風險預算建議「{risk}」（人工仍可覆寫）",
        ]
        if not tw.get("exact"):
            env.status = ST_STALE
            env.issues.append(f"基準日無加權柱，顯示最近 {_zh(tw['date'])}")
            issues.append(LayerIssue("環境", env.issues[-1]))
        else:
            env.status = ST_OK
        # TWII 比 desk 新＝指數源與現貨齊日脫鉤（常見 Yahoo 先到）
        try:
            conn = sqlite3.connect(path, timeout=10.0)
            try:
                latest = conn.execute(
                    "SELECT MAX(REPLACE(CAST(date AS TEXT),'-','')) FROM index_daily WHERE symbol='TWII'"
                ).fetchone()
                latest_d = _ymd(latest[0] if latest else "")
            finally:
                conn.close()
            if latest_d and desk and latest_d > desk:
                env.lines.append(f"注意：庫內加權已到 {_zh(latest_d)}，現貨完整日仍 {_zh(desk)}")
                issues.append(
                    LayerIssue(
                        "環境",
                        f"TWII 最新 {_zh(latest_d)} ＞ 現貨完整日 {_zh(desk)}（指數源與現貨脫鉤）",
                    )
                )
        except sqlite3.Error:
            pass
    layers.append(env)

    # —— 2 主題：資金＋洞燭 ——
    theme = Layer(id="theme", title="主題", status=ST_MISSING, as_of=desk)
    flow_as = flow_lag = ""
    chip_n = 0
    try:
        from money_flow import resolve_flow_as_of

        flow_as, flow_lag = resolve_flow_as_of(path, now=press)
        flow_as = _ymd(flow_as)
        chip_n = _chip_count(path, flow_as) if flow_as else 0
    except Exception as exc:
        theme.issues.append(f"資金解析失敗：{type(exc).__name__}")
        issues.append(LayerIssue("資金", theme.issues[-1]))
    theme.content_as_of = flow_as
    if not flow_as:
        theme.status = ST_MISSING
        theme.lines.append("資金基準日缺")
    elif chip_n <= 0:
        theme.status = ST_BAD
        theme.lines.append(f"資金標題日 {_zh(flow_as)}，但法人非0＝0（假輪動）")
        issues.append(
            LayerIssue(
                "資金",
                f"resolve 日 {_zh(flow_as)} 無法人淨額；頁面若仍排出 0 張排名＝失真",
            )
        )
    else:
        theme.status = ST_OK
        theme.lines.append(f"資金基準 {_zh(flow_as)}｜法人非0={chip_n}")
    if flow_lag:
        theme.lines.append("資金落後說明已附（見資金鈕）")

    dz_cap = ""
    dz_stamp = None
    try:
        from silent_track_runs import track_status
        from biaoke_field_scan import load_dongzhu_precursor

        dz_stamp = track_status(path, "dongzhu", desk) if desk else None
        prec = load_dongzhu_precursor(path) or {}
        dz_cap = _ymd(prec.get("cap"))
        if dz_stamp and str(dz_stamp.get("status") or "") == "success":
            theme.lines.append(
                f"洞燭戳 {dz_stamp.get('notes') or 'success'}（基準 {_zh(desk)}）"
            )
        else:
            theme.lines.append("洞燭靜默戳缺／未成功")
            if theme.status == ST_OK:
                theme.status = ST_STALE
        if dz_cap and desk and dz_cap < desk:
            theme.status = ST_BAD
            msg = f"洞燭底料 cap={_zh(dz_cap)} ＜ 基準 {_zh(desk)}（戳成功但內容舊）"
            theme.issues.append(msg)
            issues.append(LayerIssue("洞燭", msg))
        elif dz_cap:
            theme.lines.append(f"洞燭底料 cap {_zh(dz_cap)}")
    except Exception as exc:
        theme.issues.append(f"洞燭讀取失敗：{type(exc).__name__}")
        issues.append(LayerIssue("洞燭", theme.issues[-1]))
    if theme.status == ST_MISSING and theme.lines:
        theme.status = ST_BAD if theme.issues else ST_STALE
    layers.append(theme)

    # —— 3 候選池（分欄，不准合成） ——
    pool = Layer(id="pool", title="候選池", status=ST_MISSING, as_of=desk)
    screen_res: Dict[str, Any] = {}
    try:
        from screen_sessions import load_session_results, screen_session_has_data

        has = bool(desk and screen_session_has_data(path, desk))
        if has:
            screen_res = load_session_results(path, desk, "morning") or {}
            if not any(screen_res.values()):
                screen_res = load_session_results(path, desk, "evening") or {}
        n_lz = _bucket_n(screen_res, "leave_zero")
        n_ma = _bucket_n(screen_res, "ma60_lower")
        n_gb = _bucket_n(screen_res, "golden_buy")
        pool.lines = [
            f"海選快取 {_zh(desk)}｜離零 {n_lz}｜紅箭確認 {n_ma}｜還在零 {n_gb}（觀察非買）",
        ]
        if not has:
            pool.status = ST_MISSING
            pool.issues.append(f"{_zh(desk)} 無 screen_sessions")
            issues.append(LayerIssue("海選", pool.issues[-1]))
        elif n_lz == 0 and n_ma == 0 and n_gb == 0:
            pool.status = ST_EMPTY
            pool.lines.append("海選三桶皆空（空＝正常，不是齊）")
        else:
            pool.status = ST_OK
            if n_lz == 0 and n_ma == 0:
                pool.lines.append("推播兩桶皆空＝今日無過閘候選（空＝正常）")
    except Exception as exc:
        pool.status = ST_MISSING
        pool.issues.append(f"海選讀取失敗：{type(exc).__name__}")
        issues.append(LayerIssue("海選", pool.issues[-1]))

    # 連買／低估／壓撐戳
    try:
        from silent_track_runs import track_status

        for tid, lab in (
            ("streak", "連買"),
            ("pressure", "壓撐"),
            ("leave-zero-picks", "剛離零雷達"),
        ):
            st = track_status(path, tid, desk) if desk else None
            if not st:
                pool.lines.append(f"{lab}戳：缺")
                continue
            pool.lines.append(f"{lab}戳：{st.get('status')} {st.get('notes') or ''}")
            # 剛離零雷達＝窄母體（實綠首日）；海選 leave_zero＝母公式＋量／趨勢硬閘
            # 筆數不同＝產品層差異，不准當「定義壞了／失真」
            if tid == "leave-zero-picks" and str(st.get("status")) == "success":
                notes = str(st.get("notes") or "")
                n_lz = _bucket_n(screen_res, "leave_zero")
                if n_lz == 0 and "leave_zero_0=" in notes:
                    try:
                        radar_n = int(notes.split("leave_zero_0=")[1].split(",")[0])
                    except Exception:
                        radar_n = -1
                    if radar_n > 0:
                        pool.lines.append(
                            f"產品層：剛離零雷達 n≈{radar_n}、海選離零桶 0"
                            "（窄母體 vs 海選後置閘；非資料失真）"
                        )
    except Exception:
        pass

    try:
        from undervalue_sync import load_picks, load_run, resolve_button_as_of

        uv_as = _ymd(resolve_button_as_of(path))
        picks = load_picks(path, uv_as) if uv_as else []
        run = load_run(path, uv_as) if uv_as else None
        pool.lines.append(
            f"低估 {_zh(uv_as)}｜n={len(picks)}"
            + (f"｜{run.get('note')}" if run and run.get("note") else "")
            + "（估值≠買訊）"
        )
        # PE 共識對質：pe_year 應≈ peer_pe_median
        pe_bad = 0
        for p in picks:
            peer, py = p.get("peer_pe_median"), p.get("pe_year")
            if peer is None or py is None:
                continue
            try:
                if abs(float(peer) - float(py)) > 0.05:
                    pe_bad += 1
            except (TypeError, ValueError):
                pe_bad += 1
        if pe_bad:
            msg = f"低估名單 {pe_bad} 檔 pe_year≠同業中位（共識失真）"
            pool.status = ST_BAD
            pool.issues.append(msg)
            issues.append(LayerIssue("低估", msg))
        if uv_as and desk and uv_as < desk:
            pool.lines.append(f"低估日落後基準 {_zh(desk)}")
    except Exception as exc:
        pool.issues.append(f"低估讀取失敗：{type(exc).__name__}")
        issues.append(LayerIssue("低估", pool.issues[-1]))

    # 不准把「缺／空」收尾翻成「齊」；只有本層真的無問題且已標齊才維持
    if pool.status == ST_MISSING:
        pass  # 維持缺
    elif pool.issues:
        pool.status = ST_BAD
    layers.append(pool)

    # —— 4 進場閘 ——
    gate = Layer(id="gate", title="進場閘", status=ST_MISSING, as_of=desk)
    wr_ids: List[str] = []
    wr_as = ""
    try:
        from winrate_buypoint import latest_roster_as_of, load_winrate_roster, roster_marked

        wr_as = _ymd(latest_roster_as_of(path))
        desk_marked = bool(desk and roster_marked(path, desk))
        use = desk if desk_marked else wr_as
        rows = load_winrate_roster(path, use) if use else []
        wr_ids = [str(r.get("stock_id") or "") for r in rows if r.get("stock_id")]
        gate.content_as_of = use
        n_screen_lz = _bucket_n(screen_res, "leave_zero")
        n_screen_ma = _bucket_n(screen_res, "ma60_lower")
        gate.lines = [
            f"勝率買點 roster {_zh(use)}｜n={len(wr_ids)}",
            "母閘＝leave_zero_screen_ok；勝率另加：圖仍畫▲＋exclude＋AI 生態系",
            f"海選離零桶 n={n_screen_lz}（另加量熱／趨勢／短高硬閘）｜紅箭確認 n={n_screen_ma}",
            "剛離零鈕＝更窄（實綠首日）；三套產品層，不准用最終集合互判定義壞",
        ]
        if not use or not roster_marked(path, use):
            gate.status = ST_MISSING
            issues.append(LayerIssue("勝率買點", "roster 缺檔"))
        elif len(wr_ids) == 0:
            gate.status = ST_EMPTY
            gate.lines.append("空名單＝今日無過閘可執行")
        elif desk and use and use < desk:
            gate.status = ST_STALE
            gate.lines.append(f"名單日 {_zh(use)} 早於基準 {_zh(desk)}（過期，不准當今日齊）")
            issues.append(
                LayerIssue("勝率買點", f"roster {_zh(use)} ＜ 基準 {_zh(desk)}")
            )
            gate.lines.append(
                "代號：" + "、".join(wr_ids[:12]) + ("…" if len(wr_ids) > 12 else "")
            )
        else:
            gate.status = ST_OK
            gate.lines.append(
                "代號：" + "、".join(wr_ids[:12]) + ("…" if len(wr_ids) > 12 else "")
            )

        # 產品層差異＝說明，不是失真（母公式可同、後置閘不同）
        lz_ids = set(_ids_from_bucket(screen_res, "leave_zero"))
        wr_set = set(wr_ids)
        if wr_set or lz_ids:
            only_wr = sorted(wr_set - lz_ids)
            only_lz = sorted(lz_ids - wr_set)
            if only_wr or only_lz:
                gate.lines.append(
                    f"產品層差異：僅勝率 {len(only_wr)}／僅海選離零 {len(only_lz)}"
                    "（預期；非資料日失真）"
                )
    except Exception as exc:
        gate.issues.append(f"勝率讀取失敗：{type(exc).__name__}")
        issues.append(LayerIssue("勝率買點", gate.issues[-1]))
    layers.append(gate)

    # —— 5 帳簿（按人） ——
    book = Layer(id="book", title="帳簿", status=ST_OK, as_of=desk)
    uid_s = str(uid or "").strip()
    if not uid_s:
        book.lines = ["未帶 uid：跳過持股／觀察人數"]
        book.status = ST_EMPTY
    else:
        try:
            conn = sqlite3.connect(path, timeout=10.0)
            try:
                n_h = 0
                n_w = 0
                try:
                    n_h = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM user_holdings WHERE user_id=?",
                            (uid_s,),
                        ).fetchone()[0]
                        or 0
                    )
                except sqlite3.Error:
                    pass
                try:
                    n_w = int(
                        conn.execute(
                            "SELECT COUNT(*) FROM user_watchlist WHERE user_id=?",
                            (uid_s,),
                        ).fetchone()[0]
                        or 0
                    )
                except sqlite3.Error:
                    pass
            finally:
                conn.close()
            book.lines = [
                f"持股 {n_h}｜觀察 {n_w}（對照本，非選股勝率）",
                "無自動出場／無價到提醒；如何賣只標不送單",
            ]
            book.status = ST_OK
        except Exception as exc:
            book.status = ST_MISSING
            book.issues.append(str(exc))
    layers.append(book)

    # —— 6 核心靜默軌 ——
    pipe = Layer(id="pipe", title="盤後核心軌", status=ST_MISSING, as_of=desk)
    try:
        from silent_track_runs import CORE_AFTER_FUSE, list_tracks_for_day

        tracks = list_tracks_for_day(path, desk) if desk else []
        ok_n = sum(1 for t in tracks if str(t.get("status")) == "success")
        miss = [t for t in tracks if str(t.get("status")) == "missing"]
        err = [t for t in tracks if str(t.get("status")) not in ("success", "missing")]
        pipe.lines = [
            f"CORE {ok_n}/{len(CORE_AFTER_FUSE)} success",
        ]
        if miss:
            pipe.lines.append("缺：" + "、".join(t.get("track") or "" for t in miss[:10])
                              + ("…" if len(miss) > 10 else ""))
        if err:
            pipe.lines.append(
                "異狀："
                + "、".join(f"{t.get('track')}:{t.get('status')}" for t in err[:8])
            )
        if ok_n == 0:
            pipe.status = ST_MISSING
        elif miss or err:
            pipe.status = ST_STALE
            if any((t.get("track") == "money-flow") for t in miss):
                issues.append(LayerIssue("核心軌", "money-flow 靜默戳缺（資金落檔未蓋）"))
        else:
            pipe.status = ST_OK
    except Exception as exc:
        pipe.issues.append(str(exc))
        issues.append(LayerIssue("核心軌", str(exc)))
    layers.append(pipe)

    bad_n = sum(1 for L in layers if L.status == ST_BAD)
    return {
        "today": today,
        "desk_as_of": desk,
        "fuse_as_of": fuse,
        "layers": layers,
        "issues": issues,
        "summary": {
            "layer_n": len(layers),
            "bad_n": bad_n,
            "issue_n": len(issues),
            "ok_n": sum(1 for L in layers if L.status == ST_OK),
        },
        "winrate_ids": wr_ids,
        "not_buy_signal": True,
    }


def format_pipeline_observe_html(payload: Dict[str, Any]) -> str:
    """Telegram HTML：能一行就一行；分層清楚；失真置頂。"""
    from html import escape
    from tg_layout import join_dashed, title_line

    desk = _zh(payload.get("desk_as_of") or "")
    fuse = _zh(payload.get("fuse_as_of") or "")
    today = _zh(payload.get("today") or "")
    summ = payload.get("summary") or {}
    blocks: List[str] = [
        title_line("流水線觀測", desk, "非買訊"),
        f"日曆 {escape(today)}｜基準 {escape(desk)}｜fuse上限 {escape(fuse)}",
        f"層齊 {summ.get('ok_n', 0)}／{summ.get('layer_n', 0)}｜失真層 {summ.get('bad_n', 0)}｜問題 {summ.get('issue_n', 0)}",
    ]
    issues: Sequence[LayerIssue] = payload.get("issues") or []
    if issues:
        lines = [f"· {escape(i.node)}：{escape(i.detail)}" for i in list(issues)[:12]]
        blocks.append("<b>對質問題</b>\n" + "\n".join(lines))

    for L in payload.get("layers") or []:
        if not isinstance(L, Layer):
            # dict fallback
            title = str(L.get("title") or "")
            status = str(L.get("status") or "")
            body = "\n".join(escape(x) for x in (L.get("lines") or []))
            extra = "\n".join(escape(x) for x in (L.get("issues") or []))
        else:
            title, status = L.title, L.status
            body = "\n".join(escape(x) for x in L.lines)
            extra = "\n".join(escape(x) for x in L.issues)
        head = f"<b>{escape(title)}</b>〔{escape(status)}〕"
        chunk = head
        if body:
            chunk += "\n" + body
        if extra:
            chunk += "\n" + extra
        blocks.append(chunk)

    blocks.append(
        "<i>進場只認勝率買點／剛離零與已確認紅箭。低估・連買・洞燭・飆大・波浪不是買訊。</i>"
    )
    return join_dashed(*blocks)


def format_combo_screen_html(payload: Dict[str, Any]) -> str:
    """綜合篩選：機構式串節點（環境→主題→候選→進場閘→連買／帳簿）；非買訊。

    與流水線觀測共用同一套分層真相，標題與導語改成篩選鏈口吻；不准合成總分榜。
    """
    from html import escape
    from tg_layout import join_dashed, title_line

    desk = _zh(payload.get("desk_as_of") or "")
    fuse = _zh(payload.get("fuse_as_of") or "")
    today = _zh(payload.get("today") or "")
    summ = payload.get("summary") or {}
    blocks: List[str] = [
        title_line("綜合篩選", desk, "非買訊"),
        "機構式節點：環境→主題→候選池→進場閘→連買／帳簿",
        f"日曆 {escape(today)}｜基準 {escape(desk)}｜fuse上限 {escape(fuse)}",
        f"節點齊 {summ.get('ok_n', 0)}／{summ.get('layer_n', 0)}｜失真 {summ.get('bad_n', 0)}｜問題 {summ.get('issue_n', 0)}",
    ]
    issues: Sequence[LayerIssue] = payload.get("issues") or []
    if issues:
        lines = [f"· {escape(i.node)}：{escape(i.detail)}" for i in list(issues)[:12]]
        blocks.append("<b>節點對質</b>\n" + "\n".join(lines))

    for L in payload.get("layers") or []:
        if not isinstance(L, Layer):
            title = str(L.get("title") or "")
            status = str(L.get("status") or "")
            body = "\n".join(escape(x) for x in (L.get("lines") or []))
            extra = "\n".join(escape(x) for x in (L.get("issues") or []))
        else:
            title, status = L.title, L.status
            body = "\n".join(escape(x) for x in L.lines)
            extra = "\n".join(escape(x) for x in L.issues)
        head = f"<b>{escape(title)}</b>〔{escape(status)}〕"
        chunk = head
        if body:
            chunk += "\n" + body
        if extra:
            chunk += "\n" + extra
        blocks.append(chunk)

    blocks.append(
        "<i>綜合篩選＝串節點對質，不是買訊、不准合成總分。進場只認勝率買點／剛離零與已確認紅箭。</i>"
    )
    return join_dashed(*blocks)
