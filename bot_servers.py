"""
WayneBot Telegram 操作層
- 選單按鈕
- 打股票代號 → 決策卡 + 高低導航圖 + 籌碼表
- 海選 / 當沖 / 隔日沖 / 持股 / 觀察
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from config import get_charts_dir, get_db_path, get_telegram_config
from wayne_db import init_database, get_user_portfolio, add_to_watchlist, add_to_portfolio
from screening_engine import ScreeningEngine
from portfolio_engine import PortfolioEngine
from cary_navigator import (
    generate_card_with_chart,
    generate_chart,
    generate_decision_card,
    html_escape,
)
from chips import fetch_major_player_html

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        CallbackQueryHandler,
        ContextTypes,
        filters,
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    Update = Any  # type: ignore
    ContextTypes = type("ContextTypes", (), {"DEFAULT_TYPE": Any})  # type: ignore

logger = logging.getLogger(__name__)


def chunk_telegram_text(text: str, limit: int = 3500) -> List[str]:
    if not text:
        return []
    return [text[i : i + limit] for i in range(0, len(text), limit)]


class WayneTelegramBot:
    def __init__(self, token: str = None, chat_id: str = None, db_path: str = None, **kwargs):
        cfg = get_telegram_config()
        self.token = token or cfg.get("token") or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or cfg.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID")
        self.db_path = db_path or get_db_path()
        self.charts_dir = get_charts_dir()
        os.makedirs(self.charts_dir, exist_ok=True)
        init_database(self.db_path)
        self.screener = ScreeningEngine(self.db_path)
        self.portfolio_engine = PortfolioEngine(self.db_path)
        self._pending: Dict[str, str] = {}

    def send_message(self, text: str, chat_id: str = None):
        self._send_html(chat_id or self.chat_id, text)

    def _icon_btn(self, text: str, callback_data: str, mark_key: str = ""):
        kwargs = {}
        if mark_key:
            try:
                from telegram_cat_marks import load_mark_ids

                eid = load_mark_ids().get(mark_key) or ""
                if eid:
                    kwargs["api_kwargs"] = {"icon_custom_emoji_id": eid}
            except Exception:
                pass
        return InlineKeyboardButton(text, callback_data=callback_data, **kwargs)

    def _keyboard(self):
        return InlineKeyboardMarkup(
            [
                [
                    self._icon_btn("海選", "screen", "revenue_cross"),
                    self._icon_btn("當沖", "daytrade", "day_trade"),
                    self._icon_btn("隔日沖", "overnight", "overnight"),
                ],
                [
                    InlineKeyboardButton("💼 持股", callback_data="portfolio"),
                    InlineKeyboardButton("👀 觀察", callback_data="watch"),
                    InlineKeyboardButton("📌 決策卡", callback_data="card"),
                ],
                [
                    InlineKeyboardButton("📊 籌碼", callback_data="chips"),
                    InlineKeyboardButton("📈 營收毛利", callback_data="fund"),
                ],
                [
                    InlineKeyboardButton("➕ 買入紀錄", callback_data="buy"),
                    InlineKeyboardButton("➖ 賣出說明", callback_data="sell"),
                ],
            ]
        )

    def _section_markup(self, part: Dict[str, Any], include_menu: bool = False):
        if include_menu:
            return self._keyboard()
        return None

    def _screening_payload(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        from screening_engine import format_screening_payload

        parts = result.get("payload")
        if parts:
            return parts
        return format_screening_payload(
            result.get("results") or {}, result.get("as_of") or result.get("date") or ""
        )

    async def _reply_screening_payload(self, message, result: Dict[str, Any]):
        parts = self._screening_payload(result)
        if not parts:
            await message.reply_html(
                result.get("message") or self._format_screening_html(result),
                reply_markup=self._keyboard(),
            )
            return
        last = len(parts) - 1
        for i, part in enumerate(parts):
            fid = self._cat_sticker_id(part.get("mark_key") or "")
            if fid:
                try:
                    await message.reply_sticker(sticker=fid)
                except Exception:
                    logger.exception("分類貼紙傳送失敗")
            chunks = chunk_telegram_text(part.get("html") or "", 3500)
            if not chunks:
                continue
            for j, chunk in enumerate(chunks):
                is_last = i == last and j == len(chunks) - 1
                kb = self._section_markup(part, include_menu=is_last)
                await message.reply_html(chunk, reply_markup=kb)
            await asyncio.sleep(0.25)

    def _cat_sticker_id(self, key: str) -> str:
        if not key:
            return ""
        try:
            from telegram_cat_marks import load_sticker_ids

            return load_sticker_ids().get(key) or ""
        except Exception:
            return ""

    def _send_sticker(self, chat_id: str, file_id: str):
        try:
            import requests

            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendSticker",
                data={"chat_id": chat_id, "sticker": file_id},
                timeout=30,
            )
        except Exception as e:
            logger.error("send_sticker: %s", e)

    def _send_html(self, chat_id: str, html: str, extra_keyboard=None, attach_menu: bool = True):
        try:
            import requests

            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": html,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if extra_keyboard:
                payload["reply_markup"] = extra_keyboard.to_dict()
            elif attach_menu:
                payload["reply_markup"] = self._keyboard().to_dict()
            requests.post(url, json=payload, timeout=20)
        except Exception as e:
            logger.error("send_html: %s", e)

    def _send_photo(self, chat_id: str, photo_path: str, caption: str = ""):
        try:
            import requests

            url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"}
                requests.post(url, files=files, data=data, timeout=40)
        except Exception as e:
            logger.error("send_photo: %s", e)

    def send_screening_report(self, result: Dict[str, Any]):
        if not self.token or not self.chat_id:
            return
        import time as _t

        parts = self._screening_payload(result)
        if not parts:
            self._send_html(self.chat_id, result.get("message") or self._format_screening_html(result))
            return
        last = len(parts) - 1
        for i, part in enumerate(parts):
            fid = self._cat_sticker_id(part.get("mark_key") or "")
            if fid:
                self._send_sticker(self.chat_id, fid)
            chunks = chunk_telegram_text(part.get("html") or "", 3500)
            for j, chunk in enumerate(chunks):
                is_last = i == last and j == len(chunks) - 1
                kb = self._section_markup(part, include_menu=is_last)
                self._send_html(
                    self.chat_id,
                    chunk,
                    extra_keyboard=kb,
                    attach_menu=False,
                )
            _t.sleep(0.25)

    def _send_stock_card_by_code(self, chat_id: str, code: str, name: str = ""):
        if not code:
            return
        try:
            html, chart_path = generate_card_with_chart(code, self.db_path, self.charts_dir)
        except Exception:
            html = generate_decision_card(code, self.db_path)
            chart_path = generate_chart(code, name, self.db_path, os.path.join(self.charts_dir, f"{code}.png"))
        self._send_html(chat_id, html)
        if chart_path:
            self._send_photo(chat_id, chart_path, caption=f"{html_escape(code)} {html_escape(name)}")
        extra = fetch_major_player_html(code)
        if extra:
            self._send_html(chat_id, extra)

    def _format_screening_html(self, result: Dict[str, Any]) -> str:
        lines = [
            "<b>WayneBot 盤後報告</b>",
            f"日期：{html_escape(result.get('as_of') or '')}",
            "",
            "<b>營收轉強 × 量價突破</b>",
        ]
        for row in (result.get("revenue_cross") or [])[:10]:
            lines.append(self._fmt_row(row))
        lines.append("")
        lines.append("<b>當沖候選</b>")
        for row in (result.get("daytrade") or [])[:10]:
            lines.append(self._fmt_row(row))
        lines.append("")
        lines.append("<b>隔日沖候選</b>")
        for row in (result.get("overnight") or [])[:10]:
            lines.append(self._fmt_row(row))
        lines.append("")
        lines.append("<b>籌碼預警</b>")
        for row in (result.get("major_alerts") or [])[:10]:
            lines.append(
                f"• {html_escape(row.get('code'))} {html_escape(row.get('name') or '')} {html_escape(row.get('reason') or '')}"
            )
        return "\n".join(lines)

    def _fmt_row(self, row: Dict[str, Any]) -> str:
        return (
            f"• <code>{html_escape(row.get('code'))}</code> {html_escape(row.get('name') or '')} "
            f"{row.get('score', 0)}分  {row.get('close', 0)}"
        )

    async def start_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("已改成下方訊息裡的按鈕，舊的四格鍵盤會收起來。", reply_markup=ReplyKeyboardRemove())
        await update.message.reply_html(
            "WayneBot 已上線。\n"
            "直接打股票代號看決策卡，或按訊息下面的按鈕。",
            reply_markup=self._keyboard(),
        )

    async def screen_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("海選執行中…")
        try:
            result = self.screener.run_full_screening()
            await self._reply_screening_payload(update.message, result)
        except Exception as e:
            logger.exception("海選失敗")
            await update.message.reply_text(f"海選失敗：{e}", reply_markup=self._keyboard())

    async def daytrade_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        rows = self.screener.screen_daytrade()
        html = "<b>當沖候選</b>\n" + "\n".join(self._fmt_row(r) for r in rows[:15])
        await update.message.reply_html(html or "無", reply_markup=self._keyboard())

    async def overnight_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        rows = self.screener.screen_overnight()
        html = "<b>隔日沖候選</b>\n" + "\n".join(self._fmt_row(r) for r in rows[:15])
        await update.message.reply_html(html or "無", reply_markup=self._keyboard())

    async def portfolio_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        holdings = get_user_portfolio(self.db_path, uid)
        if not holdings:
            await update.message.reply_text("持股為空。用 /buy 代號 張數 價格 新增。", reply_markup=self._keyboard())
            return
        html = self.portfolio_engine.format_holdings_html(holdings)
        await update.message.reply_html(html, reply_markup=self._keyboard())

    async def watch_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from wayne_db import get_user_watchlist

        uid = str(update.effective_user.id)
        rows = get_user_watchlist(self.db_path, uid)
        if not rows:
            await update.message.reply_text("觀察清單為空。", reply_markup=self._keyboard())
            return
        lines = ["<b>觀察清單</b>"]
        for r in rows:
            lines.append(f"• {html_escape(r.get('stock_code'))} {html_escape(r.get('stock_name') or '')}")
        await update.message.reply_html("\n".join(lines), reply_markup=self._keyboard())

    async def card_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        if not args:
            await update.message.reply_text("用法：/card 2330")
            return
        await self._reply_card(update, args[0])

    async def chips_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        if not args:
            await update.message.reply_text("用法：/chips 2330")
            return
        extra = fetch_major_player_html(args[0].strip())
        await update.message.reply_html(extra or "查無籌碼", reply_markup=self._keyboard())

    async def fund_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        if not args:
            await update.message.reply_text("用法：/fund 2330")
            return
        from fundamentals import format_fundamentals_html, sync_fundamentals

        code = args[0].strip()
        html = format_fundamentals_html(code, self.db_path)
        if "尚無" in html:
            await update.message.reply_text("尚無快取，正在同步官方月營收／季報…")
            try:
                sync_fundamentals(self.db_path)
            except Exception as e:
                logger.error("fund sync: %s", e)
            html = format_fundamentals_html(code, self.db_path)
        await update.message.reply_html(html, reply_markup=self._keyboard())

    async def buy_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        if len(args) < 3:
            await update.message.reply_text("請輸入：代號 張數 價格\n例如：2330 1 500", reply_markup=self._keyboard())
            return
        uid = str(update.effective_user.id)
        code = args[0]
        shares = float(args[1])
        price = float(args[2])
        add_to_portfolio(self.db_path, uid, code, code, shares, price)
        await update.message.reply_text(f"已記錄買入 {code} {shares}張 @ {price}", reply_markup=self._keyboard())

    async def sell_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("賣出請用持股頁或直接回報。此版先以買入紀錄為主。", reply_markup=self._keyboard())

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (update.message.text or "").strip()
        uid = str(update.effective_user.id)
        if text.lower().lstrip("/") in ("start", "開始", "help", "幫助"):
            self._pending.pop(uid, None)
            await self.start_cmd(update, context)
            return
        pending = self._pending.pop(uid, "")
        if "今日海選" in text or text.endswith("海選"):
            await self.screen_cmd(update, context)
            return
        if "模擬持倉" in text or text == "持股":
            await self.portfolio_cmd(update, context)
            return
        if "自選" in text:
            await self.watch_cmd(update, context)
            return
        if "系統狀態" in text:
            await update.message.reply_html("WayneBot 雲端新版運作中。請用訊息下方按鈕操作。", reply_markup=self._keyboard())
            return
        if pending == "card":
            await self._reply_card(update, text.split()[0])
            return
        if pending == "chips":
            extra = fetch_major_player_html(text.split()[0].strip())
            await update.message.reply_html(extra or "查無籌碼", reply_markup=self._keyboard())
            return
        if pending == "fund":
            from fundamentals import format_fundamentals_html, sync_fundamentals

            code = text.split()[0].strip()
            html = format_fundamentals_html(code, self.db_path)
            if "尚無" in html:
                try:
                    sync_fundamentals(self.db_path)
                except Exception:
                    pass
                html = format_fundamentals_html(code, self.db_path)
            await update.message.reply_html(html, reply_markup=self._keyboard())
            return
        if pending == "buy":
            parts = text.split()
            if len(parts) < 3:
                self._pending[uid] = "buy"
                await update.message.reply_text("請輸入：代號 張數 價格\n例如：2330 1 500", reply_markup=self._keyboard())
                return
            add_to_portfolio(self.db_path, uid, parts[0], parts[0], float(parts[1]), float(parts[2]))
            await update.message.reply_text(
                f"已記錄買入 {parts[0]} {parts[1]}張 @ {parts[2]}", reply_markup=self._keyboard()
            )
            return
        if text.isdigit() and 3 <= len(text) <= 6:
            await self._reply_card(update, text)
            return
        await update.message.reply_text("請打股票代號，或按下方按鈕。", reply_markup=self._keyboard())

    async def _reply_card(self, update: Update, code: str):
        await update.message.reply_text(f"查詢 {code}…")
        html, chart = generate_card_with_chart(code, self.db_path, self.charts_dir)
        await update.message.reply_html(html, reply_markup=self._keyboard())
        if chart:
            try:
                with open(chart, "rb") as f:
                    await update.message.reply_photo(photo=f)
            except Exception:
                pass
        extra = fetch_major_player_html(code)
        if extra:
            await update.message.reply_html(extra)

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        data = q.data or ""
        if data.startswith("cat:") or data.startswith("noop"):
            hints = {
                "revenue_cross": "優先看：營收轉強 × 量價突破",
                "select_01": "Select 01：周帶量突破",
                "select_02": "Select 02：突破半年高",
                "select_03": "Select 03：突破兩年高",
                "select_04": "Select 04：雙綠脫離",
                "day_trade": "當沖：進場 / 停利 / 停損",
                "overnight": "隔日沖：尾盤佈局",
            }
            await q.answer(hints.get(data.split(":", 1)[-1], "分類標記")[:200])
            return
        await q.answer()
        if data == "screen":
            await q.message.reply_text("海選執行中…")
            try:
                result = self.screener.run_full_screening()
                await self._reply_screening_payload(q.message, result)
            except Exception as e:
                logger.exception("海選失敗")
                await q.message.reply_text(f"海選失敗：{e}", reply_markup=self._keyboard())
        elif data == "daytrade":
            rows = self.screener.screen_daytrade()
            html = "<b>當沖候選</b>\n" + "\n".join(self._fmt_row(r) for r in rows[:15])
            await q.message.reply_html(html or "無", reply_markup=self._keyboard())
        elif data == "overnight":
            rows = self.screener.screen_overnight()
            html = "<b>隔日沖候選</b>\n" + "\n".join(self._fmt_row(r) for r in rows[:15])
            await q.message.reply_html(html or "無", reply_markup=self._keyboard())
        elif data == "portfolio":
            uid = str(q.from_user.id)
            holdings = get_user_portfolio(self.db_path, uid)
            html = self.portfolio_engine.format_holdings_html(holdings) if holdings else "持股為空"
            await q.message.reply_html(html, reply_markup=self._keyboard())
        elif data == "watch":
            from wayne_db import get_user_watchlist

            uid = str(q.from_user.id)
            rows = get_user_watchlist(self.db_path, uid)
            lines = ["<b>觀察清單</b>"] + [
                f"• {html_escape(r.get('stock_code'))} {html_escape(r.get('stock_name') or '')}" for r in rows
            ]
            await q.message.reply_html("\n".join(lines), reply_markup=self._keyboard())
        elif data in ("card", "chips", "fund"):
            uid = str(q.from_user.id)
            self._pending[uid] = data
            hints = {
                "card": "請輸入股票代號，例如 2330",
                "chips": "請輸入要查籌碼的代號，例如 2383",
                "fund": "請輸入要查營收／毛利的代號，例如 2330",
            }
            await q.message.reply_text(hints[data], reply_markup=self._keyboard())
        elif data == "buy":
            uid = str(q.from_user.id)
            self._pending[uid] = "buy"
            await q.message.reply_text("請輸入：代號 張數 價格\n例如：2330 1 500", reply_markup=self._keyboard())
        elif data == "sell":
            await q.message.reply_text("賣出請先看持股。此版先以買入紀錄為主。", reply_markup=self._keyboard())

    def run_polling(self):
        if not TELEGRAM_AVAILABLE:
            logger.error("未安裝 python-telegram-bot")
            return
        if not self.token:
            logger.error("缺少 TELEGRAM_BOT_TOKEN")
            return
        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler("start", self.start_cmd))
        app.add_handler(CommandHandler("help", self.start_cmd))
        app.add_handler(CommandHandler("screen", self.screen_cmd))
        app.add_handler(CommandHandler("daytrade", self.daytrade_cmd))
        app.add_handler(CommandHandler("overnight", self.overnight_cmd))
        app.add_handler(CommandHandler("portfolio", self.portfolio_cmd))
        app.add_handler(CommandHandler("watch", self.watch_cmd))
        app.add_handler(CommandHandler("card", self.card_cmd))
        app.add_handler(CommandHandler("chips", self.chips_cmd))
        app.add_handler(CommandHandler("fund", self.fund_cmd))
        app.add_handler(CommandHandler("buy", self.buy_cmd))
        app.add_handler(CommandHandler("sell", self.sell_cmd))
        app.add_handler(CallbackQueryHandler(self.on_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        logger.info("Telegram polling 啟動")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    WayneTelegramBot().run_polling()
