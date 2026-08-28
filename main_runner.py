# ==============================================================================
# WayneBot 全市場量化決策系統：主排程與自動復盤總控 (main_runner.py)
# 支援雙模式：GitHub Actions 批次排程推播 / Render 伺服器常駐監聽
# ==============================================================================

import os
import sys
import time
import argparse
import asyncio
import logging
from datetime import datetime

# 導入 WayneBot 核心模組
try:
    from data_fetcher import DataFetcher
    from screening_engine import ScreeningEngine
    from portfolio_engine import PortfolioEngine
    from bot_servers import WayneTelegramBot
except ImportError as e:
    logging.error(f"模組導入失敗，請確認同目錄下包含所有核心檔案: {e}")

# 設定日誌格式
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("WayneBot-Runner")


class MainRunner:
    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = db_path
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        
        # 初始化核心元件
        self.fetcher = DataFetcher(db_path=self.db_path)
        self.screening = ScreeningEngine(db_path=self.db_path)
        self.portfolio = PortfolioEngine(db_path=self.db_path)
        self.bot = WayneTelegramBot(
            token=self.bot_token,
            chat_id=self.chat_id,
            db_path=self.db_path
        ) if self.bot_token else None

    async def run_daily_pipeline(self) -> dict:
        """
        執行每日盤後自動化流水線：
        1. 增量抓取當日 2,202 檔全市場數據並寫入 SQLite
        2. 執行 CaryBot 四大選股策略 + 當沖/隔日沖價位精算
        3. 更新 50 萬 AI 操盤手資產狀態與自選股守護
        4. 推播盤後戰報至 Telegram
        """
        logger.info("🚀 啟動今日盤後自動化量化流水線...")
        start_time = time.time()
        results = {}

        # 1. 數據增量更新
        logger.info("📥 [1/4] 檢查並執行每日盤後行情與法人籌碼增量更新...")
        try:
            update_status = self.fetcher.update_daily_quotes()
            logger.info(f"  └ 數據更新狀態: {update_status}")
        except Exception as e:
            logger.error(f"  └ 數據增量更新發生異常: {e}")

        # 2. 執行選股策略
        logger.info("⚡ [2/4] 執行四大即時選股與當沖/隔日沖價位運算...")
        try:
            picks = self.screening.run_all_strategies()
            results["picks"] = picks
            logger.info(f"  └ 篩選完成，共產出 {sum(len(v) for v in picks.values()) if isinstance(picks, dict) else len(picks)} 檔關鍵標的")
        except Exception as e:
            logger.error(f"  └ 選股運算異常: {e}")
            results["picks"] = {}

        # 3. 操盤手與資產盤後結算
        logger.info("💼 [3/4] 執行 50 萬 AI 模擬操盤手資產結算與守護評估...")
        try:
            portfolio_summary = self.portfolio.evaluate_daily_portfolio()
            results["portfolio"] = portfolio_summary
            logger.info("  └ 持倉與守護狀態結算完成")
        except Exception as e:
            logger.error(f"  └ 操盤手結算異常: {e}")
            results["portfolio"] = {}

        # 4. Telegram 推播
        logger.info("📢 [4/4] 產生《每日盤後復盤日誌》並推送通知...")
        if self.bot and self.chat_id:
            try:
                report_text = self.format_daily_report(results)
                await self.bot.send_message(chat_id=self.chat_id, text=report_text)
                logger.info("  └ Telegram 訊息推播成功 ✅")
            except Exception as e:
                logger.error(f"  └ Telegram 推播失敗: {e}")
        else:
            logger.warning("  └ 未設定 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID，跳過推播")

        cost_time = time.time() - start_time
        logger.info(f"🎉 今日量化流水線順利執行完成，耗時: {cost_time:.2f} 秒")
        return results

    def format_daily_report(self, results: dict) -> str:
        """格式化 Telegram 盤後精簡回報"""
        today_str = datetime.now().strftime("%Y/%m/%d")
        picks = results.get("picks", {})
        
        msg = f"📊 【WayneBot 每日盤後復盤戰報】 {today_str}\n"
        msg += "═" * 30 + "\n\n"
        
        if isinstance(picks, dict):
            for strat_name, stock_list in picks.items():
                msg += f"🔥 <b>{strat_name}</b> ({len(stock_list)} 檔):\n"
                if stock_list:
                    for s in stock_list[:5]:  # 最多顯示前 5 檔
                        sid = s.get("stock_id", "")
                        sname = s.get("stock_name", "")
                        close = s.get("close", 0.0)
                        pct = s.get("pct_change", 0.0)
                        msg += f"  • {sid} {sname} : {close} ({pct:+.2f}%)\n"
                else:
                    msg += "  • 今日無符合標的\n"
                msg += "\n"
        else:
            msg += f"今日精選標的共 {len(picks)} 檔\n\n"
            
        msg += "💼 <b>AI 操盤手狀態</b>: 正常運作中\n"
        msg += "⭐ 點擊 Telegram 選單查看完整明細與持股守護線。"
        return msg

    async def start_interactive_service(self):
        """啟動常駐互動模式（用於 Render 或本地伺服器）"""
        if not self.bot:
            logger.error("未設定 Telegram Bot，無法啟動互動模式")
            return

        logger.info("🤖 啟動 Telegram Bot 訊息監聽服務（常駐模式）...")
        
        # 相容不同版本的 polling 呼叫方式
        if hasattr(self.bot, "start_polling_async"):
            await self.bot.start_polling_async()
        elif hasattr(self.bot, "start_polling"):
            if asyncio.iscoroutinefunction(self.bot.start_polling):
                await self.bot.start_polling()
            else:
                self.bot.start_polling()
        elif hasattr(self.bot, "run"):
            if asyncio.iscoroutinefunction(self.bot.run):
                await self.bot.run()
            else:
                self.bot.run()
        else:
            logger.error("WayneTelegramBot 實例未提供有效的 polling/run 啟動介面")


# ------------------------------------------------------------------------------
# 主程式入口與命令列參數解析
# ------------------------------------------------------------------------------
async def main_async():
    parser = argparse.ArgumentParser(description="WayneBot 總控排程入口")
    parser.add_argument(
        "--pipeline-only",
        action="store_true",
        help="僅執行單次盤後量化流水線推播並結束（適用於 GitHub Actions）"
    )
    parser.add_argument(
        "--server",
        action="store_true",
        help="啟動常駐 Telegram 互動機器人服務（適用於 Render）"
    )
    args = parser.parse_args()

    runner = MainRunner()

    # 1. 若為 GitHub Actions 環境或指定 --pipeline-only：僅跑流水線
    is_github_actions = os.getenv("GITHUB_ACTIONS") == "true"
    
    if args.pipeline_only or is_github_actions:
        logger.info("⚡ 偵測到 CI/CD 排程環境，執行一次性盤後流水線...")
        await runner.run_daily_pipeline()
        logger.info("🏁 排程工作已完成，正常結束程序。")
        return

    # 2. 若指定 --server 或本機直接執行：先跑一次更新後常駐監聽
    if args.server:
        logger.info("🌐 伺服器常駐模式啟動...")
        await runner.start_interactive_service()
    else:
        # 預設行為：執行單次流水線，若有需要再進入常駐
        await runner.run_daily_pipeline()


def main():
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 程式安全終止")
    except Exception as e:
        logger.exception(f"❌ 執行過程發生未預期錯誤: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
