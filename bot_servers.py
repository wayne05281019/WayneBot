# ==============================================================================
# WayneBot: Telegram 互動面板核心模組 (bot_servers.py)
# 升級亮點：2x3 極簡主選單 + 🌡️ 產業資金溫度計專屬處理器
# ==============================================================================
import os
import json
import logging
from typing import Dict, Any, Optional

try:
    from telegram import ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, Update
    from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
except ImportError:
    # 支援本地無安裝 telegram 套件時的環境相容
    ReplyKeyboardMarkup = Any
    InlineKeyboardMarkup = Any
    InlineKeyboardButton = Any

# 1. 定義標準 2 行 x 3 列 主選單鍵盤
MAIN_KEYBOARD = [
    ["🚀 CaryBot 選股", "💼 AI 模擬持倉", "⚡ 當沖動能專區"],
    ["🌙 隔日沖精選", "🎯 自選守護雷達", "🌡️ 產業資金溫度計"]
]

def get_main_reply_keyboard():
    """取得 2x3 主選單 ReplyKeyboardMarkup 物件"""
    return ReplyKeyboardMarkup(MAIN_KEYBOARD, resize_keyboard=True, one_time_keyboard=False)

# 2. 產業資金溫度計卡片渲染器
def format_industry_thermometer_card(capital_data: Optional[Dict[str, Any]] = None) -> str:
    """
    格式化產業資金溫度計卡片 (支援即時數據與容錯預設)
    """
    if not capital_data:
        # 當資料庫尚在更新時的優雅預設防呆回覆
        return (
            "🌡️ <b>【WayneBot 台股產業資金溫度計】</b>\n"
            "📅 <i>狀態：歷史資料庫建置 / 每日數據同步中...</i>\n\n"
            "📊 <b>【市場資金概況】</b>\n"
            "• 核心聚焦：電子半導體、AI 伺服器與散熱零組件\n"
            "• 避險防守：高股息 ETF 與低波動族群\n\n"
            "💡 <i>提示：歷史數據庫建庫完成後，將自動解鎖 29 大類股每日成交佔比與資金移轉雷達！</i>"
        )

    # 標準數據格式化
    date_str = capital_data.get("date", "今日")
    market_vol = capital_data.get("market_turnover_billion", "4,200")
    elec_share = capital_data.get("elec_share_pct", "72.5")
    fin_share = capital_data.get("fin_share_pct", "8.2")
    trad_share = capital_data.get("trad_share_pct", "19.3")
    
    top_inflow = capital_data.get("top_inflow", [
        ("半導體", "38.5%", "+5.2%", "2330 台積電, 2454 聯發科"),
        ("電腦週邊/散熱", "14.2%", "+2.1%", "3017 奇鋐, 3324 雙鴻")
    ])
    
    top_outflow = capital_data.get("top_outflow", [
        ("航運族群", "2.1%", "-3.5%", "跌破 5MA 短線轉弱"),
        ("塑膠鋼鐵", "1.8%", "-1.2%", "量能萎縮破底")
    ])

    msg = [
        "🌡️ <b>【WayneBot 台股產業資金溫度計】</b>",
        f"📅 日期：<code>{date_str}</code> | 預估量能：<b>{market_vol} 億</b>\n",
        "📊 <b>【大盤資金三大板塊佔比】</b>",
        f"• 電子類股：<b>{elec_share}%</b> (🔥 資金高度集中)",
        f"• 金融類股：<b>{fin_share}%</b> (⚖️ 穩盤防守)",
        f"• 傳產類股：<b>{trad_share}%</b> (❄️ 資金流出)\n",
        "🔄 <b>【資金板塊移轉雷達】</b>",
        f"➔ 資金自 <b>{top_outflow[0][0]} ({top_outflow[0]})</b> 流出",
        f"➔ 湧入 <b>{top_inflow[0][0]} ({top_inflow[0]})</b> 🚀\n",
        "🔥 <b>【今日最強吸金主流 TOP 2】</b>"
    ]

    for rank, (ind_name, share, diff, leaders) in enumerate(top_inflow, 1):
        msg.append(f"{rank}. <b>{ind_name}</b> (佔比 {share} | 變動 {diff})")
        msg.append(f"   • 領軍標的：<code>{leaders}</code>")

    msg.append("\n❄️ <b>【資金撤退流出族群】</b>")
    for ind_name, share, diff, note in top_outflow:
        msg.append(f"• <b>{ind_name}</b> (佔比 {share} | {diff}) ➔ <i>{note}</i>")

    msg.append("\n🎯 <b>【AI 當沖/波段策略指引】</b>")
    msg.append("順風操作：聚焦「半導體/散熱」動能股；嚴禁逆勢承接失血弱勢股。")

    return "\n".join(msg)

# 3. 產業溫度計專屬 Inline 按鈕（第二層展開）
def get_thermometer_inline_keyboard():
    """取得第二層展開詳細資訊的按鈕"""
    keyboard = [
        [
            InlineKeyboardButton("📊 29 大類股完整排行", callback_data="thermo_all_sectors"),
            InlineKeyboardButton("🔥 主力 ETF 抱團成分股", callback_data="thermo_etf_holdings")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)
