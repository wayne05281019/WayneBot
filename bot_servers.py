"""
WayneBot Telegram 操作層
- 選單按鈕
- 打股票代號 → 決策卡 + 高低導航圖 + 籌碼表
- 海選 / 當沖 / 隔日沖 / 持股 / 觀察 / 資金
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from config import get_charts_dir, get_db_path, get_telegram_config
from wayne_db import (
    init_database,
    get_user_portfolio,
    add_to_watchlist,
    remove_from_watchlist,
    add_to_portfolio,
    sell_from_holdings,
    lookup_stocks,
)
from screening_engine import ScreeningEngine
from portfolio_engine import PortfolioEngine
from ai_trader import format_ai_desk_html
from chips import generate_chips_image

logger = logging.getLogger(__name__)


def html_escape(val) -> str:
    return (
        str(val if val is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

try:
    from telegram import (
        Update,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        ReplyKeyboardMarkup,
        KeyboardButton,
        BotCommand,
    )
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

HELP_TOPICS = {
    "menu": (
        "<b>主選單（輸入框下方兩排，永遠在）</b>\n"
        "海選／當沖／隔日沖／持股　｜　觀察／資金／說明／選單\n"
        "打股名或代號＝看這檔：先現價，再介紹圖→決策卡→導航→籌碼。\n"
        "資金＝盤後產業輪動＋當日三大法人張數（不是分點）。左下也可按 /menu。"
    ),
    "screen": (
        "<b>海選怎麼用</b>\n"
        "週一～五台灣 06:30 用昨收＋美股收盤／盤後寄出；12:45 再寄尾盤可切（對照今早名單）。\n"
        "晚間 20:00 只記台股收盤名單、不寄。【雙時段】＝晚間＋今早都在。\n"
        "海選＝昨收量化名單，不是盤中即時掃描。下一則純文字可轉貼哥哥 LINE。\n"
        "下一則純文字可整段轉哥哥 LINE。靠近 20 日收盤高會標<b>少追</b>。\n"
        "當沖會寫保險進場、第一停利(+3%)、衝頂(+6%)、均價停損；隔日沖會寫尾盤買進區間與防守。\n"
        "藍字股名＝奇摩走勢。下面按鈕由上到下對應名單：左＝代號＋股名（看圖）；右➕＝觀察。\n"
        "其餘檔也把價位寫在排名裡，不必點開才看得到。靠近 20 日收盤高會標<b>少追</b>並排後面。不是立即下單清單。\n"
        "美股看現金收盤；收盤後再看盤後（台積ADR／輝達／那指期續勢）。盤中期貨不看。大跌會在 06:30 先單獨通知一則。逆風時當沖／隔日沖不列。\n"
        "隔日會用庫內收盤對昨天名單復盤；弱的類別只讓 AI 模擬倉少買，不另外狂抓資料。"
    ),
    "daytrade": (
        "<b>當沖怎麼用</b>\n"
        "保險進場＝不要追過當日收盤；第一停利＝+3% 先出一部分；衝頂＝+6%；保險停損＝當日均價跌破先走。\n"
        "隔夜美股逆風（收盤或盤後大跌、VIX 高）時這頁會空，避免開盤缺口硬沖。\n"
        "藍字＝奇摩；左鍵代號＋股名＝現價＋圖；➕＝觀察。不是保證獲利。"
    ),
    "overnight": (
        "<b>隔日沖怎麼用</b>\n"
        "保險買進＝尾盤昨收附近、不要摸高；明早開高目標 +3.5%～+4.8%；衝頂 +7%；保險防守＝開盤與均價較低者，跌破先走。\n"
        "藍字＝奇摩；左鍵代號＋股名＝現價＋圖；➕＝觀察。"
    ),
    "portfolio": (
        "<b>持股怎麼用</b>\n"
        "上半是你手記的真實買入，不是觀察。記買入：選股→記買入→打 <code>張數 價格</code>。\n"
        "下半是 AI 模擬帳戶（50 萬本金最多分 3 等份，單檔不超過一槽）。06:30 海選後與盤後融合會自動買賣，也可按「AI操盤」。\n"
        "成交寫進庫，隔日用已有日 K 復盤；弱的類別下一輪少買。這是模擬倉，不是真實下單。"
    ),
    "watch": (
        "<b>觀察怎麼用</b>\n"
        "自選清單，還沒買也可以加。空的很正常。\n"
        "加入：打股名或海選旁的 ➕。刪除：觀察頁該檔按「刪」。\n"
        "藍字股名＝奇摩走勢（只開網頁，不帶預覽大圖）。"
    ),
    "stock": (
        "<b>單檔第一眼建議看這些</b>\n"
        "打股名或按看這檔：先現價／漲跌，再介紹圖 → 高低決策卡 → 導航 → 籌碼。\n"
        "1 股號旁當日 K 縮圖＋收盤連漲／連跌＋開高低\n"
        "2 獲利＝近60個日曆日收盤低；距60根低是另外一欄（近60根收盤）\n"
        "3 溫度＝20日收盤位置＋月乖離；120日量＝這檔自己近120根成交量排名\n"
        "4 預警 K20高＝月乖離轉正偏熱（≥4%）或靠近20日收盤高；K20低＝月乖離轉負\n"
        "5 外資／投信／自營／法人當日張數＋連買連賣；完整法人格按籌碼\n"
        "6 高低導航橫式：價格列＝20高／20高脫離／20低／20低脫離／60低；量能列才有量能異常、警告、月波動低\n"
        "7 產業說明＝同業月營收／毛利率中位＋這族法人連買／連賣，講人話；不是內幕\n"
        "8 海選靠近 20 日收盤高＝少追，排後面；高低卡才是少賠主軸\n"
        "9 隔夜美股＝現金收盤＋收盤後盤後（台積ADR／那指期續勢），盤中期貨不看；大跌 06:30 會先通知。只過濾逆風，不拿來追高"
    ),
    "chips": "<b>籌碼</b>\n三大法人買賣超（張）。紅＝買超、綠＝賣超。籌碼佔量＝法人合計買賣超÷當日成交量。",
    "fund": "<b>營收毛利</b>\n官方月營收與季報數字。產業對照請按「產業」。",
    "industry": (
        "<b>產業說明怎麼用</b>\n"
        "打股名後會附一則，或按「產業」。用官方月營收、季報毛利率跟同業中位數比，再加上這族法人張數。\n"
        "這是落後的公開數字，幫你看懂這族，不是內幕。少賠仍看高低卡：靠近 20 日收盤高少追。"
    ),
    "buy": "<b>記買入</b>\n選好股票後打 <code>張數 價格</code>，例如 <code>1 68.5</code>。",
    "pick": "請打股名或代號，例如 <b>南亞</b>、<b>2324</b>。",
    "flow": (
        "<b>資金移動怎麼用</b>\n"
        "最上面是盤後資金輪動：同一交易日依產業把三大法人張數加總，對照前一日。熱 3 族＋族內代表股當佈局參考。\n"
        "下面才是外資／投信個股買賣超，對照持股、觀察、量大波動。\n"
        "只看官方法人＋價量，不抓分點、不抓論壇。法人也會幌，輪動不單獨當訊號。"
    ),
}


def chunk_telegram_text(text: str, limit: int = 3500) -> List[str]:
    if not text:
        return []
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def chunk_telegram_html(html: str, limit: int = 3500) -> List[str]:
    """依 </blockquote> 或換行切開，避免把 <a> 切成半截導致 Telegram parse 失敗。"""
    if not html:
        return []
    if len(html) <= limit:
        return [html]
    chunks: List[str] = []
    rest = html
    close = "</blockquote>"
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break
        cut = rest.rfind(close, 0, limit)
        if cut != -1:
            cut += len(close)
        else:
            cut = rest.rfind("\n", 0, limit)
            if cut < 1:
                cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    return [c for c in chunks if c]


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

    def _reply_menu(self):
        """聊天室下方常駐兩排（每排四個，短標減少左右空白）。"""
        rows = [
            [KeyboardButton("海選"), KeyboardButton("當沖"), KeyboardButton("隔日沖"), KeyboardButton("持股")],
            [KeyboardButton("觀察"), KeyboardButton("資金"), KeyboardButton("說明"), KeyboardButton("選單")],
        ]
        try:
            return ReplyKeyboardMarkup(
                rows,
                resize_keyboard=True,
                is_persistent=True,
                input_field_placeholder="打股名／代號，或按下方兩排",
            )
        except TypeError:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True)

    def _q(self, topic: str):
        """網頁版把 ❓ 畫成紅圈問號，看起來像壞掉；改用「說明」二字。"""
        return InlineKeyboardButton("說明", callback_data=f"?:{topic}")

    def _keyboard(self):
        """舊 inline 主選單改成極短一列，避免再疊四排。常駐選單在輸入框下方。"""
        return InlineKeyboardMarkup([[self._q("menu")]])

    def _hub_keyboard(self, code: str, topic: str = "stock"):
        c = str(code).strip()[:6]
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("籌碼", callback_data=f"h:{c}"),
                    InlineKeyboardButton("營收", callback_data=f"f:{c}"),
                    InlineKeyboardButton("產業", callback_data=f"n:{c}"),
                    InlineKeyboardButton("觀察", callback_data=f"w:{c}"),
                ],
                [
                    InlineKeyboardButton("記買入", callback_data=f"b:{c}"),
                    self._q(topic),
                ],
            ]
        )

    def _stock_action_row(self, code: str, name: str = "", idx: int = 0):
        """左鍵寫代號＋股名（點下去看這檔）；右鍵加觀察。"""
        from tg_layout import stock_btn_label

        c = str(code or "").strip()[:6]
        label = stock_btn_label(c, name or "")
        return [
            InlineKeyboardButton(label, callback_data=f"k:{c}"),
            InlineKeyboardButton("➕", callback_data=f"w:{c}"),
        ]

    def _picks_keyboard(self, picks, include_menu: bool = False, topic: str = "screen"):
        rows = []
        for i, (code, name) in enumerate((picks or [])[:10], start=1):
            c = str(code or "").strip()
            if not c:
                continue
            rows.append(self._stock_action_row(c, name or "", idx=i))
        if include_menu or rows:
            rows.append([self._q(topic)])
        if not rows:
            return self._keyboard()
        return InlineKeyboardMarkup(rows)

    def _hits_keyboard(self, hits):
        """名稱撞名時當選擇器：按鈕寫代號＋股名（不是奇摩連結）。"""
        rows = []
        for h in hits[:8]:
            c = str(h.get("stock_id") or "")
            n = str(h.get("stock_name") or "")
            if not c:
                continue
            label = f"{c} {n}".strip()[:16] or c
            rows.append(
                [
                    InlineKeyboardButton(label, callback_data=f"k:{c}"),
                    InlineKeyboardButton("➕", callback_data=f"w:{c}"),
                    InlineKeyboardButton("買入", callback_data=f"b:{c}"),
                ]
            )
        rows.append([self._q("stock")])
        return InlineKeyboardMarkup(rows) if rows else self._keyboard()

    def _hits_list_html(self, hits, lead: str = "") -> str:
        """多檔時訊息裡列出藍字股名，按鈕序號才對得上。"""
        try:
            from stock_links import html_stock_anchor
        except Exception:
            html_stock_anchor = None
        lines = [
            lead
            or "名稱相近，請選要看哪一檔。藍字＝奇摩；按鈕＝看這檔。"
        ]
        for i, h in enumerate((hits or [])[:8], start=1):
            sid = str(h.get("stock_id") or "")
            sname = str(h.get("stock_name") or "")
            if not sid:
                continue
            if html_stock_anchor:
                try:
                    title = html_stock_anchor(sid, sname, self.db_path)
                except Exception:
                    title = f"{html_escape(sid)} {html_escape(sname)}"
            else:
                title = f"{html_escape(sid)} {html_escape(sname)}"
            lines.append(f"{i}. {title}")
        return "\n".join(lines)

    WATCH_LIST_LIMIT = 24

    def _watch_list_keyboard(self, rows):
        from tg_layout import stock_btn_label

        kb = []
        for r in (rows or [])[: self.WATCH_LIST_LIMIT]:
            c = str(r.get("stock_code") or "")
            if not c:
                continue
            n = str(r.get("stock_name") or "")
            kb.append(
                [
                    InlineKeyboardButton(stock_btn_label(c, n), callback_data=f"k:{c}"),
                    InlineKeyboardButton("籌碼", callback_data=f"h:{c}"),
                    InlineKeyboardButton("買入", callback_data=f"b:{c}"),
                    InlineKeyboardButton("刪", callback_data=f"rw:{c}"),
                ]
            )
        kb.append([self._q("watch")])
        return InlineKeyboardMarkup(kb)

    def _render_watch(self, rows):
        shown = list(rows or [])[: self.WATCH_LIST_LIMIT]
        lines = [
            "<b>觀察清單（自選，還沒買也可以）</b>",
            "加入：打股名按 ➕，或海選／當沖旁的 ➕。刪除：按該檔「刪」。",
        ]
        if not shown:
            lines.append("<i>目前是空的，這很正常。請先打一檔股票名稱。</i>")
            return "\n".join(lines), InlineKeyboardMarkup([[self._q("watch")]])
        for r in shown:
            c = str(r.get("stock_code") or "")
            n = str(r.get("stock_name") or "")
            try:
                from stock_links import html_stock_anchor

                lines.append(f"• {html_stock_anchor(c, n, self.db_path)}")
            except Exception:
                lines.append(f"• {html_escape(c)} {html_escape(n)}".rstrip())
        extra = len(rows or []) - len(shown)
        if extra > 0:
            lines.append(f"<i>只顯示前 {self.WATCH_LIST_LIMIT} 檔，其餘 {extra} 檔請先刪再加。</i>")
        lines.append("下面由上到下對應該檔：左＝看這檔　籌碼　記買入　刪。")
        return "\n".join(lines), self._watch_list_keyboard(shown)

    def _portfolio_keyboard(self, holdings):
        kb = []
        for h in (holdings or [])[:8]:
            c = str(h.get("stock_code") or h.get("stock_id") or "")
            if not c:
                continue
            kb.append(
                [
                    InlineKeyboardButton(f"{c}", callback_data=f"k:{c}"),
                    InlineKeyboardButton("賣出", callback_data=f"x:{c}"),
                ]
            )
        kb.append(
            [
                InlineKeyboardButton("AI操盤", callback_data="ai_run"),
                self._q("portfolio"),
            ]
        )
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
                disable_web_page_preview=True,
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
            chunks = chunk_telegram_html(part.get("html") or "", 3500)
            if not chunks:
                continue
            for j, chunk in enumerate(chunks):
                is_last = i == last and j == len(chunks) - 1
                kb = self._picks_keyboard(part.get("picks") or [], include_menu=is_last, topic="screen")
                await message.reply_html(chunk, reply_markup=kb, disable_web_page_preview=True)
            await asyncio.sleep(0.25)
        line_txt = (result.get("line_share") or "").strip()
        if line_txt:
            await message.reply_text("↓ 下面這一則可整段複製，轉貼哥哥 LINE（一次貼完）")
            await message.reply_text(line_txt)

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

    def _send_html(self, chat_id: str, html: str, extra_keyboard=None, attach_menu: bool = False):
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

    def _send_plain(self, chat_id: str, text: str):
        try:
            import requests

            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                timeout=20,
            )
        except Exception as e:
            logger.error("send_plain: %s", e)

    def _send_text_file(self, chat_id: str, file_path: str, caption: str = ""):
        try:
            import requests

            url = f"https://api.telegram.org/bot{self.token}/sendDocument"
            with open(file_path, "rb") as f:
                requests.post(
                    url,
                    data={"chat_id": chat_id, "caption": caption[:1024]},
                    files={"document": (os.path.basename(file_path), f, "text/plain; charset=utf-8")},
                    timeout=40,
                )
        except Exception as e:
            logger.error("send_text_file: %s", e)

    @staticmethod
    def _card_photo_paths(card_img):
        if not card_img:
            return []
        if isinstance(card_img, (list, tuple)):
            return [p for p in card_img if p]
        return [card_img]

    def _send_photo(self, chat_id: str, photo_path: str, caption: str = "", reply_markup=None):
        try:
            import json
            import requests

            url = f"https://api.telegram.org/bot{self.token}/sendPhoto"
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": chat_id, "caption": caption[:1024], "parse_mode": "HTML"}
                if reply_markup is not None:
                    data["reply_markup"] = json.dumps(reply_markup.to_dict())
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
            chunks = chunk_telegram_html(part.get("html") or "", 3500)
            for j, chunk in enumerate(chunks):
                is_last = i == last and j == len(chunks) - 1
                kb = self._picks_keyboard(part.get("picks") or [], include_menu=is_last, topic="screen")
                self._send_html(
                    self.chat_id,
                    chunk,
                    extra_keyboard=kb,
                    attach_menu=False,
                )
            _t.sleep(0.25)
        line_txt = (result.get("line_share") or "").strip()
        if line_txt:
            self._send_plain(self.chat_id, "↓ 下面這一則可整段複製，轉貼哥哥 LINE（一次貼完）")
            self._send_plain(self.chat_id, line_txt)
            try:
                from config import get_charts_dir

                path = os.path.join(get_charts_dir(), f"海選_{result.get('date') or ''}_轉貼LINE.txt")
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(line_txt + "\n")
                self._send_text_file(self.chat_id, path, caption="同一份檔案：也可把這個 txt 傳到 LINE")
            except Exception as e:
                logger.error("line share file: %s", e)

    def _send_stock_card_by_code(self, chat_id: str, code: str, name: str = ""):
        if not code:
            return
        from cary_navigator import generate_card_with_chart, generate_chart, generate_decision_card

        try:
            packed = generate_card_with_chart(code, self.db_path, self.charts_dir)
            html = packed[0]
            card_img = packed[1] if len(packed) > 1 else ""
            chart_path = packed[2] if len(packed) > 2 else ""
            glance = packed[3] if len(packed) > 3 else ""
        except Exception:
            html = generate_decision_card(code, self.db_path)
            card_img = ""
            chart_path = generate_chart(code, name, self.db_path, os.path.join(self.charts_dir, f"{code}.png"))
            glance = ""
        if glance:
            cap = f"{html_escape(code)}"
            self._send_photo(chat_id, glance, caption=cap)
        for path in self._card_photo_paths(card_img):
            self._send_photo(chat_id, path, caption=f"{html_escape(code)} 高低決策卡")
        if chart_path:
            self._send_photo(
                chat_id,
                chart_path,
                caption=f"{html_escape(code)} 高低導航：價格列20高／脫離／20低／60低；紫▲量能異常與紅▲警告只在量能列",
            )
        chip_img = generate_chips_image(code, self.db_path, os.path.join(self.charts_dir, f"{code}_chips.png"))
        last_kb = self._hub_keyboard(code)
        if chip_img:
            self._send_photo(chat_id, chip_img, caption="籌碼（張）", reply_markup=last_kb)
        else:
            self._send_html(chat_id, "選單", extra_keyboard=last_kb, attach_menu=False)

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
        await update.message.reply_html(
            "<b>WayneBot</b>\n"
            "主選單在<b>輸入框正下方兩排</b>（不會跟著訊息捲走）。\n"
            "打 <b>南亞</b> 或 <b>2324</b> 看單檔。左下也可按 /menu。\n"
            "各頁訊息上的「說明」是該頁用法，再按 <b>✕</b> 就收合。",
            reply_markup=self._reply_menu(),
        )

    async def menu_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(
            "已叫回主選單（下方兩排）。",
            reply_markup=self._reply_menu(),
        )

    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_html(
            HELP_TOPICS["menu"],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✕", callback_data="hx")]]),
        )

    async def screen_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("海選執行中…")
        try:
            result = await asyncio.to_thread(self.screener.run_full_screening)
            await self._reply_screening_payload(update.message, result)
        except Exception as e:
            logger.exception("海選失敗")
            await update.message.reply_text(f"海選失敗：{e}", reply_markup=self._keyboard())

    async def daytrade_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from screening_engine import _stock_card_html

        rows = await asyncio.to_thread(self.screener.screen_daytrade)
        cards = [_stock_card_html(r, i + 1) for i, r in enumerate(rows[:12])]
        html = (
            "<b>當沖候選</b>\n"
            "<i>保險進場≤收盤；第一停利+3%先出一部分；衝頂+6%；均價跌破先走。藍字＝奇摩。</i>\n"
            + ("\n".join(cards) if cards else "<i>無</i>")
        )
        picks = [(r.get("code") or r.get("stock_id"), r.get("name") or r.get("stock_name")) for r in rows[:12]]
        await update.message.reply_html(
            html, reply_markup=self._picks_keyboard(picks, include_menu=True, topic="daytrade"), disable_web_page_preview=True
        )

    async def overnight_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from screening_engine import _stock_card_html

        rows = await asyncio.to_thread(self.screener.screen_overnight)
        cards = [_stock_card_html(r, i + 1) for i, r in enumerate(rows[:12])]
        html = (
            "<b>隔日沖候選</b>\n"
            "<i>尾盤保險買進區間；明早開高+3.5～4.8%；防守跌破先走。藍字＝奇摩。</i>\n"
            + ("\n".join(cards) if cards else "<i>無</i>")
        )
        picks = [(r.get("code") or r.get("stock_id"), r.get("name") or r.get("stock_name")) for r in rows[:12]]
        await update.message.reply_html(
            html, reply_markup=self._picks_keyboard(picks, include_menu=True, topic="overnight"), disable_web_page_preview=True
        )

    async def flow_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        await update.message.reply_text("讀取當日資金移動…")
        try:
            from money_flow import format_flow_html

            html = await asyncio.to_thread(format_flow_html, self.db_path, user_id=uid)
        except Exception as e:
            logger.exception("資金移動失敗")
            await update.message.reply_text(f"資金移動失敗：{e}", reply_markup=self._keyboard())
            return
        parts = chunk_telegram_html(html)
        for i, part in enumerate(parts):
            kb = InlineKeyboardMarkup([[self._q("flow")]]) if i == len(parts) - 1 else None
            await update.message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)

    async def _send_portfolio(self, message, uid: str):
        holdings = get_user_portfolio(self.db_path, uid)
        mine = self.portfolio_engine.format_holdings_html(holdings)
        ai = format_ai_desk_html(self.portfolio_engine)
        parts = chunk_telegram_html(mine + "\n\n" + ai)
        for i, part in enumerate(parts):
            kb = self._portfolio_keyboard(holdings) if i == len(parts) - 1 else None
            await message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)

    async def _send_watch(self, message, uid: str, edit: bool = False):
        from wayne_db import get_user_watchlist

        rows = get_user_watchlist(self.db_path, uid)
        html, kb = self._render_watch(rows)
        if edit and message is not None and hasattr(message, "edit_text"):
            try:
                await message.edit_text(
                    html,
                    parse_mode="HTML",
                    reply_markup=kb,
                    disable_web_page_preview=True,
                )
                return
            except Exception:
                logger.exception("觀察清單原地更新失敗，改發新訊息")
        if message is not None and hasattr(message, "reply_html"):
            await message.reply_html(html, reply_markup=kb, disable_web_page_preview=True)
            return
        raise RuntimeError("觀察清單沒有可回覆的訊息")

    async def _cb_answer(self, q, text: str) -> None:
        try:
            await q.answer((text or "")[:200])
        except Exception:
            logger.exception("callback answer 失敗")

    async def _remove_watch_clicked(self, q, code: str) -> None:
        """按「刪」：寫庫後更新清單。失敗不要落到「請打南亞」。"""
        uid = str(q.from_user.id)
        try:
            try:
                removed = remove_from_watchlist(self.db_path, uid, code)
            except Exception:
                logger.exception("觀察刪除寫庫失敗 code=%s uid=%s", code, uid)
                await self._cb_answer(q, "刪除沒寫進庫，請再按一次")
                msg = q.message
                if msg is not None and hasattr(msg, "reply_text"):
                    await msg.reply_text("刪除沒寫進庫，請再按一次「刪」。")
                return
            await self._cb_answer(q, f"已刪除 {code}" if removed else "這檔不在觀察裡")
            try:
                await self._send_watch(q.message, uid, edit=True)
                return
            except Exception:
                logger.exception("觀察清單刪除後更新失敗 code=%s", code)
            msg = q.message
            notice = f"已從觀察刪除 {code}" if removed else f"{code} 不在觀察裡"
            if msg is not None and hasattr(msg, "reply_text"):
                await msg.reply_text(notice)
                return
            chat = getattr(msg, "chat", None) if msg is not None else None
            chat_id = getattr(msg, "chat_id", None) if msg is not None else None
            if chat_id is None and chat is not None:
                chat_id = getattr(chat, "id", None)
            if chat_id is None:
                chat_id = q.from_user.id
            bot = q.get_bot()
            await bot.send_message(chat_id=chat_id, text=notice)
        except Exception:
            logger.exception("觀察刪除流程失敗 code=%s", code)
            await self._cb_answer(q, "刪除沒做成，請再按一次")

    async def _prompt_pick(self, message, uid: str, purpose: str):
        from wayne_db import get_user_watchlist

        hints = {
            "card": "看這檔：請先選一檔。打南亞／2330，或點觀察清單。會先出現現價，再依序出圖。",
            "chips": "籌碼：請先選一檔。打名稱或代號，或點下面觀察清單。",
            "fund": "營收毛利：請先選一檔。打名稱或代號，或點下面觀察清單。",
            "industry": "產業說明：請先選一檔。會用官方營收／毛利跟同業比，講人話。",
            "buy": "記買入：請先選一檔，或直接打「2330 1 500」（代號 張數 價格）。",
        }
        rows = get_user_watchlist(self.db_path, uid)
        prefix = {"card": "k", "chips": "h", "fund": "f", "industry": "n", "buy": "b"}.get(purpose, "k")
        kb = []
        for r in rows[:8]:
            c = str(r.get("stock_code") or "")
            n = str(r.get("stock_name") or "")
            if c:
                kb.append([InlineKeyboardButton(f"{c} {n}".strip()[:22], callback_data=f"{prefix}:{c}")])
        kb.append([self._q(purpose if purpose in HELP_TOPICS else "stock")])
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
        chip_img = await asyncio.to_thread(
            generate_chips_image,
            args[0].strip(),
            self.db_path,
            os.path.join(self.charts_dir, f"{args[0].strip()}_chips.png"),
        )
        if chip_img:
            with open(chip_img, "rb") as f:
                await update.message.reply_photo(photo=f, caption="籌碼（張）", reply_markup=self._hub_keyboard(args[0].strip()))
        else:
            await update.message.reply_html("查無籌碼", reply_markup=self._keyboard())

    async def fund_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        if not args:
            await update.message.reply_text("用法：/fund 2330")
            return
        from fundamentals import format_fundamentals_html, sync_fundamentals

        code = args[0].strip()
        html = await asyncio.to_thread(format_fundamentals_html, code, self.db_path)
        if "尚無" in html:
            await update.message.reply_text("尚無快取，正在同步官方月營收／季報…")
            try:
                await asyncio.to_thread(sync_fundamentals, self.db_path)
            except Exception as e:
                logger.error("fund sync: %s", e)
            html = await asyncio.to_thread(format_fundamentals_html, code, self.db_path)
        await update.message.reply_html(html, reply_markup=self._keyboard(), disable_web_page_preview=True)

    async def industry_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        if not args:
            await self._prompt_pick(update.message, str(update.effective_user.id), "industry")
            return
        await self._send_industry(update.message, args[0].strip())

    async def _send_industry(self, message, code: str):
        from industry_brief import format_industry_html

        code = str(code).strip()
        try:
            html = await asyncio.to_thread(format_industry_html, code, self.db_path)
        except Exception as e:
            logger.exception("產業說明失敗 code=%s", code)
            html = f"產業說明失敗：{html_escape(e)}"
        await message.reply_html(html, reply_markup=self._hub_keyboard(code), disable_web_page_preview=True)

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
        if text.lower().lstrip("/") in ("start", "開始"):
            self._pending.pop(uid, None)
            await self.start_cmd(update, context)
            return
        if text in ("選單", "主選單") or text.lower().lstrip("/") == "menu":
            self._pending.pop(uid, None)
            await self.menu_cmd(update, context)
            return
        if text in ("說明", "幫助") or text.lower().lstrip("/") == "help":
            self._pending.pop(uid, None)
            await self.help_cmd(update, context)
            return
        if text == "選股":
            self._pending.pop(uid, None)
            await update.message.reply_html(
                HELP_TOPICS["pick"],
                reply_markup=InlineKeyboardMarkup([[self._q("stock")]]),
            )
            return
        if text in ("資金", "資金移動") or text.lower().lstrip("/") == "flow":
            self._pending.pop(uid, None)
            await self.flow_cmd(update, context)
            return
        if text == "當沖":
            self._pending.pop(uid, None)
            await self.daytrade_cmd(update, context)
            return
        if text == "隔日沖":
            self._pending.pop(uid, None)
            await self.overnight_cmd(update, context)
            return
        pending = self._pending.pop(uid, "")
        if text == "海選" or "今日海選" in text or text.endswith("海選"):
            await self.screen_cmd(update, context)
            return
        if "模擬持倉" in text or text == "持股":
            await self.portfolio_cmd(update, context)
            return
        if text == "觀察" or "自選" in text:
            await self.watch_cmd(update, context)
            return
        if "系統狀態" in text:
            await update.message.reply_html("WayneBot 雲端新版運作中。請用訊息下方按鈕操作。", reply_markup=self._keyboard())
            return
        if pending in ("card", "chips", "fund", "industry", "watch"):
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
        logger.info("收到文字 uid=%s 字數=%s", uid, len(text))
        try:
            await update.message.reply_text("收到，查詢中…", reply_markup=self._reply_menu())
        except Exception:
            logger.exception("ack 失敗")
        try:
            hits = lookup_stocks(self.db_path, text)
            if len(hits) == 1:
                await self._reply_card(update, hits[0]["stock_id"])
                return
            if len(hits) > 1:
                await update.message.reply_html(
                    self._hits_list_html(hits),
                    reply_markup=self._hits_keyboard(hits),
                    disable_web_page_preview=True,
                )
                return
            await update.message.reply_text("找不到這檔。請打代號或名稱（如 南亞、2330）。", reply_markup=self._keyboard())
        except Exception:
            logger.exception("查詢失敗")
            await update.message.reply_text(
                "查詢失敗。雲端可能還沒有日K，或出圖逾時。請先按 /start，稍後再試。",
                reply_markup=self._keyboard(),
            )

    async def _handle_pending_pick(self, message, uid: str, pending: str, text: str) -> bool:
        hits = lookup_stocks(self.db_path, text.split()[0].strip())
        if not hits:
            self._pending[uid] = pending
            await message.reply_text("找不到這檔。請打南亞或 2330。", reply_markup=self._keyboard())
            return True
        if len(hits) > 1:
            self._pending[uid] = pending
            await message.reply_html(
                self._hits_list_html(hits, "找到多檔，請點選："),
                reply_markup=self._hits_keyboard(hits),
                disable_web_page_preview=True,
            )
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
            chip_img = await asyncio.to_thread(
                generate_chips_image, code, self.db_path, os.path.join(self.charts_dir, f"{code}_chips.png")
            )
            if chip_img:
                try:
                    with open(chip_img, "rb") as f:
                        await message.reply_photo(photo=f, caption="籌碼（張）", reply_markup=self._hub_keyboard(code))
                except Exception:
                    await message.reply_text("籌碼圖送出失敗", reply_markup=self._hub_keyboard(code))
            else:
                await message.reply_html("查無籌碼", reply_markup=self._hub_keyboard(code))
            return True
        if pending == "fund":
            from fundamentals import format_fundamentals_html, sync_fundamentals

            html = await asyncio.to_thread(format_fundamentals_html, code, self.db_path)
            if "尚無" in html:
                try:
                    await asyncio.to_thread(sync_fundamentals, self.db_path)
                except Exception:
                    pass
                html = await asyncio.to_thread(format_fundamentals_html, code, self.db_path)
            await message.reply_html(html, reply_markup=self._hub_keyboard(code), disable_web_page_preview=True)
            return True
        if pending == "industry":
            await self._send_industry(message, code)
            return True
        return False

    async def _run_ai_now(self, message, uid: str):
        await message.reply_text("AI 模擬操盤執行中（依今日海選紀律）…")
        try:
            from ai_trader import run_ai_desk

            result = await asyncio.to_thread(self.screener.run_full_screening)
            as_of = result.get("as_of") or result.get("date") or ""
            ai = await asyncio.to_thread(run_ai_desk, self.db_path, result.get("results") or {}, as_of)
            bits = [ai.get("html") or ""]
            if not ai.get("bought") and not ai.get("sold"):
                bits.append(
                    f"<i>本次沒有新成交（候選 {ai.get('candidates') or 0} 檔）。已滿 3 檔或名單被高低卡／美股濾掉。</i>"
                )
            if ai.get("bought"):
                bits.append("<b>本次買進</b>\n" + "\n".join(html_escape(x) for x in ai["bought"]))
            if ai.get("sold"):
                bits.append("<b>本次賣出</b>\n" + "\n".join(html_escape(x) for x in ai["sold"]))
            if ai.get("lesson"):
                bits.append("進化：" + html_escape(ai["lesson"]))
            holdings = get_user_portfolio(self.db_path, uid)
            parts = chunk_telegram_html("\n\n".join(bits))
            for i, part in enumerate(parts):
                kb = self._portfolio_keyboard(holdings) if i == len(parts) - 1 else None
                await message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)
        except Exception as e:
            logger.exception("AI 操盤失敗")
            await message.reply_text(f"AI 操盤失敗：{e}", reply_markup=self._keyboard())

    def _quote_header_html(self, code: str) -> str:
        """看這檔開頭：現價／漲跌／盤中或收盤時間。熱訊用粗體（Telegram 不能指定紅字）。"""
        code = str(code or "").strip()
        hits = lookup_stocks(self.db_path, code)
        name = ""
        mkt = ""
        if hits:
            code = str(hits[0].get("stock_id") or code)
            name = str(hits[0].get("stock_name") or "")
            mkt = str(hits[0].get("market") or "")
        try:
            from stock_links import html_stock_anchor

            title = html_stock_anchor(code, name, self.db_path)
        except Exception:
            title = f"{html_escape(code)} {html_escape(name)}".strip()
        from tg_layout import html_move, html_qty, price_change

        rt = None
        try:
            from live_quote import fetch_mis_quote

            rt = fetch_mis_quote(code, mkt)
        except Exception:
            logger.exception("現價 MIS 失敗 code=%s", code)
        if rt:
            vol = int(rt.get("volume") or 0)
            t = str(rt.get("update_time") or "").strip()
            chg = rt.get("change")
            if chg is None:
                chg = price_change(rt.get("close"), rt.get("pct_change"), rt.get("yesterday_close"))
            lines = [
                title,
                f"現價　{html_escape(rt.get('close'))}",
                f"漲跌　{html_move(chg, rt.get('pct_change'))}",
                f"成交　{html_qty(vol, signed=False)}",
            ]
            if t:
                from live_quote import format_mis_clock_line

                lines.append(html_escape(format_mis_clock_line(t)))
            return "\n".join(lines)
        close = hits[0].get("close") if hits else None
        pct = hits[0].get("pct_change") if hits else None
        if close is not None:
            return "\n".join(
                [
                    title,
                    f"昨收　{html_escape(close)}",
                    f"漲跌　{html_move(price_change(close, pct), pct)}",
                    "<i>盤中報價暫時沒接到，以下圖用庫內日K。</i>",
                ]
            )
        return title

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
            mkt_raw = (h.get("market") or "").strip().upper()
            mkt = html_escape(h.get("market") or "")
            is_em = mkt_raw in ("EM", "EMERGING", "興櫃")
            if is_em:
                body = (
                    f"{title}\n此檔目前是<b>興櫃／未納入上市櫃日K母體</b>（市場 {mkt}），"
                    "所以沒有決策卡格子與法人表。請點上面奇摩連結看走勢；上櫃後會自動進日K。"
                )
            else:
                body = (
                    f"{title}\n這是上市櫃股票（市場 {mkt or 'TW'}），"
                    "但<strong>雲端這台機器還沒有日K資料</strong>，所以暫時不能出決策卡。"
                    "請等行情庫下載完成後再打一次代號。"
                )
            await message.reply_html(
                body,
                reply_markup=self._hub_keyboard(h["stock_id"]),
                disable_web_page_preview=True,
            )
            return
        try:
            header = await asyncio.to_thread(self._quote_header_html, code)
            await message.reply_html(header, disable_web_page_preview=True)
        except Exception:
            logger.exception("現價列失敗 code=%s", code)
            await message.reply_text(f"查詢 {code}…")
        hub = self._hub_keyboard(code)
        cap_links = ""
        try:
            from stock_links import yahoo_urls

            web, mobile = yahoo_urls(code, self.db_path)
            cap_links = f'<a href="{web}">網頁走勢</a>　<a href="{mobile}">技術線</a>'
        except Exception:
            cap_links = ""

        async def send_photo(path, caption, markup=None):
            if not path or not os.path.exists(path):
                return False
            try:
                with open(path, "rb") as f:
                    await message.reply_photo(
                        photo=f, caption=caption, parse_mode="HTML", reply_markup=markup
                    )
                return True
            except Exception:
                try:
                    with open(path, "rb") as f:
                        await message.reply_photo(photo=f, caption=caption[:200], reply_markup=markup)
                    return True
                except Exception:
                    logger.exception("送圖失敗 path=%s", path)
                    return False

        wait_msg = None
        try:
            wait_msg = await message.reply_text("圖產製中，會依序出現介紹圖／決策卡／導航／籌碼…")
        except Exception:
            wait_msg = None

        sent_any = False
        last_ok = False
        pending_send = None
        try:
            from cary_navigator import (
                generate_chart,
                render_decision_card_png,
                render_first_glance_png,
            )
            from cary_navigator import CaryNavigatorEngine
            from chips import generate_chips_image
            from chip_tape import build_tape

            def _card_and_tape():
                engine = CaryNavigatorEngine(self.db_path)
                card = engine.get_decision_card(code, lookback=20)
                tape = {}
                try:
                    tape = build_tape(self.db_path, code) or {}
                except Exception:
                    tape = {}
                ohlc = card.pop("_ohlc", None) if isinstance(card, dict) else None
                return card, tape, ohlc

            async def flush_send():
                nonlocal pending_send, sent_any, last_ok, wait_msg
                if pending_send is None:
                    return
                ok = await pending_send
                pending_send = None
                last_ok = bool(ok)
                sent_any = sent_any or last_ok
                if last_ok and wait_msg is not None:
                    try:
                        await wait_msg.delete()
                    except Exception:
                        pass
                    wait_msg = None

            def queue_photo(path, caption, markup=None):
                nonlocal pending_send
                pending_send = asyncio.create_task(send_photo(path, caption, markup))

            t0 = time.monotonic()
            card, tape, ohlc = await asyncio.wait_for(
                asyncio.to_thread(_card_and_tape), timeout=20
            )
            logger.info("看這檔 card %.1fs code=%s", time.monotonic() - t0, code)
            if card.get("error"):
                await message.reply_html(
                    f"⚠️ {html_escape(card.get('error'))}",
                    reply_markup=hub,
                    disable_web_page_preview=True,
                )
                return
            os.makedirs(self.charts_dir, exist_ok=True)
            t1 = time.monotonic()
            glance = await asyncio.wait_for(
                asyncio.to_thread(
                    render_first_glance_png,
                    code,
                    card,
                    tape,
                    os.path.join(self.charts_dir, f"{code}_glance.png"),
                    self.db_path,
                ),
                timeout=25,
            )
            logger.info("看這檔 glance %.1fs code=%s", time.monotonic() - t1, code)
            if glance:
                last_ok = await send_photo(glance, cap_links or "當日K＋籌碼價量")
                sent_any = sent_any or last_ok
                if last_ok and wait_msg is not None:
                    try:
                        await wait_msg.delete()
                    except Exception:
                        pass
                    wait_msg = None
            t1 = time.monotonic()
            card_path = await asyncio.wait_for(
                asyncio.to_thread(
                    render_decision_card_png,
                    card,
                    os.path.join(self.charts_dir, f"{code}_card.png"),
                ),
                timeout=25,
            )
            logger.info("看這檔 card_png %.1fs code=%s", time.monotonic() - t1, code)
            if card_path:
                last_ok = await send_photo(card_path, "高低決策卡")
                sent_any = sent_any or last_ok
            t1 = time.monotonic()
            chart = await asyncio.wait_for(
                asyncio.to_thread(
                    generate_chart,
                    code,
                    "",
                    self.db_path,
                    os.path.join(self.charts_dir, f"{code}.png"),
                    ohlc,
                ),
                timeout=35,
            )
            logger.info("看這檔 chart %.1fs code=%s", time.monotonic() - t1, code)
            await flush_send()
            if chart:
                queue_photo(
                    chart,
                    "180日高低導航：實心＝當日觸發；空心＝接近；粉紅／綠底上的箭頭會自動加深",
                )
            t1 = time.monotonic()
            chip_img = await asyncio.wait_for(
                asyncio.to_thread(
                    generate_chips_image,
                    code,
                    self.db_path,
                    os.path.join(self.charts_dir, f"{code}_chips.png"),
                ),
                timeout=20,
            )
            logger.info("看這檔 chips %.1fs code=%s", time.monotonic() - t1, code)
            await flush_send()
            hub_on = False
            if chip_img:
                hub_on = await send_photo(chip_img, "籌碼（張）", hub)
                sent_any = sent_any or hub_on
                last_ok = hub_on
                if hub_on and wait_msg is not None:
                    try:
                        await wait_msg.delete()
                    except Exception:
                        pass
                    wait_msg = None
            if sent_any and not hub_on:
                await message.reply_html("圖已出完。", reply_markup=hub, disable_web_page_preview=True)
            elif not sent_any:
                from cary_navigator import generate_decision_card

                html = await asyncio.to_thread(generate_decision_card, code, self.db_path)
                await message.reply_html(html, reply_markup=hub, disable_web_page_preview=True)
        except asyncio.TimeoutError:
            logger.exception("看這檔出圖逾時 code=%s", code)
            if pending_send is not None:
                try:
                    sent_any = bool(await pending_send) or sent_any
                except Exception:
                    pass
                pending_send = None
            if not sent_any:
                await message.reply_html(
                    "圖產製逾時。請再打一次代號；或先用下面按鈕看籌碼／產業。",
                    reply_markup=hub,
                    disable_web_page_preview=True,
                )
            else:
                await message.reply_html("後面的圖逾時。可用下面按鈕繼續。", reply_markup=hub, disable_web_page_preview=True)
        except Exception:
            logger.exception("看這檔出圖失敗 code=%s", code)
            if pending_send is not None:
                try:
                    await pending_send
                except Exception:
                    pass
                pending_send = None
            if not sent_any:
                try:
                    from cary_navigator import generate_decision_card

                    html = await asyncio.to_thread(generate_decision_card, code, self.db_path)
                except Exception:
                    html = f"查詢 {html_escape(code)} 失敗。"
                await message.reply_html(html, reply_markup=hub, disable_web_page_preview=True)
        finally:
            if wait_msg is not None:
                try:
                    await wait_msg.delete()
                except Exception:
                    pass
        try:
            await self._send_industry(message, code)
        except Exception:
            logger.exception("附產業說明失敗 code=%s", code)

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        data = q.data or ""
        if data.startswith("cat:") or data.startswith("noop"):
            hints = {
                "revenue_cross": "優先看：營收轉強 × 量價突破",
                "leave_zero": "起漲：高低卡獲利剛離零（跟決策卡同一條獲利）",
                "select_01": "周帶量：短線轉強，貼月高少追",
                "select_02": "站上季線：昨收在季線下、今日站上",
                "select_03": "止跌：月低附近有人接、量沒死",
                "select_04": "雙綠：高低卡20低剛脫離",
                "day_trade": "當沖：進場 / 停利 / 停損",
                "overnight": "隔日沖：尾盤佈局",
            }
            await q.answer(hints.get(data.split(":", 1)[-1], "分類標記")[:200])
            return
        if data.startswith("rw:"):
            await self._remove_watch_clicked(q, data[3:].strip())
            return
        await q.answer()
        if data == "hx":
            try:
                await q.message.delete()
            except Exception:
                try:
                    await q.edit_message_text("·")
                except Exception:
                    pass
            return
        if data.startswith("?:"):
            topic = data[2:] or "menu"
            await q.message.reply_html(
                HELP_TOPICS.get(topic) or HELP_TOPICS["menu"],
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✕", callback_data="hx")]]),
                disable_web_page_preview=True,
            )
            return
        if data.startswith("w:"):
            code = data[2:]
            uid = str(q.from_user.id)
            add_to_watchlist(self.db_path, uid, code, code)
            await q.message.reply_html(
                f"已加入<b>觀察</b> {html_escape(code)}（自選，還不是持股）。\n"
                "要記真實買入請按「記買入」。",
                reply_markup=self._hub_keyboard(code),
            )
            return
        if data.startswith("k:"):
            await self._send_card_to(q.message, data[2:])
            return
        if data.startswith("h:"):
            code = data[2:].strip()
            chip_img = await asyncio.to_thread(
                generate_chips_image, code, self.db_path, os.path.join(self.charts_dir, f"{code}_chips.png")
            )
            if chip_img:
                try:
                    with open(chip_img, "rb") as f:
                        await q.message.reply_photo(
                            photo=f, caption="籌碼（張）", reply_markup=self._hub_keyboard(code)
                        )
                except Exception:
                    await q.message.reply_html("籌碼圖送出失敗", reply_markup=self._hub_keyboard(code))
            else:
                await q.message.reply_html("查無籌碼", reply_markup=self._hub_keyboard(code), disable_web_page_preview=True)
            return
        if data.startswith("f:"):
            from fundamentals import format_fundamentals_html, sync_fundamentals

            code = data[2:].strip()
            html = await asyncio.to_thread(format_fundamentals_html, code, self.db_path)
            if "尚無" in html:
                try:
                    await asyncio.to_thread(sync_fundamentals, self.db_path)
                except Exception:
                    pass
                html = await asyncio.to_thread(format_fundamentals_html, code, self.db_path)
            await q.message.reply_html(
                html, reply_markup=self._hub_keyboard(code), disable_web_page_preview=True
            )
            return
        if data.startswith("n:"):
            await self._send_industry(q.message, data[2:].strip())
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
                result = await asyncio.to_thread(self.screener.run_full_screening)
                await self._reply_screening_payload(q.message, result)
            except Exception as e:
                logger.exception("海選失敗")
                await q.message.reply_text(f"海選失敗：{e}", reply_markup=self._keyboard())
        elif data == "daytrade":
            from screening_engine import _stock_card_html

            rows = await asyncio.to_thread(self.screener.screen_daytrade)
            cards = [_stock_card_html(r, i + 1) for i, r in enumerate(rows[:12])]
            html = (
                "<b>當沖候選</b>\n"
                "<i>保險進場≤收盤；第一停利+3%先出一部分；衝頂+6%；均價跌破先走。藍字＝奇摩。</i>\n"
                + ("\n".join(cards) if cards else "<i>無</i>")
            )
            picks = [(r.get("code") or r.get("stock_id"), r.get("name") or r.get("stock_name")) for r in rows[:12]]
            await q.message.reply_html(
                html, reply_markup=self._picks_keyboard(picks, include_menu=True, topic="daytrade"), disable_web_page_preview=True
            )
        elif data == "overnight":
            from screening_engine import _stock_card_html

            rows = await asyncio.to_thread(self.screener.screen_overnight)
            cards = [_stock_card_html(r, i + 1) for i, r in enumerate(rows[:12])]
            html = (
                "<b>隔日沖候選</b>\n"
                "<i>尾盤保險買進區間；明早開高+3.5～4.8%；防守跌破先走。藍字＝奇摩。</i>\n"
                + ("\n".join(cards) if cards else "<i>無</i>")
            )
            picks = [(r.get("code") or r.get("stock_id"), r.get("name") or r.get("stock_name")) for r in rows[:12]]
            await q.message.reply_html(
                html, reply_markup=self._picks_keyboard(picks, include_menu=True, topic="overnight"), disable_web_page_preview=True
            )
        elif data == "portfolio":
            await self._send_portfolio(q.message, str(q.from_user.id))
        elif data == "watch":
            await self._send_watch(q.message, str(q.from_user.id))
        elif data in ("card", "chips", "fund", "industry", "buy"):
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
        async def _on_start(app):
            try:
                from cary_navigator import prewarm_card_fonts

                await asyncio.to_thread(prewarm_card_fonts)
            except Exception:
                logger.exception("字型預熱失敗")
            try:
                await app.bot.set_my_commands(
                    [
                        BotCommand("menu", "回到主選單（下方兩排）"),
                        BotCommand("start", "開始"),
                        BotCommand("help", "使用說明"),
                        BotCommand("screen", "海選"),
                        BotCommand("portfolio", "持股"),
                        BotCommand("watch", "觀察"),
                        BotCommand("flow", "資金移動"),
                        BotCommand("industry", "產業說明"),
                    ]
                )
            except Exception:
                logger.exception("set_my_commands 失敗")

        app = Application.builder().token(self.token).post_init(_on_start).build()
        app.add_handler(CommandHandler("start", self.start_cmd))
        app.add_handler(CommandHandler("menu", self.menu_cmd))
        app.add_handler(CommandHandler("help", self.help_cmd))
        app.add_handler(CommandHandler("screen", self.screen_cmd))
        app.add_handler(CommandHandler("daytrade", self.daytrade_cmd))
        app.add_handler(CommandHandler("overnight", self.overnight_cmd))
        app.add_handler(CommandHandler("portfolio", self.portfolio_cmd))
        app.add_handler(CommandHandler("watch", self.watch_cmd))
        app.add_handler(CommandHandler("flow", self.flow_cmd))
        app.add_handler(CommandHandler("card", self.card_cmd))
        app.add_handler(CommandHandler("chips", self.chips_cmd))
        app.add_handler(CommandHandler("fund", self.fund_cmd))
        app.add_handler(CommandHandler("industry", self.industry_cmd))
        app.add_handler(CommandHandler("buy", self.buy_cmd))
        app.add_handler(CommandHandler("sell", self.sell_cmd))
        app.add_handler(CallbackQueryHandler(self.on_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))

        async def _on_error(update, context):
            logger.exception("Telegram handler 失敗: %s", context.error)
            q = getattr(update, "callback_query", None) if update else None
            if q is not None:
                try:
                    await q.answer("這步沒做成，請再按一次", show_alert=False)
                except Exception:
                    pass
                msg = q.message
                if msg is not None and hasattr(msg, "reply_text"):
                    try:
                        await msg.reply_text("這步沒做成。請再按一次該按鈕，不必打股名。")
                    except Exception:
                        pass
                return
            msg = getattr(update, "effective_message", None) if update else None
            if msg:
                try:
                    await msg.reply_text("處理失敗。請先按 /start，再打南亞或 2330。")
                except Exception:
                    pass

        app.add_error_handler(_on_error)
        logger.info("Telegram polling 啟動")
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        try:
            # False：下載行情庫期間使用者打的字不要被丟掉
            app.run_polling(drop_pending_updates=False)
        except Exception as e:
            # python-telegram-bot 的 InvalidToken 訊息會含完整 token，不可寫進 Render Logs
            if type(e).__name__ == "InvalidToken" or "InvalidToken" in type(e).__name__:
                logger.error(
                    "TELEGRAM_BOT_TOKEN 被 Telegram 拒絕。"
                    "請到 BotFather 重發，整段貼到 Render → Environment → TELEGRAM_BOT_TOKEN"
                    "（不要加引號、不要空白或換行），存檔後 Manual Deploy。"
                    "不要把 token 貼到聊天，也不要截圖 Logs。"
                )
                raise SystemExit(1) from None
            raise


if __name__ == "__main__":
    # Render 若 Start Command 仍是 python bot_servers.py，改走 main.run_web（含 /health）
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    from main import run_web

    run_web()
