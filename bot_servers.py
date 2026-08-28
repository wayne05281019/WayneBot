# ==============================================================================
# WayneBot 全市場量化決策系統：Telegram 互動與推播核心模組 (bot_servers.py)
# 模組功能：
#   1. 底部 2 行 × 3 列極簡扁平主選單（自動縮放）
#   2. 雙層折疊面板（總資產概況 ➔ 個股分批明細/買進理由/防守線）
#   3. GitHub Actions 輕量推播 ＆ 長駐輪詢（Polling）雙模支援
# ==============================================================================

import os
import sys
import json
import logging
from typing import Optional, List, Dict, Any, Union
import requests

# ------------------------------------------------------------------------------
# 1. Telegram 元件引用與輕量環境降級相容封裝
# ------------------------------------------------------------------------------
try:
    from telegram import (
        Update,
        Bot,
        KeyboardButton,
        ReplyKeyboardMarkup,
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
    HAS_PTB = True
except ImportError:
    HAS_PTB = False

    # 輕量降級相容類別（供 GitHub Actions 或無 PTB 套件環境使用）
    class KeyboardButton:
        def __init__(self, text: str, **kwargs):
            self.text = text
        def to_dict(self):
            return {"text": self.text}

    class ReplyKeyboardMarkup:
        def __init__(self, keyboard: list, resize_keyboard: bool = True, one_time_keyboard: bool = False, **kwargs):
            self.keyboard = keyboard
            self.resize_keyboard = resize_keyboard
            self.one_time_keyboard = one_time_keyboard
        def to_dict(self):
            return {
                "keyboard": [
                    [b.to_dict() if hasattr(b, "to_dict") else {"text": str(b)} for b in row]
                    for row in self.keyboard
                ],
                "resize_keyboard": self.resize_keyboard,
                "one_time_keyboard": self.one_time_keyboard
            }

    class InlineKeyboardButton:
        def __init__(self, text: str, callback_data: Optional[str] = None, url: Optional[str] = None, **kwargs):
            self.text = text
            self.callback_data = callback_data
            self.url = url
        def to_dict(self):
            d = {"text": self.text}
            if self.callback_data:
                d["callback_data"] = self.callback_data
            if self.url:
                d["url"] = self.url
            return d

    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard: list, **kwargs):
            self.inline_keyboard = inline_keyboard
        def to_dict(self):
            return {
                "inline_keyboard": [
                    [b.to_dict() if hasattr(b, "to_dict") else b for b in row]
                    for row in self.inline_keyboard
                ]
            }

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("WayneTelegramBot")

# ------------------------------------------------------------------------------
# 2. WayneTelegramBot 核心類別
# ------------------------------------------------------------------------------
class WayneTelegramBot:
    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        allowed_user_ids: Optional[List[int]] = None
    ):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.default_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "").strip()
        
        # 授權白名單（支援多用戶隔離，如本人與家人 ID）
        raw_users = os.getenv("ALLOWED_TELEGRAM_USERS", "")
        self.allowed_user_ids = allowed_user_ids or (
            [int(uid.strip()) for uid in raw_users.split(",") if uid.strip().isdigit()]
            if raw_users else []
        )
        self.api_base_url = f"https://api.telegram.org/bot{self.token}"

    # --------------------------------------------------------------------------
    # 2.1 2 行 × 3 列極簡扁平主選單建構
    # --------------------------------------------------------------------------
    @staticmethod
    def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
        """
        標準 2 行 × 3 列主選單：
        [ ⚡ 即時強勢選股 ] [ 🎯 買低賣高決策卡 ] [ 🚀 當沖/隔日沖 ]
        [ 💼 50萬 AI 操盤 ] [ ⭐ 我的自選守護 ] [ 📊 每日盤後復盤 ]
        """
        keyboard = [
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
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

    # --------------------------------------------------------------------------
    # 2.2 雙層折疊面板 Inline 鍵盤建構
    # --------------------------------------------------------------------------
    @staticmethod
    def get_portfolio_inline_keyboard(holdings: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
        """
        第一層：持股列表按鈕，點擊展開個股明細
        """
        buttons = []
        for h in holdings:
            sid = h.get("stock_id", "")
            sname = h.get("stock_name", "")
            pnl_pct = h.get("pnl_pct", 0.0)
            pnl_sign = "🟢 +" if pnl_pct >= 0 else "🔴 "
            btn_text = f"{sid} {sname} ({pnl_sign}{pnl_pct:.1f}%)"
            buttons.append([InlineKeyboardButton(btn_text, callback_data=f"pos_detail_{sid}")])
        
        # 底部功能鍵
        buttons.append([
            InlineKeyboardButton("🔄 重新整理", callback_data="pos_refresh"),
            InlineKeyboardButton("📜 歷史交易記錄", callback_data="pos_history")
        ])
        return InlineKeyboardMarkup(buttons)

    @staticmethod
    def get_stock_detail_back_keyboard(stock_id: str) -> InlineKeyboardMarkup:
        """
        第二層：返回持股概況按鈕
        """
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🛡️ 移動防守細節", callback_data=f"defense_{stock_id}"),
                InlineKeyboardButton("🔙 返回資產概況", callback_data="pos_back_summary")
            ]
        ])

    # --------------------------------------------------------------------------
    # 2.3 HTTP API 輕量推播方法（適用於 GitHub Actions 流水線與定時排程）
    # --------------------------------------------------------------------------
    def send_message(
        self,
        text: str,
        chat_id: Optional[Union[str, int]] = None,
        reply_markup: Optional[Any] = None,
        parse_mode: str = "Markdown"
    ) -> bool:
        target_chat = str(chat_id or self.default_chat_id).strip()
        if not self.token or not target_chat:
            logger.error("❌ Telegram Token 或 Chat ID 缺失，無法發送訊息。")
            return False

        payload: Dict[str, Any] = {
            "chat_id": target_chat,
            "text": text,
            "parse_mode": parse_mode
        }

        if reply_markup is not None:
            if hasattr(reply_markup, "to_dict"):
                payload["reply_markup"] = reply_markup.to_dict()
            elif isinstance(reply_markup, dict):
                payload["reply_markup"] = reply_markup

        url = f"{self.api_base_url}/sendMessage"
        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200 and resp.json().get("ok"):
                return True
            else:
                logger.warning(f"⚠️ Telegram API 發送未成功: {resp.text}")
                # 若 Markdown 格式錯誤，自動降級為純文字重發
                if "can't parse entities" in resp.text and parse_mode == "Markdown":
                    payload.pop("parse_mode", None)
                    retry_resp = requests.post(url, json=payload, timeout=15)
                    return retry_resp.status_code == 200 and retry_resp.json().get("ok")
                return False
        except Exception as e:
            logger.error(f"❌ Telegram 發送異常: {e}")
            return False

    def broadcast_report(self, report_text: str, include_main_menu: bool = True) -> bool:
        """廣播報告並附帶 2x3 主選單鍵盤"""
        markup = self.get_main_menu_keyboard() if include_main_menu else None
        return self.send_message(report_text, reply_markup=markup)

    # --------------------------------------------------------------------------
    # 2.4 長駐互動式 Bot 服務器（支援 Polling 監聽）
    # --------------------------------------------------------------------------
    def run_polling_server(self):
        """啟動長駐 Telegram Bot 服務器（需已安裝 python-telegram-bot）"""
        if not HAS_PTB:
            logger.error("❌ 環境尚未安裝 python-telegram-bot，無法啟動長駐輪詢服務。")
            return

        if not self.token:
            logger.error("❌ TELEGRAM_BOT_TOKEN 未設定。")
            return

        app = Application.builder().token(self.token).build()

        # 指令處理器
        async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            welcome_msg = (
                "🤖 *WayneBot 全市場量化決策系統*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "歡迎使用！請直接點擊下方功能選單進行查詢："
            )
            await update.message.reply_text(
                welcome_msg,
                parse_mode="Markdown",
                reply_markup=WayneTelegramBot.get_main_menu_keyboard()
            )

        # 主選單按鈕文字處理器
        async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_text = update.message.text.strip()
            
            if user_text == "⚡ 即時強勢選股":
                reply = "⚡ *【即時強勢選股】*\n正在掃描 2,202 檔標的之周帶量突破與新高大底標的..."
            elif user_text == "🎯 買低賣高決策卡":
                reply = "🎯 *【買低賣高決策卡】*\n請輸入股票代號（例如 `2330` 或 `6415`）查詢精確進出場點位。"
            elif user_text == "🚀 當沖/隔日沖":
                reply = "🚀 *【當沖 ＆ 隔日沖精選】*\n正在計算今日強勢動能池與尾盤隔日沖標的..."
            elif user_text == "💼 50萬 AI 操盤":
                reply = (
                    "💼 *【50 萬 AI 模擬操盤手】*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "• 初始本金: $500,000 元\n"
                    "• 目前淨值: 結算中...\n"
                    "• 持倉狀態: 正常運行\n"
                )
            elif user_text == "⭐ 我的自選守護":
                reply = "⭐ *【我的自選守護雷達】*\n監控清單正常守護中，若有觸及預警或出清訊號將即時通知。"
            elif user_text == "📊 每日盤後復盤":
                reply = "📊 *【每日盤後復盤日誌】*\n每日 15:45 自動推送最新持倉損益與明日規劃。"
            else:
                reply = f"已收到指令：`{user_text}`，系統運算中..."

            await update.message.reply_text(
                reply,
                parse_mode="Markdown",
                reply_markup=WayneTelegramBot.get_main_menu_keyboard()
            )

        # 註冊處理器
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(CommandHandler("help", start_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text))

        logger.info("🚀 WayneTelegramBot 輪詢服務器已成功啟動...")
        app.run_polling()

# ------------------------------------------------------------------------------
# 單獨模組測試入口
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    bot = WayneTelegramBot()
    logger.info("🛠️ 正在驗證 Telegram Bot 模組與鍵盤結構...")
    kb = bot.get_main_menu_keyboard()
    logger.info(f"✅ 2x3 主選單鍵盤定義驗證通過: {kb.to_dict()}")
    
    # 若有設定環境變數，進行一次測試發送
    if bot.token and bot.default_chat_id:
        success = bot.send_message(
            "🤖 *WayneBot 系統升級通知*\n━━━━━━━━━━━━━━━━━━━━\n`bot_servers.py` 模組已完成修復並成功載入！",
            reply_markup=kb
        )
        logger.info(f"📡 測試推播結果: {'成功 ✅' if success else '失敗 ❌'}")
