# -*- coding: utf-8 -*-
"""
WayneBot 總控核心：All_In_One 盤後 16:30 自動化量化總控流水線 (純淨推播版)
檔案名稱：main_runner.py
作者：Wayne (WayneBot Quantitative System Architect)
"""

import os
import sys
import datetime
import logging
from typing import Dict, Any, List

from wayne_market_db import WayneDatabaseEngine, QuantDataPipeline
import screening_engine
from portfolio_engine import PortfolioEngine
import bot_servers

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("WayneBot.MainRunner")


def run_daily_pipeline():
    """每日盤後 16:30 全自動量化流水線"""
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    logger.info(f"=== 啟動 WayneBot 每日盤後 16:30 量化總控流程: {today_str} ===")

    # 1. 執行每日盤後官方增量更新
    logger.info(">>> [階段 1] 執行每日盤後官方增量更新融合...")
    db_engine = WayneDatabaseEngine()
    data_pipeline = QuantDataPipeline(db_engine)
    data_pipeline.daily_1630_incremental_update(today_str)

    # 2. 讀取最新 AI 動態權重，執行籌碼多因子與雙綠脫離起漲海選 (Top 10 精選)
    logger.info(">>> [階段 2] 執行多因子海選評分與雙綠脫離起漲判定 (Top 10)...")
    port_engine = PortfolioEngine()
    current_weights = port_engine.load_weights()
    df_top = screening_engine.ScreeningEngine().run_full_screening(top_n=10, weights=current_weights)
    top_list = df_top.to_dict(orient="records") if len(df_top) > 0 else []
    logger.info(f"海選完成，共計評選出 {len(top_list)} 檔優質標的。")

    # 3. Phase 9: 背景執行模擬自動建倉 (Score >= 85 且依槓鈴策略配置 40%/35%/25%)
    logger.info(">>> [階段 3] Phase 9: 執行高分標的模擬自動建倉 (Score >= 85)...")
    new_entries = port_engine.auto_entry(top_list, total_capital=100000.0, min_score=85.0)

    # 4. Phase 9: 背景執行持倉健康度檢查與出場判定 (7% 停損 / 15% 停利 / 主力大賣)
    logger.info(">>> [階段 4] Phase 9: 執行持倉部位體檢、損益結算與出場判定...")
    checkup_result = port_engine.daily_portfolio_checkup()

    # 5. Phase 9: 績效覆盤與 AI 權重自我校準 (更新 model_weights.json)
    logger.info(">>> [階段 5] Phase 9: 執行歷史勝率評估與 model_weights.json 自我校準...")
    perf_metrics = port_engine.evaluate_performance()
    weight_update = port_engine.self_evolving_loop()

    # 6. 生成 Telegram 純淨盤後海選戰報 (不夾帶持倉洗版，持倉存於選單按鈕中)
    logger.info(">>> [階段 6] 生成 Telegram 純淨盤後視覺化戰報...")
    report_text = screening_engine.format_telegram_report(stock_list=top_list, trade_date=today_str)

    # 發送 Telegram 推播 (已徹底關閉紫色預覽圖)
    tg_chat_id = os.getenv("TG_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    bot_servers.send_telegram_safely(chat_id=tg_chat_id, text=report_text, parse_mode="HTML", reply_markup=bot_servers.PERSISTENT_KEYBOARD)
    logger.info("✅ 純淨盤後總控戰報與常駐選單已成功發送至 Telegram！")


if __name__ == "__main__":
    run_daily_pipeline()
