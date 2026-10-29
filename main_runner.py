# ==============================================================================
# WayneBot 主排程：盤後增量、四大選股、法人回補、Telegram 復盤推播
# 執行：python main.py --once  或  python main_runner.py
#
# 單一正式庫：data/wayne_market.db（UPSERT，不另開第二套行情庫）
# 盤後時間：台灣週一～五 16:30 只融合行情（不寄海選）
#   - GitHub Actions cron 30 8 * * 1-5（UTC＝台灣 16:30）WAYNE_JOB=increment
#   - Render 常駐執行緒同樣 16:30
# 早上海選：台灣週一～五 06:30 寄出（昨收＋美股收盤／盤後；大跌先單獨通知）
#   - 常駐 data 角色 06:30 寄出（有效 token＋按開始的話筒）
#   - GHA cron 30 22 * * 0-4 仍跑 morning_screen 算名單、蓋 zip；WAYNE_SCREEN_NOTIFY=0 不寄
#   - 真休市日（連假／北市停班／颱風）：不跑海選；仍寄美股＋環境精簡早報（us-digest-*）；
#     台股段寫「今日無開盤，因為〇〇」；screen-closed-* 記略過海選；不准改買訊
# 12:45 雙時段比價：只對照今早剛離零＋還在零；開盤 vs 約 12:45 現價
#   - 休市日整段略過（midday-closed-*；連「今天沒開盤」也不寄）
# 20:00 晚間台股收盤海選寫快照，並讓 AI 模擬倉依收盤名單買（海選本文不寄；不主動推播模擬倉）
# 22:15 抓人事行政總處北市停班（週日也跑）；05:10 再抓一次涵蓋 04:30 補發；06:30 海選前再確認
# 16:30 融合成功後會順便跑晚間海選＋AI，讓 Release zip 帶得走模擬持倉。
# 20:00／重啟若快照已寫過，不再重掃全市場，仍用快照再跑 AI 模擬倉（清 ETF 槽、依收盤停利停損）。
# 16:30 寫入項目（皆融合進同一 sqlite）：
#   1. 母體 stock_universe（ISIN，現股／KY／ETF）
#   2. 上市 MI_INDEX ＋ 上櫃收盤 → daily_quotes 價量
#   3. 三大法人 T86／櫃買 → daily_quotes.foreign_net / trust_net / dealer_net（張）
#      並依產業加總寫入 daily_sector_flow（盤後資金輪動，佈局參考）
#      接著重跑洞燭先機走查（佔比升還沒第一 vs 停車格 vs 黃金買點），寫進 dongzhu_precursor
#      盤後齊了就自己落當日洞燭名單（不必按鈕、不推話筒），之後連續對 1／5／10 個交易日；不改黃金買點
#      加權寫入後默默落大盤演算／內部試畫，官方柱走完對質；不推話筒；現在不在話筒發明 5／9
#   4. 缺日／上市櫃缺邊重抓（假日官方回空則略過）
#   5. 月營收 monthly_revenue（OpenAPI 全市場同期＋公開資訊觀測站 NAS 已先公告）、季報 quarterly_income（OpenAPI 最新一期；無免驗證碼 NAS 彙總表）
#   6. 除權息 ex_rights（證交所 TWT49U、櫃買 exDailyQ；決策卡還原優先用此表）
#   7. 興櫃 emerging_quotes（櫃買當日行情表／日表；不寫進上市櫃 daily_quotes）
#   8. 匯入健康檢查；上市／上櫃／興櫃沒齊就不標成功、不覆蓋完整舊資料
# 海選 06:30 寄給偉權與哥哥（兩人已在白名單）；12:45 只比剛離零＋還在零開盤／現價。盤後 16:30 只融合；20:00 不寄。
# 盤後融合順便用庫內下一根日 K 對昨天海選復盤；不另抓數。弱類別只調 AI 模擬倉權重。
# 早上海選會再抓美股現金收盤：四大＋VIX＋費半／台積ADR；收盤後再看盤後（ADR／那指期續勢）。
# 盤中期貨不看。大跌併入 06:30 早報彙整開頭，不另寄。逆風時當沖／隔日沖不列；半導體對照費半。美股抓不到就不過濾。
# 證交所 13:30 收、盤後到 14:30；櫃買 15:00 收。兩邊絕大多數收盤最慢 16:30 齊，所以抓數排 16:30。
# 16:30 前不把「今天」寫進庫；開機只補已經收完的交易日。
# Render 免費碟會在每次 Deploy 重抓 GitHub Release zip；啟動後會再跑一次
# fuse（不推播）把 Release 之後缺的交易日補進這份庫。
# ==============================================================================

import os
import sys
import time
import sqlite3
import logging
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, List, Any, Optional

import requests

from config import get_db_path, get_cache_dir, get_telegram_token, get_telegram_chat_id, taipei_today_str, fuse_end_date, taipei_now, taipei_stamp
from wayne_db import ensure_core_schema
from ops_watchdog import (
    INCREMENT_RUNNING_STALE_SEC,
    MORNING_CLAIM_AGE_DEMOTE_SEC,
    MORNING_RUNNING_STALE_SEC,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("WayneBotRunner")

# 本行程啟動牆鐘（epoch）；finished_at 早於此＝前一進程 orphan，可降 computed。
_PROCESS_BOOT_EPOCH = time.time()


def _stamp_age_seconds(raw: str, *, now=None) -> float:
    """紀錄時戳距今幾秒。含時區用該時區；舊 naive 當 UTC（Render 以前的寫法）。對比一律台北。"""
    from datetime import timezone
    from zoneinfo import ZoneInfo

    tw = ZoneInfo("Asia/Taipei")
    s = str(raw or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ref = now or taipei_now()
    if getattr(ref, "tzinfo", None) is None:
        ref = ref.replace(tzinfo=tw)
    else:
        ref = ref.astimezone(tw)
    return max(0.0, (ref - dt.astimezone(tw)).total_seconds())


try:
    from data_fetcher import DataFetcher, TaiwanMarketFetcher
except ImportError:
    try:
        from data_fetcher import DataFetcher
        TaiwanMarketFetcher = DataFetcher
    except ImportError:
        DataFetcher = None
        TaiwanMarketFetcher = None

try:
    from screening_engine import ScreeningEngine, run_full_screening
except ImportError:
    ScreeningEngine = None
    run_full_screening = None

try:
    from portfolio_engine import PortfolioEngine
except ImportError:
    PortfolioEngine = None

try:
    from bot_servers import WayneTelegramBot, chunk_telegram_text
except ImportError:
    WayneTelegramBot = None

    def chunk_telegram_text(text: str, limit: int = 3500) -> List[str]:
        if not text:
            return []
        return [text[i:i + limit] for i in range(0, len(text), limit)]


class MainRunner:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or get_db_path()
        self.cache_dir = get_cache_dir()
        self.token = get_telegram_token()
        self.chat_id = get_telegram_chat_id()
        self.today_str = taipei_today_str()
        logger.info(f"🚀 初始化 WayneBot 主排程 (DB: {self.db_path}, 日期: {self.today_str})")
        ensure_core_schema(self.db_path)
        try:
            from dongzhu_tape import ensure_dongzhu_tape_tables, tape_store_path

            ensure_dongzhu_tape_tables(tape_store_path(self.db_path))
        except Exception:
            logger.debug("進化落檔表略過", exc_info=True)

        try:
            from quote_integrity import ensure_quote_integrity

            stats = ensure_quote_integrity(self.db_path)
            if any(int(v or 0) for v in stats.values()):
                logger.info("行情庫清假資料：%s", stats)
        except Exception:
            logger.debug("行情庫清假略過", exc_info=True)

        FetcherCls = DataFetcher or TaiwanMarketFetcher
        if FetcherCls:
            self.fetcher = FetcherCls(db_path=self.db_path, cache_dir=self.cache_dir)
        else:
            self.fetcher = None
            logger.warning("⚠️ 未檢測到 data_fetcher 模組。")

        self.screening_engine = None
        if ScreeningEngine:
            try:
                self.screening_engine = ScreeningEngine(db_path=self.db_path)
            except Exception as e:
                logger.warning(f"⚠️ ScreeningEngine 初始化異常: {e}")

        self.portfolio_engine = None
        if PortfolioEngine:
            try:
                self.portfolio_engine = PortfolioEngine(db_path=self.db_path)
            except Exception as e:
                logger.warning(f"⚠️ PortfolioEngine 初始化異常: {e}")

        self.bot = None
        if WayneTelegramBot and self.token:
            try:
                self.bot = WayneTelegramBot(token=self.token, chat_id=self.chat_id, db_path=self.db_path)
            except Exception as ex:
                logger.error(f"❌ Telegram Bot 初始化失敗: {ex}")
        elif not self.token:
            logger.warning("ℹ️ 未設置 Telegram Token，將輸出日誌而不推播。")

    def already_completed_today(self, run_date: str = None) -> bool:
        key = run_date or self.today_str
        if self.pipeline_status(key) == "success":
            return True
        # 寄出回執也算完成（蓋戳失敗仍不准重寄）
        return self.push_already_delivered(key)

    def pipeline_status(self, run_date: str = None) -> str:
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                "SELECT status FROM pipeline_runs WHERE run_date = ?;",
                (run_date or self.today_str,),
            )
            row = cur.fetchone()
            return str(row[0] or "") if row else ""
        except sqlite3.OperationalError:
            # 單測／空殼 DB 可能還沒建 pipeline_runs；當成未完成，不准炸寄送路徑
            return ""
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def push_already_delivered(self, run_date: str) -> bool:
        """pipeline success 或寄出回執任一成立＝已寄到白名單。"""
        key = str(run_date or "").strip()
        if not key:
            return False
        if self.pipeline_status(key) == "success":
            return True
        try:
            from pipeline_delivery import push_delivery_recorded

            return bool(push_delivery_recorded(self.db_path, key))
        except Exception:
            logger.debug("查寄出回執略過 key=%s", key, exc_info=True)
            return False

    def record_whitelist_push(
        self,
        run_date: str,
        *,
        kind: str,
        n_ok: int = 0,
        notes: str = "",
    ) -> bool:
        """Telegram 白名單寄出成功後立刻落回執（先於／優於 pipeline success 蓋戳）。"""
        from pipeline_delivery import record_push_delivery

        return bool(
            record_push_delivery(
                self.db_path,
                run_date,
                kind=kind,
                n_ok=n_ok,
                notes=notes,
            )
        )

    def honor_push_delivery(self, run_date: str, *, notes: str = "delivery-receipt") -> bool:
        """若已有寄出回執：補標 pipeline success，回 True＝不准再寄。"""
        key = str(run_date or "").strip()
        if not key:
            return False
        if self.pipeline_status(key) == "success":
            return True
        if not self.push_already_delivered(key):
            return False
        try:
            self._mark_pipeline("success", notes[:500], run_date=key, retries=12)
        except Exception:
            logger.exception("回執補蓋 success 失敗 key=%s（仍視為已寄）", key)
        logger.info("已有寄出回執，略過重寄並補標 success key=%s", key)
        return True

    def release_stale_morning_delivery_for_open_day(self, run_date: str) -> bool:
        """§14：開市日必寄。as_of 未前進時 screen-{as_of} 舊開市日回執不准擋今日真寄。

        僅 screen-*（不含 screen-closed-*）。回執台北日 < 今日開市日曆日 → 清回執＋
        降 success→computed，回 True＝已放行可重寄。同日回執仍擋（防雙寄）。
        """
        key = str(run_date or "").strip()
        if not key.startswith("screen-") or key.startswith("screen-closed-"):
            return False
        today = str(getattr(self, "today_str", "") or "").strip()
        if len(today) != 8:
            try:
                from config import taipei_now

                today = taipei_now().strftime("%Y%m%d")
            except Exception:
                return False
        try:
            from trading_calendar import is_tw_open_calendar_day

            if not is_tw_open_calendar_day(today):
                return False
        except Exception:
            logger.debug("開市日判斷略過 key=%s", key, exc_info=True)
            return False
        try:
            from pipeline_delivery import (
                clear_push_delivery,
                delivery_taipei_ymd,
                load_push_delivery,
                push_delivery_recorded,
            )
        except Exception:
            logger.debug("pipeline_delivery 匯入略過", exc_info=True)
            return False
        delivered_ymd = ""
        try:
            loaded = load_push_delivery(self.db_path, key) or {}
            delivered_ymd = delivery_taipei_ymd(str(loaded.get("delivered_at") or ""))
        except Exception:
            logger.debug("讀回執日略過 key=%s", key, exc_info=True)
        # 無回執但 pipeline success：仍可能是舊開市日蓋戳；用 finished_at 當日
        if not delivered_ymd and self.pipeline_status(key) == "success":
            try:
                conn = sqlite3.connect(self.db_path, timeout=15.0)
                try:
                    conn.execute("PRAGMA busy_timeout=3000;")
                    row = conn.execute(
                        "SELECT finished_at FROM pipeline_runs WHERE run_date=?",
                        (key,),
                    ).fetchone()
                finally:
                    conn.close()
                if row:
                    delivered_ymd = delivery_taipei_ymd(str(row[0] or ""))
            except Exception:
                logger.debug("讀 pipeline finished_at 略過 key=%s", key, exc_info=True)
        if not delivered_ymd:
            # 有回執檔但時戳壞掉：保守不放行（避免同日雙寄）
            if push_delivery_recorded(self.db_path, key):
                return False
            return False
        if delivered_ymd >= today:
            return False
        # 舊開市日（或更早）回執：清掉才能搶鎖真寄
        try:
            clear_push_delivery(
                self.db_path, key, bak_suffix=f".bak-reissue-{today}"
            )
        except Exception:
            logger.exception("清舊開市日回執失敗 key=%s", key)
            return False
        if self.pipeline_status(key) == "success":
            try:
                self._mark_pipeline(
                    "computed",
                    f"§14 open-day reissue demote prior={delivered_ymd}",
                    run_date=key,
                    retries=8,
                )
            except Exception:
                logger.exception("舊開市日 success 降級失敗 key=%s", key)
                return False
        logger.info(
            "§14 開市日放行重寄：%s 回執日 %s < 今日 %s（as_of 未前進）",
            key,
            delivered_ymd,
            today,
        )
        return True

    def reconcile_push_deliveries(self, *, prefix: str = "") -> int:
        """掃有回執但 pipeline 非 success 的鍵，補標 success（force／catch-up 前必跑）。"""
        from pipeline_delivery import ensure_delivery_schema

        n = 0
        pref = str(prefix or "")
        rows: list = []
        try:
            ensure_delivery_schema(self.db_path)
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            try:
                conn.execute("PRAGMA busy_timeout=10000")
                rows = list(
                    conn.execute("SELECT run_date FROM pipeline_deliveries").fetchall()
                )
            finally:
                conn.close()
        except Exception:
            logger.debug("reconcile 讀回執略過", exc_info=True)
        # 檔案回執也掃（DB 寫失敗時仍在）
        try:
            from pipeline_delivery import _delivery_dir

            for p in _delivery_dir(self.db_path).glob("*.json"):
                rows.append((p.stem,))
        except Exception:
            logger.debug("reconcile 掃檔略過", exc_info=True)
        seen = set()
        for (run_date,) in rows:
            key = str(run_date or "").strip()
            if not key or key in seen:
                continue
            if pref and not key.startswith(pref):
                continue
            seen.add(key)
            if self.pipeline_status(key) == "success":
                continue
            if self.honor_push_delivery(key, notes="delivery-reconcile"):
                n += 1
        return n

    def try_claim_pipeline(
        self,
        run_date: str,
        *,
        notes: str = "claim",
        stale_running_sec: int = 600,
        allow_stale_running: bool = True,
    ) -> bool:
        """搶尾盤／早報推播鎖：同一 run_date 同時只准一個路徑寄。

        success＝已寄過，永不重搶。
        寄出回執＝已寄過（即使 pipeline 仍 running／computed），永不重搶並補標 success。
        running＝別條進行中；allow_stale_running=False 時連逾時也不重搶
        （尾盤用：Render 重開不准把「可能已寄出的 running」再寄一次）。
        computed＝明確寄失敗，可重搶補寄（無回執時）。
        回 True＝本行程取得所有權，必須寄完立刻標 success，或失敗改 computed。
        """
        key = str(run_date or "").strip()
        if not key:
            return False
        # 回執優先於搶鎖：已寄過就不准重搶（2026-10-23 雙寄根因）
        if self.honor_push_delivery(key, notes="delivery-before-claim"):
            return False
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000;")
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status, finished_at FROM pipeline_runs WHERE run_date = ?",
                (key,),
            ).fetchone()
            if row:
                st = str(row[0] or "")
                if st == "success":
                    conn.commit()
                    return False
                if st == "running":
                    if not allow_stale_running:
                        # 可能已送到 Telegram 但殺行程來不及標 success；重搶＝連寄。
                        conn.commit()
                        return False
                    fin = str(row[1] or "")
                    age_ok = False
                    try:
                        age_ok = _stamp_age_seconds(fin) > float(stale_running_sec)
                    except Exception:
                        age_ok = True
                    if not age_ok:
                        conn.commit()
                        return False
            conn.execute(
                "INSERT OR REPLACE INTO pipeline_runs "
                "(run_date, finished_at, status, notes) VALUES (?, ?, ?, ?)",
                (
                    key,
                    taipei_stamp(),
                    "running",
                    str(notes or "claim")[:500],
                ),
            )
            conn.commit()
            return True
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def touch_pipeline_running(self, run_date: str) -> bool:
        """早報進行中續租：只更新 running 的 finished_at，不改 status／notes。"""
        key = str(run_date or "").strip()
        if not key:
            return False
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            conn.execute("PRAGMA busy_timeout=5000;")
            cur = conn.execute(
                "UPDATE pipeline_runs SET finished_at = ? "
                "WHERE run_date = ? AND status = 'running'",
                (taipei_stamp(), key),
            )
            conn.commit()
            return cur.rowcount > 0
        except Exception:
            logger.debug("pipeline running 續租失敗 key=%s", key, exc_info=True)
            return False
        finally:
            conn.close()

    @contextmanager
    def _morning_running_lease(
        self,
        run_date: str,
        *,
        interval_sec: float = 60.0,
        max_lease_sec: float | None = None,
    ):
        """持鎖期間定期續 finished_at；行程死掉後租約過期才能重搶補寄。

        max_lease_sec（預設＝MORNING_CLAIM_AGE_DEMOTE_SEC）：逾時停止續租，
        讓卡死全掃的行程不再把 finished_at 一直刷新；逾齡 demote 才能放行 §14。
        不在此降 computed（避免與仍在寄送的 body 雙寄）；只停續租。
        """
        key = str(run_date or "").strip()
        stop = threading.Event()
        cap = float(
            MORNING_CLAIM_AGE_DEMOTE_SEC if max_lease_sec is None else max_lease_sec
        )
        started = time.monotonic()

        def _beat() -> None:
            while not stop.wait(float(interval_sec)):
                if time.monotonic() - started >= cap:
                    logger.warning(
                        "pipeline lease 停續租 key=%s（已滿 %.0fs，准許補寄重搶）",
                        key,
                        cap,
                    )
                    break
                try:
                    self.touch_pipeline_running(key)
                except Exception:
                    logger.debug("morning lease beat 失敗 key=%s", key, exc_info=True)

        t = threading.Thread(target=_beat, name="morning-lease", daemon=True)
        t.start()
        try:
            yield
        finally:
            stop.set()
            t.join(timeout=2.0)

    def demote_premature_morning_screens(self) -> int:
        """盤後當日補跑若先標 screen-{as_of} success，隔天 06:30 會略過、吃不到美股隔夜。

        若 success 的 finished_at（台北曆日）<= as_of，視為過早，降成 computed 讓真・早報可寄。
        """
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT run_date, finished_at, notes
                FROM pipeline_runs
                WHERE run_date LIKE 'screen-%' AND status = 'success'
                """
            ).fetchall()
            n = 0
            for run_date, finished_at, notes in rows:
                as_of = str(run_date or "").replace("screen-", "", 1)
                if not (as_of.isdigit() and len(as_of) == 8):
                    continue
                fin_tw = self._pipeline_finished_tw_ymd(finished_at)
                if not fin_tw or fin_tw > as_of:
                    continue
                note = str(notes or "")
                if "premature-morning" not in note:
                    note = (note + " premature-morning-before-us").strip()
                conn.execute(
                    """
                    UPDATE pipeline_runs
                    SET status = 'computed', notes = ?
                    WHERE run_date = ? AND status = 'success'
                    """,
                    (note, run_date),
                )
                n += 1
            if n:
                conn.commit()
            return n
        finally:
            conn.close()

    def demote_holiday_skip_morning_screens(self) -> int:
        """休市日曾把 screen-{as_of} 標 success（tw closed skip），開市日會誤略過真早報。

        連假後基準日不變（例中秋＋教師節仍 screen-20260924），必須降成 computed 才能補寄。
        """
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                """
                SELECT run_date, notes
                FROM pipeline_runs
                WHERE run_date LIKE 'screen-%'
                  AND run_date NOT LIKE 'screen-closed-%'
                  AND status = 'success'
                  AND (
                    notes LIKE '%tw closed%skip morning%'
                    OR notes LIKE '%tw closed%skip screen%'
                  )
                """
            ).fetchall()
            n = 0
            for run_date, notes in rows:
                as_of = str(run_date or "").replace("screen-", "", 1)
                if not (as_of.isdigit() and len(as_of) == 8):
                    continue
                note = str(notes or "")
                if "holiday-skip-demote" not in note:
                    note = (note + " holiday-skip-demote").strip()
                conn.execute(
                    """
                    UPDATE pipeline_runs
                    SET status = 'computed', notes = ?
                    WHERE run_date = ? AND status = 'success'
                    """,
                    (note, run_date),
                )
                n += 1
            if n:
                conn.commit()
            return n
        finally:
            conn.close()

    @staticmethod
    def _pipeline_finished_epoch(finished_at) -> float | None:
        """pipeline finished_at → epoch 秒；解析失敗回 None。"""
        raw = str(finished_at or "").strip()
        if not raw:
            return None
        try:
            from datetime import timezone

            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return float(dt.timestamp())
        except Exception:
            return None

    def demote_orphaned_morning_claims(
        self,
        *,
        retries: int = 8,
        force: bool = False,
        max_age_sec: int | None = None,
    ) -> int:
        """清卡住的 morning-claim running→computed（§14）。

        降級條件（force=True 則全降）：
        1) finished_at 早於本行程開機（前一進程 orphan），或
        2) finished_at 逾 max_age_sec（預設 MORNING_CLAIM_AGE_DEMOTE_SEC）—
           不論是否跨 boot；健康路徑會續租，卡死／OOM 後不再續→逾齡放行。
        只動 screen-*（不含 screen-closed-*）；不准動 success；不准假 success。
        DB lock 會重試；不准一次 locked 就放棄讓 §14 永遠略過。
        """
        age_limit = int(
            MORNING_CLAIM_AGE_DEMOTE_SEC if max_age_sec is None else max_age_sec
        )
        last_err: Exception | None = None
        for attempt in range(max(1, int(retries))):
            conn = None
            try:
                # connect 本身也可能 locked——必須包在重試裡（§14 今早 demote 失敗根因）
                conn = sqlite3.connect(self.db_path, timeout=60.0)
                conn.execute("PRAGMA busy_timeout=30000;")
                rows = conn.execute(
                    """
                    SELECT run_date, finished_at, notes
                    FROM pipeline_runs
                    WHERE run_date LIKE 'screen-%'
                      AND run_date NOT LIKE 'screen-closed-%'
                      AND status = 'running'
                      AND (
                        notes LIKE '%morning-claim%'
                        OR notes LIKE '%morning claim%'
                        OR notes = 'morning-claim'
                      )
                    """
                ).fetchall()
                n = 0
                stamp = taipei_stamp()
                # 5s 緩衝：開機當下時鐘／寫入先後
                boot_cut = float(_PROCESS_BOOT_EPOCH) - 5.0
                now_epoch = time.time()
                for run_date, finished_at, _notes in rows:
                    # 已有 Telegram 寄出回執：不准降 computed 讓人重搶重寄
                    try:
                        from pipeline_delivery import push_delivery_recorded

                        if push_delivery_recorded(self.db_path, str(run_date)):
                            continue
                    except Exception:
                        pass
                    epoch = self._pipeline_finished_epoch(finished_at)
                    note = "morning orphan-boot demote"
                    if not force:
                        pre_boot = epoch is None or epoch < boot_cut
                        aged = False
                        if epoch is not None and age_limit >= 0:
                            aged = (now_epoch - float(epoch)) > float(age_limit)
                        if not pre_boot and not aged:
                            # 本行程持鎖且未逾齡：保留，防雙寄
                            continue
                        if aged and not pre_boot:
                            note = "morning age demote"
                    else:
                        note = "morning force demote"
                    cur = conn.execute(
                        """
                        UPDATE pipeline_runs
                        SET status = 'computed',
                            notes = ?,
                            finished_at = ?
                        WHERE run_date = ? AND status = 'running'
                        """,
                        (note, stamp, run_date),
                    )
                    n += int(cur.rowcount or 0)
                conn.commit()
                return n
            except sqlite3.OperationalError as e:
                last_err = e
                if conn is not None:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                logger.warning(
                    "開機清 orphan morning-claim DB busy（%s/%s）：%s",
                    attempt + 1,
                    retries,
                    e,
                )
                time.sleep(1.5 * (attempt + 1))
            except Exception:
                if conn is not None:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                logger.exception("開機清 orphan morning-claim 失敗")
                return 0
            finally:
                if conn is not None:
                    conn.close()
        if last_err is not None:
            logger.error(
                "開機清 orphan morning-claim 連續 DB locked，放棄本輪：%s",
                last_err,
            )
        return 0

    def demote_orphaned_increment_claims(
        self,
        *,
        retries: int = 8,
        force: bool = False,
        max_age_sec: int | None = None,
    ) -> int:
        """清卡住的 increment-claim running→computed（§14 讓路早報）。

        前一進程 OOM／Deploy 後，假 running 會讓補跑 fuse 搶鎖失敗或雙開鎖死 DB。
        年齡預設 INCREMENT_RUNNING_STALE_SEC；force 全降。
        """
        age_limit = int(
            INCREMENT_RUNNING_STALE_SEC if max_age_sec is None else max_age_sec
        )
        last_err: Exception | None = None
        for attempt in range(max(1, int(retries))):
            conn = None
            try:
                conn = sqlite3.connect(self.db_path, timeout=60.0)
                conn.execute("PRAGMA busy_timeout=30000;")
                rows = conn.execute(
                    """
                    SELECT run_date, finished_at, notes
                    FROM pipeline_runs
                    WHERE status = 'running'
                      AND run_date NOT LIKE 'screen-%'
                      AND (
                        notes LIKE '%increment-claim%'
                        OR notes LIKE '%increment claim%'
                        OR notes = 'increment-claim'
                      )
                    """
                ).fetchall()
                n = 0
                stamp = taipei_stamp()
                boot_cut = float(_PROCESS_BOOT_EPOCH) - 5.0
                now_epoch = time.time()
                for run_date, finished_at, _notes in rows:
                    epoch = self._pipeline_finished_epoch(finished_at)
                    note = "increment orphan-boot demote"
                    if not force:
                        pre_boot = epoch is None or epoch < boot_cut
                        aged = False
                        if epoch is not None and age_limit >= 0:
                            aged = (now_epoch - float(epoch)) > float(age_limit)
                        if not pre_boot and not aged:
                            continue
                        if aged and not pre_boot:
                            note = "increment age demote"
                    else:
                        note = "increment force demote"
                    cur = conn.execute(
                        """
                        UPDATE pipeline_runs
                        SET status = 'computed',
                            notes = ?,
                            finished_at = ?
                        WHERE run_date = ? AND status = 'running'
                        """,
                        (note, stamp, run_date),
                    )
                    n += int(cur.rowcount or 0)
                conn.commit()
                return n
            except sqlite3.OperationalError as e:
                last_err = e
                if conn is not None:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                logger.warning(
                    "清 orphan increment-claim DB busy（%s/%s）：%s",
                    attempt + 1,
                    retries,
                    e,
                )
                time.sleep(1.5 * (attempt + 1))
            except Exception:
                if conn is not None:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                logger.exception("清 orphan increment-claim 失敗")
                return 0
            finally:
                if conn is not None:
                    conn.close()
        if last_err is not None:
            logger.error(
                "清 orphan increment-claim 連續 DB locked，放棄本輪：%s",
                last_err,
            )
        return 0

    def force_rescue_morning(self) -> Dict[str, Any]:
        """§14 救援：在常駐碟上強制降 morning-claim，立刻補寄白名單兩人。

        只准 web 常駐呼叫（掛永久碟）；不准 Render 無碟 one-off job。
        若 screen-{as_of} 仍未 success，即使 fuse cap 已往後走，仍針對該 as_of 補寄
        （不准被當日盤後融合把基準日洗成「今天」而略過今早漏寄）。
        """
        out: Dict[str, Any] = {
            "ok": False,
            "demoted": 0,
            "delivered": False,
            "as_of": "",
            "key": "",
            "error": "",
        }
        # 先把「已寄出但蓋戳失敗」的回執補成 success，再 demote／補寄（防 2026-10-23 雙寄）
        try:
            out["reconciled"] = int(
                self.reconcile_push_deliveries(prefix="screen-") or 0
            )
        except Exception:
            logger.exception("force_rescue_morning reconcile 失敗")
            out["reconciled"] = 0
        # 2026-10-27：Deploy 後 boot catch-up 已搶 morning-claim 進行中，force 再 demote
        # 並開第二條會整套雙寄（07:47＋07:56）。新鮮 claim 未寄達＝讓路給進行中那條。
        try:
            if self.morning_claim_is_fresh_running():
                out["ok"] = True
                out["skipped_inflight"] = True
                out["note"] = "fresh morning-claim in progress; skip demote+rerun"
                logger.info(
                    "§14 force-rescue：已有新鮮 morning-claim，不 demote、不另開第二條"
                )
                return out
        except Exception:
            logger.exception("force_rescue 查新鮮 morning-claim 略過")
        try:
            # 假 fuse running 會鎖死寄出；救援先清
            n_inc = int(self.demote_orphaned_increment_claims(force=True) or 0)
            out["demoted_increment"] = n_inc
            out["demoted"] = int(self.demote_orphaned_morning_claims(force=True) or 0)
        except Exception as e:
            out["error"] = f"demote: {e}"
            logger.exception("force_rescue_morning demote 失敗")
            return out
        # 找出未寄出的 screen-*（優先今早漏的），釘死 as_of 再寄
        # 有寄出回執的鍵已在 reconcile 變 success，不會再被當成未寄。
        pin_as_of = ""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            try:
                conn.execute("PRAGMA busy_timeout=10000;")
                row = conn.execute(
                    """
                    SELECT run_date FROM pipeline_runs
                    WHERE run_date LIKE 'screen-%'
                      AND run_date NOT LIKE 'screen-closed-%'
                      AND status != 'success'
                    ORDER BY finished_at DESC
                    LIMIT 1
                    """
                ).fetchone()
                if row and str(row[0]).startswith("screen-"):
                    pin_as_of = str(row[0]).replace("screen-", "", 1)
            finally:
                conn.close()
        except Exception:
            logger.debug("force_rescue 查未寄 screen 略過", exc_info=True)
        # 若釘到的鍵其實已有回執（檔在、表尚未）→ 補標後不要當未寄
        if pin_as_of and self.honor_push_delivery(
            f"screen-{pin_as_of}", notes="force-rescue-receipt"
        ):
            pin_as_of = ""
        try:
            from import_health import latest_complete_quote_date

            latest = str(latest_complete_quote_date(self.db_path) or "")
            # 不准釘到與 latest 無關的舊 computed（會洗掉今早真鍵）
            if pin_as_of and latest and pin_as_of != latest:
                logger.info(
                    "force_rescue 忽略舊未寄鍵 screen-%s（latest=%s）",
                    pin_as_of,
                    latest,
                )
                pin_as_of = ""
            as_of = pin_as_of or latest
            out["as_of"] = str(as_of)
            out["key"] = f"screen-{as_of or 'none'}"
        except Exception:
            pass
        # §14 救援：連假後同一 as_of 舊回執先放行，再跑早報（否則永遠略過）
        try:
            if out.get("key"):
                if self.release_stale_morning_delivery_for_open_day(str(out["key"])):
                    out["reissued_stale"] = True
                    pin_as_of = ""
        except Exception:
            logger.exception("force_rescue 開市日舊回執放行略過")
        try:
            # 救援路徑：釘基準日，避免 fuse 把 latest 推到今日後寄錯鍵／略過
            if pin_as_of:
                os.environ["WAYNE_MORNING_PIN_AS_OF"] = str(pin_as_of)
            try:
                ok = bool(self.run_morning_screen(skip_if_done=True, notify=True))
            finally:
                os.environ.pop("WAYNE_MORNING_PIN_AS_OF", None)
            out["ok"] = ok
            st = self.pipeline_status(out["key"]) if out["key"] else ""
            out["delivered"] = st == "success"
            out["status"] = st or ""
        except Exception as e:
            out["error"] = f"morning: {e}"
            logger.exception("force_rescue_morning 早報失敗")
        return out

    def morning_claim_is_fresh_running(self, *, stale_running_sec: int | None = None) -> bool:
        """是否有未過期的 morning-claim running（補建快取／開機融合應讓路）。"""
        stale = int(
            MORNING_RUNNING_STALE_SEC if stale_running_sec is None else stale_running_sec
        )
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        try:
            conn.execute("PRAGMA busy_timeout=3000;")
            rows = conn.execute(
                """
                SELECT finished_at FROM pipeline_runs
                WHERE run_date LIKE 'screen-%'
                  AND run_date NOT LIKE 'screen-closed-%'
                  AND status = 'running'
                  AND notes LIKE '%morning%'
                """
            ).fetchall()
            for (fin,) in rows:
                try:
                    if _stamp_age_seconds(str(fin or "")) <= float(stale):
                        return True
                except Exception:
                    return True
            return False
        except Exception:
            logger.debug("查 morning-claim running 略過", exc_info=True)
            return False
        finally:
            conn.close()

    @staticmethod
    def _pipeline_finished_tw_ymd(finished_at) -> str:
        """pipeline finished_at → 台北 YYYYMMDD；解析失敗回空字串。"""
        if not finished_at:
            return ""
        raw = str(finished_at).strip()
        try:
            from datetime import datetime, timezone
            from zoneinfo import ZoneInfo

            if raw.endswith("Z"):
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            else:
                dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                # Release／舊列多半當 UTC 存
                dt = dt.replace(tzinfo=timezone.utc)
            tw = dt.astimezone(ZoneInfo("Asia/Taipei"))
            return tw.strftime("%Y%m%d")
        except Exception:
            digits = "".join(ch for ch in raw[:10] if ch.isdigit())
            return digits if len(digits) == 8 else ""

    def demote_unsent_screen_success(self) -> int:
        """GHA 從不寄海選。zip 裡 screen-* success 是 401／notify-off 假已寄。

        寫進 Release 前改成 computed，空碟還原時 Render 才會真寄。
        非 GitHub Actions 不改（常駐 success 是真的送到）。
        """
        if not (os.getenv("GITHUB_ACTIONS") or "").strip():
            return 0
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                """
                UPDATE pipeline_runs
                SET status = 'computed',
                    notes = CASE
                        WHEN COALESCE(notes, '') LIKE '%gha-sanitize%' THEN notes
                        ELSE trim(COALESCE(notes, '') || ' gha-sanitize-no-send')
                    END
                WHERE run_date LIKE 'screen-%' AND status = 'success'
                """
            )
            n = int(cur.rowcount or 0)
            conn.commit()
            return n
        finally:
            conn.close()

    def _mark_pipeline(
        self,
        status: str,
        notes: str = "",
        run_date: str = None,
        *,
        retries: int = 8,
    ):
        """寫 pipeline_runs。DB locked 必須重試——海選已寄出卻蓋戳失敗會讓 force／catch-up 重寄（2026-10-23）。"""
        key = run_date or self.today_str
        stamp = taipei_stamp()
        last_err: Optional[Exception] = None
        attempts = max(1, int(retries or 1))
        for attempt in range(attempts):
            try:
                conn = sqlite3.connect(self.db_path, timeout=30)
                try:
                    conn.execute("PRAGMA busy_timeout=30000")
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT OR REPLACE INTO pipeline_runs "
                        "(run_date, finished_at, status, notes) VALUES (?, ?, ?, ?);",
                        (key, stamp, status, notes),
                    )
                    conn.commit()
                finally:
                    conn.close()
                return
            except sqlite3.OperationalError as e:
                last_err = e
                msg = str(e).lower()
                if "locked" not in msg and "busy" not in msg:
                    raise
                logger.warning(
                    "pipeline 蓋戳 DB busy（%s/%s）key=%s status=%s：%s",
                    attempt + 1,
                    attempts,
                    key,
                    status,
                    e,
                )
                time.sleep(0.4 * (attempt + 1))
        logger.error(
            "pipeline 蓋戳失敗 key=%s status=%s notes=%s：%s",
            key,
            status,
            notes,
            last_err,
        )
        if last_err is not None:
            raise last_err

    def send_telegram_message(self, text: str, chat_id: Optional[str] = None) -> bool:
        if not text:
            return False
        target = chat_id or getattr(self, "chat_id", None)
        ok = True
        n = 0
        for part in chunk_telegram_text(text):
            n += 1
            if self._send_one(part, target) is False:
                ok = False
        return bool(n and ok)

    def _family_chat_ids(self) -> list:
        """只寄白名單：偉權＋哥哥。不掃 tg_users，陌生人按開始也不會進早報。"""
        from config import allowed_telegram_uids

        ids = [str(u).strip() for u in allowed_telegram_uids() if str(u).strip()]
        if ids:
            return ids
        owner = str(getattr(self, "chat_id", None) or "").strip()
        return [owner] if owner else []

    def _broadcast_family(self, text: str) -> bool:
        if not text:
            return False
        ids = self._family_chat_ids()
        if not ids:
            return bool(self.send_telegram_message(text))
        ok = True
        for cid in ids:
            if self.send_telegram_message(text, chat_id=cid) is False:
                ok = False
        return ok

    def _send_one(self, text: str, chat_id: str) -> bool:
        if self.bot and hasattr(self.bot, "send_message"):
            try:
                sent = self.bot.send_message(text, chat_id=chat_id)
                if sent is False:
                    logger.warning("⚠️ bot.send_message 回報 Telegram 未接受，切換原生 API...")
                else:
                    logger.info("📤 透過 WayneTelegramBot 成功發送推播")
                    return True
            except Exception as e:
                logger.warning(f"⚠️ bot.send_message 失敗: {e}，切換原生 API...")
        if self.token and chat_id:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
            try:
                resp = requests.post(url, json=payload, timeout=15)
                if resp.status_code == 200:
                    logger.info("📤 原生 API 成功送出 Telegram 推播")
                    try:
                        from tg_message_ttl import record_from_api_result

                        record_from_api_result(
                            resp.json() if resp.content else {},
                            chat_id=chat_id,
                            db_path=getattr(self, "db_path", "") or "",
                            kind="runner_send",
                        )
                    except Exception:
                        pass
                    return True
                logger.error(f"❌ Telegram API 錯誤 ({resp.status_code}): {resp.text}")
                return False
            except Exception as e:
                logger.error(f"❌ 發送 Telegram 異常: {e}")
                return False
        logger.info(f"📋 [本機推播預覽]\n{text}")
        # 沒有 token 的本機預覽不算已寄到，避免 skip_if_done 把預覽當成功。
        return False

    def run_daily_increment(self, notify: bool = True) -> int:
        logger.info(f"📥 開始 {self.today_str} 增量更新...")
        try:
            from wayne_db import normalize_quote_hygiene
            hyg = normalize_quote_hygiene(self.db_path)
            if hyg.get("date_fixed") or hyg.get("volume_filled"):
                logger.info(f"行情清洗：{hyg}")
        except Exception as e:
            logger.warning(f"行情清洗略過：{e}")

        try:
            from universe import restore_universe_if_wiped, sync_universe

            healed = restore_universe_if_wiped(self.db_path)
            if healed:
                logger.warning("增量前母體全被關掉，已重新打開 %s 檔", healed)
            stats = sync_universe(self.db_path)
            logger.info(f"母體同步：{stats}")
        except Exception as e:
            logger.warning(f"母體同步略過：{e}")

        inserted_count = 0
        fuse_to = fuse_end_date()
        if self.fetcher and hasattr(self.fetcher, "fill_missing_market_days"):
            try:
                gap = self.fetcher.fill_missing_market_days(end_date=fuse_to)
                logger.info("缺日回補：%s", gap)
                inserted_count = len(gap.get("filled") or [])
                if hasattr(self.fetcher, "_refill_thin_days"):
                    extra = self.fetcher._refill_thin_days(fuse_to, lookback=40, min_rows=1800)
                    if extra:
                        logger.info("稀薄日再補：%s", extra)
                        inserted_count += len(extra)
            except Exception as e:
                logger.error(f"❌ 缺日回補異常: {e}", exc_info=True)
        elif self.fetcher and hasattr(self.fetcher, "update_daily_market_data"):
            try:
                inserted_count = int(self.fetcher.update_daily_market_data(fuse_to) or 0)
            except Exception as e:
                logger.error(f"❌ 增量更新異常: {e}", exc_info=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM daily_quotes WHERE date=?;", (fuse_to,))
        count = cursor.fetchone()[0]
        conn.close()
        if count > inserted_count:
            inserted_count = count

        # 興櫃與上市櫃日 K 同一趟必跑（2026-10-30 鎖死；失敗＝融合未完成）
        em_req = self._sync_emerging_required(fuse_to, label="盤後增量")
        if em_req.get("ok"):
            logger.info("興櫃官方日均價寫入：%s", em_req.get("stats"))
        else:
            logger.error(
                "興櫃日均價同步未完成（不准略過／不准假 success）：%s",
                em_req.get("error") or em_req,
            )

        try:
            from chips import update_chips_for_date, backfill_chips
            n = update_chips_for_date(self.db_path, self.today_str)
            logger.info(f"當日法人更新 {n} 列")
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            try:
                from quote_integrity import db_as_of_trading_date

                latest = db_as_of_trading_date(self.db_path) or ""
            except Exception:
                cur.execute("SELECT MAX(date) FROM daily_quotes;")
                latest = cur.fetchone()[0]
            chip_sum = 0
            if latest:
                chip_sum = cur.execute(
                    "SELECT COALESCE(SUM(ABS(foreign_net)+ABS(trust_net)+ABS(dealer_net)),0) FROM daily_quotes WHERE date=?",
                    (str(latest).replace("-", ""),),
                ).fetchone()[0]
            conn.close()
            # 股→張公式修好後，庫裡若已有「股當張」殘值，chip_sum≠0 不會觸發回補。
            # 每晚重抓近 90 交易日＋殘值日，把錯單位蓋成張。
            why = "最近交易日籌碼仍為 0" if chip_sum == 0 else "重抓近窗蓋掉股當張殘值"
            logger.info("%s，回補近 90 個交易日法人…", why)
            bf = backfill_chips(self.db_path, days=90)
            logger.info(f"法人回補：{bf}")
            try:
                from chips import rebake_share_as_lot_chip_dates, scrub_share_as_lot_residue_offline

                n_zero = scrub_share_as_lot_residue_offline(self.db_path)
                rb = rebake_share_as_lot_chip_dates(self.db_path, since_ymd="20260101")
                logger.info("法人殘值離線歸零 %s；殘值日重抓 %s", n_zero, rb)
            except Exception as e_rb:
                logger.warning("法人殘值重抓略過：%s", e_rb)
        except Exception as e:
            logger.error(f"法人籌碼更新失敗: {e}", exc_info=True)

        try:
            from industry_fine import sync_all_fine_industry

            fi = sync_all_fine_industry(self.db_path, workers=8)
            logger.info("籌碼K細項全市場：%s", fi)
        except Exception as e:
            logger.warning("籌碼K細項同步略過：%s", e)

        try:
            from import_health import clear_complete_date_cache
            from money_flow import recompute_sector_flow

            clear_complete_date_cache(self.db_path)
            n_sec = recompute_sector_flow(self.db_path, fuse_to)
            logger.info("盤後產業資金輪動寫入 %s 列", n_sec)
        except Exception as e:
            logger.error("產業資金輪動失敗: %s", e, exc_info=True)
        try:
            from biaoke_field_scan import record_dongzhu_flow

            n_dz = record_dongzhu_flow(self.db_path, fuse_to)
            logger.info("洞燭先機資金帶寫入 %s 列", n_dz)
        except Exception as e:
            logger.error("洞燭先機資金帶失敗: %s", e, exc_info=True)
        try:
            from import_health import audit_import

            dz_health = audit_import(self.db_path, fuse_to)
            if self._increment_ok(dz_health):
                self._refresh_dongzhu_after_close(fuse_to)
            else:
                logger.info("洞燭先機走查等盤後齊（匯入可能延遲）：%s", dz_health)
        except Exception as e:
            logger.error("洞燭先機走查失敗: %s", e, exc_info=True)

        try:
            from fundamentals import sync_fundamentals
            fund = sync_fundamentals(self.db_path)
            logger.info(f"月營收／季報同步：{fund}")
        except Exception as e:
            logger.error(f"基本面同步失敗: {e}", exc_info=True)
        try:
            from ex_rights import sync_ex_rights

            xr = sync_ex_rights(self.db_path)
            logger.info("官方除權息融合：%s", xr)
            try:
                from ex_rights import sync_ex_preview

                preview = sync_ex_preview(self.db_path)
                logger.info("除權息預告 TWT48U：%s", preview)
            except Exception as e_prev:
                logger.warning("除權息預告略過：%s", e_prev)
            try:
                from company_events import sync_company_events

                ev = sync_company_events(self.db_path)
                logger.info("股東會／法說日期建檔：%s", ev)
            except Exception as e_ev:
                logger.warning("公司行事建檔略過：%s", e_ev)
        except Exception as e:
            logger.error(f"除權息同步失敗: {e}", exc_info=True)
        try:
            from broker_points import sync_broker_archive

            br = sync_broker_archive(self.db_path, fuse_to)
            logger.info("分點建檔：%s", br)
        except Exception as e_br:
            logger.warning("分點建檔略過：%s", e_br)
        try:
            from taiwan_market import sync_index_daily

            ix = sync_index_daily(self.db_path)
            logger.info("加權指數寫入 index_daily：%s", ix)
            try:
                from taiwan_market import sync_index_breadth_daily

                br = sync_index_breadth_daily(self.db_path)
                logger.info("漲跌家數寫入 index_breadth_daily：%s", br)
            except Exception as e_br:
                logger.warning("漲跌家數同步略過：%s", e_br)
            try:
                from taiwan_market import sync_futures_daily

                fut = sync_futures_daily(self.db_path)
                logger.info("台指期寫入 futures_daily：%s", fut)
            except Exception as e_fut:
                logger.warning("台指期同步略過：%s", e_fut)
            try:
                from taiwan_market import sync_futures_inst_oi

                foi = sync_futures_inst_oi(self.db_path)
                logger.info("台指期外資未平倉寫入：%s", foi)
            except Exception as e_foi:
                logger.warning("台指期外資未平倉略過：%s", e_foi)
            try:
                from taiwan_market import sync_regime_ai_weights

                sync_regime_ai_weights(self.db_path)
            except Exception as e2:
                logger.warning("大盤 regime AI 權重略過：%s", e2)
        except Exception as e:
            logger.warning("加權指數同步略過：%s", e)
        try:
            self._refresh_twii_forecast_after_close(fuse_to)
        except Exception as e_fc:
            logger.error("大盤默默落檔失敗: %s", e_fc, exc_info=True)
        try:
            from official_snapshots import sync_official_snapshots

            extra = sync_official_snapshots(self.db_path)
            logger.info("官方估值／資券／當沖／加權量：%s", extra)
        except Exception as e_off:
            logger.warning("官方快照略過：%s", e_off)
        try:
            from import_health import audit_import, format_audit_plain
            health = audit_import(self.db_path)
            logger.info("盤後匯入檢查：%s", health)
            if self.fetcher and hasattr(self.fetcher, "sync_paired_markets"):
                paired = self.fetcher.sync_paired_markets()
                if paired:
                    logger.info("開盤日缺邊已重抓：%s", paired)
                    health = audit_import(self.db_path)
            elif health.get("history_issues") and self.fetcher and hasattr(self.fetcher, "update_daily_market_data"):
                for item in health["history_issues"]:
                    ds = item["date"]
                    logger.warning("開盤日缺邊，重抓 %s：%s", ds, item["problems"])
                    self.fetcher.update_daily_market_data(ds)
                    time.sleep(0.4)
                health = audit_import(self.db_path)
            if not self._increment_ok(health):
                # 只在日資料閘失敗時推提醒；月營收／除權息等軟缺不進 incomplete、不推告警
                logger.warning("匯入今天異常：%s", format_audit_plain(health))
                if notify:
                    try:
                        self.send_telegram_message("⚠️ " + format_audit_plain(health))
                    except Exception:
                        pass
            elif health.get("problems"):
                logger.info("日資料齊、其他待補（不擋融合／不推）：%s", format_audit_plain(health))
            elif health.get("history_issue_n"):
                logger.info("今天日K正常，舊日缺邊：%s", format_audit_plain(health))
            else:
                logger.info("盤後匯入今天正常：%s", format_audit_plain(health))
        except Exception as e:
            logger.warning("匯入檢查略過：%s", e)

        try:
            from quote_integrity import ensure_quote_integrity

            scrub = ensure_quote_integrity(self.db_path)
            if any(int(v or 0) for v in scrub.values()):
                logger.info("融合後清假資料：%s", scrub)
        except Exception:
            logger.debug("融合後清假略過", exc_info=True)

        try:
            if self.fetcher and hasattr(self.fetcher, "fill_historical_market_days"):
                hist = self.fetcher.fill_historical_market_days(
                    max_days=12, sleep_s=0.45, skip_chips=True
                )
                if hist.get("filled") or hist.get("pending"):
                    logger.info(
                        "歷史日K缺口 filled=%s pending=%s",
                        hist.get("filled"),
                        hist.get("pending"),
                    )
        except Exception as e_hist:
            logger.warning("歷史日K回補略過：%s", e_hist)
        try:
            from kline_hop import refresh_biaoke_minutes

            mins = refresh_biaoke_minutes(self.db_path)
            logger.info("台指期15/60分：%s", {k: mins.get(k) for k in ("ok", "saved", "tx")})
        except Exception as e_min:
            logger.warning("15分回補略過：%s", e_min)

        return inserted_count

    def _load_latest_quotes_map(self) -> Dict[str, Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path, timeout=8.0)
        try:
            try:
                conn.execute("PRAGMA busy_timeout=2500")
            except sqlite3.Error:
                pass
            cur = conn.cursor()
            latest = ""
            try:
                from quote_integrity import db_as_of_trading_date

                latest = db_as_of_trading_date(self.db_path) or ""
            except Exception:
                latest = ""
            if not latest:
                try:
                    cur.execute("SELECT MAX(date) FROM daily_quotes;")
                    row = cur.fetchone()
                    latest = str((row or [None])[0] or "")
                except sqlite3.Error:
                    latest = ""
            quotes: Dict[str, Dict[str, Any]] = {}
            if latest:
                try:
                    cur.execute(
                        "SELECT stock_id, stock_name, close, pct_change, volume, turnover_k FROM daily_quotes WHERE date=?;",
                        (latest,),
                    )
                    for sid, sname, close_p, pct, vol, to_k in cur.fetchall():
                        quotes[sid] = {
                            "stock_name": sname, "close": close_p, "pct_change": pct,
                            "volume": vol, "turnover_k": to_k, "is_k20_warning": False, "d20": 0.0,
                        }
                except sqlite3.Error:
                    quotes = {}
            return quotes
        finally:
            conn.close()

    def _screening_fail_message(self) -> str:
        from trading_calendar import format_trading_date_zh, resolve_screen_as_of

        as_of = resolve_screen_as_of(self.db_path) or ""
        as_of_label = format_trading_date_zh(as_of) if as_of else "—"
        return (
            "⚠️ <b>今早海選未完成</b>\n"
            f"基準日（上一個完整收盤） <code>{as_of_label}</code>\n"
            "這是<b>排程通知</b>，不是海選名單。請按主選單「海選」重試（只按一次，等幾分鐘）。\n"
            "<b>當沖／隔日沖</b>請按主選單「當沖」「隔日沖」— 會用盤中現價複核，不是盤後漲停備援名單。"
        )

    def generate_screening_report(self) -> str:
        logger.info("🔍 正在執行四大選股...")
        report_text = ""
        if run_full_screening:
            try:
                from import_health import latest_complete_quote_date

                as_of = latest_complete_quote_date(self.db_path) or ""
                output = self._screening_surviving_oom(
                    as_of, session="morning", apply_us=True
                ) or {}
                report_text = output.get("message") or ""
                logger.info(
                    "四大選股 status=%s scanned=%s",
                    output.get("status"),
                    output.get("total_scanned"),
                )
            except Exception as e:
                logger.error(f"四大選股失敗：{e}", exc_info=True)
        if not report_text:
            report_text = self._screening_fail_message()
        # 自選雷達依 Telegram uid 各做一段，不可綁進這份共用長文（會把擁有者觀察洩給家人）。
        extra = [report_text]
        try:
            from fundamentals import format_hot_revenue_html
            hot = format_hot_revenue_html(self.db_path)
            if hot:
                extra.append("───────────────────")
                extra.append(hot)
        except Exception as e:
            logger.warning("月營收轉強區塊略過：%s", e)
        extra.append("🎯 <i>WayneBot 盤後四大選股已完成</i>")
        extra.append("💡 <i>Telegram 輸入代號可查決策卡；/chips 看籌碼；/fund 看月營收與毛利率</i>")
        return "\n".join([s for s in extra if s])

    def _fallback_sql_report(self) -> str:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            from quote_integrity import db_as_of_trading_date

            latest_date = db_as_of_trading_date(self.db_path) or self.today_str
        except Exception:
            cur.execute("SELECT MAX(date) FROM daily_quotes;")
            latest_date = cur.fetchone()[0] or self.today_str
        cur.execute(
            """SELECT stock_id, stock_name, close, pct_change, volume, trust_net, foreign_net
               FROM daily_quotes WHERE date=? AND volume>=1000 AND pct_change>=2.5
               AND (trust_net>100 OR foreign_net>500) ORDER BY pct_change DESC LIMIT 5;""",
            (latest_date,),
        )
        rows = cur.fetchall()
        conn.close()
        lines = [
            f"📊 <b>【WayneBot 每日盤後量化復盤】</b>",
            f"🗓 <b>交易基準日</b>：<code>{latest_date}</code>",
            "───────────────────",
            "⚡ <b>【動能突破 ＆ 法人籌碼選股】</b>",
        ]
        if rows:
            from tg_layout import html_escape

            for sid, sname, close_p, pct, vol, t_net, f_net in rows:
                lines.append(
                    f"• <b>{html_escape(sid)} {html_escape(sname)}</b> | 收 <code>{close_p:.2f}</code> (<b>+{pct:.2f}%</b>) 量 {vol:,}張"
                )
        else:
            lines.append("• <i>今日無符合高動能突破標準之標的。</i>")
        return "\n".join(lines)

    def _format_portfolio_section(self, telegram_uid: str = "") -> str:
        if not self.portfolio_engine or not telegram_uid:
            return ""
        try:
            from ai_trader import format_ai_desk_html

            return format_ai_desk_html(self.portfolio_engine, telegram_uid)
        except Exception as e:
            logger.warning("AI 帳戶概況略過：%s", e)
            return ""

    def _watch_radar_rows(self, uid: str) -> List[Dict[str, Any]]:
        """觀察鈕寫 user_watchlist；舊表 user_watchlists 若還有列就併入，不互蓋。"""
        uid = str(uid or "").strip()
        merged: Dict[str, Dict[str, Any]] = {}
        db = str(getattr(self, "db_path", None) or "").strip()
        if db:
            try:
                from wayne_db import get_user_watchlist

                rows = []
                for attempt in range(3):
                    try:
                        rows = get_user_watchlist(db, uid) or []
                        break
                    except sqlite3.OperationalError:
                        if attempt >= 2:
                            raise
                        time.sleep(0.05 * (attempt + 1))
                for r in rows:
                    sid = str((r or {}).get("stock_code") or "").strip()
                    if not sid:
                        continue
                    merged[sid] = {
                        "stock_id": sid,
                        "stock_name": str((r or {}).get("stock_name") or sid),
                    }
            except Exception:
                logger.debug("watch radar read user_watchlist uid=%s", uid, exc_info=True)
        eng = getattr(self, "portfolio_engine", None)
        if eng is not None:
            try:
                raw = eng.get_watchlist(uid)
            except Exception:
                raw = []
            if isinstance(raw, (list, tuple)):
                for w in raw:
                    sid = str((w or {}).get("stock_id") or "").strip()
                    if not sid:
                        continue
                    name = str((w or {}).get("stock_name") or sid)
                    if sid not in merged:
                        merged[sid] = {"stock_id": sid, "stock_name": name}
                    elif not merged[sid].get("stock_name") or merged[sid]["stock_name"] == sid:
                        merged[sid]["stock_name"] = name
        return list(merged.values())

    def _format_watch_radar_section(self, telegram_uid: str = "") -> str:
        uid = str(telegram_uid or getattr(self, "chat_id", None) or "")
        if not uid:
            return ""
        watch = self._watch_radar_rows(uid)
        if not watch:
            return ""
        quotes: Dict[str, Dict[str, Any]] = {}
        try:
            quotes = self._load_latest_quotes_map() or {}
        except Exception:
            quotes = {}
        from tg_layout import html_escape

        lines = ["───────────────────", "🎯 <b>【自選守護雷達】</b>"]
        for w in watch[:8]:
            raw_sid = str(w.get("stock_id") or "")
            sid = html_escape(raw_sid)
            sname = html_escape(w.get("stock_name") or "")
            q = quotes.get(raw_sid) if isinstance(quotes, dict) else None
            close_p = None
            pct = None
            if isinstance(q, dict):
                try:
                    close_p = float(q.get("close"))
                    pct = float(q.get("pct_change") if q.get("pct_change") is not None else 0)
                except (TypeError, ValueError):
                    close_p = None
            if close_p is not None and pct is not None:
                lines.append(f"• {sid} {sname} 收 {close_p:.2f} ({pct:+.2f}%)")
            else:
                lines.append(f"• {sid} {sname}")
        return "\n".join(lines)

    def _increment_ok(self, health: Dict[str, Any]) -> bool:
        from import_health import increment_health_ok

        return increment_health_ok(health)

    def _sync_emerging_required(
        self, cap: str, *, label: str = "興櫃"
    ) -> Dict[str, Any]:
        """開市日盤後：興櫃與上市櫃日 K 同一趟必跑；失敗不准假 success。

        回傳 ok／em／error。例外或當日列數 < MIN_EM → ok=False（呼叫端蓋 incomplete）。
        """
        from emerging_quotes import emerging_rows_on, sync_emerging_quotes
        from import_health import MIN_EM

        day = str(cap or "").replace("-", "")[:8]
        out: Dict[str, Any] = {
            "ok": False,
            "cap": day,
            "em": 0,
            "label": str(label or "興櫃"),
            "error": "",
            "stats": {},
        }
        if len(day) != 8 or not day.isdigit():
            out["error"] = f"{out['label']} cap 無效"
            logger.error("%s", out["error"])
            return out
        try:
            stats = sync_emerging_quotes(self.db_path, cap=day) or {}
            out["stats"] = dict(stats) if isinstance(stats, dict) else {"raw": stats}
        except Exception as e:
            out["error"] = f"{out['label']} sync_emerging_quotes 失敗：{e}"
            logger.error("%s", out["error"], exc_info=True)
            return out
        em = int(emerging_rows_on(self.db_path, day) or 0)
        out["em"] = em
        need = int(MIN_EM)
        if em < need:
            out["error"] = f"{out['label']} {day} 興櫃 {em}/{need} 未齊"
            logger.error("%s（融合不准假 success）", out["error"])
            return out
        out["ok"] = True
        logger.info(
            "%s 興櫃必跑完成 cap=%s em=%s stats=%s",
            out["label"],
            day,
            em,
            out.get("stats"),
        )
        return out

    def _refresh_dongzhu_after_close(self, cap: str = "") -> Dict[str, Any]:
        """盤後日K＋法人齊了才重算洞燭。捕捉是機制內任何一檔，不鎖矽格。匯入晚到不准用未收完柱。"""
        from dongzhu_judge import refresh_dongzhu_judgment

        judged = refresh_dongzhu_judgment(self.db_path, cap) or {}
        if judged.get("skipped"):
            logger.info(
                "洞燭先機走查略過 skipped=%s want=%s complete=%s",
                judged.get("skipped"),
                judged.get("want"),
                judged.get("complete"),
            )
            return judged
        rates = judged.get("rates") or {}
        np_ = rates.get("no_park") or {}
        logger.info(
            "洞燭先機走查 cap=%s skip_parking=%s 非金控勝%s n=%s",
            judged.get("cap"),
            judged.get("skip_parking"),
            np_.get("gain"),
            np_.get("n"),
        )
        try:
            from dongzhu_tape import snapshot_and_score_dongzhu

            tape_cap = str(cap or judged.get("cap") or "")
            tape = snapshot_and_score_dongzhu(self.db_path, tape_cap)
            judged["tape"] = tape
            logger.info(
                "洞燭每日落檔 snap=%s scored=%s cap=%s",
                tape.get("snap"),
                tape.get("scored"),
                tape.get("cap"),
            )
        except Exception as e:
            logger.error("洞燭每日落檔失敗: %s", e, exc_info=True)
            raise
        return judged

    def _refresh_twii_forecast_after_close(self, cap: str = "") -> Dict[str, Any]:
        """盤後官方加權齊了才落演算／試畫。不推話筒。現在不在話筒發明 5／9。"""
        from biaoke_forecast import snapshot_and_score_twii

        out = snapshot_and_score_twii(self.db_path, cap) or {}
        logger.info(
            "大盤默默落檔 twii=%s try=%s scored=%s cap=%s",
            out.get("twii"),
            out.get("try"),
            out.get("scored"),
            out.get("cap"),
        )
        return out

    def _run_post_fuse_silent_tracks(
        self, cap: str = "", *, skip_ok: bool = False
    ) -> Dict[str, Any]:
        """盤後融合成功後：各靜默軌分開落檔、分開蓋成功／失敗戳。

        融合 success 不准當「每一軌都寫進庫」的證明。
        skip_ok=True 時已 success 的軌不重跑（補跑失敗／缺戳用）。
        """
        from silent_track_runs import CORE_AFTER_FUSE, mark_track, needs_rerun, run_tracked

        day = str(cap or self.today_str or "").replace("-", "")[:8]
        report: Dict[str, Any] = {"as_of": day, "tracks": {}}
        if not day:
            return report

        def _maybe(track: str, fn) -> None:
            if skip_ok and not needs_rerun(self.db_path, day, track):
                report["tracks"][track] = "skip-ok"
                return
            hit = run_tracked(self.db_path, track, day, fn)
            report["tracks"][track] = "ok" if hit.get("ok") else "error"

        _maybe("dongzhu-refresh", lambda: self._refresh_dongzhu_after_close(day))
        _maybe("twii-forecast", lambda: self._refresh_twii_forecast_after_close(day))

        def _screen_review_and_lists() -> Dict[str, Any]:
            from screen_review import score_ai_fills, score_screen_picks

            n = score_screen_picks(self.db_path, day)
            nf = score_ai_fills(self.db_path, day)
            return {"screen_picks": n, "ai_fills": nf}

        _maybe("screen-review", _screen_review_and_lists)

        # snapshot 內各子軌各自蓋 sv-*；任一核心軌缺／失敗就整輪重跑（已 success 的會重蓋）。
        need_lists = (not skip_ok) or any(
            needs_rerun(self.db_path, day, t) for t in CORE_AFTER_FUSE
        )
        if need_lists:
            try:
                from judge_tape import snapshot_button_lists

                snapshot_button_lists(self.db_path, day)
                report["tracks"]["snapshot_button_lists"] = "ran"
            except Exception as exc:
                logger.error("靜默名單總入口失敗: %s", exc, exc_info=True)
                report["tracks"]["snapshot_button_lists"] = "error"
                mark_track(
                    self.db_path,
                    "screen-buckets",
                    day,
                    "error",
                    f"snapshot_button_lists: {type(exc).__name__}: {exc}"[:800],
                )
        else:
            report["tracks"]["snapshot_button_lists"] = "skip-ok"

        def _score_live() -> int:
            from judge_tape import score_live_judges

            return int(score_live_judges(self.db_path, day) or 0)

        _maybe("score-live", _score_live)
        return report

    @staticmethod
    def _screening_delivered(screening: Optional[Dict[str, Any]]) -> bool:
        """海選有產出可推播的 payload（成功或空桶），不是例外中斷。"""
        if not screening:
            return False
        if screening.get("payload"):
            return True
        return str(screening.get("status") or "") in ("success", "empty")

    def _screening_surviving_oom(
        self,
        as_of: str,
        *,
        session: str = "morning",
        apply_us: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """全市場掃預設走子行程：最重負荷當預設，OOM 不准拖死常駐／Telegram（§14）。

        輕量日假設＝錯的。先讀 screen_sessions；無快取才 spawn。
        子行程失敗不准在父行程重掃。pytest／WAYNE_SCREEN_INLINE 才准 inline。
        """
        from screening_engine import (
            ensure_morning_session_from_cache,
            load_cached_full_screening,
        )
        from screen_sessions import screen_session_has_session_data

        as_of = str(as_of or "").strip()
        session = str(session or "morning").strip() or "morning"
        # 06:30：只有 evening 快取時必須升寫 morning，否則早報推了、12:45／morning 路徑看不到桶。
        if session == "morning":
            promoted = ensure_morning_session_from_cache(
                self.db_path, as_of, apply_us=bool(apply_us), light=True
            )
            if promoted and str(promoted.get("as_of") or promoted.get("date") or "") == as_of:
                if any((promoted.get("results") or {}).values()) or screen_session_has_session_data(
                    self.db_path, as_of, "morning"
                ):
                    logger.info(
                        "海選讀／升寫 morning 快取 as_of=%s（evening→morning 補桶）",
                        as_of,
                    )
                    return promoted
        cached = load_cached_full_screening(self.db_path)
        if cached and str(cached.get("as_of") or cached.get("date") or "") == as_of:
            if any((cached.get("results") or {}).values()):
                logger.info(
                    "海選讀既有 screen_sessions 快取 as_of=%s session=%s",
                    as_of,
                    session,
                )
                return cached

        if not run_full_screening:
            return cached

        # 本機／pytest：子行程重、且常無真庫；直接同行程掃。
        inline = os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get(
            "WAYNE_SCREEN_INLINE"
        ) or os.environ.get("WAYNE_MORNING_SCREEN_INLINE")
        if inline:
            try:
                return run_full_screening(
                    db_path=self.db_path,
                    target_date=as_of,
                    apply_us=bool(apply_us),
                    session=session,
                )
            except Exception as e:
                logger.error("四大選股（inline）失敗: %s", e, exc_info=True)
                return None

        import subprocess

        logger.info(
            "海選全掃改子行程（最重負荷預設／防 OOM）as_of=%s session=%s",
            as_of,
            session,
        )
        child = (
            "import os,sys\n"
            "os.environ['WAYNE_SCREEN_CHILD']='1'\n"
            "from screening_engine import run_full_screening\n"
            f"r=run_full_screening(db_path={self.db_path!r},target_date={as_of!r},"
            f"apply_us={bool(apply_us)!r},session={session!r})\n"
            "sys.exit(0 if r else 1)\n"
        )
        rc = -1
        try:
            env = dict(os.environ)
            env["WAYNE_SCREEN_CHILD"] = "1"
            proc = subprocess.run(
                [sys.executable, "-c", child],
                timeout=float(
                    os.getenv("WAYNE_SCREEN_CHILD_TIMEOUT")
                    or os.getenv("WAYNE_MORNING_CHILD_TIMEOUT")
                    or "900"
                ),
                env=env,
            )
            rc = int(proc.returncode)
        except subprocess.TimeoutExpired:
            logger.error("海選子行程逾時 as_of=%s session=%s", as_of, session)
        except Exception as e:
            logger.error("海選子行程失敗: %s", e, exc_info=True)

        if session == "morning":
            promoted = ensure_morning_session_from_cache(
                self.db_path, as_of, apply_us=bool(apply_us), light=True
            )
            if promoted and str(promoted.get("as_of") or promoted.get("date") or "") == as_of:
                if any((promoted.get("results") or {}).values()):
                    logger.info(
                        "海選子行程後升寫／讀到 morning 快取 as_of=%s rc=%s",
                        as_of,
                        rc,
                    )
                    return promoted
        cached = load_cached_full_screening(self.db_path)
        if cached and str(cached.get("as_of") or cached.get("date") or "") == as_of:
            if any((cached.get("results") or {}).values()):
                logger.info(
                    "海選子行程後讀到快取 as_of=%s session=%s rc=%s",
                    as_of,
                    session,
                    rc,
                )
                return cached
        # 子行程失敗／無快取：不准在父行程重掃（會再 OOM 拖死常駐）。
        logger.error(
            "海選子行程未寫出快取 rc=%s as_of=%s session=%s", rc, as_of, session
        )
        return None

    def _morning_screening_surviving_oom(self, as_of: str) -> Optional[Dict[str, Any]]:
        """相容舊名：06:30 早報全掃（預設子行程）。"""
        return self._screening_surviving_oom(
            as_of, session="morning", apply_us=True
        )

    def _push_screening(
        self,
        screening: Optional[Dict[str, Any]],
        as_of: str = "",
        *,
        morning_digest: bool = False,
        us_snap: Optional[Dict[str, Any]] = None,
        pipeline_run_date: str = "",
    ) -> bool:
        """寄出海選本文。回傳是否每個收件人都被 Telegram 接受。

        算出名單 ≠ 已寄到。401／空 token 必須回 False，否則 skip_if_done 會把失敗當成已完成。
        morning_digest：06:30 Option B＝每人先附圖（美股／電子盤／恐懼）再文字①環境／夜盤／加權精簡＋文字②兩桶海選；
        不再另寄加權研究／輪動／月營收／雷達。
        """
        pkey = str(pipeline_run_date or "").strip()
        # 雙寄擋：別條已寄出回執／已 success → 本條不准再打 Telegram（2026-10-27 07:47／07:56）。
        if pkey:
            try:
                already = self.push_already_delivered(pkey) or (
                    self.pipeline_status(pkey) == "success"
                )
            except Exception:
                already = False
            if already:
                logger.info(
                    "海選已有寄出回執／success，略過 _push_screening 重寄 key=%s", pkey
                )
                return True
        if morning_digest and screening:
            try:
                from morning_digest import apply_morning_opening_to_screening, build_morning_opening_html

                opening = build_morning_opening_html(
                    self.db_path, as_of or "", screening, us_snap=us_snap
                )
                if opening:
                    screening = apply_morning_opening_to_screening(screening, opening)
            except Exception as e:
                logger.warning("早報彙整開頭略過：%s", e)
        delivered = self._screening_delivered(screening)
        ids = self._family_chat_ids()
        logger.info("海選收件人數 %d（payload=%s）", len(ids), "有" if delivered else "無")
        sent_ok = False
        if self.bot and delivered:
            try:
                dests = ids or [str(getattr(self, "chat_id", None) or "").strip()]
                dests = [d for d in dests if d]
                if dests:
                    sent_n = 0
                    for cid in dests:
                        try:
                            # 同一人一輪：先圖後文，兩人白名單同一套；不拆成無關推播。
                            if morning_digest:
                                self._push_morning_session_cards(
                                    cid, us_snap=us_snap
                                )
                            if self.bot.send_screening_report(screening, chat_id=cid) is False:
                                logger.warning("海選 Telegram 未接受 dest_len=%s", len(str(cid)))
                            else:
                                sent_n += 1
                        except Exception as e:
                            logger.warning("海選寄出失敗 dest_len=%s: %s", len(str(cid)), e)
                    logger.info("海選寄出成功 %d/%d 人", sent_n, len(dests))
                    sent_ok = sent_n == len(dests) and sent_n > 0
                    if sent_ok and pipeline_run_date:
                        self.record_whitelist_push(
                            str(pipeline_run_date),
                            kind="morning-digest",
                            n_ok=sent_n,
                            notes="海選寄出成功",
                        )
                else:
                    if morning_digest:
                        self._push_morning_session_cards(
                            str(getattr(self, "chat_id", None) or ""), us_snap=us_snap
                        )
                    sent_ok = self.bot.send_screening_report(screening) is not False
                    if sent_ok and pipeline_run_date:
                        self.record_whitelist_push(
                            str(pipeline_run_date),
                            kind="morning-digest",
                            n_ok=1,
                            notes="海選寄出成功",
                        )
            except Exception as e:
                logger.warning("分類戰報推播失敗，改送長文: %s", e)
                self._broadcast_family(
                    screening.get("message") or self._screening_fail_message()
                )
                delivered = False
                sent_ok = False
        else:
            report_text = (screening or {}).get("message") if screening else ""
            # 沒有 bot 物件就走原生 API；有 token 且 Telegram 接受才算寄到。
            sent_ok = bool(self._broadcast_family(report_text or self._screening_fail_message()))
            if sent_ok and morning_digest and pipeline_run_date:
                self.record_whitelist_push(
                    str(pipeline_run_date),
                    kind="morning-digest",
                    n_ok=len(self._family_chat_ids() or []) or 1,
                    notes="海選寄出成功(broadcast)",
                )
        if not delivered:
            logger.warning("早上海選未產出名單，略過 AI 模擬倉／資金輪動附帶推播")
            return False
        if not sent_ok:
            logger.error("早上海選已算出但 Telegram 沒送到，附帶區塊也不寄")
            return False
        pkey = str(pipeline_run_date or "").strip()
        if morning_digest and pkey:
            # 海選＋彙整已送出即標 success，避免長掃期間 watchdog 06:55 誤報 running。
            # 蓋戳失敗不准往上炸：否則 catch-up／force-morning 以為沒寄又重寄（2026-10-23 18:32／19:17）。
            try:
                self._mark_pipeline(
                    "success", "morning-digest", run_date=pkey, retries=12
                )
            except Exception:
                logger.exception(
                    "海選已寄出但 pipeline 蓋戳失敗（稍後 run_morning 仍會再標）key=%s",
                    pkey,
                )
        # Option B：輪動／月營收／雷達不塞進 06:30 早報主輪（改盤後／按鈕路徑）
        if not morning_digest:
            extra_bits = []
            try:
                from taiwan_market import format_taiwan_market_brief_html

                mkt = format_taiwan_market_brief_html(self.db_path, as_of or "")
                if mkt and (screening or {}).get("message") and mkt not in (screening or {}).get("message", ""):
                    extra_bits.insert(0, mkt)
            except Exception:
                pass
            try:
                from money_flow import format_sector_rotation_html

                rot = format_sector_rotation_html(self.db_path)
                if rot:
                    extra_bits.append(rot)
            except Exception as e:
                logger.warning("盤後資金輪動區塊略過：%s", e)
            try:
                from fundamentals import format_hot_revenue_html

                hot = format_hot_revenue_html(self.db_path)
                if hot:
                    extra_bits.append(hot)
            except Exception:
                pass
            extra_bits = [x for x in extra_bits if x]
            owner = str(getattr(self, "chat_id", None) or "").strip()
            targets = ids or ([owner] if owner else [])
            if not targets:
                for html in extra_bits:
                    self._send_screening_extra(html)
            else:
                for cid in targets:
                    try:
                        radar = self._format_watch_radar_section(cid)
                    except Exception as e:
                        logger.warning("自選雷達略過 uid=%s: %s", cid, e)
                        radar = ""
                    for html in extra_bits:
                        self._send_screening_extra(html, chat_id=cid)
                    if radar:
                        self._send_screening_extra(radar, chat_id=cid)
        try:
            from screen_review import adapt_bucket_weights, score_ai_fills, score_screen_picks
            from taiwan_market import analyze_taiwan_market

            score_screen_picks(self.db_path, as_of or "")
            score_ai_fills(self.db_path, as_of or "")
            try:
                from judge_tape import score_live_judges, snapshot_button_lists

                snapshot_button_lists(self.db_path, as_of or "")
                score_live_judges(self.db_path, as_of or "")
            except Exception:
                pass
            snap = analyze_taiwan_market(self.db_path, as_of or "")
            adapt_bucket_weights(
                self.db_path,
                regime=snap.get("regime") if snap.get("ok") else None,
                regime_plus=snap.get("regime_plus") if snap.get("ok") else None,
            )
        except Exception as e:
            logger.warning("海選復盤略過：%s", e)
        self._run_ai_desk(as_of or self.today_str, results=(screening or {}).get("results") or {}, notify=False)
        return True

    def _push_morning_session_cards(
        self, chat_id: str, *, us_snap: Optional[Dict[str, Any]] = None
    ) -> None:
        """06:30 早報附圖：美股／台指電子盤／恐懼貪婪（兩支話筒同一套；呼叫端先圖後文）。"""
        dest = str(chat_id or "").strip()
        bot = getattr(self, "bot", None)
        if not dest or bot is None:
            return
        if not hasattr(bot, "send_market_session_cards_to_chat"):
            return
        try:
            from cnn_fear import fetch_cnn_fear_greed
            from market_session_cards import assemble_session_cards
            from us_overnight import refresh_us_for_market_page

            snap = us_snap if isinstance(us_snap, dict) else None
            if not snap:
                snap = refresh_us_for_market_page(self.db_path, None)
            else:
                snap = dict(snap)
            if not snap.get("cnn_fear"):
                fg = fetch_cnn_fear_greed(str(snap.get("us_session") or ""))
                if fg:
                    snap["cnn_fear"] = fg
            bundle = assemble_session_cards(us_snap=snap, cnn_fear=snap.get("cnn_fear"))
            bot.send_market_session_cards_to_chat(dest, bundle, uid=dest)
        except Exception as e:
            logger.warning("早報大盤附圖略過：%s", e)

    def _send_screening_extra(self, html: str, chat_id: Optional[str] = None) -> bool:
        """海選附註一則一則寄：加權研究／資金輪動／月營收／雷達分開，切塊不拆標籤。"""
        if not html:
            return True
        from tg_layout import chunk_telegram_html

        ok = True
        for part in chunk_telegram_html(html, 3500, reflow=False) or [html]:
            if self.send_telegram_message(part, chat_id=chat_id) is False:
                ok = False
        return ok

    def _run_ai_desk(
        self,
        as_of: str,
        results: Optional[Dict[str, Any]] = None,
        apply_us: bool = False,
        session: str = "",
        notify: bool = True,
        telegram_uid: str = "",
    ) -> Dict[str, Any]:
        """模擬倉真正下單（每人 ai_{uid}／總 50 萬＝30 操作＋20 抄底）。母體＝勝率買點；最多 3 檔。"""
        try:
            from ai_trader import run_ai_desk
            from config import allowed_telegram_uids, telegram_uid_allowed

            if results is None:
                if not run_full_screening:
                    return {}
                # 最重負荷預設：不准在常駐行程內重掃全市場（OOM→話筒死）。
                screening = self._screening_surviving_oom(
                    as_of,
                    session=str(session or "evening"),
                    apply_us=bool(apply_us),
                )
                results = (screening or {}).get("results") or {}

            if telegram_uid:
                uids = [str(telegram_uid)] if telegram_uid_allowed(telegram_uid) else []
            else:
                uids = list(allowed_telegram_uids())
            if not uids and self.chat_id:
                uids = [str(self.chat_id)]
            if not uids:
                logger.info("尚無已註冊 Telegram 使用者，略過 AI 模擬倉")
                return {}

            last: Dict[str, Any] = {}
            for uid in uids:
                ai = run_ai_desk(self.db_path, uid, results or {}, as_of)
                last = ai
                logger.info(
                    "AI 模擬倉 uid=%s 買進 %s 賣出 %s 候選 %s",
                    uid,
                    len(ai.get("bought") or []),
                    len(ai.get("sold") or []),
                    ai.get("candidates") or 0,
                )
                if notify:
                    bits = [ai.get("html") or ""]
                    if ai.get("bought"):
                        bits.append("<b>AI 模擬本次買進</b>\n" + "\n".join(ai["bought"]))
                    if ai.get("sold"):
                        bits.append("<b>AI 模擬本次賣出</b>\n" + "\n".join(ai["sold"]))
                    if ai.get("lesson"):
                        bits.append("進化：" + str(ai["lesson"]))
                    text = "\n\n".join(x for x in bits if x)
                    if text:
                        self.send_telegram_message(text, chat_id=uid)
            # 成交後才凍 AI倉名單；失敗不擋話筒／海選（海選 snapshot 常在 AI 成交前）。
            try:
                from button_silent_verify import snapshot_ai_desk

                snapshot_ai_desk(self.db_path, as_of or "")
            except Exception:
                pass
            return last
        except Exception as e:
            logger.warning("AI 模擬操盤略過：%s", e, exc_info=True)
            return {}

    def _maybe_send_evolve_digest(self, as_of: str) -> None:
        """週五晚間：買賣仍不推播，另寄一則進化編碼週報。"""
        try:
            from config import allowed_telegram_uids, scheduler_may_push
            from ai_trader import (
                ai_user_id,
                format_evolve_report_html,
                mark_weekly_evolve_sent,
                should_send_weekly_evolve,
            )
        except Exception:
            return
        if not scheduler_may_push("evening"):
            return
        uids = list(allowed_telegram_uids())
        if not uids and self.chat_id:
            uids = [str(self.chat_id)]
        for uid in uids:
            user_id = ai_user_id(uid)
            if not should_send_weekly_evolve(self.db_path, user_id, as_of):
                continue
            html = format_evolve_report_html(self.db_path, user_id)
            if not html:
                continue
            try:
                self.send_telegram_message(html, chat_id=uid)
                mark_weekly_evolve_sent(self.db_path, user_id, as_of)
            except Exception:
                logger.exception("AI 進化週報失敗 uid=%s", uid)

    @staticmethod
    def _fuse_done_message(cap: str, health: Dict[str, Any]) -> str:
        """盤後融合通過關卡後才准發。不是海選、不是買訊。"""
        ymd = str(cap or "").replace("-", "")[:8]
        if len(ymd) == 8 and ymd.isdigit():
            pretty = f"{ymd[:4]}/{ymd[4:6]}/{ymd[6:]}"
        else:
            pretty = ymd or "—"
        tw = int((health or {}).get("tw") or 0)
        two = int((health or {}).get("two") or 0)
        em = int((health or {}).get("em") or 0)
        return (
            f"📦 官方收盤已寫進庫（{pretty}）\n"
            f"上市 {tw}　上櫃 {two}　興櫃 {em}\n"
            "不是海選、不是買訊。明早 06:30 才寄海選。"
        )

    def run_increment_job(self, skip_if_done: bool = False, notify: bool = True) -> bool:
        from tw_holidays import closed_tw_session, refresh_tw_holiday_calendar, refresh_tw_typhoon_halt

        closed = closed_tw_session(db_path=self.db_path)
        if closed:
            # 2026-10-26 鎖死：早報／休市鍵已認「今日無開盤」→ 當日不准 16:30 融合、
            # 不准 fuse 補跑、不准推「資料處理中」。開市日才進 busy_window 融合本體。
            # 上一收盤未齊也只輕量側車／興櫃，不准掉進下方重融合。
            logger.info(
                "今日台股休市 %s %s；跳過盤後融合（開市日才融合）",
                closed.get("ymd"),
                closed.get("zh"),
            )
            try:
                logger.info("台股開休市年曆：%s", refresh_tw_holiday_calendar(self.db_path))
            except Exception as e:
                logger.warning("台股休市年曆略過：%s", e)
            try:
                logger.info("北市停班：%s", refresh_tw_typhoon_halt(self.db_path))
            except Exception as e:
                logger.warning("北市停班略過：%s", e)
            cap_closed = fuse_end_date()
            try:
                from emerging_quotes import sync_emerging_quotes

                sync_emerging_quotes(self.db_path, cap=cap_closed)
            except Exception as e_em:
                logger.warning("休市日興櫃補齊略過：%s", e_em)
            try:
                from import_health import audit_import

                health_closed = audit_import(self.db_path, cap_closed)
            except Exception:
                health_closed = {}
            prior_ok = bool(self._increment_ok(health_closed))
            if not prior_ok:
                logger.warning(
                    "休市日上一收盤 %s 未齊（上市 %s 上櫃 %s 興櫃 %s）；"
                    "仍跳過融合／不推 busy（開市日再補）",
                    cap_closed,
                    health_closed.get("tw"),
                    health_closed.get("two"),
                    health_closed.get("em"),
                )
            # 休市仍每天對月營收／季報等官方側車：連假期間公司陸續公告，
            # 不准因 skip increment 讓庫停在休市前的已公告子集（政美 7853 九月）。
            self._refresh_official_sidecars()
            note_tail = "ok" if prior_ok else "prior_incomplete"
            self._mark_pipeline(
                "success",
                f"tw closed {closed.get('ymd')} {closed.get('zh')} skip increment "
                f"cap={cap_closed} tw={health_closed.get('tw')} "
                f"two={health_closed.get('two')} em={health_closed.get('em')} "
                f"{note_tail}",
            )
            # 融合 success ≠ 各靜默軌都寫進庫；休市仍補跑缺／失敗軌（無 busy）
            try:
                self._run_post_fuse_silent_tracks(cap_closed, skip_ok=True)
            except Exception:
                logger.exception("休市日靜默各軌補跑失敗")
            return True
        if skip_if_done and self.already_completed_today():
            logger.info("ℹ️ %s 盤後融合已成功，仍對官方側車（月營收續補）。", self.today_str)
            self._refresh_official_sidecars()
            # 融合已成功仍要補跑缺／失敗的靜默軌（不准被融合 success 蓋掉）
            try:
                self._run_post_fuse_silent_tracks(fuse_end_date(), skip_ok=True)
            except Exception:
                logger.exception("融合已成功後靜默各軌補跑失敗")
            return True
        try:
            from import_health import audit_import

            cap_ready = fuse_end_date()
            health_ready = audit_import(self.db_path, cap_ready)
        except Exception:
            cap_ready = ""
            health_ready = {}
        if (
            skip_if_done
            and cap_ready
            and str(cap_ready) == str(self.today_str)
            and self._increment_ok(health_ready)
        ):
            self._mark_pipeline(
                "success",
                f"increment already-complete cap={cap_ready} "
                f"tw={health_ready.get('tw')} two={health_ready.get('two')} "
                f"em={health_ready.get('em')}",
            )
            logger.info("ℹ️ %s 官方柱已齊，補蓋盤後融合紀錄（不重抓）", cap_ready)
            try:
                self._run_post_fuse_silent_tracks(cap_ready, skip_ok=True)
            except Exception:
                logger.exception("柱齊補蓋後靜默各軌補跑失敗")
            return True
        if not self.try_claim_pipeline(
            self.today_str,
            notes="increment-claim",
            stale_running_sec=int(INCREMENT_RUNNING_STALE_SEC),
            allow_stale_running=True,
        ):
            logger.info("ℹ️ %s 盤後融合進行中或已成功，略過。", self.today_str)
            return True
        start_time = time.time()
        key = str(self.today_str)
        try:
            from busy_window_notice import busy_window

            # 融合最重；notify=0（GHA）仍由 busy_window 內 _may_push 擋寄。
            with busy_window("fuse", db_path=self.db_path, enabled=True):
                with self._morning_running_lease(key):
                    logger.info("🎬 === 盤後融合開始（不寄海選；海選 06:30／尾盤 12:45）===")
                    self.run_daily_increment(notify=notify)
                    from import_health import audit_import, format_audit_plain

                    cap = fuse_end_date()
                    em_again = self._sync_emerging_required(cap, label="興櫃收盤再寫")
                    if em_again.get("ok"):
                        logger.info("興櫃收盤再寫：%s", em_again.get("stats"))
                    else:
                        logger.error(
                            "興櫃收盤再寫未完成（不准略過）：%s",
                            em_again.get("error") or em_again,
                        )
                    health = audit_import(self.db_path, cap)
                    try:
                        wd = datetime.strptime(cap, "%Y%m%d").weekday()
                    except Exception:
                        wd = 0
                    if wd < 5 and not self._increment_ok(health) and self.fetcher:
                        for i in range(1, 9):
                            logger.warning(
                                "%s 繼續補齊（上市 %s 上櫃 %s 興櫃 %s）第 %s 次",
                                cap,
                                health.get("tw"),
                                health.get("two"),
                                health.get("em"),
                                i,
                            )
                            time.sleep(min(25 * i, 60))
                            self.fetcher.update_daily_market_data(cap)
                            if hasattr(self.fetcher, "sync_paired_markets"):
                                self.fetcher.sync_paired_markets()
                            try:
                                from chips import backfill_chips, update_chips_for_date

                                update_chips_for_date(self.db_path, cap)
                                backfill_chips(self.db_path, days=90)
                            except Exception as e_chip:
                                logger.warning("補齊輪法人再抓略過：%s", e_chip)
                            em_fill = self._sync_emerging_required(
                                cap, label="興櫃補齊寫入"
                            )
                            if em_fill.get("ok"):
                                logger.info("興櫃補齊寫入：%s", em_fill.get("stats"))
                            else:
                                logger.error(
                                    "興櫃補齊寫入未完成（不准略過）：%s",
                                    em_fill.get("error") or em_fill,
                                )
                            health = audit_import(self.db_path, cap)
                            if self._increment_ok(health):
                                break
                    elapsed = time.time() - start_time
                    # 興櫃缺日／同步失敗 → 一律 incomplete（不准假 success）
                    em_gate = self._sync_emerging_required(cap, label="融合興櫃閘")
                    health = dict(health or {})
                    health["em"] = int(em_gate.get("em") or health.get("em") or 0)
                    listed_ok = self._increment_ok(health)
                    if not em_gate.get("ok") or not listed_ok:
                        note = format_audit_plain(health)
                        err = str(em_gate.get("error") or "").strip()
                        if err and err not in note:
                            note = f"{note}；{err}" if note else err
                        self._mark_pipeline("incomplete", note[:500])
                        logger.error("盤後仍待補：%s", note)
                        if notify:
                            try:
                                self.send_telegram_message(
                                    "🔁 盤後繼續補齊（下一輪開機／16:30 會再跑）\n" + note
                                )
                            except Exception:
                                pass
                        return False
                    self._mark_pipeline(
                        "success",
                        f"increment elapsed={elapsed:.1f}s tw={health.get('tw')} "
                        f"two={health.get('two')} em={health.get('em')}",
                    )
                    logger.info(
                        "🎉 === 盤後融合完畢 上市%s 上櫃%s 興櫃%s（%.1fs）===",
                        health.get("tw"),
                        health.get("two"),
                        health.get("em"),
                        elapsed,
                    )
                    # 融合 success 只代表官方柱齊；後面各靜默軌自己蓋 sv-* 成功／失敗戳。
                    try:
                        silent_rep = self._run_post_fuse_silent_tracks(cap, skip_ok=False)
                        logger.info("盤後靜默各軌：%s", silent_rep.get("tracks"))
                    except Exception:
                        logger.exception("盤後靜默各軌入口失敗（融合仍保持 success）")
                    if notify:
                        try:
                            self._broadcast_family(self._fuse_done_message(cap, health))
                        except Exception:
                            logger.exception("盤後融合完成推播失敗")
                    try:
                        from us_holidays import refresh_us_holiday_calendar

                        hol = refresh_us_holiday_calendar(self.db_path)
                        logger.info("美股 NYSE 休市年曆：%s", hol)
                    except Exception as e:
                        logger.warning("美股休市年曆略過：%s", e)
                    try:
                        from tw_holidays import refresh_tw_holiday_calendar, refresh_tw_typhoon_halt

                        tw_hol = refresh_tw_holiday_calendar(self.db_path)
                        logger.info("台股開休市年曆：%s", tw_hol)
                        typh = refresh_tw_typhoon_halt(self.db_path)
                        logger.info("北市停班：%s", typh)
                    except Exception as e:
                        logger.warning("台股休市年曆略過：%s", e)
                    # 盤後這份庫會打進 Release zip：模擬倉也要在這裡成交，下次開機才看得到持倉。
                    self.run_evening_screen(skip_if_done=True, notify=False)
                    return True
        except Exception as exc:
            logger.exception("盤後融合未捕捉例外 key=%s", key)
            try:
                self._mark_pipeline(
                    "incomplete",
                    f"increment crashed: {type(exc).__name__}: {exc}"[:500],
                )
            except Exception:
                logger.exception("盤後融合 crash 蓋戳失敗 key=%s", key)
            return False

    def _run_closed_day_morning_digest(
        self,
        closed: Dict[str, Any],
        *,
        skip_if_done: bool = True,
        notify: bool = True,
    ) -> bool:
        """真休市日 06:30：美股＋環境精簡早報；不跑海選、不改買訊。

        鍵：
        - screen-closed-{ymd}＝略過海選（不准寫 screen-{as_of}）
        - us-digest-{ymd}＝精簡早報寄送鎖（兩支話筒）
        最重負荷預設：不准呼叫全市場海選／子行程掃；只讀庫＋美股隔夜＋附圖。
        """
        from import_health import latest_complete_quote_date
        from tw_holidays import closed_no_open_line

        ymd = str(closed.get("ymd") or "").strip() or "none"
        closed_key = f"screen-closed-{ymd}"
        digest_key = f"us-digest-{ymd}"
        reason_line = closed_no_open_line(closed)
        logger.info(
            "今日台股休市 %s %s，不跑海選（%s）；精簡早報 %s｜%s",
            closed.get("ymd"),
            closed.get("zh"),
            closed_key,
            digest_key,
            reason_line,
        )
        # 連假休市仍每天對 MOPS／OpenAPI：十月十號前後陸續公告，不准空窗。
        self._refresh_official_sidecars()
        # 略過海選鍵：有寄／不寄都先記，開市日 skip_if_done 不會誤擋。
        self._mark_pipeline(
            "success",
            f"tw closed {closed.get('ymd')} {closed.get('zh')} skip screen",
            run_date=closed_key,
        )
        if not notify:
            self._mark_pipeline(
                "computed",
                f"tw closed {closed.get('ymd')} us-digest notify-off",
                run_date=digest_key,
            )
            return True
        if skip_if_done and self.pipeline_status(digest_key) == "success":
            logger.info("休市精簡早報 %s 已寄過，略過。", digest_key)
            return True
        if not self.try_claim_pipeline(
            digest_key,
            notes="us-digest-claim",
            allow_stale_running=True,
            stale_running_sec=int(MORNING_RUNNING_STALE_SEC),
        ):
            logger.info("休市精簡早報 %s 已寄過或進行中，略過。", digest_key)
            return True

        from busy_window_notice import busy_window

        with busy_window("morning", db_path=self.db_path, enabled=True):
            as_of = (
                str(closed.get("prev_ymd") or "").strip()
                or latest_complete_quote_date(self.db_path)
                or ""
            )
            us_snap: Dict[str, Any] = {}
            try:
                from us_overnight import refresh_us_overnight, should_alert_us_drop

                us_snap = refresh_us_overnight(self.db_path, as_of) or {}
                if should_alert_us_drop(us_snap):
                    logger.info(
                        "休市日美股收盤偏弱，併入精簡早報 regime=%s",
                        us_snap.get("regime"),
                    )
            except Exception as e:
                logger.warning("休市日美股隔夜略過：%s", e)
            try:
                from taiwan_market import sync_futures_daily

                fut = sync_futures_daily(self.db_path)
                logger.info("休市日補台指期日盤／夜盤：%s", fut)
            except Exception as e:
                logger.warning("休市日台指期略過：%s", e)

            html = ""
            try:
                from morning_digest import build_closed_day_digest_html

                html = build_closed_day_digest_html(
                    self.db_path, as_of, closed, us_snap=us_snap or None
                )
            except Exception as e:
                logger.exception("休市精簡早報組文失敗：%s", e)
                html = f"<b>WayneBot 早報</b>\n{reason_line}" if reason_line else ""

            dests = self._family_chat_ids()
            if not dests:
                owner = str(getattr(self, "chat_id", None) or "").strip()
                dests = [owner] if owner else []
            sent_n = 0
            for cid in dests:
                try:
                    self._push_morning_session_cards(cid, us_snap=us_snap or None)
                except Exception as e:
                    logger.warning(
                        "休市早報附圖略過 dest_len=%s: %s", len(str(cid)), e
                    )
                ok = True
                if html:
                    ok = bool(self.send_telegram_message(html, chat_id=cid))
                if ok:
                    sent_n += 1
                else:
                    logger.warning("休市精簡早報未接受 dest_len=%s", len(str(cid)))
            sent_ok = bool(dests) and sent_n == len(dests)
            if sent_ok:
                self._mark_pipeline(
                    "success",
                    f"tw closed {closed.get('ymd')} us-digest",
                    run_date=digest_key,
                )
                logger.info("休市精簡早報寄出成功 %d/%d 人", sent_n, len(dests))
            else:
                self._mark_pipeline(
                    "computed",
                    f"tw closed {closed.get('ymd')} us-digest send-failed",
                    run_date=digest_key,
                )
                logger.error(
                    "休市精簡早報未全數送到 %d/%d，不標已寄過 %s",
                    sent_n,
                    len(dests),
                    digest_key,
                )
            return bool(sent_ok)

    def _refresh_official_sidecars(self) -> None:
        """行情已齊時仍每天對官方側車。不重抓全市場日K、不分點。

        月營收 OpenAPI 常整期才換檔；已先公告的公司要對公開資訊觀測站 NAS。
        股東會／法說、除權息預告、本益／融資快照也是查股會讀的官方列。

        硬牆逾時：MOPS／TLS 卡住不准拖死 §14 早報（含第二槍 catch-up）。
        單段已有 try／except；整包再加 wall-clock，逾時只略過側車、不擋寄。
        """
        try:
            timeout_s = float(
                os.environ.get("WAYNE_MORNING_SIDECAR_TIMEOUT_SEC") or 45
            )
        except (TypeError, ValueError):
            timeout_s = 45.0
        timeout_s = max(1.0, min(timeout_s, 180.0))

        def _body() -> None:
            try:
                from fundamentals import sync_fundamentals

                fund = sync_fundamentals(self.db_path)
                logger.info("今早月營收／季報：%s", fund)
            except Exception as e:
                logger.warning("今早基本面略過：%s", e)
            try:
                from company_events import sync_company_events

                ev = sync_company_events(self.db_path)
                logger.info("今早股東會／法說：%s", ev)
            except Exception as e:
                logger.warning("今早公司行事略過：%s", e)
            try:
                from ex_rights import sync_ex_preview

                preview = sync_ex_preview(self.db_path)
                logger.info("今早除權息預告：%s", preview)
            except Exception as e:
                logger.warning("今早除權息預告略過：%s", e)
            try:
                from official_snapshots import sync_official_snapshots

                snap = sync_official_snapshots(self.db_path)
                logger.info("今早官方快照：%s", snap)
            except Exception as e:
                logger.warning("今早官方快照略過：%s", e)

        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        # 不准 with-Executor：result 逾時後 __exit__ 仍會等卡住的側車執行緒。
        ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wayne-sidecar")
        try:
            fut = ex.submit(_body)
            fut.result(timeout=timeout_s)
        except FuturesTimeout:
            logger.warning(
                "今早官方側車逾時 %.0fs，略過不擋寄（§14）", timeout_s
            )
        except Exception as e:
            logger.warning("今早官方側車略過：%s", e)
        finally:
            ex.shutdown(wait=False, cancel_futures=True)

    def run_morning_screen(self, skip_if_done: bool = False, notify: bool = True) -> bool:
        """開市日 06:30 海選＋加權研究等同輪附帶：白名單只寄一次。

        準點／catch-up／watchdog／CLI／重開都走這裡。notify=True 時，
        補齊基準日後、任何 Telegram 寄出前，必須原子搶 screen-{as_of}；
        success 永不重寄；fresh running（租約未過期）不重搶防雙寄；
        租約過期／computed／crash 可重搶補寄（§14，與 midday 永久擋 stale 不同）。
        加權指數研究／資金輪動／月營收／雷達都在 _push_screening，同一把鎖。
        """
        from import_health import latest_complete_quote_date
        from tw_holidays import (
            closed_tw_session,
            load_tw_open_check,
            refresh_tw_typhoon_halt,
        )

        try:
            typh = refresh_tw_typhoon_halt(self.db_path)
            logger.info("今早北市停班：%s", typh)
        except Exception as e:
            logger.warning("今早北市停班略過：%s", e)
        closed = closed_tw_session(db_path=self.db_path)
        try:
            # 對質深夜 03:00 落檔：休市日不寄；開市日（含連假後第一天）必走推播路徑。
            today_ymd = self.today_str
            prior = load_tw_open_check(today_ymd, self.db_path)
            if prior is not None:
                prior_open = bool(prior.get("is_open"))
                live_open = closed is None
                if prior_open != live_open:
                    logger.info(
                        "今早開市對質：深夜查核 is_open=%s 與現況 closed=%s 不一致，以現況為準",
                        prior_open,
                        bool(closed),
                    )
                elif not prior_open:
                    logger.info(
                        "今早開市對質：深夜已記 %s 休市（%s），與現況一致",
                        today_ymd,
                        prior.get("name_zh") or prior.get("kind"),
                    )
        except Exception as e:
            logger.warning("今早開市對質略過：%s", e)
        if closed:
            # 休市：不跑海選／不改買訊；仍寄美股＋環境精簡早報（兩支話筒）。
            # screen-closed-*＝略過海選紀錄；us-digest-*＝精簡早報寄送鎖（不准寫進 screen-{as_of}）。
            return self._run_closed_day_morning_digest(
                closed, skip_if_done=skip_if_done, notify=notify
            )

        if notify:
            demoted = self.demote_premature_morning_screens()
            if demoted:
                logger.info("過早海選 success 已降級 %s 筆，改為可重寄", demoted)
            holiday_demoted = self.demote_holiday_skip_morning_screens()
            if holiday_demoted:
                logger.info(
                    "休市 skip 誤標的 screen-* success 已降級 %s 筆，改為可重寄",
                    holiday_demoted,
                )

        as_of = latest_complete_quote_date(self.db_path)
        pin = (os.environ.get("WAYNE_MORNING_PIN_AS_OF") or "").strip()
        if pin:
            # §14 救援：釘未寄出的基準日，不准被 fuse 推到「今天」洗掉今早漏寄
            logger.info("今早救援釘基準日 %s（latest=%s）", pin, as_of)
            as_of = pin
        key = f"screen-{as_of or 'none'}"
        # §14：連假後 as_of 未前進時，舊開市日 screen-{as_of} 回執不准擋今日真寄
        if notify and as_of:
            try:
                self.release_stale_morning_delivery_for_open_day(key)
            except Exception:
                logger.exception("開市日舊回執放行略過 key=%s", key)
        rebuild_only = False
        if skip_if_done and as_of:
            from screen_sessions import (
                screen_session_has_data,
                screen_session_has_session_data,
            )
            from screening_engine import ensure_morning_session_from_cache

            status = self.pipeline_status(key)
            has_rows = screen_session_has_data(self.db_path, as_of)
            # 只有 evening、沒 morning：升寫 morning（不重寄），避免 12:45／畫面桶「還沒存到」
            if has_rows and not screen_session_has_session_data(
                self.db_path, as_of, "morning"
            ):
                try:
                    ensure_morning_session_from_cache(
                        self.db_path, as_of, apply_us=True, light=True
                    )
                    logger.info(
                        "早上海選 %s 補寫 morning（由 evening 升），不重寄", key
                    )
                except Exception:
                    logger.exception("早上海選 %s evening→morning 升寫失敗", key)
            # 寄出回執＝已寄：即使 pipeline 仍 running／computed 也不重寄
            if self.honor_push_delivery(key, notes="morning-skip-receipt"):
                if has_rows:
                    logger.info("早上海選 %s 已有寄出回執，略過寄送；仍對官方側車。", key)
                    self._refresh_official_sidecars()
                    return True
                logger.warning(
                    "早上海選 %s 已有寄出回執但 screen_sessions 空，重掃補快取（不重寄）",
                    key,
                )
                notify = False
                rebuild_only = True
            if status == "success" and has_rows:
                logger.info("早上海選 %s 已寄過，略過寄送；仍對官方側車。", key)
                self._refresh_official_sidecars()
                return True
            if status == "computed" and not notify and has_rows:
                logger.info("早上海選 %s 已算出（不寄），略過；仍對官方側車。", key)
                self._refresh_official_sidecars()
                return True
            if status in ("success", "computed") and not has_rows:
                # success＝已寄過只補快取；computed＝尚未寄到，必須重掃並仍可寄（§14）。
                if status == "success":
                    logger.warning(
                        "早上海選 %s 已標 success 但 screen_sessions 空，重掃補快取（不重寄）",
                        key,
                    )
                    notify = False
                    rebuild_only = True
                else:
                    logger.warning(
                        "早上海選 %s 已標 computed 但 screen_sessions 空，重掃後補寄",
                        key,
                    )
        logger.info("☀️ 06:30 先確認庫已齊，再寄海選")
        from config import fuse_end_date

        cap = fuse_end_date()
        # 已有完整基準日＝可寄。不准再跑 fuse／重側車去追 cap（§14：
        # 今早 force-morning 被 16:30 increment-claim 鎖死 DB，永遠到不了搶鎖寄出）。
        # 最重負荷預設：寄出優先；缺日融合歸盤後排程，不擋早報。
        if not as_of:
            self.run_daily_increment(notify=False)
        elif as_of == cap:
            # 別槍已搶 running：預搶鎖側車不准擋 catch-up／watchdog 第二槍。
            # success／回執略過路徑已各自對側車；這裡只服務「尚未寄、要搶鎖」那一槍。
            pre_status = self.pipeline_status(key) if as_of else ""
            if pre_status == "running":
                logger.info(
                    "今早庫已是完整日 %s，但 %s 進行中，略過預搶鎖側車",
                    as_of,
                    key,
                )
            else:
                logger.info("今早庫已是完整日 %s，略過再抓行情，仍對官方側車", as_of)
                try:
                    self._refresh_official_sidecars()
                except Exception as e:
                    logger.warning("今早側車略過（不擋寄）：%s", e)
        else:
            logger.info(
                "今早基準日 %s 已齊（cap 尚為 %s），略過再抓行情／重側車以免擋寄",
                as_of,
                cap,
            )
        as_of = latest_complete_quote_date(self.db_path) or as_of
        key = f"screen-{as_of or 'none'}"
        if not as_of:
            logger.error("補齊後仍無完整交易日可寄海選")
            return False
        # pin／補齊後 as_of 可能變：再開市日舊回執放行一次
        if notify and as_of:
            try:
                self.release_stale_morning_delivery_for_open_day(key)
            except Exception:
                logger.exception("補齊後開市日舊回執放行略過 key=%s", key)
        # 補齊後再判一次：並行路徑可能已寄完；running 交給下面 claim。
        if skip_if_done:
            from screen_sessions import (
                screen_session_has_data,
                screen_session_has_session_data,
            )
            from screening_engine import ensure_morning_session_from_cache

            status = self.pipeline_status(key)
            has_rows = screen_session_has_data(self.db_path, as_of)
            if has_rows and not screen_session_has_session_data(
                self.db_path, as_of, "morning"
            ):
                try:
                    ensure_morning_session_from_cache(
                        self.db_path, as_of, apply_us=True, light=True
                    )
                except Exception:
                    logger.exception("早上海選 %s 補齊後 evening→morning 升寫失敗", key)
            if self.honor_push_delivery(key, notes="morning-skip-receipt-2"):
                if has_rows:
                    logger.info("早上海選 %s 補齊後已有寄出回執，略過。", key)
                    return True
                notify = False
                rebuild_only = True
            if status == "success" and has_rows:
                logger.info("早上海選 %s 補齊後已寄過，略過。", key)
                return True
            if status == "computed" and not notify and has_rows:
                logger.info("早上海選 %s 補齊後已算出（不寄），略過。", key)
                return True
        # 真寄路徑：原子搶鎖。fresh running 不重搶（防雙寄）；租約過期可重搶補寄（§14）。
        # success／寄出回執永不重搶；computed（明確寄失敗／notify-off／crashed／stale）可再搶。
        claimed = False
        if notify:
            claimed_ok = False
            for attempt in range(5):
                try:
                    claimed_ok = self.try_claim_pipeline(
                        key,
                        notes="morning-claim",
                        allow_stale_running=True,
                        stale_running_sec=int(MORNING_RUNNING_STALE_SEC),
                    )
                    break
                except sqlite3.OperationalError as e:
                    # DB lock 不准讓整段排程炸掉留下上一輪 orphan running。
                    logger.warning(
                        "早上海選搶鎖 DB busy（%s/%s）：%s",
                        attempt + 1,
                        5,
                        e,
                    )
                    time.sleep(1.5 * (attempt + 1))
            else:
                logger.error("早上海選搶鎖連續 DB locked，略過本輪（不標 success）")
                return False
            if not claimed_ok:
                logger.info("早上海選 %s 已寄過或進行中，略過。", key)
                return True
            claimed = True
        logger.info("☀️ 台灣 06:30 海選，基準日 %s", as_of)

        def _run_morning_body() -> bool:
            try:
                from taiwan_market import sync_futures_daily

                fut = sync_futures_daily(self.db_path)
                logger.info("今早補台指期日盤／夜盤：%s", fut)
            except Exception as e:
                logger.warning("今早台指期略過：%s", e)
            try:
                from taiwan_market import sync_futures_inst_oi

                foi = sync_futures_inst_oi(self.db_path)
                logger.info("今早補台指期外資未平倉：%s", foi)
            except Exception as e:
                logger.warning("今早台指期外資未平倉略過：%s", e)
            if claimed:
                self.touch_pipeline_running(key)
            us_snap: Dict[str, Any] = {}
            try:
                from us_overnight import refresh_us_overnight, should_alert_us_drop

                us_snap = refresh_us_overnight(self.db_path, as_of) or {}
                if should_alert_us_drop(us_snap):
                    logger.info(
                        "美股收盤偏弱，併入 06:30 早報彙整（不另寄一早提醒） regime=%s",
                        us_snap.get("regime"),
                    )
            except Exception as e:
                logger.warning("美股隔夜略過：%s", e)
            if claimed:
                self.touch_pipeline_running(key)
            screening = None
            try:
                screening = self._morning_screening_surviving_oom(as_of)
            except Exception as e:
                logger.error("四大選股失敗: %s", e, exc_info=True)
            if claimed:
                self.touch_pipeline_running(key)
            sent_ok = True
            if notify:
                # demote／別條搶走 claim 後，本執行緒不准再寄（防整套雙寄）
                if claimed:
                    st_now = self.pipeline_status(key)
                    if self.push_already_delivered(key) or st_now == "success":
                        logger.info(
                            "早上海選 %s 寄出前已有回執／success，中止本條", key
                        )
                        return True
                    if st_now != "running":
                        logger.warning(
                            "早上海選 %s claim 已非 running（%s），中止寄送防雙寄",
                            key,
                            st_now or "missing",
                        )
                        return False
                sent_ok = bool(
                    self._push_screening(
                        screening,
                        as_of=as_of,
                        morning_digest=True,
                        us_snap=us_snap or None,
                        pipeline_run_date=key,
                    )
                )
            else:
                logger.info("早上海選不寄 Telegram（notify=0），只寫快照")
                if self._screening_delivered(screening):
                    try:
                        self._run_ai_desk(
                            as_of or self.today_str,
                            results=(screening or {}).get("results") or {},
                            notify=False,
                        )
                    except Exception as e:
                        logger.warning("無推播早報仍跑 AI 模擬倉略過：%s", e)
            delivered = self._screening_delivered(screening)
            if delivered and sent_ok:
                if notify or rebuild_only:
                    # 已寄出：蓋戳必須盡力成功；失敗再 raise 會讓外層改 computed→重寄。
                    try:
                        self._mark_pipeline(
                            "success", "morning", run_date=key, retries=12
                        )
                    except Exception:
                        logger.exception(
                            "早上海選已寄出但最終蓋戳仍失敗 key=%s（勿當未寄）",
                            key,
                        )
                else:
                    # GHA notify=0 只算名單。若標 success，Release zip 灌進 Render
                    # 會讓 skip_if_done 以為已寄過（401 那天就是這樣）。
                    self._mark_pipeline("computed", "morning notify-off", run_date=key)
                    logger.info("早上海選已算出但不標已寄過（notify=0）%s", key)
            elif delivered and not sent_ok:
                # 已搶鎖但沒送到：放 computed，讓 catch-up／watchdog 可補寄；不准卡 running。
                self._mark_pipeline("computed", "morning send-failed", run_date=key)
                logger.error("早上海選已算出但 Telegram 沒送到，不標已寄過，基準日 %s", as_of)
            else:
                if claimed:
                    self._mark_pipeline("computed", "morning empty", run_date=key)
                logger.error("早上海選未產出名單，基準日 %s", as_of)
            return bool(delivered and sent_ok)

        try:
            from busy_window_notice import busy_window

            # 搶到 morning-claim 才推「資料處理中」；做完魔法刪（含休市精簡早報窗）。
            with busy_window(
                "morning", db_path=self.db_path, enabled=bool(claimed)
            ):
                if claimed:
                    with self._morning_running_lease(key):
                        return _run_morning_body()
                return _run_morning_body()
        except Exception:
            # 未標 success／computed 的 crash／OOM 前例外：放 computed，§14 才能補寄。
            if claimed and self.pipeline_status(key) == "running":
                try:
                    self._mark_pipeline("computed", "morning crashed", run_date=key)
                except Exception:
                    logger.exception("早上海選 crash 後改 computed 失敗 key=%s", key)
            raise

    def run_evening_screen(self, skip_if_done: bool = False, notify: bool = False) -> bool:
        """台股收盤後的名單只存庫，不寄 Telegram（美股還沒開）。"""
        from import_health import latest_complete_quote_date

        as_of = latest_complete_quote_date(self.db_path)
        key = f"evening-{as_of or 'none'}"
        if skip_if_done and as_of and self.already_completed_today(key):
            # 16:30 融合常已寫過快照；20:00／重啟補跑仍要讓 AI 模擬倉用官方收盤再成交一次
            # （例如清掉舊 ETF 持倉）。不再略過整段。
            # pipeline success 但 screen_sessions 空（碟事故／鎖死未寫）→ 必須重掃補檔。
            from screen_sessions import load_session_results, screen_session_has_data

            if not screen_session_has_data(self.db_path, as_of):
                logger.warning(
                    "晚間海選 %s 已標完成但 screen_sessions 無資料，重掃補快取", key
                )
            else:
                logger.info("晚間海選快照 %s 已寫過，改用快照再跑 AI 模擬倉。", key)
                results = load_session_results(self.db_path, as_of, "evening")
                if not any(results.values()):
                    results = load_session_results(self.db_path, as_of, "morning")
                if any(results.values()):
                    self._run_ai_desk(as_of, results=results, notify=False)
                    self._maybe_send_evolve_digest(as_of)
                    return True
                logger.warning(
                    "晚間海選 %s 有列但桶空，重掃補快取", key
                )
        if not as_of:
            logger.error("無完整交易日可寫晚間海選快照")
            return False
        logger.info("🌙 20:00 晚間海選寫快照並讓 AI 模擬倉依收盤名單買，基準日 %s", as_of)
        if not run_full_screening:
            return False
        screening = None
        try:
            # 最重負荷預設：晚間全掃也走子行程，不准拖死常駐。
            screening = self._screening_surviving_oom(
                as_of, session="evening", apply_us=False
            )
        except Exception as e:
            logger.error("晚間海選失敗: %s", e, exc_info=True)
            return False
        self._run_ai_desk(
            as_of,
            results=(screening or {}).get("results") or {},
            notify=False,
        )
        self._maybe_send_evolve_digest(as_of)
        if notify:
            logger.info("晚間海選名單不另推；AI 模擬倉在背景更新，不主動推播。")
        self._mark_pipeline("success", "evening", run_date=key)
        return True

    def run_winrate_buypoint(self, skip_if_done: bool = False, notify: bool = True) -> bool:
        """21:00 勝率買點：盤後 leave_zero（藍▲）名單落檔並推播壓力區＋高低卡。"""
        from import_health import latest_complete_quote_date
        from tw_holidays import closed_tw_session
        from winrate_buypoint import (
            EMPTY_MSG,
            pipeline_run_key,
            roster_is_current,
            save_winrate_roster,
            scan_winrate_leave_zero,
        )

        closed = closed_tw_session(db_path=self.db_path)
        if closed:
            ymd = str(closed.get("ymd") or "").strip() or "none"
            key = f"winrate-closed-{ymd}"
            logger.info(
                "今日台股休市 %s %s，不寄勝率買點（%s）",
                closed.get("ymd"),
                closed.get("zh"),
                key,
            )
            self._mark_pipeline(
                "success",
                f"tw closed {closed.get('ymd')} {closed.get('zh')} skip winrate",
                run_date=key,
            )
            return True

        as_of = latest_complete_quote_date(self.db_path)
        key = pipeline_run_key(as_of or "none")
        if skip_if_done and as_of:
            status = self.pipeline_status(key)
            if self.honor_push_delivery(key, notes="winrate-skip-receipt"):
                logger.info("勝率買點 %s 已有寄出回執，略過。", key)
                return True
            # 舊鍵 winrate-{as_of} 或掃版本未對齊藍▲ → 不略過，重掃並可再推。
            if status == "success" and roster_is_current(self.db_path, as_of):
                logger.info("勝率買點 %s 已寄過且名單現行，略過。", key)
                return True
            # 當日已寄過、僅掃版失效→重掃刷新名單，不准再推一次（避免換鍵當夜洗版）
            if status == "success" and notify and not roster_is_current(self.db_path, as_of):
                notify = False
                logger.info("勝率買點 %s 已寄過但名單非現行→重掃不重寄", key)
            if status == "computed" and not notify and roster_is_current(self.db_path, as_of):
                logger.info("勝率買點 %s 已算出（不寄），略過。", key)
                return True
        if not as_of:
            logger.error("無完整交易日可寫勝率買點")
            return False
        logger.info("🎯 21:00 勝率買點掃 leave_zero（藍▲），基準日 %s", as_of)
        try:
            day, rows = scan_winrate_leave_zero(self.db_path, as_of=as_of)
        except Exception as e:
            logger.error("勝率買點掃描失敗: %s", e, exc_info=True)
            return False
        as_of = day or as_of
        key = pipeline_run_key(as_of)
        n = save_winrate_roster(self.db_path, as_of, rows)
        logger.info("勝率買點名單 %s 檔 as_of=%s", n, as_of)
        try:
            from winrate_buypoint import silent_remember_roster

            silent_remember_roster(self.db_path, as_of, rows)
        except Exception:
            logger.debug("勝率買點靜默落檔略過", exc_info=True)
        # 建議哪檔過閘篩：推播臉用 paint；roster 落檔仍是完整 AI leave_zero
        push_rows = rows
        try:
            from winrate_buypoint import apply_suggest_paint

            push_rows = apply_suggest_paint(self.db_path, rows, as_of=as_of)
        except Exception:
            logger.debug("勝率建議篩略過，推播用整包", exc_info=True)
            push_rows = rows
        sent_ok = True
        if notify:
            # 舊鍵 winrate-{as_of} 曾錯推（公式有剛離零但圖無藍▲紅框）→ 先更正再寄正確名單。
            old_key = f"winrate-{as_of}"
            if self.pipeline_status(old_key) == "success" and self.pipeline_status(key) != "success":
                day_disp = (
                    f"{as_of[4:6]}/{as_of[6:8]}" if len(str(as_of)) == 8 else str(as_of)
                )
                fix_msg = (
                    f"更正：稍早「勝率買點」混進圖上沒有今日藍▲紅框的檔。"
                    f"以下改寄基準日 {day_disp} 正確名單"
                    f"（只含收盤圖會畫藍▲紅框；共 {n} 檔）。"
                )
                try:
                    self._broadcast_family(fix_msg)
                except Exception:
                    logger.debug("勝率買點更正說明寄出略過", exc_info=True)
            ids = self._family_chat_ids()
            dests = ids or ([str(self.chat_id)] if getattr(self, "chat_id", None) else [])
            dests = [d for d in dests if d]
            if not dests:
                logger.warning("勝率買點無白名單收件人")
                sent_ok = False
            elif self.bot and hasattr(self.bot, "push_winrate_buypoint_page"):
                ok_n = 0
                # 雙人同一份名單：整頁只渲一次，再各寄一次（省第二輪出圖）
                page_pairs = None
                if push_rows:
                    try:
                        from winrate_buypoint import PAGE_SIZE, page_slice, render_page_pairs

                        chunk, _off, _more = page_slice(push_rows, 0, limit=PAGE_SIZE)
                        page_pairs = render_page_pairs(
                            self.db_path,
                            chunk,
                            charts_dir=getattr(self.bot, "charts_dir", "") or "",
                            uid="wr_push",
                            as_of=as_of,
                            reuse_cache=True,
                        )
                    except Exception:
                        logger.exception("勝率買點整頁預渲失敗，改逐人出圖")
                        page_pairs = None
                for cid in dests:
                    try:
                        if self.bot.push_winrate_buypoint_page(
                            cid,
                            push_rows,
                            as_of=as_of,
                            offset=0,
                            mode="full",
                            uid=str(cid),
                            pairs=page_pairs,
                        ):
                            ok_n += 1
                    except Exception as e:
                        logger.warning("勝率買點寄出失敗 dest=%s: %s", cid, e)
                sent_ok = ok_n == len(dests) and ok_n > 0
            else:
                if not push_rows:
                    sent_ok = bool(self._broadcast_family(EMPTY_MSG))
                else:
                    from winrate_buypoint import header_html

                    sent_ok = bool(self._broadcast_family(header_html(as_of, len(rows))))
                    logger.info("勝率買點無 bot 圖推，只寄標題（%s 檔）", len(rows))
        else:
            logger.info("勝率買點不寄 Telegram（notify=0），只寫名單")

        if notify and sent_ok:
            # 先落回執再蓋戳：蓋戳失敗仍不准 catch-up 重寄
            self.record_whitelist_push(
                key, kind="winrate-bp", n_ok=n, notes=f"winrate-bp n={n}"
            )
            try:
                self._mark_pipeline(
                    "success", f"winrate-bp n={n}", run_date=key, retries=12
                )
            except Exception:
                logger.exception("勝率買點已寄出但蓋戳失敗 key=%s（回執已記）", key)
        elif not notify:
            self._mark_pipeline("computed", "winrate-bp notify-off", run_date=key)
        else:
            logger.error("勝率買點已算出但 Telegram 沒送到，不標已寄過 %s", key)
        return bool((not notify) or sent_ok)

    def run_midday_review(self, skip_if_done: bool = True) -> bool:
        """開市日 12:45 雙時段比價：白名單只寄一次。

        內容＝今早 06:30 剛離零＋還在零，開盤 vs 約 12:45 現價。
        準點／catch-up／watchdog／CLI／重開都走這裡。無論 skip_if_done，
        都必須先原子搶 midday-{as_of}；已 success 或未明確失敗的 running 一律不寄。
        skip_if_done 保留相容，不再允許無鎖強寄（#469 鎖死）。
        """
        from import_health import latest_complete_quote_date
        from tw_holidays import closed_tw_session

        closed = closed_tw_session(db_path=self.db_path)
        as_of = latest_complete_quote_date(self.db_path)
        if closed:
            # 休市日 12:45 整段不出（連「今天沒開盤」也不寄）。
            # 鍵用 midday-closed-{休市日}，不准寫 midday-{as_of} 污染上一開市日紀錄。
            ymd = str(closed.get("ymd") or "").strip() or "none"
            key = f"midday-closed-{ymd}"
            logger.info(
                "今日台股休市 %s %s，12:45 比價整段略過（不寄任何對話框；%s）",
                closed.get("ymd"),
                closed.get("zh"),
                key,
            )
            self._mark_pipeline(
                "success",
                f"tw closed {closed.get('ymd')} {closed.get('zh')} skip midday",
                run_date=key,
            )
            return True
        key = f"midday-{as_of or 'none'}"
        if not as_of:
            logger.error("無完整交易日可做 12:45 比價")
            return False
        # 無論參數：寄前必搶鎖。不准 stale running 重搶（重開連寄）。
        # 只有 computed（明確寄失敗）才能再搶；success／running 一律略過。
        _ = skip_if_done  # 相容舊呼叫；不再因 False 跳過 claim
        if not self.try_claim_pipeline(
            key, notes="midday-claim", allow_stale_running=False
        ):
            logger.info("12:45 比價 %s 已寄過或進行中，略過。", key)
            return True
        logger.info("🌤️ 12:45 雙時段比價，對照今早 06:30 剛離零＋還在零，基準日 %s", as_of)
        from midday_review import run_midday_review

        out = run_midday_review(self.db_path, as_of)
        html = out.get("html") or ""
        sent_ok = True
        if html:
            sent_ok = bool(self._broadcast_family(html)) and sent_ok
        if sent_ok:
            # 先回執再蓋戳：蓋戳失敗仍不准重開／補跑當未寄再寄
            n_chats = len(self._family_chat_ids() or []) or (1 if html else 0)
            self.record_whitelist_push(
                key, kind="midday", n_ok=n_chats, notes="midday"
            )
            try:
                self._mark_pipeline("success", "midday", run_date=key, retries=12)
            except Exception:
                logger.exception("12:45 已寄出但蓋戳失敗 key=%s（回執已記）", key)
        else:
            # 明確寄失敗才放 computed，讓 12:46–13:30 補跑可再寄；不准假 success。
            self._mark_pipeline("computed", "midday send-failed", run_date=key)
            logger.error("12:45 比價已算出但 Telegram 沒送到，不標已寄過，基準日 %s", as_of)
        return bool(sent_ok)

    def run_typhoon_peek(self) -> bool:
        """22:15／05:10 抓人事行政總處；北市全日／上午停班才記台股休市。"""
        from tw_holidays import refresh_tw_typhoon_halt

        out = refresh_tw_typhoon_halt(self.db_path)
        logger.info("人事行政總處北市停班：%s", out)
        return bool(out.get("ok"))

    def run_nightly_open_check(self, now=None, skip_if_done: bool = True) -> bool:
        """台北約 03:00：刷新年曆、查明日台股開否、落檔。失敗不擋 bot。

        開市日早報仍靠 06:30 run_morning_screen；休市用 screen-closed-*。
        這裡只預先對齊年曆與明日開否，讓連假後第一個開市日不會靠人提醒。
        """
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        from tw_holidays import load_tw_open_check, run_nightly_tomorrow_open_check

        tw = ZoneInfo("Asia/Taipei")
        if now is None:
            from config import taipei_now

            dt = taipei_now()
        elif getattr(now, "tzinfo", None) is None:
            dt = now.replace(tzinfo=tw)
        else:
            dt = now.astimezone(tw)
        target = (dt + timedelta(days=1)).strftime("%Y%m%d")
        key = f"open-check-{target}"
        if skip_if_done:
            try:
                if self.pipeline_status(key) == "success" and load_tw_open_check(
                    target, self.db_path
                ):
                    logger.info("深夜開盤查核 %s 已落檔，略過", key)
                    return True
            except Exception:
                pass
        try:
            out = run_nightly_tomorrow_open_check(self.db_path, now=dt)
        except Exception as e:
            logger.warning("深夜明日開盤查核失敗（不擋）：%s", e, exc_info=True)
            return False
        status = out.get("status") or {}
        target = str(status.get("target_ymd") or target).strip() or "none"
        key = f"open-check-{target}"
        try:
            note = (
                f"tomorrow {target} "
                f"{'open' if status.get('is_open') else 'closed'} "
                f"{status.get('kind') or ''} {status.get('name_zh') or ''}"
            ).strip()
            self._mark_pipeline(
                "success" if out.get("ok") else "incomplete",
                note[:500],
                run_date=key,
            )
        except Exception as e:
            logger.warning("深夜開盤查核落 pipeline 略過：%s", e)
        logger.info("深夜明日開盤查核：%s", out)
        return bool(out.get("ok"))

    def run_pipeline(self, skip_if_done: bool = False) -> bool:
        """相容舊呼叫：只做盤後融合，不寄海選。"""
        return self.run_increment_job(skip_if_done=skip_if_done)


def main():
    try:
        from config import assert_gha_screen_muted, job_kind, screen_notify_enabled

        # GHA 與 Render 碟不同；防雙寄只靠 notify=0，開了就硬失敗。
        assert_gha_screen_muted()

        runner = MainRunner()
        gha = bool((os.getenv("GITHUB_ACTIONS") or "").strip())
        if gha:
            n = runner.demote_unsent_screen_success()
            if n:
                logger.info("GHA zip 海選假成功已改成 computed：%s 筆", n)
        kind = job_kind()
        # GHA cron 與 trigger 檔可能各跑一次；略過已完成才不會寄兩份早報。
        # trigger 檔（push）是補跑：必須真的再寄，不能因為 pipeline_runs 已標成功就略過。
        if kind == "morning_screen":
            skip_if_done = True
            if (os.getenv("GITHUB_EVENT_NAME") or "").strip() == "push":
                skip_if_done = False

            ok = runner.run_morning_screen(
                skip_if_done=skip_if_done, notify=screen_notify_enabled()
            )
        elif kind == "evening_screen":
            ok = runner.run_evening_screen(skip_if_done=True, notify=False)
        elif kind == "midday_review":
            ok = runner.run_midday_review(skip_if_done=True)
        else:
            # GitHub Actions 盤後只融合、不寄「官方收盤已寫進庫」。寄訊歸 Render。
            ok = runner.run_increment_job(skip_if_done=True, notify=not gha)
        if not ok:
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 流水線異常: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
