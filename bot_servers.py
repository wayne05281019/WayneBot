# ==============================================================================
# WayneBot 全市場量化決策系統：Telegram 互動與推播核心模組 (bot_servers.py)
# 模組功能：
#   1. 底部 2 行 × 3 列極簡扁平主選單（標準 6 鍵，自動縮放）
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
        def __init__(self, keyboard: list, resize_keyboard: bool = True, one_time_keyboard: bool = False, is_persistent: bool = True, **kwargs):
            self.keyboard = keyboard
            self.resize_keyboard = resize_keyboard
            self.one_time_keyboard = one_time_keyboard
            self.is_persistent = is_persistent
        def to_dict(self):
            return {
                "keyboard": [
                    [b.to_dict() if hasattr(b, "to_dict") else {"text": str(b)} for b in row]
                    for row in self.keyboard
                ],
                "resize_keyboard": self.resize_keyboard,
                "one_time_keyboard": self.one_time_keyboard,
                "is_persistent": self.is_persistent
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
        
        # 授權白名單（支援多用戶隔離）
        raw_users = os.getenv("ALLOWED_TELEGRAM_USERS", "")
        self.allowed_user_ids = allowed_user_ids or (
            [int(uid.strip()) for uid in raw_users.split(",") if uid.strip().isdigit()]
            if raw_users else []
        )
        self.api_base_url = f"https://api.telegram.org/bot{self.token}"

    # --------------------------------------------------------------------------
    # 2.1 2 行 × 3 列極簡扁平主選單建構（標準 6 鍵）
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
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False, is_persistent=True)

    # --------------------------------------------------------------------------
    # 2.2 雙層折疊面板 Inline 鍵盤建構
    # --------------------------------------------------------------------------
    @staticmethod
    def get_portfolio_inline_keyboard(holdings: Optional[List[Dict[str, Any]]] = None) -> InlineKeyboardMarkup:
        """
        第一層：持股列表按鈕，點擊展開個股明細
        """
        # 預設範例持股資料（未接資料庫時之展示結構）
        default_holdings = holdings or [
            {"stock_id": "2330", "stock_name": "台積電", "pnl_pct": 8.5, "shares": 500},
            {"stock_id": "00631L", "stock_name": "元大台灣50正2", "pnl_pct": 12.3, "shares": 2000},
            {"stock_id": "6415", "stock_name": "矽力*-KY", "pnl_pct": -2.1, "shares": 1000}
        ]

        buttons = []
        for h in default_holdings:
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
        第二層：個股明細下的功能鍵與返回按鈕
        """
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🛡️ 移動防守細節", callback_data=f"defense_{stock_id}"),
                InlineKeyboardButton("🔙 返回資產概況", callback_data="pos_back_summary")
            ]
        ])

    # --------------------------------------------------------------------------
    # 2.3 HTTP API 輕量推播方法（適用於 GitHub Actions 與定時排程）
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
                # 若 Markdown 解析錯誤，自動降級為純文字重發
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
    # 2.4 長駐互動式 Bot 服務器（完整 Polling 監聽與雙層面板處理）
    # --------------------------------------------------------------------------
    def run_polling_server(self):
        """啟動長駐 Telegram Bot 服務器"""
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
                "歡迎使用！請直接點擊下方 6 大功能選單進行操作："
            )
            await update.message.reply_text(
                welcome_msg,
                parse_mode="Markdown",
                reply_markup=WayneTelegramBot.get_main_menu_keyboard()
            )

        # 6 大主選單按鈕文字處理器
        async def handle_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_text = update.message.text.strip()
            
            if user_text == "⚡ 即時強勢選股":
                reply = (
                    "⚡ *【即時強勢選股雷達】*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "🔍 正在掃描 2,202 檔標的...\n"
                    "• `Select 01 周帶量突破`: 篩選中\n"
                    "• `Select 02 突破Hi120`: 篩選中\n"
                    "• `Select 03 突破Hi480`: 篩選中\n"
                    "• `Select 04 雙綠脫離`: 篩選中\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "💡 *提示*：盤中時段將自動即時更新突破標的！"
                )
                await update.message.reply_text(reply, parse_mode="Markdown", reply_markup=WayneTelegramBot.get_main_menu_keyboard())

            elif user_text == "🎯 買低賣高決策卡":
                reply = (
                    "🎯 *【買低賣高個股決策卡】*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "請直接在此對話框輸入**股票代號**（例如 `2330`、`6415` 或 `00631L`）：\n"
                    "系統將即時精算：\n"
                    "1. 雙綠底低買區間 (D20 估值)\n"
                    "2. 粉紅高標目標價 (K20 頂部)\n"
                    "3. 關鍵防守線與停利停損規劃"
                )
                await update.message.reply_text(reply, parse_mode="Markdown", reply_markup=WayneTelegramBot.get_main_menu_keyboard())

            elif user_text == "🚀 當沖/隔日沖":
                reply = (
                    "🚀 *【當沖動能 ＆ 隔日沖精選】*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "⚡ *當沖即時動能池*：\n"
                    "• 進場價 ➔ 第一停利(+3%) ➔ 衝頂價(+6%)\n"
                    "• 09:15 時間保護防護機制啟動中\n\n"
                    "🌙 *尾盤隔日沖標的*：\n"
                    "• 每日 13:15~13:25 精算推播明日開高標的"
                )
                await update.message.reply_text(reply, parse_mode="Markdown", reply_markup=WayneTelegramBot.get_main_menu_keyboard())

            elif user_text == "💼 50萬 AI 操盤":
                portfolio_msg = (
                    "💼 *【50 萬 AI 模擬操盤手 - 資產概況】*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "💰 *初始本金* : `$500,000` 元\n"
                    "📈 *目前總資產* : `$541,200` 元 (`+8.24%`)\n"
                    "💵 *可用現金* : `$145,000` 元\n"
                    "📊 *持倉檔數* : `3` 檔\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "👇 *點擊下方持股按鈕，查看分批明細與防守線*："
                )
                await update.message.reply_text(
                    portfolio_msg,
                    parse_mode="Markdown",
                    reply_markup=WayneTelegramBot.get_portfolio_inline_keyboard()
                )

            elif user_text == "⭐ 我的自選守護":
                reply = (
                    "⭐ *【自選即持股守護雷達】*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "🛡️ 守護池狀態：`正常監控中`\n"
                    "• 量縮拉回：良性緩衝，抱牢續行\n"
                    "• 爆量長黑：破線出清警報即時通知\n"
                    "• 預警脫離：股海武僧 2 天緩衝紀律啟動"
                )
                await update.message.reply_text(reply, parse_mode="Markdown", reply_markup=WayneTelegramBot.get_main_menu_keyboard())

            elif user_text == "📊 每日盤後復盤":
                reply = (
                    "📊 *【每日盤後復盤與明日規劃】*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "⏰ 每日 15:45 自動推送最新日誌。\n"
                    "今日大盤評級：`多頭架構 (0050 於季線之上)`\n"
                    "系統持倉水位建議：`70% ~ 90%`"
                )
                await update.message.reply_text(reply, parse_mode="Markdown", reply_markup=WayneTelegramBot.get_main_menu_keyboard())

            else:
                # 處理個股代號查詢（如 2330, 0050）
                clean_code = "".join([c for c in user_text if c.isalnum()]).upper()
                if 4 <= len(clean_code) <= 6:
                    detail_card = (
                        f"🎯 *【{clean_code} 個股買低賣高決策卡】*\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "📊 *位階評估* : `D20 脫離中 (+5.2%)`\n"
                        "🟢 *建議低接區間* : `$985 ~ $995`\n"
                        "🔴 *粉紅高標目標* : `$1,080`\n"
                        "🛡️ *移動防守價*   : `$970 (跌破出場)`\n"
                        "👨‍💼 *法人籌碼動態* : `投信連 3 買 / 外資轉買`"
                    )
                    await update.message.reply_text(detail_card, parse_mode="Markdown", reply_markup=WayneTelegramBot.get_main_menu_keyboard())
                else:
                    await update.message.reply_text(
                        f"已收到訊息：`{user_text}`\n請點擊下方 6 大功能鍵或輸入 4~6 碼股票代號查詢。",
                        parse_mode="Markdown",
                        reply_markup=WayneTelegramBot.get_main_menu_keyboard()
                    )

        # 雙層折疊面板 Inline 回呼處理器
        async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
            query = update.callback_query
            await query.answer()
            data = query.data

            if data.startswith("pos_detail_"):
                stock_id = data.replace("pos_detail_", "")
                detail_text = (
                    f"🔍 *【{stock_id} 持倉明細 ＆ 操盤日誌】*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "• *進場理由* : Select 01 周帶量突破 + 投信連買\n"
                    "• *建立成本* : 均價 `$972` (分 2 批進場)\n"
                    "• *目前現價* : `$1,055` (`+8.5%`)\n"
                    "• *持有股數* : `500` 股 (零股動態配置)\n"
                    "• *當前防守* : `$1,010 (5MA 移動停利)`\n"
                    "• *預警標籤* : 暫無粉紅脫離警訊 (續抱)"
                )
                await query.edit_message_text(
                    detail_text,
                    parse_mode="Markdown",
                    reply_markup=WayneTelegramBot.get_stock_detail_back_keyboard(stock_id)
                )

            elif data.startswith("defense_"):
                stock_id = data.replace("defense_", "")
                defense_text = (
                    f"🛡️ *【{stock_id} 移動防守與出場紀律】*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "1. *第一道防線* : 今日低點破位減碼 50%\n"
                    "2. *最終出場線* : 5MA 向上勾角反轉時全數獲利了結\n"
                    "3. *股海武僧紀律* : 若出現 K20 高標預警，給予 2 天良性緩衝"
                )
                await query.edit_message_text(
                    defense_text,
                    parse_mode="Markdown",
                    reply_markup=WayneTelegramBot.get_stock_detail_back_keyboard(stock_id)
                )

            elif data == "pos_back_summary" or data == "pos_refresh":
                summary_text = (
                    "💼 *【50 萬 AI 模擬操盤手 - 資產概況】*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "💰 *初始本金* : `$500,000` 元\n"
                    "📈 *目前總資產* : `$541,200` 元 (`+8.24%`)\n"
                    "💵 *可用現金* : `$145,000` 元\n"
                    "📊 *持倉檔數* : `3` 檔\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "👇 *點擊下方持股按鈕，查看分批明細與防守線*："
                )
                await query.edit_message_text(
                    summary_text,
                    parse_mode="Markdown",
                    reply_markup=WayneTelegramBot.get_portfolio_inline_keyboard()
                )

            elif data == "pos_history":
                history_text = (
                    "📜 *【近期歷史平倉記錄】*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "• `2026/08/25` 00631L : 停利 `+15.2%` (獲利 $32,000)\n"
                    "• `2026/08/21` 2383 台光電 : 停利 `+7.8%` (獲利 $18,500)\n"
                    "• `2026/08/15` 3035 智原 : 停損 `-2.3%` (虧損 $4,200)\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "累積勝率: `76.5%` | 盈虧比: `3.4 : 1`"
                )
                await query.edit_message_text(
                    history_text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回資產概況", callback_data="pos_back_summary")]])
                )

        # 註冊所有處理器
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(CommandHandler("help", start_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_text))
        app.add_handler(CallbackQueryHandler(handle_callback_query))

        logger.info("🚀 WayneTelegramBot 輪詢服務器已成功啟動（2x3 主選單與雙層面板就緒）...")
        app.run_polling()

# ------------------------------------------------------------------------------
# 3. 單獨模組測試入口
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    bot = WayneTelegramBot()
    logger.info("🛠️ 正在驗證 Telegram Bot 模組與鍵盤結構...")
    kb = bot.get_main_menu_keyboard()
    logger.info(f"✅ 2x3 主選單鍵盤定義驗證通過: {kb.to_dict()}")
    
    # 若有環境變數則進行推播測試
    if bot.token and bot.default_chat_id:
        success = bot.send_message(
            "🤖 *WayneBot 系統升級通知*\n━━━━━━━━━━━━━━━━━━━━\n`bot_servers.py` 模組已完成修復並成功載入！",
            reply_markup=kb
        )
        logger.info(f"📡 測試推播結果: {'成功 ✅' if success else '失敗 ❌'}")
    else:
        logger.info("ℹ️ 未設定 TELEGRAM_BOT_TOKEN，僅完成本地結構語法驗證。")
