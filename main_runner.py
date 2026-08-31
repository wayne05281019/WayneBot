# ==============================================================================
# WayneBot 主排程：盤後增量、四大選股、法人回補、Telegram 復盤推播
# 執行：python main.py --once  或  python main_runner.py
#
# 單一正式庫：data/wayne_market.db（UPSERT，不另開第二套行情庫）
# 盤後時間：台灣週一～五 16:30 只融合行情（不寄海選）
#   - GitHub Actions cron 30 8 * * 1-5（UTC＝台灣 16:30）WAYNE_JOB=increment
#   - Render 常駐執行緒同樣 16:30
# 早上海選：台灣週一～五 07:30（用庫內「上市＋上櫃都齊」的昨收）
#   - GitHub Actions cron 30 23 * * 0-4（UTC 日～四 23:30＝台灣一～五 07:30）
# 16:30 寫入項目（皆融合進同一 sqlite）：
#   1. 母體 stock_universe（ISIN，現股／KY／ETF）
#   2. 上市 MI_INDEX ＋ 上櫃收盤 → daily_quotes 價量
#   3. 三大法人 T86／櫃買 → daily_quotes.foreign_net / trust_net / dealer_net（張）
#      並依產業加總寫入 daily_sector_flow（盤後資金輪動，佈局參考）
#   4. 缺日／上市櫃缺邊重抓（假日官方回空則略過）
#   5. 月營收 monthly_revenue、季報 quarterly_income（官方 OpenAPI 最新一期）
#   6. 除權息 ex_rights（證交所 TWT49U、櫃買 exDailyQ；決策卡還原優先用此表）
#   7. 匯入健康檢查；上市／上櫃沒齊就不標成功、不覆蓋完整舊資料
# 海選改早上 07:30 寄出（給家人轉貼），盤後 16:30 不再重複寄名單。
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
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT status FROM pipeline_runs WHERE run_date = ?;", (run_date or self.today_str,))
        row = cur.fetchone()
        conn.close()
        return bool(row and row[0] == "success")

    def _mark_pipeline(self, status: str, notes: str = "", run_date: str = None):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO pipeline_runs (run_date, finished_at, status, notes) VALUES (?, ?, ?, ?);",
            (run_date or self.today_str, datetime.now().isoformat(timespec="seconds"), status, notes),
        )
        conn.commit()
        conn.close()

    def send_telegram_message(self, text: str, chat_id: Optional[str] = None):
        if not text:
            return
        target = chat_id or self.chat_id
        for part in chunk_telegram_text(text):
            self._send_one(part, target)

    def _send_one(self, text: str, chat_id: str):
        if self.bot and hasattr(self.bot, "send_message"):
            try:
                self.bot.send_message(text, chat_id=chat_id)
                logger.info("📤 透過 WayneTelegramBot 成功發送推播")
                return
            except Exception as e:
                logger.warning(f"⚠️ bot.send_message 失敗: {e}，切換原生 API...")
        if self.token and chat_id:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
            try:
                resp = requests.post(url, json=payload, timeout=15)
                if resp.status_code == 200:
                    logger.info("📤 原生 API 成功送出 Telegram 推播")
                else:
                    logger.error(f"❌ Telegram API 錯誤 ({resp.status_code}): {resp.text}")
            except Exception as e:
                logger.error(f"❌ 發送 Telegram 異常: {e}")
        else:
            logger.info(f"📋 [本機推播預覽]\n{text}")

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
        cursor.execute("SELECT COUNT(*) FROM daily_quotes WHERE replace(date,'-','') = ?;", (fuse_to,))
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
            cur.execute("SELECT MAX(replace(date,'-','')) FROM daily_quotes;")
            latest = cur.fetchone()[0]
            chip_sum = 0
            if latest:
                chip_sum = cur.execute(
                    "SELECT COALESCE(SUM(ABS(foreign_net)+ABS(trust_net)+ABS(dealer_net)),0) FROM daily_quotes WHERE replace(date,'-','')=?",
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
            from money_flow import recompute_sector_flow

            n_sec = recompute_sector_flow(self.db_path)
            logger.info("盤後產業資金輪動寫入 %s 列", n_sec)
        except Exception as e:
            logger.error("產業資金輪動失敗: %s", e, exc_info=True)

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
        except Exception as e:
            logger.error(f"除權息同步失敗: {e}", exc_info=True)
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
            if health.get("problems") or health.get("history_issue_n"):
                logger.warning("匯入異常：%s", format_audit_plain(health))
                if notify:
                    try:
                        self.send_telegram_message("⚠️ " + format_audit_plain(health))
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("匯入檢查略過：%s", e)
        return inserted_count

    def _load_latest_quotes_map(self) -> Dict[str, Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
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

    def generate_screening_report(self) -> str:
        logger.info("🔍 正在執行四大選股...")
        report_text = ""
        if run_full_screening:
            try:
                output = run_full_screening(db_path=self.db_path)
                report_text = output.get("message") or ""
                logger.info(f"四大選股 status={output.get('status')} scanned={output.get('total_scanned')}")
            except Exception as e:
                logger.error(f"四大選股失敗，改用簡易 SQL：{e}", exc_info=True)
        if not report_text:
            report_text = self._fallback_sql_report()
        extra = [report_text, self._format_portfolio_section(), self._format_watch_radar_section()]
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
            for sid, sname, close_p, pct, vol, t_net, f_net in rows:
                lines.append(f"• <b>{sid} {sname}</b> | 收 <code>{close_p:.2f}</code> (<b>+{pct:.2f}%</b>) 量 {vol:,}張")
        else:
            lines.append("• <i>今日無符合高動能突破標準之標的。</i>")
        return "\n".join(lines)

    def _format_portfolio_section(self) -> str:
        if not self.portfolio_engine or not self.chat_id:
            return (
                "───────────────────\n💼 <b>【50萬 AI 操盤手】</b>\n"
                "• Telegram 點「AI 模擬持倉」或 /portfolio"
            )
        quotes = self._load_latest_quotes_map()
        summary = self.portfolio_engine.get_portfolio_summary(self.chat_id, quotes)
        lines = [
            "───────────────────",
            "💼 <b>【50萬 AI 操盤手部位概況】</b>",
            f"• 總資產 <code>{summary['total_assets']:,.0f}</code> | 現金 <code>{summary['cash']:,.0f}</code>",
            f"• 損益 <code>{summary['total_pnl']:+,.0f}</code> ({summary['total_pnl_pct']:+.2f}%) | 持股 {summary['positions_count']} 檔",
        ]
        for p in summary["positions"][:5]:
            lines.append(f"• {p['stock_id']} {p['stock_name']} {p['shares']}股 {p['pnl_pct']:+.2f}%")
        return "\n".join(lines)

    def _format_watch_radar_section(self) -> str:
        if not self.portfolio_engine or not self.chat_id:
            return ""
        quotes = self._load_latest_quotes_map()
        watch = self.portfolio_engine.get_watchlist(self.chat_id)
        if not watch:
            return ""
        lines = ["───────────────────", "🎯 <b>【自選守護雷達】</b>"]
        for w in watch[:8]:
            q = quotes.get(w["stock_id"])
            if q:
                lines.append(f"• {w['stock_id']} {w['stock_name']} 收 {q['close']:.2f} ({q['pct_change']:+.2f}%)")
            else:
                lines.append(f"• {w['stock_id']} {w['stock_name']}")
        return "\n".join(lines)

    def _increment_ok(self, health: Dict[str, Any]) -> bool:
        from import_health import sides_complete

        if not health:
            return False
        if int(health.get("total") or 0) == 0:
            return True
        return sides_complete(health.get("tw") or 0, health.get("two") or 0)

    def _push_screening(self, screening: Optional[Dict[str, Any]], as_of: str = ""):
        if self.bot and screening:
            try:
                self.bot.send_screening_report(screening)
            except Exception as e:
                logger.warning("分類戰報推播失敗，改送長文: %s", e)
                self.send_telegram_message(screening.get("message") or self.generate_screening_report())
        else:
            report_text = (screening or {}).get("message") if screening else ""
            self.send_telegram_message(report_text or self.generate_screening_report())
        extra_bits = [self._format_portfolio_section(), self._format_watch_radar_section()]
        try:
            from money_flow import format_sector_rotation_html

            rot = format_sector_rotation_html(self.db_path, as_of or "")
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
        if extra_text:
            self.send_telegram_message(extra_text)
        try:
            from ai_trader import run_ai_desk

            ai = run_ai_desk(self.db_path, (screening or {}).get("results") or {}, as_of or self.today_str)
            if ai.get("html"):
                self.send_telegram_message(ai["html"])
        except Exception as e:
            logger.warning("AI 模擬操盤略過：%s", e)

    def run_increment_job(self, skip_if_done: bool = False) -> bool:
        if skip_if_done and self.already_completed_today():
            logger.info("ℹ️ %s 盤後融合已成功，略過。", self.today_str)
            return True
        start_time = time.time()
        logger.info("🎬 === 盤後融合開始（不寄海選；海選改 07:30）===")
        self.run_daily_increment()
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
        return True

    def run_morning_screen(self, skip_if_done: bool = False) -> bool:
        from import_health import latest_complete_quote_date

        as_of = latest_complete_quote_date(self.db_path)
        key = f"screen-{as_of or 'none'}"
        if skip_if_done and as_of and self.already_completed_today(key):
            logger.info("早上海選 %s 已寄過，略過。", key)
            return True
        logger.info("☀️ 07:30 先補齊已收盤交易日與財報，再寄海選")
        self.run_daily_increment(notify=False)
        as_of = latest_complete_quote_date(self.db_path)
        key = f"screen-{as_of or 'none'}"
        if not as_of:
            logger.error("補齊後仍無完整交易日可寄海選")
            return False
        logger.info("☀️ 台灣 07:30 海選，基準日 %s", as_of)
        screening = None
        if run_full_screening:
            try:
                screening = run_full_screening(db_path=self.db_path, target_date=as_of)
            except Exception as e:
                logger.error("四大選股失敗: %s", e, exc_info=True)
        self._push_screening(screening, as_of=as_of)
        self._mark_pipeline("success", "morning", run_date=key)
        return True

    def run_pipeline(self, skip_if_done: bool = False) -> bool:
        """相容舊呼叫：只做盤後融合，不寄海選。"""
        return self.run_increment_job(skip_if_done=skip_if_done)


def main():
    try:
        from config import job_kind

        runner = MainRunner()
        kind = job_kind()
        if kind == "morning_screen":
            ok = runner.run_morning_screen(skip_if_done=False)
        else:
            ok = runner.run_increment_job(skip_if_done=False)
        if not ok:
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ 流水線異常: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
