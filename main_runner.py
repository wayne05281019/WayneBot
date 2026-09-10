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
# 12:45 尾盤：只複核今早名單＋高低卡；現在／今早價分開寫，先講現在要做什麼，不轉 LINE
# 20:00 晚間台股收盤海選寫快照，並讓 AI 模擬倉依收盤名單買（海選本文不寄；不主動推播模擬倉）
# 22:15 抓人事行政總處北市停班（週日也跑）；05:10 再抓一次涵蓋 04:30 補發；06:30 海選前再確認
# 16:30 融合成功後會順便跑晚間海選＋AI，讓 Release zip 帶得走模擬持倉。
# 20:00／重啟若快照已寫過，不再重掃全市場，仍用快照再跑 AI 模擬倉（清 ETF 槽、依收盤停利停損）。
# 16:30 寫入項目（皆融合進同一 sqlite）：
#   1. 母體 stock_universe（ISIN，現股／KY／ETF）
#   2. 上市 MI_INDEX ＋ 上櫃收盤 → daily_quotes 價量
#   3. 三大法人 T86／櫃買 → daily_quotes.foreign_net / trust_net / dealer_net（張）
#      並依產業加總寫入 daily_sector_flow（盤後資金輪動，佈局參考）
#   4. 缺日／上市櫃缺邊重抓（假日官方回空則略過）
#   5. 月營收 monthly_revenue（OpenAPI 全市場同期＋公開資訊觀測站 NAS 已先公告）、季報 quarterly_income（OpenAPI 最新一期；無免驗證碼 NAS 彙總表）
#   6. 除權息 ex_rights（證交所 TWT49U、櫃買 exDailyQ；決策卡還原優先用此表）
#   7. 興櫃 emerging_quotes（櫃買當日行情表／日表；不寫進上市櫃 daily_quotes）
#   8. 匯入健康檢查；上市／上櫃沒齊就不標成功、不覆蓋完整舊資料
# 海選 06:30 寄給偉權與哥哥（兩人已在白名單）；12:45 尾盤只對照今早價，不轉 LINE。盤後 16:30 只融合；20:00 不寄。
# 盤後融合順便用庫內下一根日 K 對昨天海選復盤；不另抓數。弱類別只調 AI 模擬倉權重。
# 早上海選會再抓美股現金收盤：四大＋VIX＋費半／台積ADR；收盤後再看盤後（ADR／那指期續勢）。
# 盤中期貨不看。大跌會在 06:30 海選前先單獨通知。逆風時當沖／隔日沖不列；半導體對照費半。美股抓不到就不過濾。
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
from datetime import datetime
from typing import Dict, List, Any, Optional

import requests

from config import get_db_path, get_cache_dir, get_telegram_token, get_telegram_chat_id, taipei_today_str, fuse_end_date
from wayne_db import ensure_core_schema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("WayneBotRunner")

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
        return self.pipeline_status(run_date) == "success"

    def pipeline_status(self, run_date: str = None) -> str:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT status FROM pipeline_runs WHERE run_date = ?;", (run_date or self.today_str,))
        row = cur.fetchone()
        conn.close()
        return str(row[0] or "") if row else ""

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

    def _mark_pipeline(self, status: str, notes: str = "", run_date: str = None):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO pipeline_runs (run_date, finished_at, status, notes) VALUES (?, ?, ?, ?);",
            (run_date or self.today_str, datetime.now().isoformat(timespec="seconds"), status, notes),
        )
        conn.commit()
        conn.close()

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
            from universe import sync_universe
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
            if chip_sum == 0:
                logger.info("最近交易日籌碼仍為 0，回補近 60 個交易日法人…")
                bf = backfill_chips(self.db_path, days=60)
                logger.info(f"法人回補：{bf}")
        except Exception as e:
            logger.error(f"法人籌碼更新失敗: {e}", exc_info=True)

        try:
            from import_health import clear_complete_date_cache
            from money_flow import recompute_sector_flow

            clear_complete_date_cache(self.db_path)
            n_sec = recompute_sector_flow(self.db_path, fuse_to)
            logger.info("盤後產業資金輪動寫入 %s 列", n_sec)
        except Exception as e:
            logger.error("產業資金輪動失敗: %s", e, exc_info=True)

        try:
            from emerging_quotes import sync_emerging_quotes

            em = sync_emerging_quotes(self.db_path)
            logger.info("興櫃官方日均價寫入：%s", em)
        except Exception as e:
            logger.warning("興櫃日均價同步略過：%s", e)
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
            if health.get("problems"):
                logger.warning("匯入今天異常：%s", format_audit_plain(health))
                if notify:
                    try:
                        self.send_telegram_message("⚠️ " + format_audit_plain(health))
                    except Exception:
                        pass
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

        return inserted_count

    def _load_latest_quotes_map(self) -> Dict[str, Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        try:
            from quote_integrity import db_as_of_trading_date

            latest = db_as_of_trading_date(self.db_path) or ""
        except Exception:
            cur.execute("SELECT MAX(date) FROM daily_quotes;")
            latest = cur.fetchone()[0]
        quotes: Dict[str, Dict[str, Any]] = {}
        if latest:
            cur.execute(
                "SELECT stock_id, stock_name, close, pct_change, volume, turnover_k FROM daily_quotes WHERE date=?;",
                (latest,),
            )
            for sid, sname, close_p, pct, vol, to_k in cur.fetchall():
                quotes[sid] = {
                    "stock_name": sname, "close": close_p, "pct_change": pct,
                    "volume": vol, "turnover_k": to_k, "is_k20_warning": False, "d20": 0.0,
                }
        conn.close()
        return quotes

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
                output = run_full_screening(db_path=self.db_path)
                report_text = output.get("message") or ""
                logger.info(f"四大選股 status={output.get('status')} scanned={output.get('total_scanned')}")
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

                for r in get_user_watchlist(db, uid) or []:
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

    @staticmethod
    def _screening_delivered(screening: Optional[Dict[str, Any]]) -> bool:
        """海選有產出可推播的 payload（成功或空桶），不是例外中斷。"""
        if not screening:
            return False
        if screening.get("payload"):
            return True
        return str(screening.get("status") or "") in ("success", "empty")

    def _push_screening(self, screening: Optional[Dict[str, Any]], as_of: str = "") -> bool:
        """寄出海選本文。回傳是否每個收件人都被 Telegram 接受。

        算出名單 ≠ 已寄到。401／空 token 必須回 False，否則 skip_if_done 會把失敗當成已完成。
        """
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
                            if self.bot.send_screening_report(screening, chat_id=cid) is False:
                                logger.warning("海選 Telegram 未接受 dest_len=%s", len(str(cid)))
                            else:
                                sent_n += 1
                        except Exception as e:
                            logger.warning("海選寄出失敗 dest_len=%s: %s", len(str(cid)), e)
                    logger.info("海選寄出成功 %d/%d 人", sent_n, len(dests))
                    sent_ok = sent_n == len(dests) and sent_n > 0
                else:
                    sent_ok = self.bot.send_screening_report(screening) is not False
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
        if not delivered:
            logger.warning("早上海選未產出名單，略過 AI 模擬倉／資金輪動附帶推播")
            return False
        if not sent_ok:
            logger.error("早上海選已算出但 Telegram 沒送到，附帶區塊也不寄")
            return False
        extra_bits = []
        try:
            from taiwan_market import format_taiwan_market_brief_html

            mkt = format_taiwan_market_brief_html(self.db_path, as_of or "")
            if mkt and (screening or {}).get("message") and mkt not in (screening or {}).get("message", ""):
                extra_bits.insert(0, mkt)
        except Exception:
            pass
        try:
            from screen_review import adapt_bucket_weights, score_ai_fills, score_screen_picks
            from taiwan_market import analyze_taiwan_market

            score_screen_picks(self.db_path, as_of or "")
            score_ai_fills(self.db_path, as_of or "")
            snap = analyze_taiwan_market(self.db_path, as_of or "")
            adapt_bucket_weights(
                self.db_path,
                regime=snap.get("regime") if snap.get("ok") else None,
                regime_plus=snap.get("regime_plus") if snap.get("ok") else None,
            )
        except Exception as e:
            logger.warning("海選復盤略過：%s", e)
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
        extra_text = "\n".join(x for x in extra_bits if x)
        owner = str(getattr(self, "chat_id", None) or "").strip()
        targets = ids or ([owner] if owner else [])
        if not targets:
            if extra_text:
                self.send_telegram_message(extra_text)
        else:
            for cid in targets:
                try:
                    radar = self._format_watch_radar_section(cid)
                except Exception as e:
                    logger.warning("自選雷達略過 uid=%s: %s", cid, e)
                    radar = ""
                text = "\n".join(x for x in (extra_text, radar) if x)
                if text:
                    self.send_telegram_message(text, chat_id=cid)
        self._run_ai_desk(as_of or self.today_str, results=(screening or {}).get("results") or {}, notify=False)
        return True

    def _run_ai_desk(
        self,
        as_of: str,
        results: Optional[Dict[str, Any]] = None,
        apply_us: bool = False,
        session: str = "",
        notify: bool = True,
        telegram_uid: str = "",
    ) -> Dict[str, Any]:
        """模擬倉真正下單（每人 ai_{uid}／50 萬）。有名單才買；平常 1 檔，超跌最多 2 檔，永遠留現金。"""
        try:
            from ai_trader import run_ai_desk
            from config import allowed_telegram_uids, telegram_uid_allowed

            if results is None:
                if not run_full_screening:
                    return {}
                screening = run_full_screening(
                    db_path=self.db_path,
                    target_date=as_of,
                    apply_us=apply_us,
                    session=session or "",
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
        return (
            f"📦 官方收盤已寫進庫（{pretty}）\n"
            f"上市 {tw}　上櫃 {two}\n"
            "不是海選、不是買訊。明早 06:30 才寄海選。"
        )

    def run_increment_job(self, skip_if_done: bool = False, notify: bool = True) -> bool:
        from tw_holidays import closed_tw_session, refresh_tw_holiday_calendar, refresh_tw_typhoon_halt

        closed = closed_tw_session(db_path=self.db_path)
        if closed:
            logger.info(
                "今日台股休市 %s %s，盤後融合改記成功、不重抓今天",
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
            self._mark_pipeline(
                "success",
                f"tw closed {closed.get('ymd')} {closed.get('zh')} skip increment",
            )
            return True
        if skip_if_done and self.already_completed_today():
            logger.info("ℹ️ %s 盤後融合已成功，略過。", self.today_str)
            return True
        start_time = time.time()
        logger.info("🎬 === 盤後融合開始（不寄海選；海選 06:30／尾盤 12:45）===")
        self.run_daily_increment(notify=notify)
        from import_health import audit_import, format_audit_plain

        cap = fuse_end_date()
        health = audit_import(self.db_path, cap)
        try:
            wd = datetime.strptime(cap, "%Y%m%d").weekday()
        except Exception:
            wd = 0
        if wd < 5 and not self._increment_ok(health) and self.fetcher:
            for i in range(1, 9):
                logger.warning(
                    "%s 繼續補齊（上市 %s 上櫃 %s）第 %s 次",
                    cap,
                    health.get("tw"),
                    health.get("two"),
                    i,
                )
                time.sleep(min(25 * i, 60))
                self.fetcher.update_daily_market_data(cap)
                if hasattr(self.fetcher, "sync_paired_markets"):
                    self.fetcher.sync_paired_markets()
                health = audit_import(self.db_path, cap)
                if self._increment_ok(health):
                    break
        elapsed = time.time() - start_time
        if not self._increment_ok(health):
            note = format_audit_plain(health)
            self._mark_pipeline("incomplete", note[:500])
            logger.error("盤後仍待補：%s", note)
            if notify:
                try:
                    self.send_telegram_message("🔁 盤後繼續補齊（下一輪開機／16:30 會再抓）\n" + note)
                except Exception:
                    pass
            return False
        self._mark_pipeline(
            "success",
            f"increment elapsed={elapsed:.1f}s tw={health.get('tw')} two={health.get('two')}",
        )
        logger.info("🎉 === 盤後融合完畢 上市%s 上櫃%s（%.1fs）===", health.get("tw"), health.get("two"), elapsed)
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
        try:
            from screen_review import score_ai_fills, score_screen_picks

            n = score_screen_picks(self.db_path, cap)
            nf = score_ai_fills(self.db_path, cap)
            logger.info("海選復盤已對帳 %s 檔、AI 成交 %s 筆（隔日＝%s）", n, nf, cap)
        except Exception:
            logger.exception("海選復盤對帳失敗")
        try:
            from industry_fine import sync_all_fine_industry

            fi = sync_all_fine_industry(self.db_path, workers=8)
            logger.info("籌碼K細項全市場：%s", fi)
        except Exception as e:
            logger.warning("籌碼K細項同步略過：%s", e)
        # 盤後這份庫會打進 Release zip：模擬倉也要在這裡成交，下次開機才看得到持倉。
        self.run_evening_screen(skip_if_done=True, notify=False)
        return True

    def _refresh_official_sidecars(self) -> None:
        """行情已齊時仍每天對官方側車。不重抓全市場日K、不分點。

        月營收 OpenAPI 常整期才換檔；已先公告的公司要對公開資訊觀測站 NAS。
        股東會／法說、除權息預告、本益／融資快照也是查股會讀的官方列。
        """
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

    def run_morning_screen(self, skip_if_done: bool = False, notify: bool = True) -> bool:
        from import_health import latest_complete_quote_date
        from tw_holidays import closed_tw_session, refresh_tw_typhoon_halt

        try:
            typh = refresh_tw_typhoon_halt(self.db_path)
            logger.info("今早北市停班：%s", typh)
        except Exception as e:
            logger.warning("今早北市停班略過：%s", e)
        closed = closed_tw_session(db_path=self.db_path)
        if closed:
            from trading_calendar import morning_screen_pipeline_key

            key = morning_screen_pipeline_key(self.db_path)
            logger.info(
                "今日台股休市 %s %s，不寄今早海選（%s）",
                closed.get("ymd"),
                closed.get("zh"),
                key,
            )
            self._mark_pipeline(
                "success",
                f"tw closed {closed.get('ymd')} {closed.get('zh')} skip morning",
                run_date=key,
            )
            return True

        if notify:
            demoted = self.demote_premature_morning_screens()
            if demoted:
                logger.info("過早海選 success 已降級 %s 筆，改為可重寄", demoted)

        as_of = latest_complete_quote_date(self.db_path)
        key = f"screen-{as_of or 'none'}"
        if skip_if_done and as_of:
            status = self.pipeline_status(key)
            if status == "success":
                logger.info("早上海選 %s 已寄過，略過。", key)
                return True
            if status == "computed" and not notify:
                logger.info("早上海選 %s 已算出（不寄），略過。", key)
                return True
        logger.info("☀️ 06:30 先確認庫已齊，再寄海選")
        from config import fuse_end_date

        cap = fuse_end_date()
        if as_of and as_of == cap:
            logger.info("今早庫已是完整日 %s，略過再抓行情，仍對官方側車", as_of)
            self._refresh_official_sidecars()
        else:
            self.run_daily_increment(notify=False)
        as_of = latest_complete_quote_date(self.db_path)
        key = f"screen-{as_of or 'none'}"
        if not as_of:
            logger.error("補齊後仍無完整交易日可寄海選")
            return False
        logger.info("☀️ 台灣 06:30 海選，基準日 %s", as_of)
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
        try:
            from us_overnight import (
                format_us_drop_alert,
                refresh_us_overnight,
                should_alert_us_drop,
            )

            us_snap = refresh_us_overnight(self.db_path, as_of) or {}
            if should_alert_us_drop(us_snap):
                logger.info("美股收盤偏弱，先寄一早通知 regime=%s", us_snap.get("regime"))
                if notify:
                    self._broadcast_family(format_us_drop_alert(us_snap))
        except Exception as e:
            logger.warning("美股大跌通知略過：%s", e)
        screening = None
        if run_full_screening:
            try:
                screening = run_full_screening(
                    db_path=self.db_path, target_date=as_of, apply_us=True, session="morning"
                )
            except Exception as e:
                logger.error("四大選股失敗: %s", e, exc_info=True)
        sent_ok = True
        if notify:
            sent_ok = bool(self._push_screening(screening, as_of=as_of))
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
        if self._screening_delivered(screening) and sent_ok:
            if notify:
                self._mark_pipeline("success", "morning", run_date=key)
            else:
                # GHA notify=0 只算名單。若標 success，Release zip 灌進 Render
                # 會讓 skip_if_done 以為已寄過（401 那天就是這樣）。
                self._mark_pipeline("computed", "morning notify-off", run_date=key)
                logger.info("早上海選已算出但不標已寄過（notify=0）%s", key)
        elif self._screening_delivered(screening) and not sent_ok:
            logger.error("早上海選已算出但 Telegram 沒送到，不標已寄過，基準日 %s", as_of)
        else:
            logger.error("早上海選未產出名單，基準日 %s", as_of)
        return bool(self._screening_delivered(screening) and sent_ok)

    def run_evening_screen(self, skip_if_done: bool = False, notify: bool = False) -> bool:
        """台股收盤後的名單只存庫，不寄 Telegram（美股還沒開）。"""
        from import_health import latest_complete_quote_date

        as_of = latest_complete_quote_date(self.db_path)
        key = f"evening-{as_of or 'none'}"
        if skip_if_done and as_of and self.already_completed_today(key):
            # 16:30 融合常已寫過快照；20:00／重啟補跑仍要讓 AI 模擬倉用官方收盤再成交一次
            # （例如清掉舊 ETF 持倉）。不再略過整段。
            logger.info("晚間海選快照 %s 已寫過，改用快照再跑 AI 模擬倉。", key)
            from screen_sessions import load_session_results

            results = load_session_results(self.db_path, as_of, "evening")
            if not any(results.values()):
                results = load_session_results(self.db_path, as_of, "morning")
            self._run_ai_desk(as_of, results=results, notify=False)
            self._maybe_send_evolve_digest(as_of)
            return True
        if not as_of:
            logger.error("無完整交易日可寫晚間海選快照")
            return False
        logger.info("🌙 20:00 晚間海選寫快照並讓 AI 模擬倉依收盤名單買，基準日 %s", as_of)
        if not run_full_screening:
            return False
        screening = None
        try:
            screening = run_full_screening(
                db_path=self.db_path, target_date=as_of, apply_us=False, session="evening"
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

    def run_midday_review(self, skip_if_done: bool = False) -> bool:
        from import_health import latest_complete_quote_date
        from tw_holidays import closed_tw_session

        closed = closed_tw_session(db_path=self.db_path)
        as_of = latest_complete_quote_date(self.db_path)
        key = f"midday-{as_of or 'none'}"
        if closed:
            logger.info(
                "今日台股休市 %s %s，不寄尾盤可切",
                closed.get("ymd"),
                closed.get("zh"),
            )
            self._mark_pipeline(
                "success",
                f"tw closed {closed.get('ymd')} {closed.get('zh')} skip midday",
                run_date=key,
            )
            return True
        if skip_if_done and as_of and self.already_completed_today(key):
            logger.info("尾盤可切 %s 已寄過，略過。", key)
            return True
        if not as_of:
            logger.error("無完整交易日可做尾盤複核")
            return False
        logger.info("🌤️ 12:45 尾盤可切，對照今早 06:30 基準日 %s", as_of)
        from midday_review import run_midday_review

        out = run_midday_review(self.db_path, as_of)
        html = out.get("html") or ""
        sent_ok = True
        if html:
            sent_ok = bool(self._broadcast_family(html)) and sent_ok
        if sent_ok:
            self._mark_pipeline("success", "midday", run_date=key)
        else:
            logger.error("尾盤可切已算出但 Telegram 沒送到，不標已寄過，基準日 %s", as_of)
        return bool(sent_ok)

    def run_typhoon_peek(self) -> bool:
        """22:15／05:10 抓人事行政總處；北市全日／上午停班才記台股休市。"""
        from tw_holidays import refresh_tw_typhoon_halt

        out = refresh_tw_typhoon_halt(self.db_path)
        logger.info("人事行政總處北市停班：%s", out)
        return bool(out.get("ok"))

    def run_pipeline(self, skip_if_done: bool = False) -> bool:
        """相容舊呼叫：只做盤後融合，不寄海選。"""
        return self.run_increment_job(skip_if_done=skip_if_done)


def main():
    try:
        from config import job_kind

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
            from config import screen_notify_enabled

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
