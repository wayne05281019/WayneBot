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
from wayne_db import (
    init_database,
    get_user_portfolio,
    add_to_watchlist,
    add_to_portfolio,
    sell_from_holdings,
    lookup_stocks,
)
from screening_engine import ScreeningEngine
from portfolio_engine import PortfolioEngine
from ai_trader import format_ai_desk_html
from cary_navigator import (
    generate_card_with_chart,
    generate_chart,
    generate_decision_card,
    html_escape,
)
from chips import fetch_major_player_html, generate_chips_image

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

    def _hub_keyboard(self, code: str):
        c = str(code).strip()[:6]
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📌 決策卡", callback_data=f"k:{c}"),
                    InlineKeyboardButton("➕ 觀察", callback_data=f"w:{c}"),
                ],
                [
                    InlineKeyboardButton("📊 籌碼", callback_data=f"h:{c}"),
                    InlineKeyboardButton("📈 營收毛利", callback_data=f"f:{c}"),
                ],
                [InlineKeyboardButton("➕ 記一筆買入", callback_data=f"b:{c}")],
            ]
        )

    def _picks_keyboard(self, picks, include_menu: bool = False):
        rows = []
        for code, name in (picks or [])[:8]:
            c = str(code or "").strip()
            if not c:
                continue
            label = f"{c} {(name or '')}".strip()[:18]
            rows.append(
                [
                    InlineKeyboardButton(f"➕ {label}", callback_data=f"w:{c}"),
                    InlineKeyboardButton("📌決策卡", callback_data=f"k:{c}"),
                ]
            )
        if include_menu:
            rows.extend(self._keyboard().inline_keyboard)
        if not rows:
            return self._keyboard() if include_menu else None
        return InlineKeyboardMarkup(rows)

    def _hits_keyboard(self, hits):
        rows = []
        for h in hits[:8]:
            c = str(h.get("stock_id") or "")
            n = str(h.get("stock_name") or "")
            if not c:
                continue
            label = f"{c} {n}".strip()[:18]
            rows.append(
                [
                    InlineKeyboardButton(f"➕ {label}", callback_data=f"w:{c}"),
                    InlineKeyboardButton("📌決策卡", callback_data=f"k:{c}"),
                    InlineKeyboardButton("記買入", callback_data=f"b:{c}"),
                ]
            )
        return InlineKeyboardMarkup(rows) if rows else self._keyboard()

    def _watch_list_keyboard(self, rows):
        kb = []
        for r in (rows or [])[:8]:
            c = str(r.get("stock_code") or "")
            if not c:
                continue
            kb.append(
                [
                    InlineKeyboardButton(f"📌 {c}", callback_data=f"k:{c}"),
                    InlineKeyboardButton("📊籌碼", callback_data=f"h:{c}"),
                    InlineKeyboardButton("記買入", callback_data=f"b:{c}"),
                ]
            )
        kb.extend(self._keyboard().inline_keyboard)
        return InlineKeyboardMarkup(kb)

    def _portfolio_keyboard(self, holdings):
        kb = []
        for h in (holdings or [])[:8]:
            c = str(h.get("stock_code") or h.get("stock_id") or "")
            if not c:
                continue
            kb.append(
                [
                    InlineKeyboardButton(f"📌 {c}", callback_data=f"k:{c}"),
                    InlineKeyboardButton(f"➖賣出 {c}", callback_data=f"x:{c}"),
                ]
            )
        kb.append([InlineKeyboardButton("🤖 AI 立刻依海選操盤", callback_data="ai_run")])
        kb.extend(self._keyboard().inline_keyboard)
        return InlineKeyboardMarkup(kb)

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
                kb = self._picks_keyboard(part.get("picks") or [], include_menu=is_last)
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
                kb = self._picks_keyboard(part.get("picks") or [], include_menu=is_last)
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
            html, card_img, chart_path = generate_card_with_chart(code, self.db_path, self.charts_dir)
        except Exception:
            html = generate_decision_card(code, self.db_path)
            card_img = ""
            chart_path = generate_chart(code, name, self.db_path, os.path.join(self.charts_dir, f"{code}.png"))
        self._send_html(chat_id, html)
        if card_img:
            self._send_photo(chat_id, card_img, caption=f"{html_escape(code)} 決策卡")
        if chart_path:
            self._send_photo(chat_id, chart_path, caption=f"{html_escape(code)} {html_escape(name)} 高低導航")
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
            "<b>WayneBot 怎麼用（請先選一檔股票）</b>\n"
            "1. 對話框打 <b>南亞</b> 或 <b>2330</b> → 出現 ➕觀察／📌決策卡／記買入\n"
            "2. 海選／當沖／隔日沖 → 股名旁按 <b>➕</b> 加入觀察，按 <b>📌決策卡</b> 直接出卡與導航圖\n"
            "3. <b>觀察</b>＝自選（還沒買也可以加）。空的很正常，用上面兩種方式加入\n"
            "4. <b>持股</b>＝你真實買入的手記，不是觀察。要記買入：選股後按「記一筆買入」，再打 <code>張數 價格</code>\n"
            "5. 決策卡／籌碼／營收毛利：選好股票後按鈕就會出內容，不必再按第二次\n"
            "6. <b>AI 模擬倉</b>在持股頁下方，50 萬本金、盤後依海選紀律買賣；也可按「立刻依海選操盤」",
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
        from screening_engine import _stock_card_html

        rows = self.screener.screen_daytrade()
        cards = [_stock_card_html(r, i + 1) for i, r in enumerate(rows[:12])]
        html = "<b>當沖候選</b>\n" + ("\n".join(cards) if cards else "<i>無</i>")
        picks = [(r.get("code") or r.get("stock_id"), r.get("name") or r.get("stock_name")) for r in rows[:12]]
        await update.message.reply_html(html, reply_markup=self._picks_keyboard(picks, include_menu=True))

    async def overnight_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from screening_engine import _stock_card_html

        rows = self.screener.screen_overnight()
        cards = [_stock_card_html(r, i + 1) for i, r in enumerate(rows[:12])]
        html = "<b>隔日沖候選</b>\n" + ("\n".join(cards) if cards else "<i>無</i>")
        picks = [(r.get("code") or r.get("stock_id"), r.get("name") or r.get("stock_name")) for r in rows[:12]]
        await update.message.reply_html(html, reply_markup=self._picks_keyboard(picks, include_menu=True))

    async def _send_portfolio(self, message, uid: str):
        holdings = get_user_portfolio(self.db_path, uid)
        if holdings:
            mine = self.portfolio_engine.format_holdings_html(holdings)
        else:
            mine = (
                "<b>我的持股（手記）</b>\n"
                "這頁是「你已經買了」的紀錄，空的代表還沒記過買入。\n"
                "做法：打南亞或 2330 → 按「記買入」→ 輸入 <code>1 68.5</code>（張數 價格）。"
            )
        ai = format_ai_desk_html(self.portfolio_engine)
        await message.reply_html(mine + "\n\n" + ai, reply_markup=self._portfolio_keyboard(holdings))

    async def _send_watch(self, message, uid: str):
        from wayne_db import get_user_watchlist

        rows = get_user_watchlist(self.db_path, uid)
        lines = [
            "<b>觀察清單（自選，還沒買也可以）</b>",
            "加入方式：打「南亞」按 ➕　或海選／當沖／隔日沖股名旁的 ➕",
        ]
        if not rows:
            lines.append("<i>目前是空的，這很正常。請先打一檔股票名稱。</i>")
            await message.reply_html("\n".join(lines), reply_markup=self._keyboard())
            return
        for r in rows:
            lines.append(f"• {html_escape(r.get('stock_code'))} {html_escape(r.get('stock_name') or '')}")
        lines.append("\n點下面按鈕可直接開決策卡／籌碼／記買入。")
        await message.reply_html("\n".join(lines), reply_markup=self._watch_list_keyboard(rows))

    async def _prompt_pick(self, message, uid: str, purpose: str):
        from wayne_db import get_user_watchlist

        hints = {
            "card": "決策卡：請先選一檔。打南亞／2330，或點觀察清單。選到就會出卡與圖。",
            "chips": "籌碼：請先選一檔。打名稱或代號，或點下面觀察清單。",
            "fund": "營收毛利：請先選一檔。打名稱或代號，或點下面觀察清單。",
            "buy": "記買入：請先選一檔，或直接打「2330 1 500」（代號 張數 價格）。",
        }
        rows = get_user_watchlist(self.db_path, uid)
        prefix = {"card": "k", "chips": "h", "fund": "f", "buy": "b"}.get(purpose, "k")
        kb = []
        for r in rows[:8]:
            c = str(r.get("stock_code") or "")
            n = str(r.get("stock_name") or "")
            if c:
                kb.append([InlineKeyboardButton(f"{c} {n}".strip()[:22], callback_data=f"{prefix}:{c}")])
        kb.extend(self._keyboard().inline_keyboard)
        self._pending[uid] = purpose
        await message.reply_html(hints[purpose], reply_markup=InlineKeyboardMarkup(kb))

    async def portfolio_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_portfolio(update.message, str(update.effective_user.id))

    async def watch_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._send_watch(update.message, str(update.effective_user.id))

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
        args = context.args or []
        uid = str(update.effective_user.id)
        if len(args) < 3:
            self._pending[uid] = "sell"
            await update.message.reply_text("請輸入：代號 張數 價格\n例如：2330 1 520", reply_markup=self._keyboard())
            return
        msg = sell_from_holdings(self.db_path, uid, args[0], float(args[1]), float(args[2]))
        await update.message.reply_text(msg, reply_markup=self._keyboard())

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
        if pending in ("card", "chips", "fund", "watch"):
            handled = await self._handle_pending_pick(update.message, uid, pending, text)
            if handled:
                return
        if pending == "sell" or pending.startswith("sell:"):
            parts = text.split()
            code = pending.split(":", 1)[1] if pending.startswith("sell:") else ""
            if code and len(parts) >= 2 and not (len(parts) >= 3):
                shares, price = parts[0], parts[1]
            elif len(parts) >= 3:
                code, shares, price = parts[0], parts[1], parts[2]
            else:
                self._pending[uid] = pending or "sell"
                await update.message.reply_text(
                    "請輸入：張數 價格　例如：1 72\n或：代號 張數 價格　例如：2330 1 520",
                    reply_markup=self._keyboard(),
                )
                return
            msg = sell_from_holdings(self.db_path, uid, code, float(shares), float(price))
            await update.message.reply_text(msg, reply_markup=self._keyboard())
            return
        if pending == "buy" or pending.startswith("buy:"):
            parts = text.split()
            code = pending.split(":", 1)[1] if pending.startswith("buy:") else ""
            if code and len(parts) >= 2 and not (len(parts) >= 3):
                shares, price = parts[0], parts[1]
            elif len(parts) >= 3:
                raw, shares, price = parts[0], parts[1], parts[2]
                hits = lookup_stocks(self.db_path, raw)
                code = hits[0]["stock_id"] if hits else raw
            else:
                self._pending[uid] = pending or "buy"
                await update.message.reply_text(
                    "請輸入：張數 價格　例如：1 68.5\n或：代號 張數 價格　例如：2330 1 500",
                    reply_markup=self._keyboard(),
                )
                return
            hits = lookup_stocks(self.db_path, code)
            name = hits[0]["stock_name"] if hits else code
            add_to_portfolio(self.db_path, uid, code, name, float(shares), float(price))
            await update.message.reply_text(
                f"已記錄買入 {code} {name} {shares}張 @ {price}", reply_markup=self._keyboard()
            )
            return
        hits = lookup_stocks(self.db_path, text)
        if len(hits) == 1:
            await self._reply_card(update, hits[0]["stock_id"])
            return
        if len(hits) > 1:
            await update.message.reply_html(
                "找到多檔。按 ➕ 加入觀察，📌 開決策卡，或記買入：",
                reply_markup=self._hits_keyboard(hits),
            )
            return
        await update.message.reply_text("找不到這檔。請打代號或名稱（如 南亞、2330）。", reply_markup=self._keyboard())

    async def _handle_pending_pick(self, message, uid: str, pending: str, text: str) -> bool:
        hits = lookup_stocks(self.db_path, text.split()[0].strip())
        if not hits:
            self._pending[uid] = pending
            await message.reply_text("找不到這檔。請打南亞或 2330。", reply_markup=self._keyboard())
            return True
        if len(hits) > 1:
            self._pending[uid] = pending
            await message.reply_html("找到多檔，請點選：", reply_markup=self._hits_keyboard(hits))
            return True
        code = hits[0]["stock_id"]
        name = hits[0].get("stock_name") or code
        if pending == "watch":
            add_to_watchlist(self.db_path, uid, code, name)
            await message.reply_text(f"已加入觀察 {code} {name}", reply_markup=self._keyboard())
            return True
        if pending == "card":
            await self._send_card_to(message, code)
            return True
        if pending == "chips":
            extra = fetch_major_player_html(code)
            await message.reply_html(extra or "查無籌碼", reply_markup=self._hub_keyboard(code))
            return True
        if pending == "fund":
            from fundamentals import format_fundamentals_html, sync_fundamentals

            html = format_fundamentals_html(code, self.db_path)
            if "尚無" in html:
                try:
                    sync_fundamentals(self.db_path)
                except Exception:
                    pass
                html = format_fundamentals_html(code, self.db_path)
            await message.reply_html(html, reply_markup=self._hub_keyboard(code))
            return True
        return False

    async def _run_ai_now(self, message, uid: str):
        await message.reply_text("AI 模擬操盤執行中（依今日海選紀律）…")
        try:
            from ai_trader import run_ai_desk

            result = self.screener.run_full_screening()
            as_of = result.get("as_of") or result.get("date") or ""
            ai = run_ai_desk(self.db_path, result.get("results") or {}, as_of)
            bits = [ai.get("html") or ""]
            if ai.get("bought"):
                bits.append("<b>本次買進</b>\n" + "\n".join(html_escape(x) for x in ai["bought"]))
            if ai.get("sold"):
                bits.append("<b>本次賣出</b>\n" + "\n".join(html_escape(x) for x in ai["sold"]))
            if ai.get("lesson"):
                bits.append("進化：" + html_escape(ai["lesson"]))
            holdings = get_user_portfolio(self.db_path, uid)
            await message.reply_html("\n\n".join(bits), reply_markup=self._portfolio_keyboard(holdings))
        except Exception as e:
            logger.exception("AI 操盤失敗")
            await message.reply_text(f"AI 操盤失敗：{e}", reply_markup=self._keyboard())

    async def _reply_card(self, update: Update, code: str):
        await self._send_card_to(update.message, code)

    async def _send_card_to(self, message, code: str):
        code = str(code).strip()
        hits = lookup_stocks(self.db_path, code)
        if hits and hits[0].get("close") is None:
            h = hits[0]
            try:
                from stock_links import html_stock_anchor

                title = html_stock_anchor(h["stock_id"], h.get("stock_name") or "", self.db_path)
            except Exception:
                title = f"{html_escape(h['stock_id'])} {html_escape(h.get('stock_name') or '')}"
            mkt = html_escape(h.get("market") or "EM")
            await message.reply_html(
                f"{title}\n此檔目前是<b>興櫃／未納入上市櫃日K母體</b>（市場 {mkt}），"
                "所以沒有決策卡格子與法人表。請點上面奇摩連結看走勢；上櫃後會自動進日K。",
                reply_markup=self._hub_keyboard(h["stock_id"]),
                disable_web_page_preview=True,
            )
            return
        await message.reply_text(f"查詢 {code}…")
        packed = generate_card_with_chart(code, self.db_path, self.charts_dir)
        html, card_img, chart = packed if len(packed) == 3 else (packed[0], "", packed[1] if len(packed) > 1 else "")
        await message.reply_html(html, reply_markup=self._hub_keyboard(code), disable_web_page_preview=True)
        if card_img:
            try:
                with open(card_img, "rb") as f:
                    await message.reply_photo(photo=f, caption="決策卡格子（表頭與欄位對齊）")
            except Exception:
                pass
        if chart:
            try:
                with open(chart, "rb") as f:
                    await message.reply_photo(photo=f, caption="180日高低導航（紅綠底區＝深淺）")
            except Exception:
                pass
        extra = fetch_major_player_html(code)
        if extra:
            await message.reply_html(extra, reply_markup=self._hub_keyboard(code), disable_web_page_preview=True)
            chip_img = generate_chips_image(code, self.db_path, os.path.join(self.charts_dir, f"{code}_chips.png"))
            if chip_img:
                try:
                    with open(chip_img, "rb") as f:
                        await message.reply_photo(photo=f, caption="主力買賣超格子（外資／投信／自營）")
                except Exception:
                    pass

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
        if data.startswith("w:"):
            code = data[2:]
            uid = str(q.from_user.id)
            add_to_watchlist(self.db_path, uid, code, code)
            await q.message.reply_html(
                f"已加入<b>觀察</b> {html_escape(code)}（自選，還不是持股）。\n"
                "要記真實買入請按「記一筆買入」。",
                reply_markup=self._hub_keyboard(code),
            )
            return
        if data.startswith("k:"):
            await self._send_card_to(q.message, data[2:])
            return
        if data.startswith("h:"):
            code = data[2:].strip()
            extra = fetch_major_player_html(code)
            await q.message.reply_html(extra or "查無籌碼", reply_markup=self._hub_keyboard(code), disable_web_page_preview=True)
            chip_img = generate_chips_image(code, self.db_path, os.path.join(self.charts_dir, f"{code}_chips.png"))
            if chip_img:
                try:
                    with open(chip_img, "rb") as f:
                        await q.message.reply_photo(photo=f, caption="主力買賣超格子（外資／投信／自營）")
                except Exception:
                    pass
            return
        if data.startswith("f:"):
            from fundamentals import format_fundamentals_html, sync_fundamentals

            code = data[2:].strip()
            html = format_fundamentals_html(code, self.db_path)
            if "尚無" in html:
                try:
                    sync_fundamentals(self.db_path)
                except Exception:
                    pass
                html = format_fundamentals_html(code, self.db_path)
            await q.message.reply_html(html, reply_markup=self._hub_keyboard(code))
            return
        if data.startswith("b:"):
            uid = str(q.from_user.id)
            code = data[2:].strip()
            self._pending[uid] = f"buy:{code}"
            await q.message.reply_text(
                f"記買入 {code}。請輸入：張數 價格\n例如：1 68.5",
                reply_markup=self._keyboard(),
            )
            return
        if data.startswith("x:"):
            uid = str(q.from_user.id)
            code = data[2:].strip()
            self._pending[uid] = f"sell:{code}"
            await q.message.reply_text(
                f"賣出 {code}。請輸入：張數 價格\n例如：1 72",
                reply_markup=self._keyboard(),
            )
            return
        if data == "ai_run":
            await self._run_ai_now(q.message, str(q.from_user.id))
            return
        if data == "screen":
            await q.message.reply_text("海選執行中…")
            try:
                result = self.screener.run_full_screening()
                await self._reply_screening_payload(q.message, result)
            except Exception as e:
                logger.exception("海選失敗")
                await q.message.reply_text(f"海選失敗：{e}", reply_markup=self._keyboard())
        elif data == "daytrade":
            from screening_engine import _stock_card_html

            rows = self.screener.screen_daytrade()
            cards = [_stock_card_html(r, i + 1) for i, r in enumerate(rows[:12])]
            html = "<b>當沖候選</b>\n" + ("\n".join(cards) if cards else "<i>無</i>")
            picks = [(r.get("code") or r.get("stock_id"), r.get("name") or r.get("stock_name")) for r in rows[:12]]
            await q.message.reply_html(html, reply_markup=self._picks_keyboard(picks, include_menu=True))
        elif data == "overnight":
            from screening_engine import _stock_card_html

            rows = self.screener.screen_overnight()
            cards = [_stock_card_html(r, i + 1) for i, r in enumerate(rows[:12])]
            html = "<b>隔日沖候選</b>\n" + ("\n".join(cards) if cards else "<i>無</i>")
            picks = [(r.get("code") or r.get("stock_id"), r.get("name") or r.get("stock_name")) for r in rows[:12]]
            await q.message.reply_html(html, reply_markup=self._picks_keyboard(picks, include_menu=True))
        elif data == "portfolio":
            await self._send_portfolio(q.message, str(q.from_user.id))
        elif data == "watch":
            await self._send_watch(q.message, str(q.from_user.id))
        elif data in ("card", "chips", "fund", "buy"):
            await self._prompt_pick(q.message, str(q.from_user.id), data)
        elif data == "sell":
            uid = str(q.from_user.id)
            self._pending[uid] = "sell"
            await q.message.reply_text("請輸入：代號 張數 價格\n例如：2330 1 520", reply_markup=self._keyboard())

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
