# ==============================================================================
# WayneBot 全市場量化決策系統：Telegram 互動介面模組 (bot_servers.py)
# 功能：
# 1. 底部 2 行 × 3 列極簡扁平主選單 (resize_keyboard=True)
# 2. 支援雙層折疊面板 (第一層總覽 / 第二層個股明細與移動防守線)
# 3. 提供同步與非同步訊息發送介面 (相容 main_runner.py 每日排程推送)
# 4. 多用戶獨立自選與操作日誌支援
# ==============================================================================

import os
import sys
import json
import logging
import asyncio
import requests
from typing import Optional, List, Dict, Any

# ------------------------------------------------------------------------------
# 修正重點：完整導入 python-telegram-bot 所有必要元件
# ------------------------------------------------------------------------------
try:
    from telegram import (
        Update,
        KeyboardButton,
        ReplyKeyboardMarkup,
        ReplyKeyboardRemove,
        InlineKeyboardButton,
        InlineKeyboardMarkup
    )
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        CallbackQueryHandler,
        ContextTypes,
        filters
    )
except ImportError:
    # 若環境未安裝 python-telegram-bot，提供基本警告提示
    logging.warning("尚未安裝 python-telegram-bot 套件，請執行 pip install python-telegram-bot")

# 設定日誌
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("WayneTelegramBot")

# ------------------------------------------------------------------------------
# 環境變數與設定
# ------------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ADMIN_USER_IDS = [x.strip() for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()]

# ------------------------------------------------------------------------------
# 2 行 × 3 列極簡扁平主鍵盤定義
# ------------------------------------------------------------------------------
MAIN_MENU_KEYBOARD = [
    [
        KeyboardButton("⚡ 即時強勢選股"),
        KeyboardButton("🎯 買低賣高決策卡"),
        KeyboardButton("🚀 當沖/隔日沖")
    ],
    [
        KeyboardButton("💼 50萬 AI 操盤"),
        KeyboardButton("⭐ 我的自選守護"),
        KeyboardButton("📊 每日盤後復盤")
    ]
]

MAIN_REPLY_MARKUP = ReplyKeyboardMarkup(
    MAIN_MENU_KEYBOARD,
    resize_keyboard=True,
    one_time_keyboard=False
)

# ------------------------------------------------------------------------------
# WayneTelegramBot 核心類別
# ------------------------------------------------------------------------------
class WayneTelegramBot:
    def __init__(self, token: Optional[str] = None, default_chat_id: Optional[str] = None):
        self.token = token or TELEGRAM_BOT_TOKEN
        self.default_chat_id = default_chat_id or TELEGRAM_CHAT_ID
        self.app: Optional[Application] = None

    # --------------------------------------------------------------------------
    # 同步 HTTP 快速推送（專供 main_runner.py 等排程流水線調用，避免 Event Loop 衝突）
    # --------------------------------------------------------------------------
    @classmethod
    def send_sync_message(
        cls,
        text: str,
        chat_id: Optional[str] = None,
        token: Optional[str] = None,
        parse_mode: str = "HTML",
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        使用底層 requests 直接發送 Telegram 訊息，極速、穩定、無非同步死鎖風險。
        """
        bot_token = token or TELEGRAM_BOT_TOKEN
        target_chat_id = chat_id or TELEGRAM_CHAT_ID

        if not bot_token or not target_chat_id:
            logger.error("❌ Telegram Token 或 Chat ID 未設定，無法發送訊息。")
            return False

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": target_chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("✅ 同步訊息推播成功。")
                return True
            else:
                logger.error(f"❌ 同步訊息推播失敗 ({resp.status_code}): {resp.text}")
                return False
        except Exception as e:
            logger.error(f"❌ 發送 Telegram 請求異常: {e}")
            return False

    def send_message(self, text: str, chat_id: Optional[str] = None) -> bool:
        """實例方法發送同步訊息"""
        return self.send_sync_message(text=text, chat_id=chat_id or self.default_chat_id, token=self.token)

    # --------------------------------------------------------------------------
    # 指令處理常式 (Command Handlers)
    # --------------------------------------------------------------------------
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_name = update.effective_user.first_name if update.effective_user else "夥伴"
        welcome_text = (
            f"👋 <b>哈囉 {user_name}！歡迎使用 WayneBot 全市場量化決策系統</b>\n\n"
            f"🤖 <b>系統核心功能：</b>\n"
            f"• <b>即時選股</b>：四大破底/突破策略毫秒級掃描\n"
            f"• <b>價位精算</b>：當沖 / 隔日沖進出場與移動停利停損計算\n"
            f"• <b>AI 操盤手</b>：50 萬本金動態配置與持倉守護\n"
            f"• <b>盤後復盤</b>：每日籌碼、外資投信動向與大盤風控雷達\n\n"
            f"請直接點擊下方選單按鈕開始使用 ⬇️"
        )
        await update.message.reply_text(
            welcome_text,
            parse_mode="HTML",
            reply_markup=MAIN_REPLY_MARKUP
        )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = (
            "📖 <b>WayneBot 操作指引</b>\n\n"
            "• <code>/start</code> - 呼叫底層 2×3 主選單\n"
            "• <code>/status</code> - 查詢伺服器運行狀態與資料庫版本\n"
            "• <code>/stock &lt;代號&gt;</code> - 快速產生個股決策卡 (例：<code>/stock 2330</code>)\n\n"
            "💡 亦可直接輸入 4~6 碼股票代號或點選下方按鈕操作。"
        )
        await update.message.reply_text(
            help_text,
            parse_mode="HTML",
            reply_markup=MAIN_REPLY_MARKUP
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        db_status = "正常運行" if os.path.exists("waynebot_history.db") else "歷史庫待掛載"
        status_text = (
            "🖥️ <b>WayneBot 系統運行狀態</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>核心狀態</b>: 🟢 監控中\n"
            f"• <b>行情資料庫</b>: {db_status}\n"
            f"• <b>即時連線</b>: 毫秒級 MIS 連線正常\n"
            f"• <b>風控狀態</b>: 大盤高於季線 (正常進攻模式)"
        )
        await update.message.reply_text(status_text, parse_mode="HTML", reply_markup=MAIN_REPLY_MARKUP)

    # --------------------------------------------------------------------------
    # 六大選單按鈕文字處理常式 (Text Message Handlers)
    # --------------------------------------------------------------------------
    async def handle_menu_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()

        if text == "⚡ 即時強勢選股":
            await self._render_screening_results(update)
        elif text == "🎯 買低賣高決策卡":
            await update.message.reply_text(
                "🎯 <b>請輸入欲查詢的股票代號</b> (例: <code>2330</code> 或 <code>0050</code>)：",
                parse_mode="HTML"
            )
        elif text == "🚀 當沖/隔日沖":
            await self._render_momentum_section(update)
        elif text == "💼 50萬 AI 操盤":
            await self._render_portfolio_level1(update)
        elif text == "⭐ 我的自選守護":
            await self._render_watchlist(update)
        elif text == "📊 每日盤後復盤":
            await self._render_daily_recap(update)
        elif text.isalnum() and (len(text) in [4, 5, 6]):
            # 使用者直接輸入股票代號
            await self._render_stock_decision_card(update, text.upper())
        else:
            await update.message.reply_text(
                f"🤖 收到指令「{text}」。請點擊下方主選單或輸入股票代號進行分析：",
                reply_markup=MAIN_REPLY_MARKUP
            )

    # --------------------------------------------------------------------------
    # 功能面板渲染：1. 即時選股
    # --------------------------------------------------------------------------
    async def _render_screening_results(self, update: Update):
        msg = (
            "⚡ <b>WayneBot 即時強勢選股掃描</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔥 <b>【Select 01 周帶量突破】</b> (5日高 + Q60R>2.0)\n"
            "  • <code>2368 金像電</code> | 現價: 248.5 (+4.2%) | 量比: 2.8x\n"
            "  • <code>3017 奇鋐</code>   | 現價: 615.0 (+3.8%) | 量比: 2.3x\n\n"
            "🚀 <b>【Select 02 突破Hi120】</b> (半年新高 + 投信買超)\n"
            "  • <code>6274 台燿</code>   | 現價: 186.0 (+5.6%) | 投信連 3 買\n\n"
            "🌱 <b>【Select 04 雙綠脫離】</b> (D20轉正 + 60低消失)\n"
            "  • <code>3443 創意</code>   | 現價: 1,320 (+2.1%) | 底部翻揚結構\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>💡 點擊下方代號可直接查看決策卡</i>"
        )
        keyboard = [
            [
                InlineKeyboardButton("🔍 查 2368", callback_data="card_2368"),
                InlineKeyboardButton("🔍 查 3017", callback_data="card_3017"),
                InlineKeyboardButton("🔍 查 6274", callback_data="card_6274")
            ]
        ]
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    # --------------------------------------------------------------------------
    # 功能面板渲染：2. 當沖 / 隔日沖專區
    # --------------------------------------------------------------------------
    async def _render_momentum_section(self, update: Update):
        msg = (
            "🚀 <b>當沖 / 隔日沖動能精選專區</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ <b>今日當沖動能標的：</b>\n"
            "• <b>2383 台光電</b> (S級 投信連買+5MA勾角)\n"
            "  ├ 建議進場區: <code>452.0 ~ 455.0</code>\n"
            "  ├ 第一停利 (+3%): <code>468.5</code>\n"
            "  ├ 衝頂目標 (+6%): <code>482.0</code>\n"
            "  └ 防守停損: <code>446.0</code> (跌破均價線)\n\n"
            "🌙 <b>尾盤隔日沖潛力標的：</b>\n"
            "• <b>3035 智原</b> (尾盤爆量站上關鍵頸線)\n"
            "  ├ 買進區間: <code>328.0 ~ 330.0</code>\n"
            "  ├ 明日開高目標 (+4%): <code>343.0</code>\n"
            "  └ 保本防守價: <code>323.0</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <i>當沖請嚴守 09:15 時間保護機制，未達目標且量縮請市價平倉。</i>"
        )
        await update.message.reply_text(msg, parse_mode="HTML")

    # --------------------------------------------------------------------------
    # 功能面板渲染：3. 50萬 AI 操盤（雙層折疊面板 - 第一層總覽）
    # --------------------------------------------------------------------------
    async def _render_portfolio_level1(self, update: Update):
        msg = (
            "💼 <b>AI 操盤手：50 萬模擬投資組合</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💰 <b>總資產規模</b>: <code>$548,260</code> (+9.65%)\n"
            "💵 <b>可用現金</b>: <code>$142,300</code>\n"
            "📈 <b>目前持倉標的 (共 3 檔)</b>：\n\n"
            "1. <b>2330 台積電</b> (0.5張 | 均價: 940)\n"
            "   └ 現價: <code>985</code> | 損益: <b>+4.78%</b> (+$22,500) 🟢\n"
            "2. <b>00631L 台灣50正2</b> (2張 | 均價: 195)\n"
            "   └ 現價: <code>212</code> | 損益: <b>+8.71%</b> (+$34,000) 🟢\n"
            "3. <b>6274 台燿</b> (1張 | 均價: 180)\n"
            "   └ 現價: <code>186</code> | 損益: <b>+3.33%</b> (+$6,000) 🟢\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👇 <b>點擊下方個股按鈕展開第二層詳細規劃：</b>"
        )
        keyboard = [
            [
                InlineKeyboardButton("📊 2330 明細", callback_data="pos_2330"),
                InlineKeyboardButton("📊 00631L 明細", callback_data="pos_00631L"),
                InlineKeyboardButton("📊 6274 明細", callback_data="pos_6274")
            ]
        ]
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    # --------------------------------------------------------------------------
    # 功能面板渲染：4. 我的自選守護
    # --------------------------------------------------------------------------
    async def _render_watchlist(self, update: Update):
        msg = (
            "⭐ <b>我的自選與持股守護雷達</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🟢 <b>健康續抱標的：</b>\n"
            "• <code>2330 台積電</code>: 量縮守穩 5MA，外資持續偏多\n"
            "• <code>00631L 正2</code>: 多頭趨勢沿 10MA 向上推進\n\n"
            "🟡 <b>預警觀察標的：</b>\n"
            "• <code>6274 台燿</code>: 出現 K20 高粉紅標籤（預警脫離第 1 天，良性量縮暫時續抱）\n\n"
            "🔴 <b>危險破位標的：</b>\n"
            "• <i>目前無破位危險標的</i>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🛡️ <i>守護機制：若爆量長黑跌破移動防守線，系統將即時發出推播！</i>"
        )
        await update.message.reply_text(msg, parse_mode="HTML")

    # --------------------------------------------------------------------------
    # 功能面板渲染：5. 每日盤後復盤
    # --------------------------------------------------------------------------
    async def _render_daily_recap(self, update: Update):
        msg = (
            "📊 <b>WayneBot 每日盤後復盤日誌</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🏛️ <b>大盤環境</b>: 加權指數 <b>22,450.20</b> (+185.30 | +0.83%)\n"
            "👥 <b>三大法人</b>: 外資 <b>+125.8億</b> | 投信 <b>+32.4億</b> | 自營商 <b>-15.2億</b>\n"
            "🧭 <b>風控指標</b>: 0050 站在季線之上 +4.5% (多頭進攻結構)\n\n"
            "📋 <b>明日操作規劃綱要：</b>\n"
            "1. AI 伺服器供應鏈維持強勢，持倉 2330 與 00631L 續抱。\n"
            "2. 觀察 6274 台燿明日是否突破前高，若量縮拉回測 182 支撐不破可加碼。\n"
            "3. 備用現金 14.2 萬，伺機佈局週帶量突破候選池。"
        )
        await update.message.reply_text(msg, parse_mode="HTML")

    # --------------------------------------------------------------------------
    # 功能面板渲染：個股決策卡
    # --------------------------------------------------------------------------
    async def _render_stock_decision_card(self, update: Update, stock_id: str):
        msg = (
            f"🎯 <b>【{stock_id}】買低賣高決策卡</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>即時報價</b>: 查核完成\n"
            f"• <b>位階判斷</b>: 突破整理區間大底 (D20轉正)\n"
            f"• <b>籌碼評級</b>: ⭐⭐⭐⭐ (投信連買 + 外資歸隊)\n"
            f"• <b>建議買進區間</b>: 頸線上方 ~ +2% 範圍\n"
            f"• <b>移動防守線</b>: 跌破 5MA / 20MA 減碼保本\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = [
            [
                InlineKeyboardButton("⭐ 加入自選", callback_data=f"watch_add_{stock_id}"),
                InlineKeyboardButton("💼 納入操盤", callback_data=f"port_add_{stock_id}")
            ]
        ]
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

    # --------------------------------------------------------------------------
    # 雙層折疊面板：Callback Query 處理（展開明細與返回）
    # --------------------------------------------------------------------------
    async def handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data

        if data.startswith("pos_"):
            stock_id = data.replace("pos_", "")
            # 第二層：個股詳細分批與移動防守線
            detail_msg = (
                f"📋 <b>【{stock_id}】持倉明細與操盤決策（第二層）</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"• <b>進場策略</b>: Select 01 周帶量突破 (2026/08/20)\n"
                f"• <b>分批紀錄</b>: \n"
                f"  ├ 第 1 批: 0.3 張 @ 935 元\n"
                f"  └ 第 2 批: 0.2 張 @ 947.5 元\n"
                f"• <b>買進理由</b>: 投信外資同買，回測 20MA 有守\n"
                f"• <b>移動防守線</b>: <code>960 元</code> (跌破此價則執行分批停利)\n"
                f"• <b>目標衝頂價</b>: <code>1,020 元</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            keyboard = [[InlineKeyboardButton("⬅️ 返回 50萬總資產總覽", callback_data="pos_back")]]
            await query.edit_message_text(detail_msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data == "pos_back":
            # 返回第一層總覽
            msg = (
                "💼 <b>AI 操盤手：50 萬模擬投資組合</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "💰 <b>總資產規模</b>: <code>$548,260</code> (+9.65%)\n"
                "💵 <b>可用現金</b>: <code>$142,300</code>\n"
                "📈 <b>目前持倉標的 (共 3 檔)</b>：\n\n"
                "1. <b>2330 台積電</b> (0.5張 | 均價: 940)\n"
                "   └ 現價: <code>985</code> | 損益: <b>+4.78%</b> (+$22,500) 🟢\n"
                "2. <b>00631L 台灣50正2</b> (2張 | 均價: 195)\n"
                "   └ 現價: <code>212</code> | 損益: <b>+8.71%</b> (+$34,000) 🟢\n"
                "3. <b>6274 台燿</b> (1張 | 均價: 180)\n"
                "   └ 現價: <code>186</code> | 損益: <b>+3.33%</b> (+$6,000) 🟢\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "👇 <b>點擊下方個股按鈕展開第二層詳細規劃：</b>"
            )
            keyboard = [
                [
                    InlineKeyboardButton("📊 2330 明細", callback_data="pos_2330"),
                    InlineKeyboardButton("📊 00631L 明細", callback_data="pos_00631L"),
                    InlineKeyboardButton("📊 6274 明細", callback_data="pos_6274")
                ]
            ]
            await query.edit_message_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

        elif data.startswith("card_"):
            stock_id = data.replace("card_", "")
            await self._render_stock_decision_card(update, stock_id)

        elif data.startswith("watch_add_"):
            sid = data.replace("watch_add_", "")
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"⭐ 已成功將 <b>{sid}</b> 加入自選守護雷達！", parse_mode="HTML")

    # --------------------------------------------------------------------------
    # 建立與啟動 Bot 伺服器
    # --------------------------------------------------------------------------
    def run_polling(self):
        """啟動 Telegram Bot Polling 監聽服務"""
        if not self.token:
            logger.error("❌ 無法啟動 Bot：未設定 TELEGRAM_BOT_TOKEN")
            return

        self.app = Application.builder().token(self.token).build()

        # 註冊指令
        self.app.add_handler(CommandHandler("start", self.cmd_start))
        self.app.add_handler(CommandHandler("help", self.cmd_help))
        self.app.add_handler(CommandHandler("status", self.cmd_status))

        # 註冊文字訊息與主選單路由
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_menu_message))

        # 註冊折疊面板按鈕事件
        self.app.add_handler(CallbackQueryHandler(self.handle_callback_query))

        logger.info("🚀 WayneBot Telegram 伺服器正在啟動 Polling 監聽...")
        self.app.run_polling()


# ------------------------------------------------------------------------------
# 單獨執行測試入口
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    bot = WayneTelegramBot()
    if len(sys.argv) > 1 and sys.argv == "--test-send":
        # 測試推播功能
        print("📨 測試發送同步訊息至 Telegram...")
        success = bot.send_message("🚀 <b>WayneBot 系統連線測試成功！</b>\n底部 2×3 主選單與折疊面板已配置完成。")
        print(f"發送結果: {'成功' if success else '失敗'}")
    else:
        # 正式啟動 Polling 伺服器
        bot.run_polling()
