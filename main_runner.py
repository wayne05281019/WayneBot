# ==============================================================================
# WayneBot 主排程：盤後增量、四大選股、法人回補、Telegram 復盤推播
# 執行：python main.py --once  或  python main_runner.py
#
# 單一正式庫：data/wayne_market.db（UPSERT，不另開第二套行情庫）
# 盤後時間：台灣週一至週五 16:30
#   - GitHub Actions cron 30 8 * * 1-5（UTC＝台灣 16:30）
#   - Render 常駐執行緒同樣 16:30（ENABLE_DAILY_SCHEDULER，預設開）
# 16:30 寫入項目（皆融合進同一 sqlite）：
#   1. 母體 stock_universe（ISIN，現股／KY／ETF）
#   2. 上市 MI_INDEX ＋ 上櫃收盤 → daily_quotes 價量
#   3. 三大法人 T86／櫃買 → daily_quotes.foreign_net / trust_net / dealer_net（張）
#   4. 缺日／上市櫃缺邊重抓（假日官方回空則略過）
#   5. 月營收 monthly_revenue、季報 quarterly_income（官方 OpenAPI 最新一期）
#   6. 匯入健康檢查；通過後海選推播、AI 模擬倉
# 證交所收盤約 13:30 後陸續出表，法人常 15:30～16:30 才齊，所以排 16:30。
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

from config import get_db_path, get_cache_dir, get_telegram_token, get_telegram_chat_id, taipei_today_str
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

    def already_completed_today(self) -> bool:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT status FROM pipeline_runs WHERE run_date = ?;", (self.today_str,))
        row = cur.fetchone()
        conn.close()
        return bool(row and row[0] == "success")

    def _mark_pipeline(self, status: str, notes: str = ""):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO pipeline_runs (run_date, finished_at, status, notes) VALUES (?, ?, ?, ?);",
            (self.today_str, datetime.now().isoformat(timespec="seconds"), status, notes),
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
        if self.fetcher and hasattr(self.fetcher, "fill_missing_market_days"):
            try:
                gap = self.fetcher.fill_missing_market_days(end_date=self.today_str)
                logger.info("缺日回補：%s", gap)
                inserted_count = len(gap.get("filled") or [])
                if hasattr(self.fetcher, "_refill_thin_days"):
                    extra = self.fetcher._refill_thin_days(self.today_str, lookback=40, min_rows=1800)
                    if extra:
                        logger.info("稀薄日再補：%s", extra)
                        inserted_count += len(extra)
            except Exception as e:
                logger.error(f"❌ 缺日回補異常: {e}", exc_info=True)
        elif self.fetcher and hasattr(self.fetcher, "update_daily_market_data"):
            try:
                inserted_count = int(self.fetcher.update_daily_market_data(self.today_str) or 0)
            except Exception as e:
                logger.error(f"❌ 增量更新異常: {e}", exc_info=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM daily_quotes WHERE date = ?;", (self.today_str,))
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
            cur.execute("SELECT MAX(date) FROM daily_quotes;")
            latest = cur.fetchone()[0]
            chip_sum = 0
            if latest:
                chip_sum = cur.execute(
                    "SELECT COALESCE(SUM(ABS(foreign_net)+ABS(trust_net)+ABS(dealer_net)),0) FROM daily_quotes WHERE date=?",
                    (latest,),
                ).fetchone()[0]
            conn.close()
            if chip_sum == 0:
                logger.info("最近交易日籌碼仍為 0，回補近 20 個交易日法人…")
                bf = backfill_chips(self.db_path, days=20)
                logger.info(f"法人回補：{bf}")
        except Exception as e:
            logger.error(f"法人籌碼更新失敗: {e}", exc_info=True)

        try:
            from fundamentals import sync_fundamentals
            fund = sync_fundamentals(self.db_path)
            logger.info(f"月營收／季報同步：{fund}")
        except Exception as e:
            logger.error(f"基本面同步失敗: {e}", exc_info=True)
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

    def run_pipeline(self, skip_if_done: bool = False) -> bool:
        if skip_if_done and self.already_completed_today():
            logger.info(f"ℹ️ {self.today_str} 流水線已成功執行過，略過。")
            return False
        start_time = time.time()
        logger.info("🎬 === WayneBot 流水線開始 ===")
        self.run_daily_increment()
        screening = None
        if run_full_screening:
            try:
                screening = run_full_screening(db_path=self.db_path)
            except Exception as e:
                logger.error("四大選股失敗: %s", e, exc_info=True)
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

            ai = run_ai_desk(self.db_path, (screening or {}).get("results") or {}, self.today_str)
            if ai.get("html"):
                self.send_telegram_message(ai["html"])
        except Exception as e:
            logger.warning("AI 模擬操盤略過：%s", e)
        elapsed = time.time() - start_time
        self._mark_pipeline("success", f"elapsed={elapsed:.1f}s")
        logger.info(f"🎉 === 流水線完畢 (耗時: {elapsed:.2f} 秒) ===")
        return True


def main():
    try:
        MainRunner().run_pipeline(skip_if_done=False)
    except Exception as e:
        logger.error(f"❌ 流水線異常: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
