"""
WayneBot Telegram 操作層
- 兩排主選單（輸入列旁邊四格鍵盤圖示）；直立式不再重複主選單按鈕
- 打股票代號 → 介紹圖＋決策卡＋產業圖＋導航圖同一則四格相簿；點開是 Telegram 允許的最高像素。圖下「K線」＝奇摩股市同一檔日K
- 海選 / 當沖 / 隔日沖 / 剛脫離零 / 洞燭先機 / 持股 / 觀察 / 資金 / 連買區
"""
from __future__ import annotations

import asyncio
import gc
import logging
import os
import re
import struct
import tempfile
import time
import unicodedata
from contextvars import ContextVar
from typing import Any, Dict, List, Optional, Tuple

# 當下一則是誰在按。asyncio 任務各自一份，不能用 instance 全域。
# 例外頁回鍵盤也帶這，才不會哥哥出錯把偉權的兩排蓋過去。
_ACTIVE_PHONE_UID: ContextVar[str] = ContextVar("wayne_phone_uid", default="")
PHONE_BUSY = "這一步暫時沒跑完，請稍後再按一次。細節已記在後台，不會影響你其他按鈕。"

# Render 免費方案冷啟＋行情庫索引期間，第一檔查詢常超過 45s。
_CARD_BUILD_TIMEOUT = float(os.getenv("WAYNE_CARD_BUILD_TIMEOUT", "90"))
_CHART_RENDER_TIMEOUT = float(os.getenv("WAYNE_CHART_RENDER_TIMEOUT", "120"))
# 介紹圖／決策卡／產業圖與導航圖同一逾時。醒機時 matplotlib 冷啟，60s 會只送到介紹圖。
_LOOKUP_PNG_TIMEOUT = float(os.getenv("WAYNE_LOOKUP_PNG_TIMEOUT", str(_CHART_RENDER_TIMEOUT)))
# Telegram 相簿點開上限：寬+高 ≤10000、檔 ≤10MB、長寬比 ≤20。三張都拉到這個上限。
_LOOKUP_TG_MAX_WH = 10000
_LOOKUP_TG_MAX_RATIO = 20.0
_LOOKUP_TG_MAX_BYTES = 10 * 1024 * 1024
_LOOKUP_JPEG_QUALITY = 95
_LOOKUP_JPEG_QUALITY_FLOOR = 78

from config import (
    allowed_telegram_uids,
    get_charts_dir,
    get_db_path,
    get_telegram_config,
    skip_chart_warmup,
    skip_telegram_polling,
    telegram_uid_allowed,
)
from phone_update import (
    phone_code_reply,
    phone_git_sha,
    phone_update_notice,
)
from lookup_fuzzy import hits_need_picker, lookup_picker_lead
from wayne_db import (
    init_database,
    get_user_portfolio,
    add_to_watchlist,
    remove_from_watchlist,
    lookup_stocks,
    listing_is_emerging,
    touch_tg_user,
    export_private_user_payload,
)
from trade_journal import (
    ensure_user_trade_logs,
    format_user_review_html,
    format_user_trades_html,
    held_is_odd_lot_only,
    held_has_odd_shares,
    normalize_trade_tokens,
    parse_lots_price,
    parse_qty_to_lots,
    coerce_bare_qty_if_share_count,
    qty_token_has_unit,
    record_buy,
    record_sell,
)
from screening_engine import ScreeningEngine
from portfolio_engine import PortfolioEngine
from ai_trader import format_ai_desk_html, format_ai_desk_pages, run_ai_desk
from chips import generate_chips_image
from intent_router import (
    NEEDS_STOCK,
    no_cost_honest_html,
    parse_intent,
    sell_honest_html,
)

logger = logging.getLogger(__name__)


def _circled_menu_label(text: str) -> str:
    """每個字後面加圈（Telegram 鍵盤畫得出來的圈住字）。"""
    return "".join(ch + "\u20dd" for ch in str(text or "") if not ch.isspace())


def _normalize_menu_text(text: str) -> str:
    """主選單按鈕文字正規化（全形、空白、圈圈）。"""
    t = unicodedata.normalize("NFKC", (text or "").strip())
    t = "".join(ch for ch in t if unicodedata.category(ch) not in ("Mn", "Me"))
    t = t.replace("\u3000", "").strip()
    try:
        from biaoke_digest import normalize_biaoke_button

        t = normalize_biaoke_button(t)
    except Exception:
        pass
    return t


def _text_escapes_pending(text: str) -> bool:
    """連買／記買入精靈若收到平常話或代號，不要吞掉改重問步驟。"""
    from universe import is_lookup_ticker

    t = _normalize_menu_text(text)
    if not t:
        return False
    if t in MENU_COMPACT_ALIASES or t in MENU_FULL_ALIASES:
        return True
    if parse_intent(t) is not None:
        return True
    compact = t.replace(" ", "")
    return is_lookup_ticker(compact)


def html_escape(val) -> str:
    return (
        str(val if val is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def is_phone_code_query(text: str) -> bool:
    """整句問現在更新代碼。不要把「代碼」當子字去搶查股。"""
    t = unicodedata.normalize("NFKC", str(text or "").strip())
    t = t.lower().lstrip("/").replace(" ", "").replace("_", "")
    return t in {"代碼", "更新代碼", "現在代碼", "版本代碼", "gitsha", "code"}


def _notified_sha_path() -> str:
    db = get_db_path()
    parent = os.path.dirname(os.path.abspath(db)) or "data"
    return os.path.join(parent, ".wayne_notified_sha")


def notified_sha_is(sha: str) -> bool:
    s = str(sha or "").strip()[:40]
    if not s:
        return True
    try:
        with open(_notified_sha_path(), encoding="utf-8") as f:
            return f.read().strip()[:40] == s
    except Exception:
        return False


def remember_notified_sha(sha: str) -> None:
    s = str(sha or "").strip()[:40]
    if not s:
        return
    path = _notified_sha_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(s + "\n")


def should_notify_phone_update(sha: str) -> bool:
    """同一 SHA 不重送；Cursor／略過輪詢不送。pytest 也不送真訊息。"""
    if skip_telegram_polling():
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    s = str(sha or "").strip()[:40]
    if not s or notified_sha_is(s):
        return False
    return True


def _http_url(url: str) -> str:
    """Telegram URL 鈕只收 http(s)；缺 scheme 會讓整則訊息送不出去。"""
    u = str(url or "").strip()
    if u.startswith("https://") or u.startswith("http://"):
        return u
    return ""


def _stock_caption_name(card: dict | None, code: str = "") -> str:
    """決策卡圖說第一行用股名（台積電），不要寫「高低決策卡」。"""
    name = str((card or {}).get("stock_name") or "").strip()
    sid = str((card or {}).get("stock_id") or code or "").strip()
    if name and sid and (name == sid or name.startswith(sid)):
        name = name[len(sid) :].strip(" 　") if name.startswith(sid) else ""
    try:
        from universe import prefer_display_stock_name

        name = prefer_display_stock_name(name, "", sid)
    except Exception:
        pass
    return name or sid or "決策卡"


def _photo_sell_caption(base: str, card: dict | None, *, fallback: str = "當日K＋籌碼價量") -> str:
    """圖說：有如何賣就寫在圖底下；沒有就不硬塞網頁走勢／點縮圖講解。"""
    cap = str(base or "").strip() or str(fallback or "").strip()
    if not card:
        return cap
    short = ""
    try:
        from sell_discipline import attach_sell, sell_note_short

        if not str(card.get("sell_action") or "").strip():
            attach_sell(card)
        short = sell_note_short(card)
    except Exception:
        short = ""
    if short:
        note = f"Ai建議　{html_escape(short)}"
        cap = f"{cap}\n{note}" if cap else note
    flow = str((card or {}).get("industry_flow") or "").strip()
    if flow:
        bit = html_escape(flow)
        cap = f"{cap}\n{bit}" if cap else bit
    return cap


def _decision_card_photo_caption(card: dict | None, code: str = "", live_note: str = "") -> str:
    title = f"{_stock_caption_name(card, code)}{live_note}"
    return _photo_sell_caption(title, card, fallback=title)


def _glance_photo_caption(base: str, card: dict | None) -> str:
    """介紹圖圖說：只留如何賣；不要網頁走勢／點縮圖講義。"""
    return _photo_sell_caption(base, card, fallback="")


def _buy_holdings_prompt(code: str, lots=None) -> str:
    """記買入：零股持股要舉 200股，不要只舉 2 68.5 讓人打成張。"""
    head = f"記買入 {code}。"
    if lots is not None:
        try:
            from tg_layout import holdings_qty_text

            head += f"現有 {holdings_qty_text(lots)}。"
        except Exception:
            pass
    if held_is_odd_lot_only(lots) or held_has_odd_shares(lots):
        return head + "請輸入：價格（1張）\n例如：631.6 或 200股 631.6"
    return head + "請輸入：價格（1張）\n例如：68.5 或 2 68.5"


def _sell_holdings_prompt(code: str, lots=None) -> str:
    """賣出手記持股：帶現有張數／股數，零股不要讓人以為是 0張。"""
    head = f"賣出 {code}。"
    if lots is not None:
        try:
            from tg_layout import holdings_qty_text

            head += f"現有 {holdings_qty_text(lots)}。"
        except Exception:
            pass
    if held_is_odd_lot_only(lots) or held_has_odd_shares(lots):
        return head + "請輸入：價格（全賣）\n例如：72 或 200股 72"
    return head + "請輸入：價格（全賣）\n例如：72 或 1 72"


try:
    from telegram import (
        Update,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        ReplyKeyboardMarkup,
        KeyboardButton,
        BotCommand,
        MenuButtonCommands,
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

# 查股：股票四碼＋ETF（被動／主動／兩倍槓桿）。海選仍不收 ETF。
LOOKUP_CODE_EXAMPLES_HTML = (
    "<code>2330</code>、<code>0050</code>、<code>0052</code>、"
    "<code>00631L</code>、<code>00981A</code>"
)

HELP_TOPICS = {}
# 說明／圖文／介紹已取消。舊氣泡 ?:／pg:／/help／打「說明」「圖文」靜音。
# 主選單兩排：拿掉刷新／回報後整排往前，平均 6+6；下排最右洞燭先機。圈已拿掉。
MENU_BTN_MARKET = "大盤"
MENU_BTN_STREAK = "連買區"
MENU_BTN_AI = "AI倉"
MENU_BTN_REPORT = "回報"
MENU_BTN_CARD = "刷新"
MENU_BTN_BIAOKE = "飆大"
MENU_BTN_BIAOKE_FACE = MENU_BTN_BIAOKE
MENU_BTN_SLOT = "\u3000"
MENU_BTN_DONGZHU = "洞燭先機"
MENU_BTN_DONGZHU_ALIASES = (
    MENU_BTN_DONGZHU,
    "洞燭",
    "先機",
)
MENU_BTN_LEAVE_DONGZHU = "離開洞燭先機"
MENU_BTN_LEAVE_DONGZHU_ALIASES = (
    MENU_BTN_LEAVE_DONGZHU,
    "離開洞燭",
    "退出洞燭先機",
    "跳出洞燭先機",
)
MENU_BTN_LEAVE_ZERO = "剛脫離零"
MENU_BTN_LEAVE_ZERO_ALIASES = (
    MENU_BTN_LEAVE_ZERO,
    "剛離零",
    "離零",
    "盤中離零",
    "獲利剛離零",
    "獲利剛剛脫離零",
)
MENU_BTN_BIAOKE_ALIASES = (
    MENU_BTN_BIAOKE,
    MENU_BTN_BIAOKE_FACE,
    _circled_menu_label(MENU_BTN_BIAOKE),
    "飆客",
    "AI飆客",
    "期股多空雙飆客",
)
MENU_BTN_CARD_ALIASES = (MENU_BTN_CARD, "刷新上一檔", "決策卡")
MENU_BTN_BACK_MAIN = "回主選單"
MENU_BTN_LEAVE_BIAOKE = "離開飆大"
MENU_BTN_LEAVE_BIAOKE_ALIASES = (
    MENU_BTN_LEAVE_BIAOKE,
    "離開飆客",
    "退出飆大",
    "跳出飆大",
)
MENU_BTN_BACK_STEP = "上一步"
MENU_BTN_NEXT_PAGE = "下一批"
MENU_BTN_PREV_PAGE = "上一批"
MENU_ROW1 = (
    "海選",
    "持股",
    "觀察",
    MENU_BTN_BIAOKE_FACE,
    MENU_BTN_MARKET,
    "資金",
)
MENU_ROW2 = (
    "當沖",
    "隔日沖",
    MENU_BTN_AI,
    MENU_BTN_STREAK,
    MENU_BTN_LEAVE_ZERO,
    MENU_BTN_DONGZHU,
)
MENU_COMPACT_ALIASES = ("精簡選單", "精簡鍵盤")
MENU_FULL_ALIASES = ("完整選單", "完整鍵盤")
# 版面改版時遞增，讓舊客戶端自動強制刷新一次。
# v6：進度／暫態泡泡也不掛 ReplyKeyboard（刪進度時鍵盤會一起沒）。
# v7：次排「連買區」取代「選單」。
# v8：版面過期必「新發」帶 ReplyKeyboard 的訊息（edit 無法換兩排按鈕）。
# v9：次排改為隔日沖／大盤／資金／說明／連買區（少用放最後）。
# v10：兩排各加一格＝6+6；第一排最右 AI倉；第二排最右回報（文字／截圖）。
# v11：說明與連買區對調＝隔日沖／大盤／資金／連買區／說明／回報。
# v12：第一排最左「刷新上一檔」（決策卡當別名）。
# v14：精簡六顆全兩字（刷新上一檔→刷新）避免換行；完整十二顆第一排同步。
# v15：兩排各加一格＝7+7；上排最右飆客獨立區，下排最右空白格。
# v16：上排最右改「飆大」；按進去直接對話，不放裡面選單。
# v17：飆大兩個字上的圈拿掉；舊圈圈鍵盤仍認。
# v18：v17 去圈後，只按飆大不會重掛 ReplyKeyboard，手機仍顯示舊圈圈。這版任何進飆大都會帶現在的兩排（沒圈）。
# v19：進飆大時鍵盤最上加「離開飆大」，用完一鍵回兩排主選單，不必在十四顆裡找出口。
# v20：離開不再多一排；上排最右同一顆由「飆大」改成「離開飆大」。
# v21：下排最右空白格改「剛離零」（盤中現價複核獲利剛離零；★ 最佳五檔）。
# v22：剛離零→剛脫離零；等待泡泡等寬框線；飆大個股不倒舊文舊圖。
# v23：拿掉說明，整排往前；第一排最右大盤，第二排最右空白。說明／圖文／/help 取消。
# v24：取消精簡鍵盤；偉權與哥哥都固定完整兩排。
# v25：拿掉刷新／回報，後面鈕往前；兩排各六格。舊鍵盤「刷新」「回報」仍認。
# v26：下排最右空白格改「洞燭先機」（族群＋黃金買點交集；沒買點不准發明）。
# v27：進洞燭後同一顆改「離開洞燭先機」，用完回兩排主選單（對齊離開飆大）。
MENU_LAYOUT_VERSION = "27"
MAX_PICK_INLINE_ROWS = 8

# 輸入列左邊三條槓（Telegram BotCommand）。跟下方兩排重複的不放，避免兩套入口。
# 兩排已有海選／持股／觀察／大盤／資金，橫槓不再放 screen／portfolio／watch／market／flow。
TELEGRAM_BOT_COMMANDS = (
    ("menu", "回到主選單（下方兩排）"),
    ("industry", "產業說明（先打代號）"),
    ("code", "現在更新說明"),
    ("start", "開始"),
)


from tg_layout import chunk_telegram_html, chunk_telegram_text, reflow_telegram_html


class WayneTelegramBot:
    def __init__(self, token: str = None, chat_id: str = None, db_path: str = None, **kwargs):
        cfg = get_telegram_config()
        self.token = token or cfg.get("token") or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or cfg.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID")
        self.db_path = db_path or get_db_path()
        self.charts_dir = get_charts_dir()
        os.makedirs(self.charts_dir, exist_ok=True)
        init_database(self.db_path)
        ensure_user_trade_logs(self.db_path)
        self.screener = ScreeningEngine(self.db_path)
        self.portfolio_engine = PortfolioEngine(self.db_path)
        self._pending: Dict[str, str] = {}
        self._biaoke_hist: Dict[str, list] = {}
        self._last_card: Dict[str, str] = {}
        self._lookup_ctx: Dict[str, dict] = {}
        # actor_key（chat_id:uid）隔離，避免同機多用戶互相刪訊息／搶快取
        self._menu_fade_msgs: Dict[str, list] = {}
        self._lookup_fade_msgs: Dict[str, list] = {}
        # actor_key → pack_id → 海選分類訊息
        self._screening_msgs: Dict[str, Dict[str, list]] = {}
        self._line_pack_status_msgs: Dict[str, list] = {}
        self._help_msgs: Dict[str, list] = {}
        self._lookup_locks: Dict[str, asyncio.Lock] = {}
        # actor → 查股進行到哪（介紹圖／決策卡），進度泡泡跟這裡同步
        self._lookup_op_state: Dict[str, dict] = {}
        self._pending_locks: Dict[str, asyncio.Lock] = {}
        self._screening_running: set[str] = set()
        self._trade_running: set[str] = set()
        self._screening_gate = asyncio.Lock()
        self._screening_global_owner: str = ""
        self._menu_fade_gen: Dict[str, int] = {}
        self._menu_pin_msgs: Dict[str, object] = {}

    @staticmethod
    def _actor_key(
        message=None,
        *,
        user=None,
        chat_id: int | None = None,
        uid: str = "",
    ) -> str:
        if message is not None:
            if not uid:
                uid = WayneTelegramBot._uid_from_message(message)
                ctx = str(_ACTIVE_PHONE_UID.get() or "")
                if ctx:
                    uid = ctx
            if chat_id is None:
                chat_id = int(message.chat_id)
        if user is not None:
            uid = uid or str(getattr(user, "id", "") or "")
        if chat_id is not None and uid:
            return f"{int(chat_id)}:{uid}"
        if uid:
            return str(uid)
        return str(chat_id or "0")

    def _op_state_map(self) -> Dict[str, dict]:
        """查股進度表。測試用 __new__ 沒跑 __init__ 時也要能寫。"""
        state = getattr(self, "_lookup_op_state", None)
        if not isinstance(state, dict):
            self._lookup_op_state = {}
            return self._lookup_op_state
        return state

    def _pending_actor(self, message=None, *, uid: str = "") -> str:
        return self._actor_key(message, uid=uid)

    def _pending_lock(self, actor: str) -> asyncio.Lock:
        lock = self._pending_locks.get(actor)
        if lock is None:
            lock = asyncio.Lock()
            self._pending_locks[actor] = lock
        return lock

    async def _enter_main_menu(
        self,
        message,
        uid: str,
        *,
        silent_keyboard: bool = True,
        clear_pending: bool = True,
    ) -> str:
        """主選單功能入口：清 pending、刪暫態泡泡，必要時靜默刷新鍵盤（不洗版）。"""
        actor = self._actor_key(message, uid=uid)
        if clear_pending:
            self._pending.pop(actor, None)
            try:
                self._biaoke_hist.pop(actor, None)
            except Exception:
                pass
        await self._dismiss_menu_transients(actor)
        if not self._menu_layout_ok(uid):
            await self._refresh_reply_menu(message, uid=uid, silent=silent_keyboard)
        return actor

    async def _dismiss_help_msgs(self, actor_key: str) -> None:
        """重開說明頁時刪掉上一則，避免鍵盤連按堆滿聊天室。"""
        msgs = self._help_msgs.pop(str(actor_key), [])
        for msg in msgs:
            try:
                await msg.delete()
            except Exception:
                pass

    async def _dismiss_menu_transients(self, actor_key: str) -> None:
        """選單刷新提示：主功能開始時立刻刪除，像轉場消失。"""
        msgs = self._menu_fade_msgs.pop(str(actor_key), [])
        for msg in msgs:
            try:
                await msg.delete()
            except Exception:
                pass

    def _track_lookup_fade(self, actor_key: str, msg, role: str) -> None:
        if msg is None:
            return
        self._lookup_fade_msgs.setdefault(str(actor_key), []).append((msg, role))

    def _track_screening_msg(self, actor_key: str, pack_id: str, msg) -> None:
        if msg is None or not pack_id:
            return
        self._screening_msgs.setdefault(str(actor_key), {}).setdefault(str(pack_id), []).append(msg)

    def _track_line_pack_status(self, actor_key: str, msg) -> None:
        """海選生成中進度；完成後刪除。"""
        if msg is None:
            return
        self._line_pack_status_msgs.setdefault(str(actor_key), []).append(msg)

    async def _dismiss_line_pack_status(self, actor_key: str) -> None:
        msgs = self._line_pack_status_msgs.pop(str(actor_key), [])
        for msg in msgs:
            try:
                await msg.delete()
            except Exception:
                pass

    async def _dismiss_screening_section(self, actor_key: str, pack_id: str) -> None:
        """海選該分類的貼紙＋文字塊。"""
        bucket = (self._screening_msgs.get(str(actor_key)) or {}).pop(str(pack_id), [])
        for msg in bucket:
            try:
                await msg.delete()
            except Exception:
                pass

    async def _dismiss_lookup_fades(self, actor_key: str, roles: set | None = None) -> None:
        """查股暫存訊息：圖出來後整批刪除（或只刪 ack／wait）。"""
        items = self._lookup_fade_msgs.pop(str(actor_key), [])
        keep: list = []
        for msg, role in items:
            if roles is not None and role not in roles:
                keep.append((msg, role))
                continue
            try:
                await msg.delete()
            except Exception:
                pass
        if keep:
            self._lookup_fade_msgs[str(actor_key)] = keep

    async def _delete_message(self, msg) -> None:
        if msg is None:
            return
        try:
            await msg.delete()
        except Exception:
            pass

    async def _transient_status(self, message, text: str, *, reply_markup=None):
        """暫時狀態；完成後呼叫 _delete_message 或 _dismiss_lookup_fades 收起。"""
        try:
            return await message.reply_text(text, reply_markup=reply_markup)
        except Exception:
            logger.debug("暫時狀態送出失敗", exc_info=True)
            return None

    def send_message(self, text: str, chat_id: str = None):
        return self._send_html(chat_id or self.chat_id, text)

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

    @staticmethod
    def _uid_from_message(message) -> str:
        user = getattr(message, "from_user", None)
        return str(getattr(user, "id", "") or "")

    @staticmethod
    def _uid_from_update(update) -> str:
        """正式 Update 有 effective_user；測試 callback 往往只有 callback_query.from_user。"""
        user = getattr(update, "effective_user", None)
        uid = str(getattr(user, "id", None) or "")
        if uid:
            return uid
        q = getattr(update, "callback_query", None)
        if q is not None:
            uid = str(getattr(getattr(q, "from_user", None), "id", None) or "")
            if uid:
                return uid
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        if msg is not None:
            return WayneTelegramBot._uid_from_message(msg)
        return ""

    def _touch_user(self, uid: str, display_name: str = "") -> None:
        if not telegram_uid_allowed(uid):
            return
        try:
            touch_tg_user(self.db_path, uid, display_name)
        except Exception:
            logger.debug("touch_tg_user failed uid=%s", uid, exc_info=True)

    def _touch_from_update(self, update: Update) -> str:
        uid = self._uid_from_update(update)
        user = getattr(update, "effective_user", None)
        if user is None:
            q = getattr(update, "callback_query", None)
            user = getattr(q, "from_user", None) if q is not None else None
        if uid:
            self._touch_user(uid, getattr(user, "first_name", "") or "")
        return uid

    async def _reject_stranger(self, update: Update) -> bool:
        """陌生人按開始只回「這是私人 Bot」，不進 tg_users、不做事。"""
        uid = self._uid_from_update(update)
        if telegram_uid_allowed(uid):
            return False
        q = getattr(update, "callback_query", None)
        if q is not None:
            try:
                await q.answer("這是私人 Bot", show_alert=True)
            except Exception:
                pass
            return True
        msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
        if msg is not None and hasattr(msg, "reply_text"):
            try:
                await msg.reply_text("這是私人 Bot")
            except Exception:
                pass
        return True

    def _wrap_cmd(self, handler):
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if await self._reject_stranger(update):
                return
            uid = self._touch_from_update(update)
            token = _ACTIVE_PHONE_UID.set(uid)
            try:
                return await handler(update, context)
            finally:
                _ACTIVE_PHONE_UID.reset(token)

        return wrapped

    def _remember_card(self, uid: str, code: str) -> None:
        c = str(code or "").strip()
        if uid and c:
            self._last_card[uid] = c

    def _hit_is_emerging(self, code: str, hits: list | None = None) -> bool:
        rows = hits if hits is not None else lookup_stocks(self.db_path, code)
        return bool(rows) and listing_is_emerging(rows[0])

    def _em_no_listed_html(self, code: str, hits: list | None = None) -> str:
        h = (hits or lookup_stocks(self.db_path, code) or [{}])[0]
        sid = html_escape(h.get("stock_id") or code)
        name = html_escape(h.get("stock_name") or "")
        mkt = html_escape(h.get("market") or "EM")
        try:
            from stock_links import html_stock_anchor

            title = html_stock_anchor(h.get("stock_id") or code, h.get("stock_name") or "", self.db_path)
        except Exception:
            title = f"{sid} {name}".strip()
        return (
            f"{title}\n此檔是<b>興櫃</b>（市場 {mkt}）。"
            "沒有上市櫃集合競價日 K，線圖用櫃買官方<b>日均價</b>／日最高／日最低。"
            "盤後 16:30 會把當天興櫃日表寫進獨立表，不混進上市櫃海選。"
            "三大法人表興櫃沒有就不顯示。有日均價序列就一次出介紹圖／高低卡／產業圖／導航圖。要看日K按「K線」（奇摩股市同一檔）。"
        )

    def _cache_lookup_ctx(self, uid: str, code: str, ohlc) -> None:
        if not uid or not code or ohlc is None:
            return
        key = f"{uid}:{str(code).strip()}"
        self._lookup_ctx[key] = {"ohlc": ohlc, "ts": time.time()}
        if len(self._lookup_ctx) > 128:
            oldest = sorted(self._lookup_ctx.items(), key=lambda kv: kv[1].get("ts", 0))[:20]
            for k, _ in oldest:
                self._lookup_ctx.pop(k, None)

    def _get_lookup_ohlc(self, uid: str, code: str):
        key = f"{uid}:{str(code).strip()}"
        hit = self._lookup_ctx.get(key)
        if not hit:
            return None
        if time.time() - float(hit.get("ts") or 0) > 900:
            self._lookup_ctx.pop(key, None)
            return None
        return hit.get("ohlc")

    async def _prompt_decision_card(self, message, uid: str):
        from wayne_db import get_user_watchlist

        rows = get_user_watchlist(self.db_path, uid)
        kb = []
        for r in rows[:8]:
            c = str(r.get("stock_code") or "")
            n = str(r.get("stock_name") or "")
            if c:
                kb.append([InlineKeyboardButton(f"{c} {n}".strip()[:22], callback_data=f"d:{c}")])
        self._pending[self._pending_actor(message, uid=uid)] = "dcard"
        await message.reply_html(
            "還沒查過股票，沒有上一檔可重畫。\n"
            "請直接打代號，例如 "
            + LOOKUP_CODE_EXAMPLES_HTML
            + "；或點下面觀察清單。",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    async def decision_card_btn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        await self._enter_main_menu(update.message, uid)
        last = self._last_card.get(uid)
        if not last:
            await self._prompt_decision_card(update.message, uid)
            return
        status = await self._transient_status(update.message, "決策卡產製中…")
        try:
            await self._send_decision_card_quick(update.message, last, uid, skip_wait_msg=True)
        finally:
            await self._delete_message(status)

    def _menu_compact_on(self, uid: str) -> bool:
        """精簡鍵盤已取消；舊旗不論開過都當沒開。"""
        _ = uid
        return False

    def _set_menu_compact(self, uid: str, on: bool) -> None:
        """精簡鍵盤已取消；寫入無效。"""
        _ = uid, on
        return

    def _reply_menu(self, uid: str = ""):
        """兩排各六格；下排最右洞燭先機。偉權與哥哥同一套，沒有精簡。"""
        uid = str(uid or _ACTIVE_PHONE_UID.get() or "")
        biaoke_face = MENU_BTN_BIAOKE_FACE
        try:
            from biaoke_digest import biaoke_button_label

            biaoke_face = biaoke_button_label(
                str(uid or ""),
                str(getattr(self, "db_path", "") or ""),
            ) or MENU_BTN_BIAOKE_FACE
        except Exception:
            biaoke_face = MENU_BTN_BIAOKE_FACE
        row1 = [
            KeyboardButton(biaoke_face if t == MENU_BTN_BIAOKE_FACE else t)
            for t in MENU_ROW1
        ]
        rows = [
            row1,
            [KeyboardButton(t) for t in MENU_ROW2],
        ]
        placeholder = "打股名／代號"
        try:
            return ReplyKeyboardMarkup(
                rows,
                resize_keyboard=True,
                is_persistent=True,
                input_field_placeholder=placeholder,
            )
        except TypeError:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True)

    def _biaoke_reply_menu(self, uid: str = ""):
        """還在飆大：上排「飆大」同一顆改成「離開飆大」。"""
        row1 = [
            KeyboardButton(MENU_BTN_LEAVE_BIAOKE if t == MENU_BTN_BIAOKE_FACE else t)
            for t in MENU_ROW1
        ]
        rows = [
            row1,
            [KeyboardButton(t) for t in MENU_ROW2],
        ]
        placeholder = "還在飆大。打字＝問飆大。同一顆「離開飆大」回主選單。"
        try:
            return ReplyKeyboardMarkup(
                rows,
                resize_keyboard=True,
                is_persistent=True,
                input_field_placeholder=placeholder,
            )
        except TypeError:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True)

    def _dongzhu_reply_menu(self, uid: str = ""):
        """還在洞燭先機：下排最右同一顆改成「離開洞燭先機」。"""
        _ = uid
        row2 = [
            KeyboardButton(MENU_BTN_LEAVE_DONGZHU if t == MENU_BTN_DONGZHU else t)
            for t in MENU_ROW2
        ]
        rows = [
            [KeyboardButton(t) for t in MENU_ROW1],
            row2,
        ]
        placeholder = "還在洞燭。打代號＝能不能留。同一顆「離開洞燭先機」回主選單。"
        try:
            return ReplyKeyboardMarkup(
                rows,
                resize_keyboard=True,
                is_persistent=True,
                input_field_placeholder=placeholder,
            )
        except TypeError:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True)

    def _menu_uid_from_message(self, message, uid: str = "") -> str:
        if uid:
            return str(uid)
        ctx = str(_ACTIVE_PHONE_UID.get() or "")
        if ctx:
            return ctx
        try:
            return str(getattr(message.from_user, "id", "") or "")
        except Exception:
            return ""

    async def _pin_reply_menu(self, message) -> None:
        """把兩排主選單釘在輸入框區；訊息必須留下，刪掉會讓許多客戶端把鍵盤一起收掉。

        注意：Telegram editMessageText 只能改文字／Inline，不能更新 ReplyKeyboard。
        要換兩排按鈕內容，一定要新發一則帶 reply_markup 的訊息。
        """
        actor = self._actor_key(message)
        prev = getattr(self, "_menu_pin_msgs", None)
        if prev is None:
            self._menu_pin_msgs = {}
            prev = self._menu_pin_msgs
        uid = self._menu_uid_from_message(message)
        markup = self._reply_menu(uid)
        # Telegram 只能用新訊息掛 ReplyKeyboard；字愈短愈好，不要再講鍵盤位置。
        for text in ("·", "主選單"):
            try:
                pin = await message.reply_text(text, reply_markup=markup)
                self._menu_pin_msgs[actor] = pin
                return
            except Exception:
                continue
        logger.exception("pin reply menu 失敗")

    @staticmethod
    def _scratch_chart_path(charts_dir: str, code: str, kind: str, uid: str = "") -> str:
        """每人每次出圖用獨立檔名，避免哥哥／偉權同時查同一檔互相覆蓋。"""
        from wayne_navigator import unique_chart_path

        return unique_chart_path(charts_dir, code, kind, uid)

    def _menu_layout_ok(self, uid: str) -> bool:
        from wayne_db import get_cached_data

        row = get_cached_data(f"tg_menu_layout:{uid}", self.db_path)
        return bool(row and str(row.get("content") or "") == MENU_LAYOUT_VERSION)

    def _mark_menu_layout_ok(self, uid: str) -> None:
        from wayne_db import set_cached_data

        set_cached_data(
            f"tg_menu_layout:{uid}",
            "menu",
            MENU_LAYOUT_VERSION,
            db_path=self.db_path,
        )

    def _invalidate_menu_layout(self, uid: str) -> None:
        from wayne_db import set_cached_data

        set_cached_data(f"tg_menu_layout:{uid}", "menu", "0", db_path=self.db_path)

    async def _refresh_reply_menu(self, message, *, uid: str = "", silent: bool = False):
        """重掛兩排主選單。絕不送 Remove、也不刪帶鍵盤的訊息（刪了鍵盤會跟著消失）。

        silent 也必須新發帶 ReplyKeyboard 的訊息——edit 換不了按鈕（舊「選單」不會變「連買區」）。
        """
        await self._dismiss_menu_transients(self._actor_key(message, uid=uid))
        uid = str(uid or self._menu_uid_from_message(message))
        text = (
            "兩排已更新：第一排海選…資金，第二排當沖…洞燭先機。點輸入列旁邊四格 ⌨️。"
            if silent
            else "主選單已掛上（輸入列旁邊四格鍵盤圖示展開兩排；第二排最右洞燭先機）。"
        )
        try:
            pin = await message.reply_text(text, reply_markup=self._reply_menu(uid))
            actor = self._actor_key(message, uid=uid)
            if getattr(self, "_menu_pin_msgs", None) is None:
                self._menu_pin_msgs = {}
            self._menu_pin_msgs[actor] = pin
        except Exception:
            logger.exception("掛上新選單失敗")
            await self._pin_reply_menu(message)
        if uid:
            self._mark_menu_layout_ok(uid)

    async def _ensure_reply_menu_if_needed(
        self, message, uid: str, *, silent: bool = True
    ) -> None:
        """版面過期時刷新鍵盤；功能按鈕預設靜默，避免與專頁內容同時出現。"""
        if self._menu_layout_ok(uid):
            return
        await self._refresh_reply_menu(message, uid=uid, silent=silent)

    async def _force_reply_menu(self, message, uid: str) -> None:
        """/menu：一律重掛兩排鍵盤（不刪訊息，避免鍵盤被客戶端收掉）。"""
        self._invalidate_menu_layout(uid)
        await self._refresh_reply_menu(message, uid=uid, silent=False)

    def _streak_kind_inline(self, market: str = "ALL"):
        from buy_streak import KIND_BTN

        m = str(market or "ALL").strip() or "ALL"
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(KIND_BTN["foreign"], callback_data=f"fb:k:foreign:{m}"),
                    InlineKeyboardButton(KIND_BTN["trust"], callback_data=f"fb:k:trust:{m}"),
                    InlineKeyboardButton(KIND_BTN["both"], callback_data=f"fb:k:both:{m}"),
                ],
                [InlineKeyboardButton("回主選單", callback_data="fb:home")],
            ]
        )

    def _streak_days_inline(self, kind: str, market: str, days: list[int]):
        k = str(kind or "").strip()
        m = str(market or "").strip() or "ALL"
        rows = []
        row = []
        for n in days:
            row.append(InlineKeyboardButton(str(n), callback_data=f"fb:d:{k}:{m}:{int(n)}"))
            if len(row) == 5:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append(
            [
                InlineKeyboardButton("上一步", callback_data=f"fb:back:kind:{m}"),
                InlineKeyboardButton("回主選單", callback_data="fb:home"),
            ]
        )
        return InlineKeyboardMarkup(rows)

    def _streak_pick_inline(self, rows_data, *, kind: str, market: str, days: int, offset: int, has_prev: bool, has_next: bool):
        from buy_streak import PAGE_SIZE

        kb = []
        for item in rows_data:
            c = str(item.stock_id).strip()[:6]
            kb.append(
                [
                    InlineKeyboardButton(f"{c} {item.name}".strip()[:22], callback_data=f"k:{c}"),
                    InlineKeyboardButton("籌碼", callback_data=f"h:{c}"),
                ]
            )
        nav = []
        if has_prev:
            nav.append(
                InlineKeyboardButton(
                    "上一頁",
                    callback_data=f"fb:p:{kind}:{market}:{int(days)}:{max(0, int(offset) - PAGE_SIZE)}",
                )
            )
        if has_next:
            nav.append(
                InlineKeyboardButton(
                    "下一頁",
                    callback_data=f"fb:p:{kind}:{market}:{int(days)}:{int(offset) + PAGE_SIZE}",
                )
            )
        if nav:
            kb.append(nav)
        kb.append(
            [
                InlineKeyboardButton("上一步", callback_data=f"fb:back:days:{kind}:{market}"),
                InlineKeyboardButton("回主選單", callback_data="fb:home"),
            ]
        )
        return InlineKeyboardMarkup(kb)

    def _streak_em_inline(self):
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("改看上市櫃", callback_data="fb:uni:ALL")],
                [InlineKeyboardButton("興櫃海選", callback_data="em:go")],
                [InlineKeyboardButton("回主選單", callback_data="fb:home")],
            ]
        )

    async def _streak_send_step(self, message, html: str, *, inline) -> None:
        """精靈步驟只掛訊息下方 Inline；輸入列維持兩排主選單，不要複製同一排按鈕。"""
        await message.reply_html(html, reply_markup=inline, disable_web_page_preview=True)

    async def streak_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        actor = self._actor_key(update.message, uid=uid)
        self._pending.pop(actor, None)
        await self._dismiss_menu_transients(actor)
        await self._start_buy_streak(update.message, uid)

    async def _start_buy_streak(self, message, uid: str) -> None:
        actor = self._actor_key(message, uid=uid)
        await self._streak_show_kind(message, uid, actor, "ALL")

    async def _streak_show_kind(self, message, uid: str, actor: str, market: str = "ALL") -> None:
        from buy_streak import MARKET_ALL, MARKET_EM

        market = str(market or MARKET_ALL).strip().upper() or MARKET_ALL
        if market == MARKET_EM:
            await self._streak_show_emerging(message, uid, actor)
            return
        self._pending[actor] = f"fbuy:kind:{MARKET_ALL}"
        await self._streak_send_step(
            message,
            "<b>連買區</b>\n"
            "興櫃沒有官方法人表，這裡只看上市櫃。\n"
            "點訊息下方選哪一種連買。\n"
            "• <b>外資</b>＝外資連續買超\n"
            "• <b>投信</b>＝投信連續買超\n"
            "• <b>外資+投信</b>＝同一天兩家都買超，再連起來算天數",
            inline=self._streak_kind_inline(MARKET_ALL),
        )

    async def _streak_show_emerging(self, message, uid: str, actor: str) -> None:
        from buy_streak import EM_NO_CHIPS_HTML

        self._pending[actor] = "fbuy:em"
        await self._streak_send_step(
            message,
            EM_NO_CHIPS_HTML,
            inline=self._streak_em_inline(),
        )

    async def _restore_main_menu(self, message, uid: str) -> None:
        actor = self._actor_key(message, uid=uid)
        self._pending.pop(actor, None)
        text = "已回到兩排主選單。"
        await message.reply_html(text, reply_markup=self._reply_menu(uid))

    async def _leave_biaoke(self, message, uid: str) -> None:
        """用完飆大：清對話狀態、把鍵盤換回兩排主選單。兩人同一顆。"""
        actor = self._actor_key(message, uid=uid)
        self._pending.pop(actor, None)
        if uid:
            try:
                self._mark_menu_layout_ok(uid)
            except Exception:
                pass
        await message.reply_html(
            "已離開<b>飆大</b>。下面兩排是主選單。打代號會出介紹圖＋決策卡。",
            reply_markup=self._reply_menu(uid),
        )

    async def _leave_dongzhu(self, message, uid: str) -> None:
        """用完洞燭先機：清 pending、把鍵盤換回兩排主選單。兩人同一顆。"""
        actor = self._actor_key(message, uid=uid)
        self._pending.pop(actor, None)
        if uid:
            try:
                self._mark_menu_layout_ok(uid)
            except Exception:
                pass
        await message.reply_html(
            "已離開<b>洞燭先機</b>。下面兩排是主選單。打代號會出介紹圖＋決策卡。",
            reply_markup=self._reply_menu(uid),
        )

    async def _handle_buy_streak(
        self, message, uid: str, pending: str, text: str, *, actor: str
    ) -> bool:
        from buy_streak import (
            MARKET_ALL,
            MARKET_EM,
            PAGE_SIZE,
            parse_days,
            parse_kind,
            parse_stock_code,
            parse_universe,
        )

        parts = (pending or "").split(":")
        if not parts or parts[0] != "fbuy":
            return False

        if text == MENU_BTN_BACK_MAIN:
            await self._restore_main_menu(message, uid)
            return True
        if text == MENU_BTN_BACK_STEP:
            step = parts[1] if len(parts) > 1 else "uni"
            if step in ("uni",):
                await self._restore_main_menu(message, uid)
            elif step in ("kind", "em", "mkt"):
                await self._start_buy_streak(message, uid)
            elif step == "days":
                await self._streak_show_kind(message, uid, actor, MARKET_ALL)
            elif step == "pick":
                kind = parts[2] if len(parts) > 2 else ""
                market = parts[3] if len(parts) > 3 else MARKET_ALL
                await self._streak_show_days(message, uid, actor, kind, market)
            else:
                await self._start_buy_streak(message, uid)
            return True

        step = parts[1] if len(parts) > 1 else "uni"
        if step == "uni":
            uni = parse_universe(text)
            if uni == MARKET_EM:
                await self._streak_show_emerging(message, uid, actor)
                return True
            if uni == MARKET_ALL:
                await self._streak_show_kind(message, uid, actor, MARKET_ALL)
                return True
            kind = parse_kind(text)
            if kind:
                await self._streak_show_days(message, uid, actor, kind, MARKET_ALL)
                return True
            if _text_escapes_pending(text):
                return False
            await self._start_buy_streak(message, uid)
            return True

        if step == "em":
            uni = parse_universe(text)
            if uni == MARKET_ALL or text in ("改看上市櫃", "上市櫃"):
                await self._streak_show_kind(message, uid, actor, MARKET_ALL)
                return True
            if uni == MARKET_EM:
                await self._streak_show_emerging(message, uid, actor)
                return True
            if _text_escapes_pending(text):
                return False
            await self._streak_show_emerging(message, uid, actor)
            return True

        if step == "kind":
            uni = parse_universe(text)
            if uni == MARKET_EM:
                await self._streak_show_emerging(message, uid, actor)
                return True
            kind = parse_kind(text)
            if not kind:
                if _text_escapes_pending(text):
                    return False
                await self._streak_show_kind(message, uid, actor, MARKET_ALL)
                return True
            await self._streak_show_days(message, uid, actor, kind, MARKET_ALL)
            return True

        if step == "mkt":
            kind = parts[2] if len(parts) > 2 else ""
            await self._streak_show_days(message, uid, actor, kind, MARKET_ALL)
            return True

        if step == "days":
            kind = parts[2] if len(parts) > 2 else ""
            market = parts[3] if len(parts) > 3 else MARKET_ALL
            if str(market).upper() == MARKET_EM:
                await self._streak_show_emerging(message, uid, actor)
                return True
            days = parse_days(text)
            if days is None:
                if _text_escapes_pending(text):
                    return False
                await self._streak_show_days(message, uid, actor, kind, MARKET_ALL)
                return True
            await self._streak_show_stocks(
                message, uid, actor, kind, MARKET_ALL, days, offset=0
            )
            return True

        if step == "pick":
            kind = parts[2] if len(parts) > 2 else ""
            market = parts[3] if len(parts) > 3 else MARKET_ALL
            days = int(parts[4]) if len(parts) > 4 and str(parts[4]).isdigit() else 0
            offset = int(parts[5]) if len(parts) > 5 and str(parts[5]).isdigit() else 0
            if text == MENU_BTN_NEXT_PAGE:
                await self._streak_show_stocks(
                    message, uid, actor, kind, market, days, offset=offset + PAGE_SIZE
                )
                return True
            if text == MENU_BTN_PREV_PAGE:
                await self._streak_show_stocks(
                    message, uid, actor, kind, market, days, offset=max(0, offset - PAGE_SIZE)
                )
                return True
            code = parse_stock_code(text)
            if not code:
                hits = lookup_stocks(self.db_path, text.split()[0].strip()) if text else []
                if hits_need_picker(hits):
                    self._pending[actor] = f"fbuy:pick:{kind}:{market}:{days}:{offset}"
                    await message.reply_html(
                        self._hits_list_html(hits),
                        reply_markup=self._hits_keyboard(hits),
                        disable_web_page_preview=True,
                    )
                    return True
                if len(hits) == 1:
                    code = str(hits[0]["stock_id"])
            if not code:
                if _text_escapes_pending(text):
                    return False
                self._pending[actor] = f"fbuy:pick:{kind}:{market}:{days}:{offset}"
                await message.reply_html(
                    "請點名單下方的股名，或打代號。",
                    disable_web_page_preview=True,
                )
                return True
            self._pending[actor] = f"fbuy:pick:{kind}:{market}:{days}:{offset}"
            await self._send_card_to(message, code, uid)
            return True

        return False

    async def _handle_buy_streak_callback(self, q, uid: str, data: str) -> None:
        """連買精靈只掛訊息下方 Inline；輸入列維持兩排主選單。"""
        from buy_streak import MARKET_ALL, MARKET_EM

        actor = self._actor_key(q.message, uid=uid)
        parts = (data or "").split(":")
        try:
            await q.answer()
        except Exception:
            pass
        if len(parts) < 2:
            return
        op = parts[1]
        if op == "home":
            await self._restore_main_menu(q.message, uid)
            return
        if op == "uni":
            market = parts[2] if len(parts) > 2 else MARKET_ALL
            if str(market).upper() == MARKET_EM:
                await self._streak_show_emerging(q.message, uid, actor)
            else:
                await self._streak_show_kind(q.message, uid, actor, MARKET_ALL)
            return
        if op == "back":
            dest = parts[2] if len(parts) > 2 else "uni"
            if dest == "uni":
                await self._start_buy_streak(q.message, uid)
                return
            if dest == "kind":
                await self._streak_show_kind(q.message, uid, actor, MARKET_ALL)
                return
            if dest == "days":
                kind = parts[3] if len(parts) > 3 else ""
                market = parts[4] if len(parts) > 4 else MARKET_ALL
                await self._streak_show_days(q.message, uid, actor, kind, market)
                return
            if dest == "mkt":
                await self._start_buy_streak(q.message, uid)
                return
            await self._start_buy_streak(q.message, uid)
            return
        if op == "kind":
            await self._start_buy_streak(q.message, uid)
            return
        if op == "k" and len(parts) > 2:
            kind = parts[2]
            market = parts[3] if len(parts) > 3 else MARKET_ALL
            if kind not in ("foreign", "trust", "both"):
                await self._start_buy_streak(q.message, uid)
                return
            if str(market).upper() == MARKET_EM:
                await self._streak_show_emerging(q.message, uid, actor)
                return
            await self._streak_show_days(q.message, uid, actor, kind, MARKET_ALL)
            return
        if op == "m" and len(parts) > 3:
            kind = parts[2]
            await self._streak_show_days(q.message, uid, actor, kind, MARKET_ALL)
            return
        if op == "d" and len(parts) > 4:
            kind = parts[2]
            market = parts[3]
            try:
                days = int(parts[4])
            except ValueError:
                days = 0
            if days < 2:
                await self._streak_show_days(q.message, uid, actor, kind, market)
                return
            await self._streak_show_stocks(
                q.message, uid, actor, kind, market, days, offset=0
            )
            return
        if op == "p" and len(parts) > 5:
            kind = parts[2]
            market = parts[3]
            try:
                days = int(parts[4])
                offset = int(parts[5])
            except ValueError:
                await self._streak_show_days(q.message, uid, actor, kind, market)
                return
            await self._streak_show_stocks(
                q.message, uid, actor, kind, market, days, offset=max(0, offset)
            )
            return

    async def _streak_show_days(self, message, uid: str, actor: str, kind: str, market: str) -> None:
        from buy_streak import KIND_LABEL, MARKET_ALL, MARKET_EM, load_snapshot

        market = str(market or MARKET_ALL).strip().upper() or MARKET_ALL
        if market == MARKET_EM:
            await self._streak_show_emerging(message, uid, actor)
            return
        market = MARKET_ALL
        status = await self._transient_status(message, "整理連買名單…")
        try:
            snap = await asyncio.wait_for(
                asyncio.to_thread(load_snapshot, self.db_path, kind, market),
                timeout=25.0,
            )
        except Exception:
            logger.exception("連買名單失敗 kind=%s market=%s", kind, market)
            await self._delete_message(status)
            await self._streak_send_step(
                message,
                PHONE_BUSY,
                inline=self._streak_kind_inline(MARKET_ALL),
            )
            self._pending[actor] = f"fbuy:kind:{MARKET_ALL}"
            return
        await self._delete_message(status)
        self._pending[actor] = f"fbuy:days:{kind}:{market}"
        days = snap.days_menu()
        as_of = snap.as_of
        try:
            from trading_calendar import format_trading_date_zh

            as_of_s = format_trading_date_zh(as_of)
        except Exception:
            as_of_s = f"{as_of[:4]}/{as_of[4:6]}/{as_of[6:8]}" if len(as_of) == 8 else (as_of or "—")
        title = f"<b>{KIND_LABEL.get(kind, kind)} · 上市櫃</b>"
        if not days:
            await self._streak_send_step(
                message,
                f"{title}\n截至 {as_of_s}。目前沒有連續買超 2 天以上的股票。",
                inline=self._streak_kind_inline(MARKET_ALL),
            )
            self._pending[actor] = f"fbuy:kind:{MARKET_ALL}"
            return
        await self._streak_send_step(
            message,
            f"{title}\n"
            f"截至 {as_of_s} 官方籌碼。目前最長 <b>{snap.max_days}</b> 天。\n"
            "請點訊息下方天數。名單是「剛好連買這麼多天」（不是以上）。",
            inline=self._streak_days_inline(kind, market, days),
        )

    async def _streak_show_stocks(
        self,
        message,
        uid: str,
        actor: str,
        kind: str,
        market: str,
        days: int,
        *,
        offset: int = 0,
    ) -> None:
        from buy_streak import PAGE_SIZE, MARKET_ALL, MARKET_EM, format_list_html, load_snapshot, page_bounds

        market = str(market or MARKET_ALL).strip().upper() or MARKET_ALL
        if market == MARKET_EM:
            await self._streak_show_emerging(message, uid, actor)
            return
        market = MARKET_ALL

        status = await self._transient_status(message, "列出連買股票…")
        try:
            snap = await asyncio.wait_for(
                asyncio.to_thread(load_snapshot, self.db_path, kind, market),
                timeout=25.0,
            )
        except Exception:
            logger.exception("連買清單失敗")
            await self._delete_message(status)
            await message.reply_html(PHONE_BUSY, reply_markup=self._keyboard())
            return
        await self._delete_message(status)
        rows = snap.stocks(days)
        off, has_prev, has_next = page_bounds(len(rows), offset, PAGE_SIZE)
        chunk = rows[off : off + PAGE_SIZE]
        self._pending[actor] = f"fbuy:pick:{kind}:{market}:{days}:{off}"
        html = format_list_html(snap, days, self.db_path, offset=off, limit=PAGE_SIZE)
        inline = self._streak_pick_inline(
            chunk,
            kind=kind,
            market=market,
            days=days,
            offset=off,
            has_prev=has_prev,
            has_next=has_next,
        )
        try:
            await message.reply_html(
                html,
                reply_markup=inline,
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("連買清單 HTML 失敗")
            await message.reply_html(
                f"連買 {days} 天 {len(chunk)} 檔。請點訊息下方股名看圖。",
                reply_markup=inline,
                disable_web_page_preview=True,
            )

    def _q(self, topic: str):
        """說明已取消，不再畫鈕。舊氣泡 ?: 在 callback 靜音。"""
        _ = topic
        return None

    def _help_nav_keyboard(self, active: str = "guide"):
        """說明已取消；舊氣泡 hx／?: 仍靜音。"""
        _ = active
        return InlineKeyboardMarkup([])

    async def _reply_help_topic(self, message, topic: str = "guide", *, edit_target=None) -> None:
        _ = (message, topic, edit_target)
        return

    def _keyboard(self, uid: str = ""):
        """錯誤／提示改釘回兩排主選單。直立式「說明／主選單」已廢。"""
        return self._reply_menu(uid)

    def _hub_keyboard(
        self,
        code: str,
        topic: str = "stock",
        *,
        em: bool = False,
        news: dict | None = None,
    ):
        """查股圖下鈕：K線／籌碼／營收／觀察／記買入。產業圖與導航圖已在四格相簿，不再放鈕。"""
        _ = topic
        c = str(code).strip()[:6]
        news = news or {}
        news_label = str(news.get("label") or "").strip()
        news_url = _http_url(news.get("url") or "")
        k_url = ""
        try:
            from stock_links import kline_page_url

            dbp = getattr(self, "db_path", None)
            k_url = _http_url(kline_page_url(c, dbp))
        except Exception:
            k_url = ""
        kline = InlineKeyboardButton("K線", url=k_url) if k_url else None
        news_btn = (
            InlineKeyboardButton(news_label[:16], url=news_url)
            if news_label and news_url
            else None
        )
        watch = InlineKeyboardButton("觀察", callback_data=f"w:{c}")
        buy = InlineKeyboardButton("記買入", callback_data=f"b:{c}")
        actions = [watch, buy]
        if em:
            rows = []
            if kline:
                rows.append([kline])
            rows.append(actions)
            return InlineKeyboardMarkup(rows)
        etf = False
        try:
            from universe import is_etf_asset

            etf = is_etf_asset(stock_id=c)
        except Exception:
            etf = False
        chips = InlineKeyboardButton("籌碼", callback_data=f"h:{c}")
        fund = None if etf else InlineKeyboardButton("營收", callback_data=f"f:{c}")
        row1 = []
        if news_btn:
            row1.append(news_btn)
        if kline:
            row1.append(kline)
        row1.append(chips)
        if fund and len(row1) < 3:
            row1.append(fund)
            return InlineKeyboardMarkup([row1, actions])
        rows = [row1]
        if fund:
            rows.append([fund, watch, buy])
        else:
            rows.append(actions)
        return InlineKeyboardMarkup(rows)

    def _stock_action_row(self, code: str, name: str = "", idx: int = 0):
        """左鍵寫代號＋股名（點下去看這檔）；右鍵加觀察。"""
        from tg_layout import stock_btn_label

        c = str(code or "").strip()[:6]
        label = stock_btn_label(c, name or "")
        return [
            InlineKeyboardButton(label, callback_data=f"k:{c}"),
            InlineKeyboardButton("➕", callback_data=f"w:{c}"),
        ]

    def _lookup_like_action_row(self, code: str, name: str = ""):
        """剛脫離零：看這檔／觀察／記買入。洞燭推薦列用 _dongzhu_pick_rows。"""
        from tg_layout import stock_btn_label

        c = str(code or "").strip()[:6]
        label = stock_btn_label(c, name or "")
        return [
            InlineKeyboardButton(label, callback_data=f"k:{c}"),
            InlineKeyboardButton("觀察", callback_data=f"w:{c}"),
            InlineKeyboardButton("記買入", callback_data=f"b:{c}"),
        ]

    def _dongzhu_card_row(self, code: str):
        """產業／高低溫度卡／介紹卡。不是觀察、不是記買入。"""
        c = str(code or "").strip()[:6]
        return [
            InlineKeyboardButton("產業", callback_data=f"n:{c}"),
            InlineKeyboardButton("高低溫度卡", callback_data=f"d:{c}"),
            InlineKeyboardButton("介紹卡", callback_data=f"i:{c}"),
        ]

    def _dongzhu_pick_rows(self, code: str, name: str = "", *, win_btn: str = ""):
        """一行四鈕：代號股名（買點可加勝％）｜產業｜高低溫度卡｜介紹卡。"""
        from tg_layout import stock_btn_label

        c = str(code or "").strip()[:6]
        if not c:
            return []
        # 四鈕並排：代號名略縮；買點才加短勝率標，觀察／落後不加。
        win = str(win_btn or "").strip()
        budget = 22 if win else 28
        label = stock_btn_label(c, name or "", max_bytes=budget)
        if win:
            label = f"{label} {win}".strip()
        return [
            [
                InlineKeyboardButton(label, callback_data=f"k:{c}"),
                *self._dongzhu_card_row(c),
            ]
        ]

    def _dongzhu_held_sids(self, uid: str):
        """這人持股代號。偉權／哥哥分開，功能同一套。"""
        try:
            from wayne_db import get_user_portfolio

            rows = get_user_portfolio(self.db_path, str(uid or "")) or []
        except Exception:
            return []
        out = []
        for r in rows:
            sid = str((r or {}).get("stock_code") or (r or {}).get("stock_id") or "").strip()
            if sid:
                out.append(sid)
        return out

    def _dongzhu_picks_keyboard(self, picks=None):
        rows = []
        for pair in list(picks or [])[:MAX_PICK_INLINE_ROWS]:
            win_btn = ""
            if isinstance(pair, (list, tuple)):
                code = str((pair[0] if pair else "") or "").strip()
                name = str((pair[1] if len(pair) > 1 else "") or "")
                if len(pair) > 2 and pair[2]:
                    win_btn = str(pair[2]).strip()
            else:
                code = str(pair or "").strip()
                name = ""
            rows.extend(self._dongzhu_pick_rows(code, name, win_btn=win_btn))
        if not rows:
            return None
        return InlineKeyboardMarkup(rows)

    def _dongzhu_hold_keyboard(self, code: str):
        c = str(code or "").strip()[:6]
        if not c:
            return None
        return InlineKeyboardMarkup([self._dongzhu_card_row(c)])

    @staticmethod
    def _leave_zero_case_html(
        title: str, subtitle: str, cards: str, extra: str = ""
    ) -> str:
        """案件紅邊框。Telegram 鍵盤不能上色，結果頁用紅角標示。"""
        bits = [
            "🟥────────────────────────🟥",
            f"<b>{html_escape(title)}</b>",
            f"<i>{html_escape(subtitle)}</i>",
        ]
        if extra:
            bits.append(extra)
        bits.append(cards)
        bits.append("🟥────────────────────────🟥")
        return "\n".join(x for x in bits if x)

    def _leave_zero_section_keyboard(self, picks=None, include_menu: bool = False):
        rows = []
        for i, pair in enumerate(list(picks or [])[:MAX_PICK_INLINE_ROWS], start=1):
            if isinstance(pair, (list, tuple)):
                code = str((pair[0] if pair else "") or "").strip()
                name = str((pair[1] if len(pair) > 1 else "") or "")
            else:
                code = str(pair or "").strip()
                name = ""
            if code:
                rows.append(self._lookup_like_action_row(code, name))
        if not rows:
            return None
        return InlineKeyboardMarkup(rows)

    def _screening_section_keyboard(
        self,
        line_pack_id: str = None,
        include_menu: bool = False,
        picks=None,
    ):
        """海選整區：左鍵看這檔、右鍵加觀察。"""
        rows = []
        for i, pair in enumerate(list(picks or [])[:MAX_PICK_INLINE_ROWS], start=1):
            if isinstance(pair, (list, tuple)):
                code = str((pair[0] if pair else "") or "").strip()
                name = str((pair[1] if len(pair) > 1 else "") or "")
            else:
                code = str(pair or "").strip()
                name = ""
            if code:
                rows.append(self._stock_action_row(code, name, idx=i))
        if not rows:
            return None
        return InlineKeyboardMarkup(rows)

    def _picks_keyboard(
        self,
        picks,
        include_menu: bool = False,
        topic: str = "screen",
        line_pack_id: str = None,
    ):
        rows = []
        for i, (code, name) in enumerate((picks or [])[:MAX_PICK_INLINE_ROWS], start=1):
            c = str(code or "").strip()
            if not c:
                continue
            rows.append(self._stock_action_row(c, name or "", idx=i))
        if not rows:
            return None
        return InlineKeyboardMarkup(rows)

    def _persist_bucket_line_pack(self, bucket_key: str, rows: list) -> None:
        return

    def _hits_keyboard(self, hits):
        """名稱撞名時當選擇器：按鈕寫代號＋股名（不是奇摩連結）。"""
        rows = []
        for h in hits[:8]:
            if h.get("category_choice"):
                pick = str(h.get("category_pick") or h.get("stock_id") or "").strip()
                label = str(h.get("stock_name") or pick).strip()[:18] or pick
                if not pick:
                    continue
                rows.append([InlineKeyboardButton(label, callback_data=f"e:{pick}")])
                continue
            c = str(h.get("stock_id") or "")
            n = str(h.get("stock_name") or "")
            if not c:
                continue
            label = f"{c} {n}".strip()[:16] or c
            rows.append(
                [
                    InlineKeyboardButton(label, callback_data=f"k:{c}"),
                    InlineKeyboardButton("➕", callback_data=f"w:{c}"),
                ]
            )
        return InlineKeyboardMarkup(rows) if rows else None

    def _biaoke_hits_keyboard(self, hits):
        """飆大撞名選擇器：點了仍問飆大，不准走查股兩張圖。"""
        rows = []
        pair = []
        for h in (hits or [])[:8]:
            c = str(h.get("stock_id") or "").strip()
            n = str(h.get("stock_name") or "").strip()
            if not c:
                continue
            label = f"{c} {n}".strip()[:16] or c
            pair.append(InlineKeyboardButton(label, callback_data=f"bkq:{c}"))
            if len(pair) == 2:
                rows.append(pair)
                pair = []
        if pair:
            rows.append(pair)
        return InlineKeyboardMarkup(rows) if rows else None

    def _biaoke_hub_markup(self, ask: str = ""):
        """進去就能點：大盤、查個股。官方日K有檔才加一顆。"""
        if not TELEGRAM_AVAILABLE:
            return None
        rows = [
            [
                InlineKeyboardButton("大盤", callback_data="bk:mkt"),
                InlineKeyboardButton("查個股", callback_data="bk:ask"),
            ]
        ]
        extra = self._biaoke_dayk_markup(ask)
        if extra is not None:
            rows.extend(list(extra.inline_keyboard or []))
        return InlineKeyboardMarkup(rows)

    def _biaoke_dayk_markup(self, ask: str = ""):
        """開口那則下一顆：點了送官方日K結構圖，不走查股兩張圖。"""
        if not TELEGRAM_AVAILABLE:
            return None
        q = (ask or "").strip()
        sid = ""
        name = ""
        try:
            from biaoke_brain import is_market_question
            from biaoke_chain import _resolve_sid
            from biaoke_wave import is_wave_question

            if q:
                sid, name = _resolve_sid(self.db_path, q)
            if sid:
                name = name or sid
            elif not q or is_wave_question(q) or is_market_question(q):
                sid, name = "TWII", "加權"
        except Exception:
            logger.exception("官方日K鈕對檔略過")
            return None
        if not sid:
            return None
        label = f"官方日K {name}".strip()[:16]
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton(label, callback_data=f"bkdk:{sid}")]]
        )

    def _hits_list_html(self, hits, lead: str = "") -> str:
        """多檔時訊息裡列出藍字股名，按鈕序號才對得上。"""
        try:
            from stock_links import html_stock_anchor
        except Exception:
            html_stock_anchor = None
        lines = [
            lead or lookup_picker_lead(hits)
        ]
        for i, h in enumerate((hits or [])[:8], start=1):
            sid = str(h.get("stock_id") or "")
            sname = str(h.get("stock_name") or "")
            if h.get("category_choice"):
                lines.append(f"{i}. {html_escape(sname or sid)}")
                continue
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
                ]
            )
            kb.append(
                [
                    InlineKeyboardButton("買入", callback_data=f"b:{c}"),
                    InlineKeyboardButton("刪", callback_data=f"rw:{c}"),
                ]
            )
        return InlineKeyboardMarkup(kb)

    def _render_watch(self, rows):
        shown = list(rows or [])[: self.WATCH_LIST_LIMIT]
        lines = [
            "<b>觀察清單（自選，還沒買也可以）</b>",
            "加入：打股名按 ➕，或海選／當沖旁的 ➕。刪除：按該檔「刪」。",
        ]
        if not shown:
            lines.append("<i>目前是空的，這很正常。請先打一檔股票名稱。</i>")
            return "\n".join(lines), None
        flows = {}
        try:
            from money_flow import industry_flows_for_stocks

            flows = industry_flows_for_stocks(
                self.db_path,
                [str(r.get("stock_code") or "") for r in shown],
            )
        except Exception:
            flows = {}
        for r in shown:
            c = str(r.get("stock_code") or "")
            n = str(r.get("stock_name") or "")
            try:
                from stock_links import html_stock_anchor

                lines.append(f"• {html_stock_anchor(c, n, self.db_path)}")
            except Exception:
                lines.append(f"• {html_escape(c)} {html_escape(n)}".rstrip())
            flow = str((flows or {}).get(c) or "").strip()
            if flow:
                from tg_layout import kv_compact

                lines.append(kv_compact("資金", flow.rstrip("。")))
        extra = len(rows or []) - len(shown)
        if extra > 0:
            lines.append(f"<i>只顯示前 {self.WATCH_LIST_LIMIT} 檔，其餘 {extra} 檔請先刪再加。</i>")
        lines.append("下面每檔兩排：上＝看這檔／籌碼；下＝記買入／刪。")
        return "\n".join(lines), self._watch_list_keyboard(shown)

    def _ai_desk_keyboard(self, positions=None):
        """AI 倉專用鍵盤：持倉可點進去查圖；不含真實持股賣出。"""
        from tg_layout import stock_btn_label

        kb = []
        for p in (positions or [])[:3]:
            c = str(p.get("stock_id") or p.get("stock_code") or "").strip()
            if not c:
                continue
            n = str(p.get("stock_name") or "")
            kb.append(
                [InlineKeyboardButton(stock_btn_label(c, n), callback_data=f"k:{c}")]
            )
        kb.append(
            [
                InlineKeyboardButton("AI操盤", callback_data="ai_run"),
                InlineKeyboardButton("進化", callback_data="ai_evolve"),
            ]
        )
        return InlineKeyboardMarkup(kb)

    def _portfolio_keyboard(self, holdings):
        from tg_layout import stock_btn_label

        kb = []
        for h in (holdings or [])[:8]:
            c = str(h.get("stock_code") or h.get("stock_id") or "")
            if not c:
                continue
            n = str(h.get("stock_name") or "")
            kb.append(
                [
                    InlineKeyboardButton(stock_btn_label(c, n), callback_data=f"k:{c}"),
                    InlineKeyboardButton("賣出", callback_data=f"x:{c}"),
                ]
            )
        kb.append(
            [
                InlineKeyboardButton("成交", callback_data="tj:trades"),
                InlineKeyboardButton("復盤", callback_data="tj:review"),
                InlineKeyboardButton("AI倉", callback_data="ai_view"),
            ]
        )
        return InlineKeyboardMarkup(kb)

    async def _send_trade_journal(self, message, uid: str, *, review: bool = False) -> None:
        fn = format_user_review_html if review else format_user_trades_html
        html = await asyncio.to_thread(fn, self.db_path, uid)
        parts = chunk_telegram_html(html, reflow=True)
        holdings = get_user_portfolio(self.db_path, uid)
        for i, part in enumerate(parts):
            kb = self._portfolio_keyboard(holdings) if i == len(parts) - 1 else None
            await message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)

    def _held_lots_for(self, uid: str, code: str):
        """手記持股張數；查不到回 None。"""
        if not uid or not code:
            return None
        try:
            for h in get_user_portfolio(self.db_path, uid) or []:
                if str(h.get("stock_code") or h.get("stock_id") or "") == str(code).strip():
                    return float(h.get("shares") or 0)
        except Exception:
            return None
        return None

    def _parse_buy_text(self, text: str, code: str = "", uid: str = "") -> tuple:
        """回傳 (code, lots, price) 或 (None, None, None)。"""
        parts = normalize_trade_tokens(text)
        if code and len(parts) >= 3 and parts[0] == str(code).strip():
            parts = parts[1:]
            text = " ".join(parts)
        qty_tok = ""
        held_lots = None
        if not code and len(parts) >= 3:
            raw, lots_s, price_s = parts[0], parts[1], parts[2]
            hits = lookup_stocks(self.db_path, raw)
            code = hits[0]["stock_id"] if hits else raw
            try:
                price = float(price_s)
            except ValueError:
                return None, None, None
            if not code:
                return None, None, None
            if uid:
                held_lots = self._held_lots_for(uid, code)
            default_unit = "股" if held_is_odd_lot_only(held_lots) else "張"
            lots = parse_qty_to_lots(lots_s, default_unit=default_unit)
            if lots is None:
                return None, None, None
            qty_tok = lots_s
        else:
            if uid and code:
                held_lots = self._held_lots_for(uid, code)
            bare_shares = held_is_odd_lot_only(held_lots)
            lots, price = parse_lots_price(
                text, default_lots=1.0, bare_qty_is_shares=bare_shares
            )
            if lots is None or price is None or not code:
                return None, None, None
            if len(parts) >= 2:
                qty_tok = parts[0]
        if lots and not qty_token_has_unit(qty_tok):
            lots = coerce_bare_qty_if_share_count(
                lots, held_lots, allow_unheld=True
            )
        return code, lots, price

    def _parse_sell_text(self, text: str, code: str = "", held_lots=None, uid: str = "") -> tuple:
        """回傳 (code, lots, price)；lots=0 表示全賣。"""
        parts = normalize_trade_tokens(text)
        if code and len(parts) >= 3 and parts[0] == str(code).strip():
            parts = parts[1:]
            text = " ".join(parts)
        qty_tok = ""
        if not code and len(parts) >= 3:
            raw, lots_s, price_s = parts[0], parts[1], parts[2]
            hits = lookup_stocks(self.db_path, raw)
            code = hits[0]["stock_id"] if hits else raw
            try:
                price = float(price_s)
            except ValueError:
                return None, None, None
            if not code:
                return None, None, None
            if held_lots is None and uid:
                held_lots = self._held_lots_for(uid, code)
            default_unit = "股" if held_is_odd_lot_only(held_lots) else "張"
            lots = parse_qty_to_lots(lots_s, default_unit=default_unit)
            if lots is None:
                return None, None, None
            qty_tok = lots_s
        else:
            if held_lots is None and uid and code:
                held_lots = self._held_lots_for(uid, code)
            bare_shares = held_is_odd_lot_only(held_lots)
            lots, price = parse_lots_price(
                text, price_only_sell_all=True, bare_qty_is_shares=bare_shares
            )
            if price is None or not code:
                return None, None, None
            if len(parts) >= 2:
                qty_tok = parts[0]
        if lots and held_lots is not None and not qty_token_has_unit(qty_tok):
            lots = coerce_bare_qty_if_share_count(lots, held_lots)
        return code, float(lots or 0), price

    def _screening_payload(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        from screening_engine import EMERGING_PUSH_SPECS, format_screening_payload

        parts = result.get("payload")
        if parts:
            return parts
        as_of = result.get("as_of") or result.get("date") or ""
        if str(result.get("universe") or "").upper() == "EM":
            return format_screening_payload(
                {
                    "leave_zero": result.get("leave_zero") or [],
                    "golden_buy": result.get("golden_buy") or [],
                },
                as_of,
                title="WayneBot 興櫃海選",
                specs=EMERGING_PUSH_SPECS,
            )
        return format_screening_payload(result.get("results") or {}, as_of)

    async def _reply_screening_payload(self, message, result: Dict[str, Any]):
        parts = self._screening_payload(result)
        actor = self._actor_key(message)
        if not parts:
            await message.reply_html(
                result.get("message") or self._format_screening_html(result),
                reply_markup=self._keyboard(),
                disable_web_page_preview=True,
            )
            return
        last = len(parts) - 1
        for i, part in enumerate(parts):
            pack_id = str(part.get("line_pack_id") or "")
            chunks = chunk_telegram_html(part.get("html") or "", 3500)
            if not chunks:
                continue
            for j, chunk in enumerate(chunks):
                is_last_chunk = j == len(chunks) - 1
                is_last_part = i == last
                kb = self._screening_section_keyboard(
                    line_pack_id=part.get("line_pack_id") if is_last_chunk else None,
                    include_menu=is_last_part and is_last_chunk,
                    picks=part.get("picks") if is_last_chunk else None,
                )
                sent = await message.reply_html(
                    chunk,
                    reply_markup=kb,
                    disable_web_page_preview=True,
                )
                if pack_id:
                    self._track_screening_msg(actor, pack_id, sent)
            await asyncio.sleep(0.25)

    def _mark_gif_path(self, key: str) -> str:
        if not key:
            return ""
        try:
            from telegram_cat_marks import ensure_mark_gif

            return ensure_mark_gif(key) or ""
        except Exception:
            return ""

    def _cat_sticker_id(self, key: str) -> str:
        """舊椅子貼紙不再送。保留函式以免測試／排程舊呼叫炸掉。"""
        return ""

    def _send_animation(self, chat_id: str, path: str):
        try:
            import requests

            with open(path, "rb") as fh:
                requests.post(
                    f"https://api.telegram.org/bot{self.token}/sendAnimation",
                    data={"chat_id": chat_id},
                    files={"animation": fh},
                    timeout=30,
                )
        except Exception as e:
            logger.error("send_animation: %s", e)

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
                payload["reply_markup"] = self._reply_menu(str(chat_id)).to_dict()
            resp = requests.post(url, json=payload, timeout=20)
            if getattr(resp, "status_code", 0) != 200:
                logger.error(
                    "send_html HTTP %s body=%s",
                    getattr(resp, "status_code", "?"),
                    (getattr(resp, "text", None) or "")[:240],
                )
                return False
            return True
        except Exception as e:
            logger.error("send_html: %s", e)
            return False

    def _send_plain(self, chat_id: str, text: str, reply_markup=None):
        try:
            import requests

            payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup.to_dict()
            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json=payload,
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

    def send_screening_report(self, result: Dict[str, Any], chat_id: str | None = None):
        dest = str(chat_id or self.chat_id or "").strip()
        if not self.token or not dest:
            logger.warning("海選未寄：token 或 chat_id 空")
            return False
        import time as _t

        parts = self._screening_payload(result)
        ok = True
        if not parts:
            ok = bool(self._send_html(dest, result.get("message") or self._format_screening_html(result)))
        else:
            last = len(parts) - 1
            n_ok = 0
            n_try = 0
            for i, part in enumerate(parts):
                chunks = chunk_telegram_html(part.get("html") or "", 3500)
                for j, chunk in enumerate(chunks):
                    is_last_chunk = j == len(chunks) - 1
                    is_last_part = i == last
                    kb = self._screening_section_keyboard(
                        line_pack_id=part.get("line_pack_id") if is_last_chunk else None,
                        include_menu=is_last_part and is_last_chunk,
                        picks=part.get("picks") if is_last_chunk else None,
                    )
                    n_try += 1
                    if self._send_html(
                        dest,
                        chunk,
                        extra_keyboard=kb,
                        attach_menu=False,
                    ):
                        n_ok += 1
                    else:
                        ok = False
                _t.sleep(0.25)
            logger.info("海選本文送出 %d/%d 則", n_ok, n_try)
        return ok

    def _send_stock_card_by_code(self, chat_id: str, code: str, name: str = "", uid: str = ""):
        if not code:
            return
        from wayne_navigator import generate_card_with_chart

        try:
            packed = generate_card_with_chart(
                code, self.db_path, self.charts_dir, uid=uid or str(chat_id or "0")
            )
            card_img = packed[1] if len(packed) > 1 else ""
            glance = packed[3] if len(packed) > 3 else ""
        except Exception:
            card_img = ""
            glance = ""
        if glance:
            self._send_photo(chat_id, glance, caption=html_escape(name or code))
        for path in self._card_photo_paths(card_img):
            self._send_photo(chat_id, path, caption=html_escape(name or code))
        self._send_html(
            chat_id, html_escape(name or code), extra_keyboard=self._hub_keyboard(code), attach_menu=False
        )

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
        uid = str(update.effective_user.id)
        self._touch_user(uid, getattr(update.effective_user, "first_name", "") or "")
        await update.message.reply_html(
            reflow_telegram_html(
                "<b>WayneBot</b>\n"
                "主選單在輸入列旁邊<b>四格鍵盤圖示 ⌨️</b>展開的兩排（不附在訊息最下面）。\n"
                "\n"
                "<b>第一次用，先做這三步</b>\n"
                "1　點輸入列旁邊四格 ⌨️ 叫出兩排（不見就打 /menu）\n"
                "2　直接打代號看圖，例如 "
                + LOOKUP_CODE_EXAMPLES_HTML
                + "\n"
                "3　四張圖同一則；圖下剩籌碼／營收／K線，不在右側四格鍵盤\n"
                "\n"
                "主選單不見就打 /menu。\n"
                "這是私人 Bot，只認指定帳號。偉權與哥哥已各用各的，持股各看各的。不要拉進同一個群組。不必再分享邀請。\n"
            ),
        )
        await self._force_reply_menu(update.message, str(update.effective_user.id))

    async def backup_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """把這人的持股／觀察／成交／AI 倉匯出成 JSON。不要上傳 GitHub。"""
        if not update.message:
            return
        import json
        from io import BytesIO

        uid = str(update.effective_user.id)
        if not telegram_uid_allowed(uid):
            await update.message.reply_text("這是私人 Bot")
            return
        payload = await asyncio.to_thread(export_private_user_payload, self.db_path, uid)
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        bio = BytesIO(raw)
        try:
            from config import taipei_today_str

            ymd = taipei_today_str()
        except Exception:
            ymd = time.strftime("%Y%m%d")
        fname = f"waynebot_private_{uid}_{ymd}.json"
        await update.message.reply_document(
            document=bio,
            filename=fname,
            caption="私人備份：持股／觀察／成交／AI倉。放自己電腦或加密雲端，不要上傳 GitHub。",
        )

    async def code_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """偉權／哥哥手機回目前這次更新：功能名的更新、全數完成、與畫面同一串代碼。"""
        if not update.message:
            return
        await update.message.reply_text(phone_code_reply())

    async def menu_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        self._touch_user(uid, getattr(update.effective_user, "first_name", "") or "")
        await self._force_reply_menu(update.message, uid)

    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        return

    @staticmethod
    def _message_is_photo(message) -> bool:
        """真的是圖訊息才算。MagicMock.photo 不能當真。"""
        photo = getattr(message, "photo", None)
        return isinstance(photo, (list, tuple)) and len(photo) > 0

    def _picture_guide_keyboard(self, page: int, n: int):
        _ = (page, n)
        return InlineKeyboardMarkup([])

    async def _show_picture_guide_page(
        self, message, page: int, *, edit: bool, from_page: int | None = None
    ) -> None:
        """圖文說明已取消；舊氣泡 pg: 在 callback 靜音。"""
        _ = (message, page, edit, from_page)
        return

    async def _send_picture_guide(self, message) -> None:
        """圖文說明已取消；打「圖文」靜音。"""
        _ = message
        return

    @staticmethod
    def _format_elapsed(sec: int) -> str:
        sec = max(0, int(sec))
        m, s = divmod(sec, 60)
        return f"{m}:{s:02d}" if m else f"{s} 秒"

    @classmethod
    def _screening_progress_text(cls, elapsed_sec: int, *, done: bool = False) -> str:
        if done:
            return WayneTelegramBot._wait_bubble("海選完成", elapsed_sec, now="推送名單")
        now = "掃描全市場"
        rest = "黃金買點／重點觀察"
        return WayneTelegramBot._wait_bubble(
            "海選進行中", elapsed_sec, now=now, rest=rest, fill_sec=300.0
        )

    async def _run_manual_screening(self, message, uid: str = ""):
        """手動海選：進度提示 + 逾時保護 + 完成後提示當沖可用。"""
        uid = str(uid or self._menu_uid_from_message(message) or "")
        actor = self._actor_key(message, uid=uid)
        if actor in self._screening_running:
            await message.reply_text(
                "海選進行中，請稍候完成後再按。",
                reply_markup=self._reply_menu(uid),
            )
            return
        async with self._screening_gate:
            if self._screening_global_owner and self._screening_global_owner != actor:
                await message.reply_html(
                    "海選正在掃描全市場（可能是你或家人剛按的），約 2～5 分鐘。\n"
                    "完成後你再按一次「海選」讀快取即可；名單是同一份，"
                    "不會和對方的持股／觀察／連買混在一起。",
                    reply_markup=self._reply_menu(uid),
                )
                return
            self._screening_global_owner = actor
        self._screening_running.add(actor)
        await self._dismiss_menu_transients(actor)
        hub = self._reply_menu(uid)
        # 進度泡泡絕不可掛 ReplyKeyboard：刪掉時許多客戶端會把兩排主選單一起收掉。
        status = await message.reply_text(
            self._screening_progress_text(0), parse_mode="HTML"
        )
        stop = asyncio.Event()
        t0 = time.monotonic()

        async def _tick():
            while not stop.is_set():
                elapsed = int(time.monotonic() - t0)
                try:
                    await status.edit_text(
                        self._screening_progress_text(elapsed), parse_mode="HTML"
                    )
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5.0)
                    break
                except asyncio.TimeoutError:
                    continue

        ticker = asyncio.create_task(_tick())
        result = None
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self.screener.run_full_screening),
                timeout=480.0,
            )
            stop.set()
            try:
                await status.edit_text(
                    self._screening_progress_text(0, done=True), parse_mode="HTML"
                )
            except Exception:
                pass
            await self._reply_screening_payload(message, result)
            as_of = str(result.get("as_of") or result.get("date") or "")
            try:
                from screen_sessions import screen_session_has_data

                if screen_session_has_data(self.db_path, as_of):
                    await message.reply_text(
                        "名單已寫入快取。現在可按主選單「當沖」「隔日沖」做盤中複核。",
                        reply_markup=hub,
                    )
            except Exception:
                pass
        except asyncio.TimeoutError:
            logger.exception("手動海選逾時")
            await message.reply_text(
                "海選逾時（超過 8 分鐘）。\n"
                "Render 免費主機較慢時會這樣。請 5 分鐘後再按一次「海選」，"
                "或等明早 06:30 自動海選。",
                reply_markup=hub,
            )
        except Exception:
            logger.exception("海選失敗")
            await message.reply_text(
                PHONE_BUSY,
                reply_markup=hub,
            )
        finally:
            stop.set()
            ticker.cancel()
            self._screening_running.discard(actor)
            async with self._screening_gate:
                if self._screening_global_owner == actor:
                    self._screening_global_owner = ""
            try:
                await status.delete()
            except Exception:
                pass
            # 刪進度泡泡後再釘一次，避免中途狀態讓客戶端收掉兩排。
            try:
                await self._pin_reply_menu(message)
            except Exception:
                pass

    _WAIT_SQUARES = 10

    @staticmethod
    def _wait_bubble(
        title: str,
        elapsed_sec: int,
        *,
        now: str = "",
        rest: str = "",
        fill_sec: float = 45.0,
    ) -> str:
        """進行中只留一條小方塊進度條。不要＋－｜框、不要第二種轉圈樣式。好了會刪。"""
        span = float(fill_sec or 45.0)
        width = int(WayneTelegramBot._WAIT_SQUARES)
        filled = int(round(min(1.0, max(0.0, float(elapsed_sec)) / span) * width))
        bar = "■" * filled + "□" * (width - filled)
        lines = [str(title or "").strip(), bar, f"已 {WayneTelegramBot._format_elapsed(elapsed_sec)}"]
        if now:
            lines.append(f"現在：{now}")
        if rest:
            lines.append(f"接著：{rest}")
        lines.append("好了這則會消失")
        return html_escape("\n".join(x for x in lines if x))

    @staticmethod
    def _chart_progress_text(
        elapsed_sec: int,
        *,
        sent: list | None = None,
        current: str = "",
    ) -> str:
        """查股進度：跟實際階段同步，不要只停在 0 秒。"""
        labels = {"glance": "介紹圖", "card": "決策卡", "industry": "產業圖", "chart": "導航圖", "table": "讀高低卡", "album": "一次送出"}
        order = ("glance", "card", "industry", "chart")
        sent_ks = [str(k) for k in (sent or [])]
        now = labels.get(str(current or ""), "")
        if not now:
            now = next((labels[k] for k in order if k not in sent_ks), "出圖")
        rest = "、".join(labels[k] for k in order if k not in sent_ks and labels[k] != now)
        return WayneTelegramBot._wait_bubble("查股進行中", elapsed_sec, now=now, rest=rest)

    @staticmethod
    def _biaoke_progress_text(elapsed_sec: int, *, current: str = "chart") -> str:
        """飆大產圖：方框泡泡，好了刪掉。"""
        labels = {"chart": "結構圖", "reply": "回覆", "stock": "對檔"}
        now = labels.get(str(current or ""), "結構圖")
        rest = "回覆" if now != "回覆" else "結構圖"
        return WayneTelegramBot._wait_bubble("飆大進行中", elapsed_sec, now=now, rest=rest)

    async def _start_plain_wait(self, message, *, text_fn):
        """查股那種連續更新的方塊。不掛鍵盤，免得刪掉時把主選單收走。"""
        t0 = time.monotonic()
        wait_msg = None
        try:
            wait_msg = await message.reply_text(text_fn(0), parse_mode="HTML")
        except Exception:
            return None, None, None
        stop = asyncio.Event()

        async def _tick() -> None:
            while not stop.is_set():
                try:
                    await wait_msg.edit_text(
                        text_fn(int(time.monotonic() - t0)), parse_mode="HTML"
                    )
                except Exception:
                    pass
                try:
                    chat = getattr(message, "chat", None)
                    if chat is not None and hasattr(chat, "send_action"):
                        await chat.send_action("typing")
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(stop.wait(), timeout=2.0)
                    break
                except asyncio.TimeoutError:
                    continue

        return wait_msg, stop, asyncio.create_task(_tick())

    async def _stop_plain_wait(self, wait_msg, stop, task) -> None:
        if stop is not None:
            stop.set()
        if task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=0.4)
            except Exception:
                task.cancel()
        if wait_msg is not None:
            try:
                await wait_msg.delete()
            except Exception:
                pass

    @staticmethod
    def _png_looks_ok(path: str, *, min_bytes: int = 24_000, min_w: int = 400, min_h: int = 500) -> bool:
        if not path or not os.path.exists(path):
            return False
        try:
            if os.path.getsize(path) < min_bytes:
                return False
            with open(path, "rb") as f:
                if f.read(8) != b"\x89PNG\r\n\x1a\n":
                    return False
                f.read(4)
                if f.read(4) != b"IHDR":
                    return False
                w, h = struct.unpack(">II", f.read(8))
                return w >= min_w and h >= min_h
        except Exception:
            return False

    @staticmethod
    def _fit_lookup_photo_wh(w: int, h: int) -> tuple:
        """Telegram 相簿點開上限：寬+高=10000、長寬比≤20。三張都拉滿，不准先縮小。"""
        w = max(1, int(w))
        h = max(1, int(h))
        total = w + h
        if total != _LOOKUP_TG_MAX_WH:
            scale = _LOOKUP_TG_MAX_WH / float(total)
            w = max(1, int(round(w * scale)))
            h = max(1, int(round(h * scale)))
        while w + h > _LOOKUP_TG_MAX_WH:
            if w >= h and w > 1:
                w -= 1
            elif h > 1:
                h -= 1
            else:
                break
        while w + h < _LOOKUP_TG_MAX_WH:
            if w >= h:
                w += 1
            else:
                h += 1
        long_s, short_s = (w, h) if w >= h else (h, w)
        if short_s > 0 and long_s / float(short_s) > _LOOKUP_TG_MAX_RATIO:
            long_s = max(1, int(_LOOKUP_TG_MAX_RATIO * short_s))
            if w >= h:
                w = long_s
            else:
                h = long_s
            while w + h > _LOOKUP_TG_MAX_WH:
                if w >= h and w > 1:
                    w -= 1
                elif h > 1:
                    h -= 1
                else:
                    break
        return w, h

    @staticmethod
    def _prepare_lookup_album_photo(path: str) -> str:
        """相簿點開用 JPEG，三張都拉到 Telegram 允許的最高像素。"""
        from PIL import Image

        if not path or not os.path.isfile(path):
            return path
        try:
            im = Image.open(path)
            im.load()
            if im.mode == "RGBA":
                bg = Image.new("RGB", im.size, (12, 18, 28))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            w, h = im.size
            if w <= 0 or h <= 0:
                return path
            tw, th = WayneTelegramBot._fit_lookup_photo_wh(w, h)
            if (tw, th) != (w, h):
                im = im.resize((tw, th), Image.Resampling.LANCZOS)
            out = path + ".hq.jpg"
            limit = _LOOKUP_TG_MAX_BYTES - 64
            for q in (
                _LOOKUP_JPEG_QUALITY,
                92,
                88,
                84,
                _LOOKUP_JPEG_QUALITY_FLOOR,
            ):
                im.save(
                    out,
                    "JPEG",
                    quality=int(q),
                    subsampling=0,
                    optimize=True,
                )
                if os.path.isfile(out) and 0 < os.path.getsize(out) <= limit:
                    return out
            if os.path.isfile(out) and os.path.getsize(out) > 0:
                return out
        except Exception:
            logger.exception("查股相簿轉高解析失敗 path=%s", path)
        return path

    @staticmethod
    def _chart_png_looks_ok(path: str) -> bool:
        """併發產圖偶發殘缺檔（只有標題、中間全白）；送出前擋掉。"""
        return WayneTelegramBot._png_looks_ok(path, min_bytes=48_000, min_w=500, min_h=900)

    async def screen_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        await self._run_manual_screening(update.message, uid)

    def _screen_uni_inline(self):
        return None

    async def _start_screen_pick(self, message, uid: str) -> None:
        await self._run_manual_screening(message, uid)

    async def _handle_screen_pick(self, message, uid: str, text: str, *, actor: str) -> bool:
        from buy_streak import MARKET_ALL, MARKET_EM, MARKET_TW, MARKET_TWO, parse_universe

        t = _normalize_menu_text(text)
        if t == MENU_BTN_BACK_MAIN:
            await self._restore_main_menu(message, uid)
            return True
        uni = parse_universe(t)
        if uni == MARKET_EM or t in ("興櫃海選", "興櫃名單"):
            self._pending.pop(actor, None)
            await self._run_emerging_screening(message)
            return True
        if uni in (MARKET_ALL, MARKET_TW, MARKET_TWO):
            self._pending.pop(actor, None)
            await self._run_manual_screening(message)
            return True
        if _text_escapes_pending(t):
            return False
        await self._start_screen_pick(message, uid)
        return True

    async def _handle_screen_pick_callback(self, q, uid: str, data: str) -> None:
        try:
            await q.answer()
        except Exception:
            pass
        op = (data or "").split(":")[1] if ":" in (data or "") else ""
        if op == "home":
            await self._restore_main_menu(q.message, uid)
            return
        actor = self._actor_key(q.message, uid=uid)
        self._pending.pop(actor, None)
        if op == "em":
            await self._run_emerging_screening(q.message)
            return
        if op == "listed":
            await self._run_manual_screening(q.message)
            return
        await self._start_screen_pick(q.message, uid)

    async def emerging_screen_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._run_emerging_screening(update.message)

    async def _run_emerging_screening(self, message, uid: str = ""):
        """興櫃獨立海選：不跟上市櫃海選搶同一把鎖、不寫進上市櫃快取。"""
        uid = str(uid or self._menu_uid_from_message(message) or "")
        hub = self._reply_menu(uid)
        status = await message.reply_text(
            "興櫃海選開始：抓櫃買官方日均價、只掃黃金買點／重點觀察。\n"
            "跟上市櫃「海選」分開，不會混進那份名單。"
        )
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(self.screener.run_emerging_screening, None, True),
                timeout=240.0,
            )
        except asyncio.TimeoutError:
            await message.reply_text(
                "興櫃海選逾時。請稍後再按「海選」選興櫃，或打「興櫃海選」。",
                reply_markup=hub,
            )
            return
        except Exception:
            logger.exception("興櫃海選失敗")
            await message.reply_text("興櫃海選失敗。請稍後再按「海選」選興櫃，或打「興櫃海選」。", reply_markup=hub)
            return
        finally:
            try:
                await status.delete()
            except Exception:
                pass
        n = int(result.get("n") or 0)
        if n <= 0:
            await message.reply_html(
                "興櫃海選：目前沒有可用的官方日均價序列。\n"
                "請等盤後同步櫃買「興櫃股票當日行情表」後再按「海選」選興櫃。",
                reply_markup=hub,
                disable_web_page_preview=True,
            )
            return
        await self._reply_screening_payload(message, result)
        await message.reply_html(
            f"以上是<b>興櫃</b>獨立名單（官方日均價 {html_escape(str(result.get('as_of') or ''))}，"
            f"掃描 {n} 檔）。上市櫃請再按「海選」，選上市櫃。",
            reply_markup=hub,
            disable_web_page_preview=True,
        )

    async def _reply_trade_list(
        self,
        message,
        rows: list,
        *,
        title: str,
        subtitle: str,
        bucket_key: str,
        topic: str,
        live_bucket: str | None = None,
    ):
        from screening_engine import LINE_BUCKET_TITLES, _stock_card_html
        from trade_live import apply_trade_live
        from universe import is_screen_equity

        rows = [
            r
            for r in list(rows)
            if is_screen_equity(
                str(r.get("code") or r.get("stock_id") or ""),
                str(r.get("name") or r.get("stock_name") or ""),
            )
        ]
        pre_live = len(rows)
        raw_rows = list(rows)
        live_skipped = False
        live_filtered = False
        if live_bucket:
            try:
                rows = await asyncio.wait_for(
                    asyncio.to_thread(apply_trade_live, raw_rows, self.db_path, live_bucket),
                    timeout=45.0,
                )
            except asyncio.TimeoutError:
                logger.warning("%s 盤中複核逾時，改顯示昨收候選", live_bucket)
                rows = [dict(r, _live_skipped=True) for r in raw_rows]
                live_skipped = True
            else:
                live_skipped = bool(rows) and bool(rows[0].get("_live_skipped"))
                live_filtered = bool(rows) and bool(rows[0].get("_live_filtered"))

        label = LINE_BUCKET_TITLES.get(bucket_key, "")
        cards = [_stock_card_html(r, i + 1, bucket_label=label) for i, r in enumerate(rows)]
        head = f"<b>{title}</b>\n<i>{subtitle}</i>\n────────────────"
        if cards and live_skipped:
            body = (
                head
                + "\n<i>⚠️ 盤中即時價暫時無法複核，以下為昨收候選（請自行確認現價與漲幅）。</i>\n"
                + "\n".join(cards)
            )
        elif cards and live_filtered:
            body = (
                head
                + "\n<i>此刻無標的落在盤中漲幅條件內，以下為昨收候選供參考。</i>\n"
                + "\n".join(cards)
            )
        elif cards:
            body = head + "\n" + "\n".join(cards)
        elif pre_live > 0:
            body = head + "\n<i>盤中複核後無符合（當沖漲幅須 2%～8.5%，隔日沖須 ≥2.5%）。</i>"
        else:
            body = head + "\n<i>今日無符合</i>"
        picks = [(r.get("code") or r.get("stock_id"), r.get("name") or r.get("stock_name")) for r in rows[:12]]
        chunks = chunk_telegram_html(body, 3500) or [body]
        last = len(chunks) - 1
        for j, chunk in enumerate(chunks):
            is_last = j == last
            kb = self._picks_keyboard(
                picks,
                include_menu=is_last,
                line_pack_id=bucket_key if is_last else None,
                topic=topic,
            )
            await message.reply_html(chunk, reply_markup=kb, disable_web_page_preview=True)

    async def _run_trade_bucket(
        self,
        message,
        *,
        bucket_key: str,
        live_bucket: str,
        title: str,
        subtitle: str,
        topic: str,
        status_text: str,
        menu_label: str,
        loader,
    ):
        from trading_calendar import (
            daytrade_closed_message,
            daytrade_closed_title,
            daytrade_list_heading,
            is_tw_equity_session,
            is_tw_tail_session,
            overnight_list_heading,
            tw_session_phase,
        )

        uid = str(
            _ACTIVE_PHONE_UID.get()
            or getattr(getattr(message, "from_user", None), "id", "")
            or ""
        )
        actor = self._actor_key(message, uid=uid)
        if not hasattr(self, "_trade_running"):
            self._trade_running = set()
        if actor in self._trade_running:
            await message.reply_text(
                f"{menu_label}進行中，請稍候完成後再按。",
                reply_markup=self._reply_menu(uid),
            )
            return
        self._trade_running.add(actor)
        # 進度泡泡不掛 ReplyKeyboard，否則 delete 時兩排主選單會被客戶端收掉。
        status = None
        try:
            status = await message.reply_text(status_text)
            await self._enter_main_menu(message, uid)
            phase = tw_session_phase()
            display_title = title
            effective_live_bucket = live_bucket
            effective_subtitle = subtitle
            if live_bucket == "daytrade" and not is_tw_equity_session():
                await message.reply_html(
                    f"<b>{daytrade_closed_title(phase)}</b>\n<i>{daytrade_closed_message(phase)}</i>",
                    reply_markup=self._reply_menu(uid),
                )
                return
            if live_bucket == "daytrade" and is_tw_equity_session():
                kind = "tail" if is_tw_tail_session() else "open"
                display_title, effective_subtitle = daytrade_list_heading(kind)
            if live_bucket == "overnight" and not is_tw_equity_session():
                effective_live_bucket = None
                display_title, effective_subtitle = overnight_list_heading(phase)
            try:
                rows = await asyncio.wait_for(asyncio.to_thread(loader), timeout=45.0)
            except asyncio.TimeoutError:
                await message.reply_text(
                    f"⚠️ {menu_label}查詢逾時（名單讀取較久）。"
                    "請稍後再按一次；若持續發生請回報。",
                    reply_markup=self._reply_menu(uid),
                )
                return
            try:
                await status.delete()
            except Exception:
                pass
            status = None
            if not rows:
                from screen_sessions import screen_session_has_data

                as_of = self.screener.get_latest_trading_date()
                if not screen_session_has_data(self.db_path, as_of):
                    from trading_calendar import format_trading_date_zh

                    as_of_label = format_trading_date_zh(as_of)
                    await message.reply_html(
                        f"<b>{display_title}</b>\n"
                        f"<i>今日名單尚未就緒（今早海選未完成，基準日 {html_escape(as_of_label)}）。"
                        "請按主選單「海選」執行後再查；會用盤中即時現價複核。</i>",
                        reply_markup=self._reply_menu(uid),
                    )
                else:
                    await message.reply_html(
                        f"<b>{display_title}</b>\n"
                        f"<i>昨收掃描後此桶無候選，或盤中複核後無符合標的。</i>",
                        reply_markup=self._reply_menu(uid),
                    )
                return
            await self._reply_trade_list(
                message,
                rows,
                title=display_title,
                subtitle=effective_subtitle,
                bucket_key=bucket_key,
                topic=topic,
                live_bucket=effective_live_bucket,
            )
        except asyncio.TimeoutError:
            await message.reply_text(
                f"⚠️ {menu_label}盤中複核逾時，請稍後再按一次。",
                reply_markup=self._reply_menu(uid),
            )
        except Exception:
            logger.exception("%s 查詢失敗", live_bucket)
            await message.reply_text(
                PHONE_BUSY,
                reply_markup=self._reply_menu(uid),
            )
        finally:
            self._trade_running.discard(actor)
            if status is not None:
                try:
                    await status.delete()
                except Exception:
                    pass

    async def daytrade_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._run_trade_bucket(
            update.message,
            bucket_key="day_trade",
            live_bucket="daytrade",
            title="⚡ 當沖候選（盤中）",
            subtitle="現在盤中。沒進場：不要貴過「現在不要貴過」那一價。已進場：漲 3% 先出一部分，跌破均價先走。",
            topic="daytrade",
            status_text="⚡ 當沖查詢中（盤中現價複核）…",
            menu_label="當沖",
            loader=self.screener.screen_daytrade,
        )

    async def overnight_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._run_trade_bucket(
            update.message,
            bucket_key="overnight",
            live_bucket="overnight",
            title="⚡ 隔日沖候選（盤中即時）",
            subtitle="盤中即時複核：只列此刻漲幅≥2.5% 的標的；現價旁小字＝報價時間。尾盤保險買進；明早開高+3.5～4.8%；防守跌破先走。",
            topic="overnight",
            status_text="⚡ 隔日沖查詢中（盤中現價複核）…",
            menu_label="隔日沖",
            loader=self.screener.screen_overnight,
        )

    async def leave_zero_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._run_leave_zero_now(update.message)

    async def dongzhu_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE, code: str = ""):
        del context
        q = str(code or "").strip()
        if q:
            await self._send_dongzhu_hold(update.message, q)
            return
        await self._send_dongzhu_page(update.message)

    async def _send_dongzhu_hold(self, message, query: str) -> None:
        from biaoke_field_scan import dongzhu_hold_page

        uid = str(
            _ACTIVE_PHONE_UID.get()
            or getattr(getattr(message, "from_user", None), "id", "")
            or ""
        )
        actor = self._actor_key(message, uid=uid)
        q = str(query or "").strip()
        hits = lookup_stocks(self.db_path, q.split()[0].strip() if q else "")
        if not hits and q:
            hits = lookup_stocks(self.db_path, q)
        if not hits:
            self._pending[actor] = "dongzhu"
            await message.reply_text(
                "找不到這檔。打代號或股名，看這檔自己的產業鏈能不能留（不是整層電子）。",
                reply_markup=self._dongzhu_reply_menu(uid),
            )
            return
        if hits_need_picker(hits):
            self._pending[actor] = "dongzhu"
            await message.reply_html(
                self._hits_list_html(hits),
                reply_markup=self._hits_keyboard(hits),
                disable_web_page_preview=True,
            )
            return
        sid = str(hits[0].get("stock_id") or "").strip()
        wait_h = (None, None, None)
        try:
            wait_h = await self._start_plain_wait(
                message,
                text_fn=lambda s: self._wait_bubble(
                    "洞燭先機進行中",
                    s,
                    now="讀這檔產業鏈",
                    rest="能不能留",
                    fill_sec=16.0,
                ),
            )
            try:
                held = sid in set(self._dongzhu_held_sids(uid))
                html = await asyncio.wait_for(
                    asyncio.to_thread(dongzhu_hold_page, self.db_path, sid, held=held),
                    timeout=20.0,
                )
            except asyncio.TimeoutError:
                await message.reply_text(
                    "⚠️ 洞燭先機查詢逾時。請稍後再打一次代號。",
                    reply_markup=self._dongzhu_reply_menu(uid),
                )
                return
            except Exception:
                logger.exception("洞燭先機能不能留失敗")
                await message.reply_text(
                    PHONE_BUSY,
                    reply_markup=self._dongzhu_reply_menu(uid),
                )
                return
            await self._stop_plain_wait(*wait_h)
            wait_h = (None, None, None)
            self._pending[actor] = "dongzhu"
            chunks = chunk_telegram_html(html, 3500, reflow=True) or [html]
            last = len(chunks) - 1
            kb = self._dongzhu_hold_keyboard(sid)
            for j, chunk in enumerate(chunks):
                await message.reply_html(
                    chunk,
                    reply_markup=kb if j == last else None,
                    disable_web_page_preview=True,
                )
            # ReplyKeyboard 與 Inline 不能同則；另發離開鈕鍵盤。
            await message.reply_text(
                "還在洞燭。同一顆「離開洞燭先機」回主選單。",
                reply_markup=self._dongzhu_reply_menu(uid),
            )
        finally:
            await self._stop_plain_wait(*wait_h)

    async def _send_dongzhu_page(self, message) -> None:
        from biaoke_field_scan import PRE_BUY_WIN_BTN, dongzhu_page, dongzhu_picks

        uid = str(
            _ACTIVE_PHONE_UID.get()
            or getattr(getattr(message, "from_user", None), "id", "")
            or ""
        )
        actor = self._actor_key(message, uid=uid)
        if not hasattr(self, "_trade_running"):
            self._trade_running = set()
        if actor in self._trade_running:
            await message.reply_text(
                "洞燭先機進行中，請稍候完成後再按。",
                reply_markup=self._dongzhu_reply_menu(uid),
            )
            return
        self._trade_running.add(actor)
        wait_h = (None, None, None)
        try:
            await self._enter_main_menu(message, uid)
            wait_h = await self._start_plain_wait(
                message,
                text_fn=lambda s: self._wait_bubble(
                    "洞燭先機進行中",
                    s,
                    now="讀產業鏈佔比",
                    rest="排出推薦",
                    fill_sec=20.0,
                ),
            )
            try:
                held_sids = self._dongzhu_held_sids(uid)
                html = await asyncio.wait_for(
                    asyncio.to_thread(dongzhu_page, self.db_path, held_sids=held_sids),
                    timeout=20.0,
                )
            except asyncio.TimeoutError:
                await message.reply_text(
                    "⚠️ 洞燭先機查詢逾時。請稍後再按一次；若持續發生請回報。",
                    reply_markup=self._dongzhu_reply_menu(uid),
                )
                return
            except Exception:
                logger.exception("洞燭先機查詢失敗")
                await message.reply_text(
                    PHONE_BUSY,
                    reply_markup=self._dongzhu_reply_menu(uid),
                )
                return
            picks = []
            try:
                data = dongzhu_picks(self.db_path)
                seen = set()
                buy_sids = {
                    str(x.get("sid") or "")
                    for x in list(data.get("buys") or [])
                    if x.get("sid")
                }
                for item in (
                    list(data.get("buys") or [])
                    + list(data.get("watches") or [])
                    + list(data.get("laggards") or [])
                ):
                    sid = str(item.get("sid") or "")
                    if not sid or sid in seen:
                        continue
                    seen.add(sid)
                    # 只有黃金買點標這型勝率；觀察／落後不加，不准發明。
                    win = PRE_BUY_WIN_BTN if sid in buy_sids else ""
                    picks.append((sid, item.get("name") or "", win))
            except Exception:
                picks = []
            await self._stop_plain_wait(*wait_h)
            wait_h = (None, None, None)
            chunks = chunk_telegram_html(html, 3500, reflow=True) or [html]
            last = len(chunks) - 1
            for j, chunk in enumerate(chunks):
                kb = self._dongzhu_picks_keyboard(picks if j == last else None)
                await message.reply_html(
                    chunk,
                    reply_markup=kb,
                    disable_web_page_preview=True,
                )
            # 內容／選檔用 Inline；離開鈕用 ReplyKeyboard 另發（對齊離開飆大）。
            await message.reply_text(
                "還在洞燭。同一顆「離開洞燭先機」回主選單。",
                reply_markup=self._dongzhu_reply_menu(uid),
            )
            self._pending[actor] = "dongzhu"
        finally:
            await self._stop_plain_wait(*wait_h)
            self._trade_running.discard(actor)

    async def _run_leave_zero_now(self, message):
        from live_quote import is_live_merge_window
        from screening_engine import _stock_card_html
        from universe import is_screen_equity

        uid = str(
            _ACTIVE_PHONE_UID.get()
            or getattr(getattr(message, "from_user", None), "id", "")
            or ""
        )
        actor = self._actor_key(message, uid=uid)
        if not hasattr(self, "_trade_running"):
            self._trade_running = set()
        if actor in self._trade_running:
            await message.reply_text(
                "剛脫離零進行中，請稍候完成後再按。",
                reply_markup=self._reply_menu(uid),
            )
            return
        self._trade_running.add(actor)
        wait_h = (None, None, None)
        try:
            from trading_calendar import is_tw_equity_session, leave_zero_closed_message

            await self._enter_main_menu(message, uid)
            if not is_tw_equity_session():
                html = self._leave_zero_case_html(
                    "剛脫離零（非盤中）",
                    "平日 09:00–13:30 才提供現價複核。",
                    f"<i>{leave_zero_closed_message()}</i>",
                )
                kb = InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("海選", callback_data="screen")],
                    ]
                )
                await message.reply_html(
                    html, reply_markup=kb, disable_web_page_preview=True
                )
                return
            wait_h = await self._start_plain_wait(
                message,
                text_fn=lambda s: self._wait_bubble(
                    "剛脫離零進行中",
                    s,
                    now="讀海選快取",
                    rest="盤中現價複核",
                    fill_sec=20.0,
                ),
            )
            live_on = bool(is_live_merge_window())
            try:
                rows = await asyncio.wait_for(
                    asyncio.to_thread(self.screener.screen_leave_zero_now),
                    timeout=45.0,
                )
            except asyncio.TimeoutError:
                await message.reply_text(
                    "⚠️ 剛脫離零查詢逾時。請稍後再按一次；若持續發生請回報。",
                    reply_markup=self._reply_menu(uid),
                )
                return
            await self._stop_plain_wait(*wait_h)
            wait_h = (None, None, None)
            rows = [
                r
                for r in list(rows or [])
                if is_screen_equity(
                    str(r.get("code") or r.get("stock_id") or ""),
                    str(r.get("name") or r.get("stock_name") or ""),
                )
            ]
            if live_on:
                title = "剛脫離零（盤中現價）"
                subtitle = (
                    "現價對近 60 個日曆天收盤低。股名旁五角星＝值不值得買（滿五星＝按表該買）。"
                    "未收盤不寫進官方收。"
                )
            else:
                title = "剛脫離零（最近完整收）"
                subtitle = (
                    "盤中已過。以下是最近一次完整收盤的黃金買點，不是盤中現價。"
                    "股名旁五角星＝值不值得買（滿五星＝按表該買）。"
                )
            if not rows:
                from screen_sessions import screen_session_has_data

                as_of = self.screener.get_latest_trading_date()
                if not screen_session_has_data(self.db_path, as_of):
                    from trading_calendar import format_trading_date_zh

                    as_of_label = format_trading_date_zh(as_of)
                    inner = (
                        f"<i>今日名單尚未就緒（今早海選未完成，基準日 {html_escape(as_of_label)}）。"
                        "請按主選單「海選」執行後再查；盤中會用即時現價複核，不寫未收盤。</i>"
                    )
                    await message.reply_html(
                        self._leave_zero_case_html(title, subtitle, inner),
                        reply_markup=self._reply_menu(uid),
                    )
                else:
                    empty = (
                        "此刻沒有獲利剛離零的檔。"
                        if live_on
                        else "最近一次完整收沒有黃金買點。"
                    )
                    await message.reply_html(
                        self._leave_zero_case_html(title, subtitle, f"<i>{empty}</i>"),
                        reply_markup=self._reply_menu(uid),
                    )
                return
            live_skipped = bool(rows) and bool(rows[0].get("_live_skipped"))
            cards = [
                _stock_card_html(r, i + 1, bucket_label=MENU_BTN_LEAVE_ZERO)
                for i, r in enumerate(rows)
            ]
            extra = ""
            if live_skipped:
                extra = (
                    "<i>⚠️ 盤中即時價暫時無法複核，以下為昨收黃金買點（請自行確認現價）。</i>"
                )
            body = self._leave_zero_case_html(
                title, subtitle, "\n".join(cards), extra=extra
            )
            picks = [
                (r.get("code") or r.get("stock_id"), r.get("name") or r.get("stock_name"))
                for r in rows[:MAX_PICK_INLINE_ROWS]
            ]
            chunks = chunk_telegram_html(body, 3500) or [body]
            last = len(chunks) - 1
            for j, chunk in enumerate(chunks):
                kb = self._leave_zero_section_keyboard(
                    picks, include_menu=(j == last)
                )
                await message.reply_html(
                    chunk, reply_markup=kb, disable_web_page_preview=True
                )
        except Exception:
            logger.exception("剛脫離零查詢失敗")
            await message.reply_text(
                PHONE_BUSY,
                reply_markup=self._reply_menu(uid),
            )
        finally:
            self._trade_running.discard(actor)
            await self._stop_plain_wait(*wait_h)

    async def _send_market_page(self, message, *, status=None) -> None:
        """大盤專頁：庫內結構 + 盤中 MIS 指數（不寫庫）。"""
        if status is None:
            status = await self._transient_status(message, "讀取大盤…")
        html = ""
        live_quote = None
        try:

            def _build():
                from concurrent.futures import ThreadPoolExecutor

                from live_quote import fetch_mis_index_quote
                from taiwan_market import analyze_taiwan_market, format_taiwan_market_page_html

                with ThreadPoolExecutor(max_workers=2) as ex:
                    live_f = ex.submit(fetch_mis_index_quote)
                    snap_f = ex.submit(
                        analyze_taiwan_market, self.db_path, None, db_only=True, page_light=True
                    )
                    live = live_f.result()
                    snap = snap_f.result()
                html = format_taiwan_market_page_html(self.db_path, live=live, snap=snap)
                return html, live

            html, live_quote = await asyncio.wait_for(asyncio.to_thread(_build), timeout=28.0)
        except asyncio.TimeoutError:
            logger.warning("大盤專頁逾時 db=%s", self.db_path)
            await self._delete_message(status)
            await message.reply_text(
                "大盤讀取逾時，請稍後再按一次。",
                reply_markup=self._keyboard(),
            )
            return
        except Exception:
            logger.exception("大盤專頁失敗")
            await self._delete_message(status)
            await message.reply_text(PHONE_BUSY, reply_markup=self._keyboard())
            return
        parts = chunk_telegram_html(html, reflow=True)
        if not parts:
            await self._delete_message(status)
            await message.reply_text(
                "大盤資料暫時讀不到，請稍後再試。",
                reply_markup=self._keyboard(),
            )
            return
        try:
            for i, part in enumerate(parts):
                await message.reply_html(part, disable_web_page_preview=True)
            await self._send_market_kline(
                message, live=live_quote, uid=self._uid_from_message(message)
            )
        except Exception as e:
            logger.exception("大盤 HTML 送出失敗")
            plain = html.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
            await message.reply_text(
                f"大盤顯示失敗，改純文字：\n{plain[:3500]}",
                reply_markup=self._keyboard(),
            )
        finally:
            await self._delete_message(status)

    async def _send_market_kline(self, message, *, live=None, uid: str = "") -> None:
        """大盤專頁附圖：加權日 K（淺底）。"""
        from config import skip_chart_warmup

        if skip_chart_warmup():
            return
        wait = None
        try:
            wait = await message.reply_text(
                self._wait_bubble("日K圖進行中", 0, now="加權官方日K", fill_sec=30.0),
                parse_mode="HTML",
            )
        except Exception:
            pass
        os.makedirs(self.charts_dir, exist_ok=True)
        uid = uid or self._uid_from_message(message)
        chart_path = self._scratch_chart_path(self.charts_dir, "TWII", "kline", uid)
        try:
            from index_kline_chart import build_market_kline_chart

            path = await asyncio.wait_for(
                asyncio.to_thread(
                    build_market_kline_chart,
                    chart_path,
                    live=live,
                    db_path=self.db_path,
                ),
                timeout=_CHART_RENDER_TIMEOUT,
            )
        except asyncio.TimeoutError:
            path = ""
            logger.warning("大盤日K圖逾時")
        except Exception:
            path = ""
            logger.exception("大盤日K圖失敗")
        if not path or not self._chart_png_looks_ok(path):
            if wait is not None:
                try:
                    await wait.delete()
                except Exception:
                    pass
            return
        cap = "加權指數日K（K棒・MA5/20/60・量）"
        try:
            with open(path, "rb") as f:
                await message.reply_photo(
                    photo=f,
                    caption=cap,
                    parse_mode="HTML",
                    reply_markup=None,
                )
        except Exception:
            logger.exception("大盤日K圖送出失敗")
        if wait is not None:
            try:
                await wait.delete()
            except Exception:
                pass

    def _enter_biaoke_chat(self, message, uid: str = "") -> None:
        uid = str(uid or self._uid_from_message(message) or "")
        if not uid:
            return
        actor = self._actor_key(message, uid=uid)
        try:
            from biaoke_brain import PENDING as BIAOKE_PENDING
        except Exception:
            BIAOKE_PENDING = "biaoke:chat"
        self._pending[actor] = BIAOKE_PENDING

    async def _send_biaoke_page(self, message, *, ask: str = "", uid: str = "") -> None:
        """飆大＝這顆對話腦的即時窗口。問句在這邊彙整。資料庫沒寫過的檔也套官方 K。不進海選。"""
        from biaoke_brain import answer_biaoke
        from biaoke_desk import format_biaoke_html

        uid = str(uid or self._uid_from_message(message) or "")
        self._enter_biaoke_chat(message, uid)
        if uid:
            try:
                self._mark_menu_layout_ok(uid)
            except Exception:
                pass
        q = (ask or "").strip()
        actor = self._actor_key(message, uid=uid)
        if not hasattr(self, "_biaoke_hist") or self._biaoke_hist is None:
            self._biaoke_hist = {}
        hist = list(self._biaoke_hist.get(actor) or [])
        mark_read = False
        chart_task = None
        wait_h = (None, None, None)
        try:
            if q:
                wait_h = await self._start_plain_wait(
                    message,
                    text_fn=lambda s: self._biaoke_progress_text(s, current="chart"),
                )
                picker = []
                try:
                    from biaoke_brain import format_stock_picker_html, stock_picker_hits

                    picker = await asyncio.to_thread(stock_picker_hits, self.db_path, q)
                except Exception:
                    logger.exception("飆大撞名選擇器略過")
                    picker = []
                if picker:
                    await self._stop_plain_wait(*wait_h)
                    wait_h = (None, None, None)
                    html = format_stock_picker_html(picker)
                    await message.reply_html(
                        html,
                        disable_web_page_preview=True,
                        reply_markup=self._biaoke_hits_keyboard(picker),
                    )
                    return
                chart_task = asyncio.create_task(
                    self._send_biaoke_structure_chart(message, q, uid)
                )
                html = await asyncio.to_thread(answer_biaoke, self.db_path, q, hist, uid)
                bucket = self._biaoke_hist.setdefault(actor, [])
                plain = re.sub(r"<[^>]+>", "", html)
                bucket.append({"ask": q, "answer": plain[:900]})
                del bucket[:-16]
                mark_read = True
            else:
                html = ""
                try:
                    from biaoke_digest import format_latest_focus, take_unread_digest

                    html = take_unread_digest(uid, self.db_path)
                    if not html:
                        html = format_latest_focus(self.db_path)
                except Exception:
                    html = ""
                if html:
                    mark_read = True
                else:
                    html = format_biaoke_html(q)
            # 對話不要再切成 18 字講義行；Telegram 自己會折。
            parts = chunk_telegram_html(html, reflow=False)
            if parts and mark_read:
                try:
                    from biaoke_digest import mark_biaoke_read

                    mark_biaoke_read(uid, self.db_path)
                except Exception:
                    pass
            kb = self._biaoke_hub_markup(q)
            if not parts:
                if chart_task is not None:
                    try:
                        await chart_task
                    except Exception:
                        logger.exception("飆大結構圖並行失敗")
                await message.reply_text("飆客區讀取失敗。", reply_markup=self._biaoke_reply_menu(uid))
                return
            from biaoke_chain import split_lead_detail

            lead_html, detail_html = split_lead_detail("\n\n".join(parts) if len(parts) == 1 else html)
            if lead_html and detail_html:
                parts = [lead_html, *chunk_telegram_html(detail_html, reflow=False)]
            n = len(parts)
            for i, part in enumerate(parts):
                markup = kb if i == n - 1 else None
                await message.reply_html(
                    part,
                    disable_web_page_preview=True,
                    reply_markup=markup,
                )
            if chart_task is not None:
                try:
                    await chart_task
                except Exception:
                    logger.exception("飆大結構圖並行失敗")
        finally:
            await self._stop_plain_wait(*wait_h)

    async def _send_biaoke_structure_chart(self, message, ask: str, uid: str) -> None:
        """飆大視窗才附量價／連點圖。不是介紹圖、不是決策卡。"""
        q = (ask or "").strip()
        if not q:
            return
        try:
            from biaoke_wave import is_twii_plain_ask, is_wave_question

            if is_wave_question(q) or is_twii_plain_ask(q):
                await self._send_biaoke_twii_degree_chart(message, uid)
                return
        except Exception:
            logger.exception("飆大加權位階圖判斷略過")
        try:
            from biaoke_brain import is_market_question, resolve_stock

            if is_market_question(q) and not resolve_stock(self.db_path, q):
                return
            hits = await asyncio.to_thread(resolve_stock, self.db_path, q)
        except Exception:
            logger.exception("飆大結構圖對檔略過")
            return
        if not hits:
            return
        sid = str(hits[0].get("stock_id") or "")
        name = str(hits[0].get("stock_name") or sid)
        if not sid:
            return
        os.makedirs(self.charts_dir, exist_ok=True)
        path = self._scratch_chart_path(self.charts_dir, sid, "biaoke", uid)
        try:
            chat = getattr(message, "chat", None)
            if chat is not None and hasattr(chat, "send_action"):
                await chat.send_action("upload_photo")
        except Exception:
            pass
        try:
            from biaoke_chart import build_biaoke_structure_chart

            built = await asyncio.wait_for(
                asyncio.to_thread(
                    build_biaoke_structure_chart,
                    self.db_path,
                    sid,
                    path,
                    name=name,
                    ask=q,
                    uid=uid,
                ),
                timeout=_CHART_RENDER_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("飆大結構圖逾時 sid=%s", sid)
            return
        except Exception:
            logger.exception("飆大結構圖失敗 sid=%s", sid)
            return
        png = str((built or {}).get("path") or "")
        if not png or not self._png_looks_ok(png, min_bytes=24_000, min_w=800, min_h=500):
            return
        cap = str((built or {}).get("caption") or "飆大結構圖。這不是買訊。")
        try:
            with open(png, "rb") as f:
                await message.reply_photo(
                    photo=f,
                    caption=cap[:900],
                    reply_markup=self._biaoke_reply_menu(uid),
                )
        except Exception:
            logger.exception("飆大結構圖送出失敗")

    async def _send_biaoke_twii_degree_chart(self, message, uid: str) -> None:
        """問大盤位階才附加權官方日K＋他自己的轉折線。不數段。"""
        os.makedirs(self.charts_dir, exist_ok=True)
        path = self._scratch_chart_path(self.charts_dir, "TWII", "biaoke-wave", uid)
        try:
            chat = getattr(message, "chat", None)
            if chat is not None and hasattr(chat, "send_action"):
                await chat.send_action("upload_photo")
        except Exception:
            pass
        try:
            from biaoke_wave import build_twii_degree_chart

            built = await asyncio.wait_for(
                asyncio.to_thread(
                    build_twii_degree_chart,
                    self.db_path,
                    path,
                ),
                timeout=_CHART_RENDER_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("飆大加權位階圖逾時")
            return
        except Exception:
            logger.exception("飆大加權位階圖失敗")
            return
        png = str((built or {}).get("path") or "")
        if not png or not self._png_looks_ok(png, min_bytes=12_000, min_w=600, min_h=360):
            return
        cap = str((built or {}).get("caption") or "加權位階圖。這不是買訊。")
        try:
            with open(png, "rb") as f:
                await message.reply_photo(
                    photo=f,
                    caption=cap[:900],
                    reply_markup=self._biaoke_reply_menu(uid),
                )
        except Exception:
            logger.exception("飆大加權位階圖送出失敗")

    async def _send_biaoke_origin_charts(self, message, ask: str, uid: str) -> None:
        """飆大視窗才帶他的公開附圖。一般查股兩張圖不走這裡。社團不送。"""
        q = (ask or "").strip()
        if not q:
            return
        try:
            from biaoke_brain import is_market_question, resolve_stock
            from biaoke_wave import is_twii_plain_ask, is_wave_question

            if is_wave_question(q) or is_twii_plain_ask(q):
                return
            if is_market_question(q) and not resolve_stock(self.db_path, q):
                return
            else:
                hits = await asyncio.to_thread(resolve_stock, self.db_path, q)
        except Exception:
            logger.exception("飆大原文附圖對檔略過")
            return
        if not hits:
            return
        sid = str(hits[0].get("stock_id") or "")
        if not sid:
            return
        try:
            from biaoke_charts import pick_charts

            rows = pick_charts(sid, limit=2, public_only=True, hold=False)
        except Exception:
            logger.exception("飆大原文附圖索引略過")
            return
        kb = self._biaoke_reply_menu(uid)
        sent = 0
        for row in rows:
            url = str(row.get("url") or "").strip()
            if not url or "profile/" in url:
                continue
            cap = (
                f"{row.get('date') or ''} {row.get('note') or '他的附圖'}。"
                "公開附圖對官方日K看第4顆。不是買訊。"
            ).strip()
            try:
                await message.reply_photo(
                    photo=url,
                    caption=cap[:900],
                    reply_markup=kb,
                )
                sent += 1
            except Exception:
                logger.debug("飆大原文附圖送出略過 url=%s", url, exc_info=True)
            if sent >= 2:
                break

    async def market_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """大盤專頁：只讀庫內指數／廣度／regime，不觸發匯入或寫入。"""
        uid = str(update.effective_user.id)
        status = await self._transient_status(update.message, "讀取大盤…")
        try:
            await self._enter_main_menu(update.message, uid)
            await self._send_market_page(update.message, status=status)
        except Exception:
            await self._delete_message(status)
            raise

    async def flow_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        status = await self._transient_status(update.message, "讀取當日資金移動…")
        try:
            await self._enter_main_menu(update.message, uid)
            from money_flow import format_flow_html, resolve_flow_as_of, sector_flow_ready

            as_of, lag = resolve_flow_as_of(self.db_path)
            # 按鈕路徑不重算產業輪動（會拖 10s+）；缺資料就直接讀庫／提示稍後。
            if as_of:
                ready = await asyncio.to_thread(sector_flow_ready, self.db_path, as_of)
                if not ready:
                    lag = (lag or "") + (
                        "\n<i>今日產業輪動表尚未寫入（盤後融合後會有）；以下可能是前一交易日快取。</i>"
                    )
            html = await asyncio.wait_for(
                asyncio.to_thread(format_flow_html, self.db_path, user_id=uid),
                timeout=12.0,
            )
            if lag and lag not in html:
                html = lag + "\n" + html
        except asyncio.TimeoutError:
            logger.warning("資金移動逾時，改送精簡版")
            await self._delete_message(status)
            from trading_calendar import is_tw_equity_session

            if is_tw_equity_session():
                hint = "資金頁載入逾時（盤中即時較慢），請 30 秒後再按一次「資金」。"
            else:
                hint = "資金頁載入逾時，請稍後再按一次「資金」。"
            await update.message.reply_text(
                hint,
                reply_markup=self._keyboard(),
            )
            return
        except Exception:
            logger.exception("資金移動失敗")
            await self._delete_message(status)
            await update.message.reply_text(PHONE_BUSY, reply_markup=self._keyboard())
            return
        await self._delete_message(status)
        parts = chunk_telegram_html(html, reflow=True)
        for i, part in enumerate(parts):
            await update.message.reply_html(part, disable_web_page_preview=True)

    async def _send_portfolio(self, message, uid: str):
        """持股＝手記真實買入，不是觀察、也不是 AI 模擬倉。"""
        holdings = get_user_portfolio(self.db_path, uid)
        mine = self.portfolio_engine.format_holdings_html(holdings)
        parts = chunk_telegram_html(mine, reflow=True)
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
            "card": "看這檔：請先打代號（例 2330、0050、00631L、00981A）或點觀察清單。會一次出介紹圖、決策卡。",
            "chips": "籌碼：請先選一檔。打名稱或代號，或點下面觀察清單。",
            "fund": "營收毛利：請先選一檔。打名稱或代號，或點下面觀察清單。",
            "industry": "產業說明：請先選一檔。會送一張圖卡。同業＝同一產業鏈才比；跨族檔另標他還有的鏈。",
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
        self._pending[self._pending_actor(message, uid=uid)] = purpose
        await message.reply_html(hints[purpose], reply_markup=InlineKeyboardMarkup(kb))

    async def portfolio_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        status = await self._transient_status(update.message, "讀取持股…")
        try:
            await self._enter_main_menu(update.message, uid)
            await self._send_portfolio(update.message, uid)
        finally:
            await self._delete_message(status)

    async def watch_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        status = await self._transient_status(update.message, "讀取觀察清單…")
        try:
            await self._enter_main_menu(update.message, uid)
            await self._send_watch(update.message, uid)
        finally:
            await self._delete_message(status)

    async def card_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        if not args:
            await update.message.reply_text("用法：/card 2330")
            return
        await self._reply_card(update, args[0])

    async def chips_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        uid = str(update.effective_user.id)
        if not args:
            last = self._last_card.get(uid)
            if last:
                await self._send_chips_to(update.message, last, uid)
                return
            await self._prompt_pick(update.message, uid, "chips")
            return
        await self._send_chips_to(update.message, args[0].strip(), uid)

    async def _send_chips_to(self, message, code: str, uid: str = ""):
        code = str(code or "").strip()
        uid = uid or self._uid_from_message(message)
        hits = lookup_stocks(self.db_path, code)
        if self._hit_is_emerging(code, hits):
            await message.reply_html(
                self._em_no_listed_html(code, hits),
                reply_markup=self._hub_keyboard(code, em=True),
                disable_web_page_preview=True,
            )
            return
        wait_h = await self._start_plain_wait(
            message,
            text_fn=lambda s: self._wait_bubble("籌碼圖進行中", s, now="法人張數", fill_sec=20.0),
        )
        try:
            chip_img = await asyncio.to_thread(
                generate_chips_image,
                code,
                self.db_path,
                self._scratch_chart_path(self.charts_dir, code, "chips", uid),
            )
            if chip_img:
                try:
                    with open(chip_img, "rb") as f:
                        await message.reply_photo(
                            photo=f, caption="籌碼（張）", reply_markup=self._hub_keyboard(code)
                        )
                except Exception:
                    await message.reply_text("籌碼圖送出失敗", reply_markup=self._hub_keyboard(code))
            else:
                await message.reply_html("查無籌碼", reply_markup=self._hub_keyboard(code))
        finally:
            await self._stop_plain_wait(*wait_h)

    async def fund_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        uid = str(update.effective_user.id)
        if not args:
            last = self._last_card.get(uid)
            if last:
                await self._send_fund_to(update.message, last)
                return
            await self._prompt_pick(update.message, uid, "fund")
            return
        await self._send_fund_to(update.message, args[0].strip())

    async def _send_fund_to(self, message, code: str):
        from fundamentals import format_fundamentals_html

        # 按鈕／指令路徑只讀庫，不跑全市場 sync（那會卡死整機；交給盤後流水線）。
        code = str(code or "").strip()
        hits = lookup_stocks(self.db_path, code)
        if self._hit_is_emerging(code, hits):
            await message.reply_html(
                self._em_no_listed_html(code, hits),
                reply_markup=self._hub_keyboard(code, em=True),
                disable_web_page_preview=True,
            )
            return
        html = await asyncio.to_thread(format_fundamentals_html, code, self.db_path)
        await message.reply_html(
            html, reply_markup=self._hub_keyboard(code), disable_web_page_preview=True
        )

    async def industry_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        uid = str(update.effective_user.id)
        if not args:
            last = self._last_card.get(uid)
            if last:
                await self._send_industry(update.message, last, uid)
                return
            await self._prompt_pick(update.message, uid, "industry")
            return
        await self._send_industry(update.message, args[0].strip(), uid)

    async def _send_industry(self, message, code: str, uid: str = ""):
        from industry_brief import format_industry_html
        from industry_card import render_industry_png

        code = str(code).strip()
        hits = lookup_stocks(self.db_path, code)
        em = self._hit_is_emerging(code, hits)
        uid = str(uid or self._uid_from_message(message) or "0")
        png_path = self._scratch_chart_path(self.charts_dir, code, "industry", uid)
        wait_h = await self._start_plain_wait(
            message,
            text_fn=lambda s: self._wait_bubble("產業圖進行中", s, now="產業卡", fill_sec=20.0),
        )

        def _build():
            return render_industry_png(code, self.db_path, png_path, allow_fetch=True, max_fetch=1)

        try:
            try:
                out = await asyncio.to_thread(_build)
            except Exception:
                logger.exception("產業說明圖失敗 code=%s", code)
                out = ""
            if out and os.path.isfile(out):
                try:
                    send_path = self._prepare_lookup_album_photo(out)
                    with open(send_path, "rb") as f:
                        await message.reply_photo(
                            photo=f,
                            caption=f"{html_escape(code)}　產業",
                            reply_markup=self._hub_keyboard(code, em=em),
                        )
                    return
                except Exception:
                    logger.exception("產業圖送出失敗 code=%s", code)
            try:
                html = await asyncio.to_thread(format_industry_html, code, self.db_path)
            except Exception:
                logger.exception("產業說明失敗 code=%s", code)
                html = PHONE_BUSY
            await message.reply_html(
                html, reply_markup=self._hub_keyboard(code, em=em), disable_web_page_preview=True
            )
        finally:
            await self._stop_plain_wait(*wait_h)

    async def why_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """舊版三條槓／why：已拿掉。舊客戶端還會送 /why，不能靜默。"""
        await update.message.reply_text(
            "請直接打代號或股名看圖，不必再點原因。",
            reply_markup=self._keyboard(),
        )

    async def _dispatch_intent(
        self,
        message,
        uid: str,
        text: str,
        *,
        update=None,
        context=None,
    ) -> bool:
        hit = parse_intent(text)
        if hit is None:
            return False
        kind = hit.kind
        if kind == "biaoke":
            await self._send_biaoke_page(
                message, ask=hit.query or hit.code, uid=uid
            )
            return True
        code = str(hit.code or "").strip()
        hits = []
        if code:
            hits = lookup_stocks(self.db_path, code)
            if hits:
                code = str(hits[0]["stock_id"])
            else:
                code = ""
        if not code and hit.query:
            hits = lookup_stocks(self.db_path, hit.query)
            if hits_need_picker(hits):
                await message.reply_html(
                    self._hits_list_html(hits),
                    reply_markup=self._hits_keyboard(hits),
                    disable_web_page_preview=True,
                )
                return True
            if len(hits) == 1:
                code = str(hits[0]["stock_id"])
        if not code and kind in NEEDS_STOCK:
            code = str(self._last_card.get(uid) or "").strip()
        if kind in NEEDS_STOCK and not code:
            await message.reply_html(
                "這句要帶一檔才出得了正確資料。請打代號，例如 <code>2330</code>、<code>00631L</code>；"
                "或先查一檔再問。",
                disable_web_page_preview=True,
            )
            return True
        await self._run_intent_kind(
            message, uid, kind, code, update=update, context=context
        )
        return True

    async def _run_intent_kind(
        self,
        message,
        uid: str,
        kind: str,
        code: str,
        *,
        update=None,
        context=None,
    ) -> None:
        from types import SimpleNamespace

        code = str(code or "").strip()
        if kind in ("lookup", "card"):
            if kind == "card":
                await self._send_decision_card_quick(message, code, uid)
            else:
                await self._send_card_to(message, code, uid)
            return
        if kind == "sell":
            await message.reply_html(sell_honest_html(), disable_web_page_preview=True)
            await self._send_card_to(message, code, uid)
            return
        if kind == "no_cost":
            await message.reply_html(no_cost_honest_html(), disable_web_page_preview=True)
            await self._send_chips_to(message, code, uid)
            return
        if kind == "chips":
            await self._send_chips_to(message, code, uid)
            return
        if kind == "industry":
            await self._send_industry(message, code, uid)
            return
        if kind == "fund":
            await self._send_fund_to(message, code)
            return
        user = getattr(message, "from_user", None)
        upd = update if update is not None else SimpleNamespace(
            message=message, effective_user=user
        )
        ctx = context if context is not None else SimpleNamespace(args=[])
        if kind == "market":
            await self.market_cmd(upd, ctx)
            return
        if kind == "biaoke":
            await self._send_biaoke_page(message, ask="", uid=uid)
            return
        if kind == "flow":
            await self.flow_cmd(upd, ctx)
            return
        if kind == "screen":
            await self.screen_cmd(upd, ctx)
            return
        if kind == "emerging_screen":
            await self.emerging_screen_cmd(upd, ctx)
            return
        if kind == "portfolio":
            await self.portfolio_cmd(upd, ctx)
            return
        if kind == "watch":
            await self.watch_cmd(upd, ctx)
            return
        if kind == "daytrade":
            await self.daytrade_cmd(upd, ctx)
            return
        if kind == "overnight":
            await self.overnight_cmd(upd, ctx)
            return
        if kind == "leave_zero":
            await self.leave_zero_cmd(upd, ctx)
            return
        if kind == "dongzhu":
            await self.dongzhu_cmd(upd, ctx, code=code)
            return
        if kind == "streak":
            await self.streak_cmd(upd, ctx)
            return
        if kind == "ai":
            await self._send_ai_desk_view(message, uid)
            return
        if kind == "help":
            return
        if kind == "report":
            await self.report_cmd(upd, ctx)
            return
        await self._send_card_to(message, code, uid)

    async def buy_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        uid = str(update.effective_user.id)
        if len(args) < 3:
            await update.message.reply_text(
                "請輸入：代號 張數 價格\n例如：2330 1 500\n"
                "或先按「記買入」再打價格：68.5",
                reply_markup=self._keyboard(),
            )
            return
        code, lots, price = self._parse_buy_text(" ".join(args), uid=uid)
        if not code:
            code, lots, price = args[0], float(args[1]), float(args[2])
        hits = lookup_stocks(self.db_path, code)
        name = hits[0]["stock_name"] if hits else code
        msg = await asyncio.to_thread(record_buy, self.db_path, uid, code, name, lots, price)
        await update.message.reply_text(msg, reply_markup=self._keyboard())

    async def sell_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        uid = str(update.effective_user.id)
        actor = self._actor_key(update.message, uid=uid)
        if len(args) < 3:
            self._pending[actor] = "sell"
            await update.message.reply_text(
                "請輸入：代號 張數 價格\n例如：2330 1 520\n"
                "或持股按「賣出」再打價格：72（全賣）",
                reply_markup=self._keyboard(),
            )
            return
        code, lots, price = self._parse_sell_text(" ".join(args), uid=uid)
        if not code:
            code, lots, price = args[0], float(args[1]), float(args[2])
        msg = await asyncio.to_thread(record_sell, self.db_path, uid, code, lots, price)
        await update.message.reply_text(msg, reply_markup=self._keyboard())

    async def report_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        self._touch_user(uid, getattr(update.effective_user, "first_name", "") or "")
        await self._begin_issue_report(update.message, uid)

    async def _begin_issue_report(self, message, uid: str) -> None:
        actor = await self._enter_main_menu(message, uid)
        self._pending[actor] = "report"
        await message.reply_html(
            "<b>回報問題</b>\n"
            "請用<b>文字</b>或<b>截圖</b>說：哪裡怪、哪顆按鈕、哪一檔。\n"
            "會記下來並轉給偉權。不用給程式密鑰、不用給機器人密碼。\n"
            "要取消請按其他按鈕。",
            disable_web_page_preview=True,
        )

    def _notify_owner_issue(self, rec: dict) -> None:
        from issue_reports import format_owner_notice_html

        if not self.token or not self.chat_id:
            return
        if str(rec.get("user_id") or "") == str(self.chat_id):
            return
        try:
            import requests

            self._send_html(self.chat_id, format_owner_notice_html(rec))
            fid = str(rec.get("photo_file_id") or "").strip()
            if fid:
                requests.post(
                    f"https://api.telegram.org/bot{self.token}/sendPhoto",
                    json={
                        "chat_id": self.chat_id,
                        "photo": fid,
                        "caption": f"回報 #{rec.get('id')}",
                    },
                    timeout=20,
                )
        except Exception:
            logger.exception("回報轉偉權失敗")

    async def _commit_issue_report(
        self, message, uid: str, *, body: str = "", photo_file_id: str = ""
    ) -> None:
        from issue_reports import save_issue_report

        name = ""
        user = getattr(message, "from_user", None)
        if user is not None:
            name = getattr(user, "first_name", "") or ""
        try:
            rec = await asyncio.to_thread(
                save_issue_report,
                self.db_path,
                uid,
                display_name=name,
                body=body,
                photo_file_id=photo_file_id,
            )
        except ValueError:
            actor = self._actor_key(message, uid=uid)
            self._pending[actor] = "report"
            await message.reply_html("請打幾個字或傳一張截圖。要取消請按其他按鈕。")
            return
        except Exception:
            logger.exception("回報寫入失敗")
            await message.reply_text("這則沒記下，請再傳一次，或按其他按鈕取消。")
            return
        await message.reply_html(
            f"已記下（#{html_escape(rec.get('id'))}）。偉權會看到，之後對照修正。"
        )
        await asyncio.to_thread(self._notify_owner_issue, rec)

    async def on_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if msg is None:
            return
        if await self._reject_stranger(update):
            return
        uid = str(getattr(update.effective_user, "id", "") or "")
        if not uid:
            return
        token = _ACTIVE_PHONE_UID.set(uid)
        try:
            actor = self._actor_key(msg, uid=uid)
            self._touch_user(uid, getattr(update.effective_user, "first_name", "") or "")
            photos = getattr(msg, "photo", None) or []
            fid = str(getattr(photos[-1], "file_id", "") or "") if photos else ""
            cap = str(getattr(msg, "caption", "") or "")
            async with self._pending_lock(actor):
                if self._pending.get(actor) != "report":
                    return
                self._pending.pop(actor, None)
            await self._commit_issue_report(
                msg, uid, body=cap or "（截圖）", photo_file_id=fid
            )
        finally:
            _ACTIVE_PHONE_UID.reset(token)

    async def on_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.message
        if msg is None:
            return
        if await self._reject_stranger(update):
            return
        doc = getattr(msg, "document", None)
        mime = str(getattr(doc, "mime_type", "") or "")
        if not mime.startswith("image/"):
            return
        uid = str(getattr(update.effective_user, "id", "") or "")
        if not uid:
            return
        token = _ACTIVE_PHONE_UID.set(uid)
        try:
            actor = self._actor_key(msg, uid=uid)
            self._touch_user(uid, getattr(update.effective_user, "first_name", "") or "")
            fid = str(getattr(doc, "file_id", "") or "")
            cap = str(getattr(msg, "caption", "") or "")
            async with self._pending_lock(actor):
                if self._pending.get(actor) != "report":
                    return
                self._pending.pop(actor, None)
            await self._commit_issue_report(
                msg, uid, body=cap or "（截圖）", photo_file_id=fid
            )
        finally:
            _ACTIVE_PHONE_UID.reset(token)

    async def on_text(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        *,
        spoken: str | None = None,
    ):
        if not update.message:
            return
        if await self._reject_stranger(update):
            return
        raw_msg = spoken if spoken is not None else (update.message.text or "")
        raw = raw_msg.strip()
        if not raw:
            return
        text = _normalize_menu_text(raw)
        if not text:
            return
        uid = str(update.effective_user.id)
        token = _ACTIVE_PHONE_UID.set(uid)
        try:
            await self._on_text_bound(update, context, raw=raw, text=text, uid=uid)
        finally:
            _ACTIVE_PHONE_UID.reset(token)

    async def _on_text_bound(self, update, context, *, raw, text, uid: str):
        actor = self._actor_key(update.message, uid=uid)
        self._touch_user(uid, getattr(update.effective_user, "first_name", "") or "")
        if text.lower().lstrip("/") in ("start", "開始"):
            self._pending.pop(actor, None)
            await self.start_cmd(update, context)
            return
        if text in ("備份", "私人備份") or text.lower().lstrip("/") == "backup":
            self._pending.pop(actor, None)
            await self.backup_cmd(update, context)
            return
        if is_phone_code_query(text):
            self._pending.pop(actor, None)
            await self.code_cmd(update, context)
            return
        if text == MENU_BTN_BACK_MAIN:
            if str(self._pending.get(actor) or "") in ("biaoke:ask", "biaoke:chat"):
                await self._leave_biaoke(update.message, uid)
            elif str(self._pending.get(actor) or "") == "dongzhu":
                await self._leave_dongzhu(update.message, uid)
            else:
                await self._restore_main_menu(update.message, uid)
            return
        if text in MENU_BTN_LEAVE_BIAOKE_ALIASES:
            await self._leave_biaoke(update.message, uid)
            return
        if text in MENU_BTN_LEAVE_DONGZHU_ALIASES:
            await self._leave_dongzhu(update.message, uid)
            return
        if text in (MENU_BTN_STREAK, "連買區域", "外資連買區域"):
            logger.info("主選單：連買區 uid=%s", uid)
            await self.streak_cmd(update, context)
            return
        if text in MENU_COMPACT_ALIASES or text in MENU_FULL_ALIASES:
            self._pending.pop(actor, None)
            await self._force_reply_menu(update.message, uid)
            return
        if text in ("選單", "主選單") or text.lower().lstrip("/") == "menu":
            self._pending.pop(actor, None)
            await self.menu_cmd(update, context)
            return
        if text in ("說明", "幫助") or text.lower().lstrip("/") == "help":
            self._pending.pop(actor, None)
            return
        if text == "圖文":
            self._pending.pop(actor, None)
            return
        if text == "選股":
            self._pending.pop(actor, None)
            return
        if text in ("資金", "資金移動") or text.lower().lstrip("/") == "flow":
            logger.info("主選單：資金 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.flow_cmd(update, context)
            return
        if text in MENU_BTN_BIAOKE_ALIASES or text.lower().lstrip("/") in ("biaoke", "biaoda"):
            logger.info("主選單：飆客 uid=%s", uid)
            self._enter_biaoke_chat(update.message, uid)
            await self._send_biaoke_page(update.message, uid=uid)
            return
        if text == MENU_BTN_MARKET or text.lower().lstrip("/") == "market":
            if str(self._pending.get(actor) or "") in ("biaoke:ask", "biaoke:chat"):
                await self._send_biaoke_page(
                    update.message, ask="大盤現在", uid=uid
                )
                return
            logger.info("主選單：大盤 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.market_cmd(update, context)
            return
        if text == "當沖":
            logger.info("主選單：當沖 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.daytrade_cmd(update, context)
            return
        if text in ("隔日沖", "隔沖", "隔日"):
            logger.info("主選單：隔日沖 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.overnight_cmd(update, context)
            return
        if text in MENU_BTN_LEAVE_ZERO_ALIASES:
            logger.info("主選單：剛脫離零 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.leave_zero_cmd(update, context)
            return
        if text in MENU_BTN_DONGZHU_ALIASES:
            logger.info("主選單：洞燭先機 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.dongzhu_cmd(update, context)
            return
        if text in ("AI模擬倉", "模擬倉", "AI倉"):
            logger.info("主選單：AI模擬倉 uid=%s", uid)
            self._pending.pop(actor, None)
            await self._send_ai_desk_view(update.message, uid)
            return
        if text in MENU_BTN_CARD_ALIASES:
            logger.info("主選單：刷新 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.decision_card_btn(update, context)
            return
        if text == "海選":
            logger.info("主選單：海選 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.screen_cmd(update, context)
            return
        if text in ("興櫃", "興櫃海選", "興櫃名單"):
            logger.info("主選單：興櫃海選 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.emerging_screen_cmd(update, context)
            return
        if text in ("持股", "持倉"):
            logger.info("主選單：持股 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.portfolio_cmd(update, context)
            return
        if text in ("成交", "成交紀錄", "我的成交"):
            logger.info("主選單：成交 uid=%s", uid)
            self._pending.pop(actor, None)
            await self._send_trade_journal(update.message, uid, review=False)
            return
        if text in ("復盤", "我的復盤"):
            logger.info("主選單：復盤 uid=%s", uid)
            self._pending.pop(actor, None)
            await self._send_trade_journal(update.message, uid, review=True)
            return
        if text == "觀察":
            logger.info("主選單：觀察 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.watch_cmd(update, context)
            return
        if text in ("原因",) or text.lower().lstrip("/") == "why":
            logger.info("主選單：原因 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.why_cmd(update, context)
            return
        if text in (MENU_BTN_REPORT, "回報問題", "狀況回覆", "狀況"):
            logger.info("主選單：回報 uid=%s", uid)
            await self.report_cmd(update, context)
            return
        if text == "系統狀態":
            await update.message.reply_html(
                "WayneBot 雲端新版運作中。請用訊息下方按鈕操作。",
                reply_markup=self._keyboard(),
            )
            return
        async with self._pending_lock(actor):
            pending = self._pending.get(actor, "")
            if pending.startswith("fbuy:"):
                handled = await self._handle_buy_streak(
                    update.message, uid, pending, text, actor=actor
                )
                if handled:
                    return
            if pending == "screen:uni":
                handled = await self._handle_screen_pick(
                    update.message, uid, text, actor=actor
                )
                if handled:
                    return
            if pending == "report":
                self._pending.pop(actor, None)
                await self._commit_issue_report(
                    update.message, uid, body=raw, photo_file_id=""
                )
                return
            if pending in ("biaoke:ask", "biaoke:chat"):
                # 飆大視窗：股名／股號走飆大完全體＋主庫，不改走查股兩張圖。
                self._pending[actor] = "biaoke:chat"
                await self._send_biaoke_page(
                    update.message, ask=raw or text, uid=uid
                )
                return
            if pending == "dongzhu":
                self._pending[actor] = "dongzhu"
                await self._send_dongzhu_hold(update.message, raw or text)
                return
            pending = self._pending.pop(actor, "")
            if pending in ("card", "dcard", "chips", "fund", "industry", "watch"):
                handled = await self._handle_pending_pick(
                    update.message, uid, pending, text, actor=actor
                )
                if handled:
                    return
            if pending == "sell" or pending.startswith("sell:"):
                code = pending.split(":", 1)[1] if pending.startswith("sell:") else ""
                held_lots = self._held_lots_for(uid, code) if code else None
                parsed_code, lots, price = self._parse_sell_text(
                    text, code, held_lots=held_lots, uid=uid
                )
                if parsed_code is None:
                    if not _text_escapes_pending(text):
                        self._pending[actor] = pending or "sell"
                        if held_is_odd_lot_only(held_lots):
                            hint = _sell_holdings_prompt(code or "代號", held_lots)
                        else:
                            hint = (
                                "請輸入：價格（全賣）　例如：72\n或：張數 價格　例如：1 72\n"
                                "也可：代號 張數 價格　例如：2330 1 520"
                            )
                        await update.message.reply_text(
                            hint,
                            reply_markup=self._keyboard(),
                        )
                        return
                else:
                    msg = await asyncio.to_thread(
                        record_sell, self.db_path, uid, parsed_code, lots, price
                    )
                    await update.message.reply_text(msg, reply_markup=self._keyboard())
                    return
            if pending == "buy" or pending.startswith("buy:"):
                code = pending.split(":", 1)[1] if pending.startswith("buy:") else ""
                parsed_code, lots, price = self._parse_buy_text(text, code, uid=uid)
                if parsed_code is None:
                    if not _text_escapes_pending(text):
                        self._pending[actor] = pending or "buy"
                        held_lots = self._held_lots_for(uid, code) if code else None
                        if code:
                            hint = _buy_holdings_prompt(code, held_lots)
                        else:
                            hint = (
                                "請輸入：價格（1張）　例如：68.5\n或：張數 價格　例如：2 68.5\n"
                                "也可：代號 張數 價格　例如：2330 1 500"
                            )
                        await update.message.reply_text(
                            hint,
                            reply_markup=self._keyboard(),
                        )
                        return
                else:
                    hits = lookup_stocks(self.db_path, parsed_code)
                    name = hits[0]["stock_name"] if hits else parsed_code
                    msg = await asyncio.to_thread(
                        record_buy, self.db_path, uid, parsed_code, name, lots, price
                    )
                    await update.message.reply_text(msg, reply_markup=self._keyboard())
                    return
        logger.info("收到文字 uid=%s 字數=%s", uid, len(text))
        try:
            # 一般功能：代號／股名出三張圖卡（一則相簿）。沒按飆大就不進 overlay。
            handled = await self._dispatch_intent(
                update.message, uid, text, update=update, context=context
            )
            if handled:
                return
            hits = lookup_stocks(self.db_path, text)
            if hits_need_picker(hits):
                await update.message.reply_html(
                    self._hits_list_html(hits),
                    reply_markup=self._hits_keyboard(hits),
                    disable_web_page_preview=True,
                )
                return
            if len(hits) == 1:
                code = str(hits[0]["stock_id"])
                logger.info("名稱查詢命中 %s -> %s", text, code)
                await self._reply_card(update, code)
                return
            await update.message.reply_text(
                "找不到這檔。請打代號或名稱。撞名或國字打不準會列出相近的請你點。",
                reply_markup=self._keyboard(),
            )
        except Exception:
            logger.exception("查詢失敗")
            await update.message.reply_text(
                "查詢失敗。雲端可能還沒有日K，或出圖逾時。請先按 /start，稍後再試。",
                reply_markup=self._keyboard(),
            )

    async def on_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """語音／音檔（麥克風）→ 聽寫 → 同一條 on_text。人在飆大視窗就回飆大，不必打字。"""
        if not update.message:
            return
        if await self._reject_stranger(update):
            return
        uid = str(getattr(update.effective_user, "id", "") or "")
        token = _ACTIVE_PHONE_UID.set(uid)
        try:
            await self._on_voice_bound(update, context)
        finally:
            _ACTIVE_PHONE_UID.reset(token)

    async def _on_voice_bound(self, update, context):
        from voice_stt import (
            STT_MAX_BYTES,
            STT_MAX_SEC,
            audio_suffix,
            heard_html,
            stt_configured,
            stt_missing_html,
            transcribe_audio,
        )

        if not stt_configured():
            await update.message.reply_html(
                stt_missing_html(), disable_web_page_preview=True
            )
            return
        voice = update.message.voice or update.message.audio
        if voice is None:
            return
        duration = int(getattr(voice, "duration", 0) or 0)
        if duration > STT_MAX_SEC:
            await update.message.reply_html(
                f"這段語音超過 {STT_MAX_SEC} 秒。請講短一點再傳，例如「2330 為什麼漲」。"
            )
            return
        wait = await update.message.reply_text("正在聽…")
        tmp = None
        try:
            tg_file = await context.bot.get_file(voice.file_id)
            suffix = audio_suffix(voice)
            fd, tmp = tempfile.mkstemp(suffix=suffix)
            os.close(fd)
            await tg_file.download_to_drive(tmp)
            if os.path.getsize(tmp) > STT_MAX_BYTES:
                try:
                    await wait.delete()
                except Exception:
                    pass
                await update.message.reply_html("這段語音太大。請講短一點再傳。")
                return
            text = await asyncio.to_thread(transcribe_audio, tmp)
        except Exception:
            logger.exception("voice stt failed")
            try:
                await wait.delete()
            except Exception:
                pass
            await update.message.reply_html(PHONE_BUSY, reply_markup=self._keyboard())
            return
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        try:
            await wait.delete()
        except Exception:
            pass
        if not text:
            await update.message.reply_html("沒聽清楚。請再講一次，或直接打字。")
            return
        await update.message.reply_html(
            heard_html(text), disable_web_page_preview=True
        )
        await self.on_text(update, context, spoken=text)

    async def _handle_pending_pick(
        self, message, uid: str, pending: str, text: str, *, actor: str = ""
    ) -> bool:
        actor = actor or self._pending_actor(message, uid=uid)
        hits = lookup_stocks(self.db_path, text.split()[0].strip())
        if not hits:
            self._pending[actor] = pending
            await message.reply_text(
                "找不到這檔。請打代號或名稱。撞名或國字打不準會列出相近的請你點。",
                reply_markup=self._keyboard(),
            )
            return True
        if hits_need_picker(hits):
            self._pending[actor] = pending
            await message.reply_html(
                self._hits_list_html(hits),
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
            await self._send_card_to(message, code, uid)
            return True
        if pending == "dcard":
            await self._send_decision_card_quick(message, code, uid)
            return True
        if pending == "chips":
            chip_img = await asyncio.to_thread(
                generate_chips_image,
                code,
                self.db_path,
                self._scratch_chart_path(self.charts_dir, code, "chips", uid),
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
            from fundamentals import format_fundamentals_html

            html = await asyncio.to_thread(format_fundamentals_html, code, self.db_path)
            await message.reply_html(html, reply_markup=self._hub_keyboard(code), disable_web_page_preview=True)
            return True
        if pending == "industry":
            await self._send_industry(message, code, uid)
            return True
        return False

    async def _send_ai_desk_view(self, message, uid: str):
        """只顯示模擬倉現況，不執行買賣。晚上 20:00 模擬操盤不推播。"""
        from ai_trader import ai_desk_positions

        self._touch_user(uid)
        try:
            pages = await asyncio.to_thread(format_ai_desk_pages, self.portfolio_engine, uid)
            positions = await asyncio.to_thread(ai_desk_positions, self.portfolio_engine, uid)
            # 這頁已依手機自行斷行；再 reflow 會把「5檔漲2檔」「倍數 1.00」拆到下一行。
            parts: list = []
            for page in pages:
                parts.extend(chunk_telegram_html(page))
            for i, part in enumerate(parts):
                kb = self._ai_desk_keyboard(positions) if i == len(parts) - 1 else None
                await message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)
        except Exception:
            logger.exception("AI 模擬倉顯示失敗")
            await message.reply_text(PHONE_BUSY, reply_markup=self._keyboard())

    async def _send_ai_evolve(self, message, uid: str):
        """只看進化編碼與日誌，不執行買賣。"""
        from ai_trader import ai_user_id, format_evolve_report_html

        self._touch_user(uid)
        try:
            html = await asyncio.to_thread(
                format_evolve_report_html, self.db_path, ai_user_id(uid)
            )
            from ai_trader import ai_desk_positions

            positions = await asyncio.to_thread(ai_desk_positions, self.portfolio_engine, uid)
            parts = chunk_telegram_html(html, reflow=True)
            for i, part in enumerate(parts):
                kb = self._ai_desk_keyboard(positions) if i == len(parts) - 1 else None
                await message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)
        except Exception:
            logger.exception("AI 進化回報失敗")
            await message.reply_text(PHONE_BUSY, reply_markup=self._keyboard())

    async def _run_ai_now(self, message, uid: str):
        self._touch_user(uid)
        status = await self._transient_status(message, "AI 模擬操盤執行中（依今日海選紀律）…")
        try:
            result = await asyncio.to_thread(self.screener.run_full_screening)
            as_of = result.get("as_of") or result.get("date") or ""
            ai = await asyncio.to_thread(run_ai_desk, self.db_path, uid, result.get("results") or {}, as_of)
            bits = [ai.get("html") or ""]
            if not ai.get("bought") and not ai.get("sold"):
                bits.append(
                    f"<i>本次沒有新成交（候選 {ai.get('candidates') or 0} 檔）。平常最多 1 份、超跌才第 2 份，第 3 份留現金；或名單被高低卡／美股濾掉。</i>"
                )
            if ai.get("bought"):
                bits.append("<b>本次買進</b>\n" + "\n".join(html_escape(x) for x in ai["bought"]))
            if ai.get("sold"):
                bits.append("<b>本次賣出</b>\n" + "\n".join(html_escape(x) for x in ai["sold"]))
            if ai.get("lesson"):
                bits.append("進化：" + html_escape(ai["lesson"]))
            parts = chunk_telegram_html("\n\n".join(bits), reflow=True)
            from ai_trader import ai_desk_positions

            positions = await asyncio.to_thread(
                ai_desk_positions, self.portfolio_engine, uid
            )
            for i, part in enumerate(parts):
                kb = self._ai_desk_keyboard(positions) if i == len(parts) - 1 else None
                await message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)
        except Exception:
            logger.exception("AI 操盤失敗")
            await message.reply_text(PHONE_BUSY, reply_markup=self._keyboard())
        finally:
            await self._delete_message(status)

    def _quote_header_html(
        self,
        code: str,
        live_quote=None,
        hits: list | None = None,
    ) -> str:
        """看這檔開頭：現價／漲跌／盤中或收盤時間。熱訊用粗體（Telegram 不能指定紅字）。"""
        code = str(code or "").strip()
        if hits is None:
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

        rt = live_quote
        db_hit = hits[0] if hits else None
        if rt is None:
            try:
                from live_quote import fetch_lookup_quote

                rt = fetch_lookup_quote(code, mkt, self.db_path, db_hit=db_hit)
            except Exception:
                logger.exception("現價查詢失敗 code=%s", code)
        if rt:
            vol = int(rt.get("volume") or 0)
            t = str(rt.get("update_time") or "").strip()
            chg = rt.get("change")
            if chg is None:
                chg = price_change(rt.get("close"), rt.get("pct_change"), rt.get("yesterday_close"))
            from tg_layout import headline_lines, html_price, kv_html_compact

            price_label = "現價" if rt.get("source") != "yahoo" else "收盤"
            rows = [
                title,
                kv_html_compact(price_label, html_price(rt.get("close"))),
                kv_html_compact("漲跌", html_move(chg, rt.get("pct_change"))),
            ]
            if vol > 0:
                rows.append(kv_html_compact("成交", html_qty(vol, signed=False)))
            if t:
                if rt.get("source") == "yahoo":
                    rows.append(
                        html_escape(f"收盤　{t}　奇摩（16:30 融合後以官方庫為準）")
                    )
                else:
                    from live_quote import format_mis_clock_line

                    rows.append(html_escape(format_mis_clock_line(t)))
            return headline_lines(*rows)
        close = hits[0].get("close") if hits else None
        pct = hits[0].get("pct_change") if hits else None
        quote_date = str(hits[0].get("quote_date") or "") if hits else ""
        from config import taipei_now
        from live_quote import is_lookup_trading_day
        from trading_calendar import format_trading_date_zh
        from tg_layout import headline_lines, html_price, kv_html_compact

        today = taipei_now().strftime("%Y%m%d")
        if is_lookup_trading_day() and quote_date and quote_date < today:
            return headline_lines(
                title,
                "<i>盤中報價暫時無法取得，請稍後再試（不顯示過期庫內價）。</i>",
            )
        if close is not None:
            if quote_date:
                label = f"庫內收盤（{format_trading_date_zh(quote_date)}）"
            else:
                label = "庫內收盤"
            if quote_date and quote_date < today:
                note = (
                    f"<i>以下為 {format_trading_date_zh(quote_date)} 官方收盤"
                    f"（非交易日或盤後已融合）。</i>"
                )
            else:
                note = "<i>即時報價暫時沒接到，以下圖用庫內日K。</i>"
            return headline_lines(
                title,
                kv_html_compact(label, html_price(close)),
                kv_html_compact("漲跌", html_move(price_change(close, pct), pct)),
                note,
            )
        return title

    def _prefetch_mis_quote(self, code: str, hits: list | None = None):
        from live_quote import fetch_lookup_quote, is_lookup_trading_day

        if not is_lookup_trading_day():
            return None
        mkt = ""
        db_hit = hits[0] if hits else None
        if hits:
            mkt = str(hits[0].get("market") or "")
        elif code:
            h = lookup_stocks(self.db_path, code)
            if h:
                db_hit = h[0]
            mkt = str(h[0].get("market") or "") if h else ""
        return fetch_lookup_quote(code, mkt, self.db_path, db_hit=db_hit)

    async def _reply_card(self, update: Update, code: str):
        uid = str(update.effective_user.id)
        await self._send_card_to(update.message, code, uid)

    async def _send_decision_card_quick(self, message, code: str, uid: str = "", *, skip_wait_msg: bool = False):
        """盤中快捷：MIS 現價 + 高低決策卡（不重跑導航／籌碼，較快）。"""
        code = str(code).strip()
        uid = uid or self._uid_from_message(message)
        hits = lookup_stocks(self.db_path, code)
        if hits and hits[0].get("close") is None:
            await self._send_card_to(message, code, uid)
            return
        hub = self._hub_keyboard(code)
        actor = self._actor_key(message, uid=uid)
        wait_msg = None
        if not skip_wait_msg:
            try:
                wait_msg = await message.reply_text(
                    self._wait_bubble(
                        "決策卡進行中", 0, now="現價", rest="出圖", fill_sec=20.0
                    ),
                    parse_mode="HTML",
                )
                self._track_lookup_fade(actor, wait_msg, "wait")
            except Exception:
                wait_msg = None
        live_rt = None
        try:
            live_rt = await asyncio.wait_for(
                asyncio.to_thread(self._prefetch_mis_quote, code, hits),
                timeout=6.0,
            )
        except Exception:
            live_rt = None
        header_msg = None
        lookup_faded = False
        mkt_note = ""
        # 大盤結構提示改背景，不擋第一行現價
        async def _mkt_hint():
            nonlocal mkt_note
            try:
                from taiwan_market import analyze_taiwan_market

                snap = await asyncio.to_thread(analyze_taiwan_market, self.db_path, db_only=True, page_light=True)
                if snap.get("ok"):
                    fr = int(snap.get("falling_risk") or 0)
                    rp = str(snap.get("regime_plus") or "")
                    if fr >= 60 or rp in ("trend_down", "trend_up_late"):
                        hint = "大盤結構偏弱，少追。" if fr >= 60 else "多頭末端，少追。"
                        mkt_note = f"<i>⚠️ {hint}</i>\n"
                        if header_msg is not None and hasattr(header_msg, "edit_text"):
                            try:
                                header = mkt_note + await asyncio.to_thread(
                                    self._quote_header_html, code, live_rt, hits
                                )
                                await header_msg.edit_text(
                                    header, parse_mode="HTML", disable_web_page_preview=True
                                )
                            except Exception:
                                pass
            except Exception:
                pass

        hint_task = asyncio.create_task(_mkt_hint())
        try:
            header = mkt_note + await asyncio.to_thread(
                self._quote_header_html, code, live_rt, hits
            )
            header_msg = await message.reply_html(header, disable_web_page_preview=True)
            self._track_lookup_fade(actor, header_msg, "header")
        except Exception:
            logger.exception("決策卡現價列失敗 code=%s", code)
        if skip_wait_msg:
            wait_msg = None
        try:
            from wayne_navigator import NavigatorEngine, render_decision_card_png

            def _build_card():
                engine = NavigatorEngine(self.db_path)
                card = engine.get_decision_card(
                    code, lookback=20, merge_live=True, live_quote=live_rt
                )
                if isinstance(card, dict):
                    try:
                        from broker_points import attach_main_cost

                        attach_main_cost(card, self.db_path, fetch=False)
                    except Exception:
                        pass
                    card.pop("_ohlc", None)
                return card

            card = await asyncio.wait_for(asyncio.to_thread(_build_card), timeout=_CARD_BUILD_TIMEOUT)
            if card.get("error"):
                await message.reply_html(
                    f"⚠️ {html_escape(card.get('error'))}",
                    reply_markup=hub,
                    disable_web_page_preview=True,
                )
                return
            os.makedirs(self.charts_dir, exist_ok=True)
            card_path = await asyncio.wait_for(
                asyncio.to_thread(
                    render_decision_card_png,
                    card,
                    self._scratch_chart_path(self.charts_dir, code, "dcard", uid),
                ),
                timeout=_LOOKUP_PNG_TIMEOUT,
            )
            sent = False
            if card_path and os.path.exists(card_path):
                live_note = ""
                if card.get("is_live"):
                    clock_line = str(card.get("query_clock") or "")
                    if not clock_line:
                        from decision_card_signals import format_card_query_stamp

                        _, clock_line = format_card_query_stamp(
                            is_live=True,
                            latest_date=card.get("latest_date"),
                            generated_at=card.get("generated_at"),
                        )
                    live_note = f"（{clock_line}）" if clock_line else "（盤中即時）"
                with open(card_path, "rb") as f:
                    await message.reply_photo(
                        photo=f,
                        caption=_decision_card_photo_caption(card, code, live_note),
                        parse_mode="HTML",
                        reply_markup=hub,
                    )
                sent = True
                await self._dismiss_lookup_fades(actor)
                lookup_faded = True
            if not sent:
                from wayne_navigator import generate_decision_card

                html = await asyncio.to_thread(generate_decision_card, code, self.db_path)
                await message.reply_html(html, reply_markup=hub, disable_web_page_preview=True)
                await self._dismiss_lookup_fades(actor)
                lookup_faded = True
            self._remember_card(uid, code)
        except asyncio.TimeoutError:
            logger.exception("決策卡快捷逾時 code=%s", code)
            await message.reply_html(
                "決策卡產製逾時，請再按一次「決策卡」或打代號重試。",
                reply_markup=hub,
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("決策卡快捷失敗 code=%s", code)
            await message.reply_text("決策卡失敗，請稍後再試。", reply_markup=hub)
        finally:
            if wait_msg is not None:
                try:
                    await wait_msg.delete()
                except Exception:
                    pass
            if not lookup_faded:
                await self._dismiss_lookup_fades(actor, roles={"ack", "wait"})

    async def _send_navigation_chart(self, message, code: str, uid: str = ""):
        """按需產 180 日高低導航（重用剛查過的 _ohlc，免重跑決策卡）。"""
        code = str(code or "").strip()
        uid = uid or self._uid_from_message(message)
        wait = None
        try:
            wait = await message.reply_text(
                self._wait_bubble("導航圖進行中", 0, now="180日高低", fill_sec=30.0),
                parse_mode="HTML",
            )
        except Exception:
            pass
        hits = lookup_stocks(self.db_path, code)
        hub = self._hub_keyboard(code, em=self._hit_is_emerging(code, hits))
        ohlc = self._get_lookup_ohlc(uid, code)
        if ohlc is None or getattr(ohlc, "empty", True):
            from wayne_navigator import NavigatorEngine

            live_rt = await asyncio.to_thread(self._prefetch_mis_quote, code, None)

            def _reload():
                engine = NavigatorEngine(self.db_path)
                card = engine.get_decision_card(
                    code, lookback=20, merge_live=True, live_quote=live_rt
                )
                ctx = card.pop("_ohlc", None) if isinstance(card, dict) else None
                return ctx

            ohlc = await asyncio.wait_for(asyncio.to_thread(_reload), timeout=_CARD_BUILD_TIMEOUT)
            self._cache_lookup_ctx(uid, code, ohlc)
        if ohlc is None or getattr(ohlc, "empty", True):
            if wait is not None:
                try:
                    await wait.delete()
                except Exception:
                    pass
            await message.reply_html(
                f"⚠️ {html_escape(code)} 尚無足夠日K，無法出導航圖。",
                reply_markup=hub,
                disable_web_page_preview=True,
            )
            return
        os.makedirs(self.charts_dir, exist_ok=True)
        chart_path = self._scratch_chart_path(self.charts_dir, code, "nav", uid)
        try:
            from wayne_navigator import generate_chart

            path = await asyncio.wait_for(
                asyncio.to_thread(
                    generate_chart,
                    code,
                    "",
                    self.db_path,
                    chart_path,
                    ohlc,
                    already_normalized=True,
                ),
                timeout=_CHART_RENDER_TIMEOUT,
            )
        except asyncio.TimeoutError:
            path = ""
            logger.warning("導航圖逾時 code=%s", code)
        except Exception:
            path = ""
            logger.exception("導航圖失敗 code=%s", code)
        try:
            if not path or not self._chart_png_looks_ok(path):
                await message.reply_html(
                    "導航圖產出失敗，請再打一次代號。",
                    reply_markup=hub,
                    disable_web_page_preview=True,
                )
                return
            cap = "180日高低導航：實心＝當日觸發；空心＝接近。高點紫／低點綠。要看日K按圖下「K線」（奇摩股市）。"
            for attempt in range(3):
                try:
                    with open(self._prepare_lookup_album_photo(path), "rb") as f:
                        await message.reply_photo(
                            photo=f, caption=cap, parse_mode="HTML", reply_markup=hub
                        )
                    return
                except Exception as exc:
                    if attempt < 2 and type(exc).__name__ in ("TimedOut", "NetworkError", "RetryAfter"):
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    logger.exception("導航圖送出失敗 code=%s", code)
            await message.reply_html("導航圖送出失敗。", reply_markup=hub, disable_web_page_preview=True)
        finally:
            if wait is not None:
                try:
                    await wait.delete()
                except Exception:
                    pass

    async def _send_etf_category_pick(self, message, phrase: str, uid: str = ""):
        """分類詞還沒打完：先讓人點主動／被動／配息型，再列出成交量較大的幾檔。"""
        phrase = str(phrase or "").strip()
        if not phrase:
            await message.reply_text("請再打一次主動、被動或配息型。", reply_markup=self._keyboard())
            return
        hits = lookup_stocks(self.db_path, phrase)
        if hits_need_picker(hits):
            await message.reply_html(
                self._hits_list_html(hits),
                reply_markup=self._hits_keyboard(hits),
                disable_web_page_preview=True,
            )
            return
        if len(hits) == 1:
            await self._send_card_to(message, str(hits[0].get("stock_id") or phrase), uid)
            return
        await message.reply_text(
            "找不到這個 ETF 分類。可打主動、被動、配息型、月配、高股息。",
            reply_markup=self._keyboard(),
        )

    async def _send_card_to(self, message, code: str, uid: str = ""):
        code = str(code).strip()
        actor = self._actor_key(message, uid=uid or self._uid_from_message(message))
        lock = self._lookup_locks.setdefault(actor, asyncio.Lock())
        if lock.locked():
            await message.reply_text("上一檔還在出圖，請稍候再查。")
            return
        wait_msg = None
        try:
            wait_msg = await message.reply_text(
                self._chart_progress_text(0, current="table"),
                parse_mode="HTML",
            )
            self._track_lookup_fade(actor, wait_msg, "wait")
        except Exception:
            wait_msg = None
        hits = lookup_stocks(self.db_path, code)
        if hits and (
            hits[0].get("category_choice")
            or (
                hits[0].get("category")
                and str(hits[0].get("stock_id") or "") != code
            )
        ):
            if hits_need_picker(hits) or hits[0].get("category_choice"):
                await self._delete_message(wait_msg)
                await message.reply_html(
                    self._hits_list_html(hits),
                    reply_markup=self._hits_keyboard(hits),
                    disable_web_page_preview=True,
                )
                return
        if hits and hits[0].get("close") is None:
            await self._delete_message(wait_msg)
            h = hits[0]
            try:
                from stock_links import html_stock_anchor

                title = html_stock_anchor(h["stock_id"], h.get("stock_name") or "", self.db_path)
            except Exception:
                title = f"{html_escape(h['stock_id'])} {html_escape(h.get('stock_name') or '')}"
            mkt_raw = (h.get("market") or "").strip().upper()
            mkt = html_escape(h.get("market") or "")
            is_em = mkt_raw in ("EM", "EMERGING", "興櫃")
            uid_em = uid or self._uid_from_message(message)
            self._remember_card(uid_em, str(h.get("stock_id") or code))
            if is_em:
                body = self._em_no_listed_html(str(h.get("stock_id") or code), [h])
            else:
                body = (
                    f"{title}\n這是上市櫃股票（市場 {mkt or 'TW'}），"
                    "但<strong>雲端這台機器還沒有日K資料</strong>，所以暫時不能出決策卡。"
                    "請等行情庫下載完成後再打一次代號。"
                )
            try:
                await message.reply_html(
                    body,
                    reply_markup=self._hub_keyboard(h["stock_id"], em=is_em),
                    disable_web_page_preview=True,
                )
            except Exception:
                logger.exception("無日K提示失敗 code=%s", code)
                await message.reply_text(
                    f"{h.get('stock_id') or code} 還沒有日K，請稍後再打一次代號。"
                )
            return
        async with lock:
            await self._send_card_to_locked(
                message, code, uid, actor, hits, wait_msg=wait_msg
            )

    async def _send_card_to_locked(
        self,
        message,
        code: str,
        uid: str,
        actor: str,
        hits: list,
        wait_msg=None,
    ):
        lookup_faded = False
        sent_any = False
        is_em = self._hit_is_emerging(code, hits)
        progress_stop = asyncio.Event()
        progress_task = None
        op_t0 = time.monotonic()
        self._op_state_map()[actor] = {"sent": [], "current": "table", "t0": op_t0}
        if wait_msg is None:
            try:
                wait_msg = await message.reply_text(
                    self._chart_progress_text(0, current="table"),
                    parse_mode="HTML",
                )
                self._track_lookup_fade(actor, wait_msg, "wait")
            except Exception:
                wait_msg = None
        news_stats = None
        live_rt = None

        async def _fetch_news():
            try:
                from stock_news import fetch_stock_news_stats

                name0 = ""
                if hits:
                    name0 = str(hits[0].get("stock_name") or "")
                return await asyncio.wait_for(
                    asyncio.to_thread(
                        fetch_stock_news_stats, self.db_path, code, name0
                    ),
                    timeout=5.0,
                )
            except Exception:
                return None

        async def _fetch_mis():
            if is_em:
                return None
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._prefetch_mis_quote, code, hits),
                    timeout=6.0,
                )
            except Exception:
                return None

        news_stats, live_rt = await asyncio.gather(_fetch_news(), _fetch_mis())
        hub = self._hub_keyboard(code, em=is_em, news=news_stats)

        async def _header_bg() -> None:
            try:
                header = await asyncio.wait_for(
                    asyncio.to_thread(self._quote_header_html, code, live_rt, hits),
                    timeout=4.0,
                )
                header_msg = await message.reply_html(header, disable_web_page_preview=True)
                self._track_lookup_fade(actor, header_msg, "header")
            except asyncio.TimeoutError:
                logger.warning("現價列逾時 code=%s", code)
                fallback = await message.reply_text(f"查詢 {code}…（盤中報價較慢，繼續出圖）")
                self._track_lookup_fade(actor, fallback, "header")
            except Exception:
                logger.exception("現價列失敗 code=%s", code)
                fallback = await message.reply_text(f"查詢 {code}…")
                self._track_lookup_fade(actor, fallback, "header")

        header_task = asyncio.create_task(_header_bg())

        async def send_photo(path, caption, markup=None, *, kind: str = ""):
            nonlocal sent_any, lookup_faded
            min_h = 900 if kind == "chart" else 500
            if not self._png_looks_ok(path, min_h=min_h):
                logger.warning(
                    "略過殘缺圖 kind=%s code=%s size=%s",
                    kind,
                    code,
                    os.path.getsize(path) if path and os.path.exists(path) else 0,
                )
                return False
            for attempt in range(3):
                try:
                    with open(self._prepare_lookup_album_photo(path), "rb") as f:
                        await message.reply_photo(
                            photo=f, caption=caption, parse_mode="HTML", reply_markup=markup
                        )
                    logger.info(
                        "送圖成功 kind=%s code=%s bytes=%s attempt=%s",
                        kind,
                        code,
                        os.path.getsize(path),
                        attempt + 1,
                    )
                    if not lookup_faded:
                        lookup_faded = True
                        await self._dismiss_lookup_fades(actor, roles={"ack", "header"})
                    return True
                except Exception as exc:
                    err_name = type(exc).__name__
                    if attempt < 2 and err_name in ("TimedOut", "NetworkError", "RetryAfter"):
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    try:
                        with open(path, "rb") as f:
                            await message.reply_photo(photo=f, caption=caption[:200], reply_markup=markup)
                        logger.info("送圖成功(無HTML) kind=%s code=%s", kind, code)
                        if not lookup_faded:
                            lookup_faded = True
                            await self._dismiss_lookup_fades(actor, roles={"ack", "header"})
                        return True
                    except Exception:
                        try:
                            with open(path, "rb") as f:
                                await message.reply_photo(photo=f, caption=str(code)[:64])
                            logger.info("送圖成功(無鍵盤) kind=%s code=%s", kind, code)
                            sent_any = True
                            return True
                        except Exception:
                            logger.exception("送圖失敗 kind=%s path=%s attempt=%s", kind, path, attempt + 1)
            return False

        async def _progress_tick():
            while not progress_stop.is_set():
                if wait_msg is None:
                    break
                st = self._op_state_map().get(actor) or {}
                elapsed = int(time.monotonic() - op_t0)
                try:
                    await wait_msg.edit_text(
                        self._chart_progress_text(
                            elapsed,
                            sent=st.get("sent") or [],
                            current=str(st.get("current") or ""),
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(progress_stop.wait(), timeout=2.0)
                    break
                except asyncio.TimeoutError:
                    continue

        if wait_msg is not None:
            progress_task = asyncio.create_task(_progress_tick())

        hub_on = False

        async def _reply_visible(text, *, html=False, markup=None) -> bool:
            nonlocal sent_any
            attempts = ((html, markup), (html, None), (False, None))
            for use_html, mk in attempts:
                try:
                    if use_html:
                        await message.reply_html(
                            text, reply_markup=mk, disable_web_page_preview=True
                        )
                    else:
                        await message.reply_text(str(text)[:3500], reply_markup=mk)
                    sent_any = True
                    return True
                except Exception:
                    continue
            try:
                await message.reply_text(f"{code} 查詢結果送不出，請再打一次代號。")
                sent_any = True
                return True
            except Exception:
                logger.exception("查股可見回覆失敗 code=%s", code)
                return False

        async def _clear_wait() -> None:
            nonlocal wait_msg
            if wait_msg is not None:
                try:
                    await wait_msg.delete()
                except Exception:
                    pass
                wait_msg = None

        try:
            from chip_tape import build_tape
            from wayne_navigator import (
                NavigatorEngine,
                render_decision_card_png,
                render_first_glance_png,
            )
            from industry_card import render_industry_png

            def _build_card():
                engine = NavigatorEngine(self.db_path)
                card = engine.get_decision_card(
                    code, lookback=20, merge_live=not is_em, live_quote=None if is_em else live_rt
                )
                if isinstance(card, dict):
                    try:
                        from broker_points import attach_main_cost

                        attach_main_cost(card, self.db_path, fetch=False)
                    except Exception:
                        pass
                    if news_stats and news_stats.get("label"):
                        card["news_label"] = str(news_stats.get("label") or "")
                ohlc = card.pop("_ohlc", None) if isinstance(card, dict) else None
                return card, ohlc

            def _build_tape():
                try:
                    return build_tape(
                        self.db_path,
                        code,
                        merge_live=not is_em,
                        live_quote=None if is_em else live_rt,
                    ) or {}
                except Exception:
                    return {}

            t0 = time.monotonic()
            (card, ohlc), tape = await asyncio.gather(
                asyncio.wait_for(asyncio.to_thread(_build_card), timeout=_CARD_BUILD_TIMEOUT),
                asyncio.to_thread(_build_tape),
            )
            logger.info("看這檔 card+tape %.1fs code=%s", time.monotonic() - t0, code)
            try:
                await asyncio.wait_for(header_task, timeout=6.0)
            except Exception:
                logger.debug("現價列背景任務未完成 code=%s", code, exc_info=True)
            if card.get("error"):
                await _reply_visible(
                    f"⚠️ {html_escape(card.get('error'))}",
                    html=True,
                    markup=hub,
                )
                return
            os.makedirs(self.charts_dir, exist_ok=True)
            uid_key = uid or self._uid_from_message(message)
            glance_path = self._scratch_chart_path(self.charts_dir, code, "glance", uid_key)
            card_path_f = self._scratch_chart_path(self.charts_dir, code, "card", uid_key)
            industry_path = self._scratch_chart_path(self.charts_dir, code, "industry", uid_key)
            chart_path_f = self._scratch_chart_path(self.charts_dir, code, "nav", uid_key)
            ohlc = ohlc if ohlc is not None else card.get("_ohlc")
            if isinstance(card, dict):
                card.pop("_ohlc", None)
            self._cache_lookup_ctx(uid_key, code, ohlc)

            def _render_glance():
                return render_first_glance_png(
                    code, card, tape, glance_path, self.db_path, ohlc=ohlc
                )

            glance_cap = _glance_photo_caption("", card)
            card_cap = _decision_card_photo_caption(card, code)
            name_cap = html_escape(_stock_caption_name(card, code) or code)
            industry_cap = f"{name_cap}　產業"
            chart_cap = f"{name_cap}　導航"

            def _render_industry():
                return render_industry_png(
                    code, self.db_path, industry_path, allow_fetch=True, max_fetch=1
                )

            def _render_chart():
                from wayne_navigator import generate_chart

                return generate_chart(
                    code,
                    "",
                    self.db_path,
                    chart_path_f,
                    ohlc,
                    already_normalized=True,
                )

            render_plan = [
                ("glance", _render_glance, _LOOKUP_PNG_TIMEOUT, glance_cap, None),
                ("card", lambda: render_decision_card_png(card, card_path_f), _LOOKUP_PNG_TIMEOUT, card_cap, hub),
                ("industry", _render_industry, _LOOKUP_PNG_TIMEOUT, industry_cap, None),
                ("chart", _render_chart, _LOOKUP_PNG_TIMEOUT, chart_cap, None),
            ]
            kind_labels = {"glance": "介紹圖", "card": "決策卡", "industry": "產業圖", "chart": "導航圖"}
            sent_kinds: list[str] = []
            ready_items: list = []

            # 四張畫完一次送相簿（2×2 縮圖，點開最高像素）。
            for kind, fn, timeout_s, caption, markup in render_plan:
                st = self._op_state_map().setdefault(actor, {"sent": [], "current": kind})
                st["current"] = kind
                logger.info("查股階段 current=%s sent=%s code=%s", kind, st.get("sent"), code)
                path = ""
                attempts = 2
                for attempt in range(attempts):
                    try:
                        path = await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout_s)
                    except asyncio.TimeoutError:
                        logger.warning("看這檔 %s 逾時 code=%s attempt=%s", kind, code, attempt + 1)
                        path = ""
                        break
                    except Exception:
                        logger.exception("看這檔 %s 產圖失敗 code=%s", kind, code)
                        path = ""
                        break
                    looks_ok = (
                        self._chart_png_looks_ok(path)
                        if kind == "chart"
                        else self._png_looks_ok(path)
                    )
                    if not looks_ok:
                        logger.warning(
                            "殘缺圖重試 kind=%s code=%s attempt=%s size=%s",
                            kind,
                            code,
                            attempt + 1,
                            os.path.getsize(path) if path and os.path.exists(path) else 0,
                        )
                        path = ""
                        continue
                    break
                logger.info("看這檔 %s ready code=%s path=%s", kind, code, bool(path))
                if path:
                    ready_items.append((kind, path, caption, markup))
                    sent_kinds.append(kind)
                    st = self._op_state_map().setdefault(actor, {"sent": [], "current": ""})
                    st["sent"] = list(sent_kinds)
                    nxt = next((k for k, *_ in render_plan if k not in sent_kinds), "")
                    st["current"] = nxt
                    logger.info("查股階段已畫 %s code=%s", sent_kinds, code)
                    if wait_msg is not None:
                        try:
                            await wait_msg.edit_text(
                                self._chart_progress_text(
                                    int(time.monotonic() - op_t0),
                                    sent=sent_kinds,
                                    current=nxt or "album",
                                )
                            )
                        except Exception:
                            pass

            try:
                gc.collect()
            except Exception:
                pass

            album_ok = False
            if len(ready_items) >= 2:
                album_ok = await self._send_lookup_album(message, ready_items)
            if album_ok:
                sent_any = True
                if not lookup_faded:
                    lookup_faded = True
                    await self._dismiss_lookup_fades(actor, roles={"ack", "header"})
            else:
                for kind, path, caption, markup in ready_items:
                    ok = await send_photo(path, caption, markup, kind=kind)
                    if ok and markup is hub:
                        hub_on = True
                    if ok:
                        sent_any = True

            if sent_any and not hub_on:
                if len(sent_kinds) >= len(render_plan):
                    done_txt = html_escape(_stock_caption_name(card, code) or code)
                else:
                    miss = [kind_labels[k] for k, *_ in render_plan if k not in sent_kinds]
                    done_txt = (
                        f"已送 {len(sent_kinds)}/{len(render_plan)} 張"
                        f"（缺：{'、'.join(miss)}）。請再打一次代號補圖。"
                    )
                await _reply_visible(done_txt, html=True, markup=hub)
            elif not sent_any:
                from wayne_navigator import generate_decision_card

                html = await asyncio.to_thread(generate_decision_card, code, self.db_path)
                await _reply_visible(
                    f"圖片產出失敗，改送文字版（{html_escape(code)}）。\n{html}",
                    html=True,
                    markup=hub,
                )
                if not lookup_faded:
                    lookup_faded = True
                    await self._dismiss_lookup_fades(actor)
        except asyncio.TimeoutError:
            logger.exception("看這檔出圖逾時 code=%s", code)
            if not sent_any:
                await _reply_visible(
                    "圖產製逾時（雲端較慢或剛醒機）。請再打一次代號；若仍卡住請回報。",
                    html=True,
                    markup=hub,
                )
            else:
                await _reply_visible(
                    "後面的圖逾時。可用下面按鈕繼續。", html=True, markup=hub
                )
        except Exception:
            logger.exception("看這檔出圖失敗 code=%s", code)
            if not sent_any:
                try:
                    from wayne_navigator import generate_decision_card

                    html = await asyncio.to_thread(generate_decision_card, code, self.db_path)
                except Exception:
                    html = f"查詢 {html_escape(code)} 失敗。"
                await _reply_visible(html, html=True, markup=hub)
        finally:
            progress_stop.set()
            if progress_task is not None:
                progress_task.cancel()
            await _clear_wait()
            fade_roles = {"ack", "wait"}
            if sent_any:
                fade_roles.add("header")
            await self._dismiss_lookup_fades(actor, roles=fade_roles)
            if not sent_any:
                await _reply_visible(f"{code} 卡片沒送出，請再打一次代號。")
            self._op_state_map().pop(actor, None)
        uid = uid or self._uid_from_message(message)
        self._remember_card(uid, code)

    async def _send_lookup_album(self, message, items: list) -> bool:
        """四張一次送，Telegram 一則四格縮圖。圖說不講義。"""
        from telegram import InputFile, InputMediaPhoto

        if len(items) < 2:
            return False
        handles = []
        try:
            media = []
            first_cap = str(items[0][2] or "").strip()
            album_cap = first_cap
            for kind, path, _caption, _markup in items:
                if kind == "chart":
                    if not self._chart_png_looks_ok(path):
                        continue
                elif not self._png_looks_ok(path):
                    continue
                send_path = self._prepare_lookup_album_photo(path)
                fh = open(send_path, "rb")
                handles.append(fh)
                fname = os.path.basename(send_path)
                if not fname.lower().endswith((".jpg", ".jpeg")):
                    fname = (os.path.splitext(fname)[0] or "photo") + ".jpg"
                file_obj = InputFile(fh, filename=fname)
                if not media:
                    if album_cap:
                        media.append(
                            InputMediaPhoto(
                                media=file_obj, caption=album_cap[:1024], parse_mode="HTML"
                            )
                        )
                    else:
                        media.append(InputMediaPhoto(media=file_obj))
                else:
                    media.append(InputMediaPhoto(media=file_obj))
            if len(media) < 2:
                return False
            await message.reply_media_group(media=media)
            logger.info("送相簿成功 n=%s", len(media))
            return True
        except Exception:
            logger.exception("送相簿失敗，改逐張")
            return False
        finally:
            for fh in handles:
                try:
                    fh.close()
                except Exception:
                    pass

    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        uid = str(q.from_user.id)
        if await self._reject_stranger(update):
            return
        self._touch_user(uid, getattr(q.from_user, "first_name", "") or "")
        token = _ACTIVE_PHONE_UID.set(uid)
        try:
            await self._on_callback_bound(update, context, q, uid)
        finally:
            _ACTIVE_PHONE_UID.reset(token)

    async def _on_callback_bound(self, update, context, q, uid: str):
        data = q.data or ""
        if data.startswith("cat:") or data.startswith("noop"):
            hints = {
                "revenue_cross": "優先看：營收轉強 × 量價突破",
                "leave_zero": "黃金買點：獲利格剛離零且趨勢向上（按表，不是每個紅箭頭低點）",
                "golden_buy": "重點觀察：60低超跌且趨勢向上（注意觀察，不是今天必買）",
                "select_01": "周帶量：短線轉強且趨勢向上，靠近20日高少追",
                "select_02": "站上季線：昨收在季線下、今日站上；空頭反彈不進",
                "select_03": "止跌：月低附近有人接、量沒死；空頭反彈不進",
                "day_trade": "當沖：進場 / 停利 / 停損",
                "overnight": "隔日沖：尾盤佈局",
            }
            await q.answer(hints.get(data.split(":", 1)[-1], "分類標記")[:200])
            return
        if data.startswith("rw:"):
            await self._remove_watch_clicked(q, data[3:].strip())
            return
        if data.startswith("fb:"):
            await self._handle_buy_streak_callback(q, uid, data)
            return
        if data.startswith("pg:"):
            await q.answer()
            return
        if data.startswith("sc:"):
            await self._handle_screen_pick_callback(q, uid, data)
            return
        if data.startswith("bkdk:"):
            sid = data[5:].strip()
            await q.answer("官方日K")
            if not sid:
                return
            self._enter_biaoke_chat(q.message, uid)
            ask = "現在波浪位階" if sid == "TWII" else sid
            await self._send_biaoke_structure_chart(q.message, ask, uid)
            return
        if data.startswith("bkq:"):
            sid = data[4:].strip()
            await q.answer("問飆大")
            if not sid:
                return
            self._enter_biaoke_chat(q.message, uid)
            await self._send_biaoke_page(q.message, ask=sid, uid=uid)
            return
        if data.startswith("bk:"):
            kind = data[3:]
            if kind == "leave":
                await q.answer("離開飆大")
                await self._leave_biaoke(q.message, uid)
                return
            if kind == "see":
                await q.answer("怎麼觀察")
                await self._send_biaoke_page(q.message, ask="怎麼觀察", uid=uid)
                return
            if kind == "yend":
                await q.answer("去年年底")
                await self._send_biaoke_page(q.message, ask="去年年底", uid=uid)
                return
            if kind == "ask":
                await q.answer("查個股")
                from biaoke_brain import CHAT_HINT

                self._enter_biaoke_chat(q.message, uid)
                await q.message.reply_html(
                    CHAT_HINT,
                    disable_web_page_preview=True,
                    reply_markup=self._biaoke_hub_markup(""),
                )
                return
            if kind == "mkt":
                await q.answer("大盤")
                self._enter_biaoke_chat(q.message, uid)
                await self._send_biaoke_page(q.message, ask="大盤現在", uid=uid)
                return
            await q.answer()
            return
        if data == "em:go":
            await q.answer("興櫃海選開始")
            await self._run_emerging_screening(q.message)
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
        if data.startswith("g:"):
            uid = str(q.from_user.id)
            await self._send_navigation_chart(q.message, data[2:].strip(), uid)
            return
        if data.startswith("d:") or data.startswith("r:"):
            uid = str(q.from_user.id)
            await self._send_decision_card_quick(q.message, data[2:].strip(), uid)
            return
        if data.startswith("e:"):
            uid = str(q.from_user.id)
            await self._send_etf_category_pick(q.message, data[2:].strip(), uid)
            return
        if data.startswith("k:"):
            uid = str(q.from_user.id)
            code = data[2:].strip()
            actor = self._actor_key(q.message, uid=uid)
            if str(self._pending.get(actor) or "") == "dongzhu":
                await self._send_dongzhu_hold(q.message, code)
                return
            try:
                await self._send_card_to(q.message, code, uid)
            except Exception:
                logger.exception("callback 查股失敗")
                try:
                    await q.message.reply_text(
                        f"{code} 出圖失敗，請再打一次代號。"
                    )
                except Exception:
                    pass
            return
        if data.startswith("ys:"):
            uid = str(q.from_user.id)
            code = data[3:].strip()
            await q.message.reply_html(sell_honest_html(), disable_web_page_preview=True)
            await self._send_card_to(q.message, code, uid)
            return
        if data.startswith("yw:"):
            uid = str(q.from_user.id)
            kind = data[3:].strip()
            await self._run_intent_kind(q.message, uid, kind, "")
            return
        if data.startswith("h:"):
            await self._send_chips_to(q.message, data[2:].strip(), str(q.from_user.id))
            return
        if data.startswith("f:"):
            await self._send_fund_to(q.message, data[2:].strip())
            return
        if data.startswith("n:"):
            await self._send_industry(q.message, data[2:].strip(), str(q.from_user.id))
            return
        if data.startswith("i:"):
            uid = str(q.from_user.id)
            await self._send_card_to(q.message, data[2:].strip(), uid)
            return
        if data.startswith("b:"):
            uid = str(q.from_user.id)
            code = data[2:].strip()
            actor = self._actor_key(q.message, uid=uid)
            self._pending[actor] = f"buy:{code}"
            lots = self._held_lots_for(uid, code)
            await q.message.reply_text(
                _buy_holdings_prompt(code, lots),
                reply_markup=self._keyboard(),
            )
            return
        if data.startswith("x:"):
            uid = str(q.from_user.id)
            code = data[2:].strip()
            actor = self._actor_key(q.message, uid=uid)
            self._pending[actor] = f"sell:{code}"
            lots = self._held_lots_for(uid, code)
            await q.message.reply_text(
                _sell_holdings_prompt(code, lots),
                reply_markup=self._keyboard(),
            )
            return
        if data == "tj:trades":
            await self._send_trade_journal(q.message, str(q.from_user.id), review=False)
            return
        if data == "tj:review":
            await self._send_trade_journal(q.message, str(q.from_user.id), review=True)
            return
        if data == "ai_view":
            await self._send_ai_desk_view(q.message, str(q.from_user.id))
            return
        if data == "ai_run":
            await self._run_ai_now(q.message, str(q.from_user.id))
            return
        if data == "ai_evolve":
            await self._send_ai_evolve(q.message, str(q.from_user.id))
            return
        if data == "screen":
            await self._start_screen_pick(q.message, str(q.from_user.id))
        elif data == "daytrade":
            await self._run_trade_bucket(
                q.message,
                bucket_key="day_trade",
                live_bucket="daytrade",
                title="⚡ 當沖候選（盤中）",
                subtitle="現在盤中。沒進場：不要貴過「現在不要貴過」那一價。已進場：漲 3% 先出一部分，跌破均價先走。",
                topic="daytrade",
                status_text="⚡ 當沖查詢中（盤中現價複核）…",
                menu_label="當沖",
                loader=self.screener.screen_daytrade,
            )
        elif data == "overnight":
            await self._run_trade_bucket(
                q.message,
                bucket_key="overnight",
                live_bucket="overnight",
                title="⚡ 隔日沖候選（盤中即時）",
                subtitle="盤中即時複核：只列此刻漲幅≥2.5% 的標的；現價旁小字＝報價時間。尾盤保險買進；明早開高+3.5～4.8%；防守跌破先走。",
                topic="overnight",
                status_text="⚡ 隔日沖查詢中（盤中現價複核）…",
                menu_label="隔日沖",
                loader=self.screener.screen_overnight,
            )
        elif data == "portfolio":
            await self._send_portfolio(q.message, str(q.from_user.id))
        elif data == "watch":
            await self._send_watch(q.message, str(q.from_user.id))
        elif data in ("card", "chips", "fund", "industry", "buy"):
            await self._prompt_pick(q.message, str(q.from_user.id), data)
        elif data == "sell":
            uid = str(q.from_user.id)
            actor = self._actor_key(q.message, uid=uid)
            self._pending[actor] = "sell"
            await q.message.reply_text("請輸入：代號 張數 價格\n例如：2330 1 520", reply_markup=self._keyboard())

    async def _notify_phones_updated(self, app) -> None:
        """新版上線才跟偉權／哥哥說已更新。同一 SHA 重開不重送。"""
        sha = phone_git_sha()
        if not should_notify_phone_update(sha):
            return
        uids = [str(u).strip() for u in allowed_telegram_uids() if str(u).strip()]
        if not uids:
            return
        text = phone_update_notice(sha)
        n = 0
        for uid in uids:
            try:
                chat_id = int(uid) if str(uid).isdigit() else uid
                await app.bot.send_message(chat_id=chat_id, text=text)
                n += 1
            except Exception:
                logger.exception("已更新通知失敗 uid 略")
        if n:
            try:
                remember_notified_sha(sha)
            except Exception:
                logger.exception("已更新 SHA 沒寫成")

    def run_polling(self):
        if not TELEGRAM_AVAILABLE:
            logger.error("未安裝 python-telegram-bot")
            return
        if not self.token:
            logger.error("缺少 TELEGRAM_BOT_TOKEN")
            return
        if skip_telegram_polling():
            logger.info("WAYNE_SKIP_POLLING／Cursor Cloud：拒絕啟動 getUpdates 輪詢")
            return
        async def _heartbeat_loop():
            """在事件迴圈裡跳，迴圈卡死心跳就變舊，/health 才抓得到。"""
            from ops_watchdog import HEARTBEAT_POLLING, record_heartbeat

            while True:
                try:
                    await asyncio.to_thread(record_heartbeat, self.db_path, HEARTBEAT_POLLING, "run_polling")
                except Exception:
                    logger.debug("輪詢心跳失敗", exc_info=True)
                await asyncio.sleep(120)

        async def _on_start(app):
            try:
                asyncio.create_task(_heartbeat_loop())
            except Exception:
                logger.exception("輪詢心跳啟動失敗")
            try:
                if not skip_chart_warmup():
                    from wayne_navigator import prewarm_card_fonts

                    await asyncio.to_thread(prewarm_card_fonts)
            except Exception:
                logger.exception("字型預熱失敗")
            try:
                await app.bot.set_my_commands(
                    [BotCommand(name, desc) for name, desc in TELEGRAM_BOT_COMMANDS]
                )
                await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
            except Exception:
                logger.exception("set_my_commands 失敗")
            try:
                await self._notify_phones_updated(app)
            except Exception:
                logger.exception("手機已更新通知失敗")

        app = (
            Application.builder()
            .token(self.token)
            .concurrent_updates(True)
            .connect_timeout(30.0)
            .read_timeout(30.0)
            .write_timeout(120.0)
            .pool_timeout(30.0)
            .get_updates_connect_timeout(30.0)
            .get_updates_read_timeout(60.0)
            .get_updates_write_timeout(30.0)
            .get_updates_pool_timeout(30.0)
            .post_init(_on_start)
            .build()
        )
        app.add_handler(CommandHandler("start", self._wrap_cmd(self.start_cmd)))
        app.add_handler(CommandHandler("menu", self._wrap_cmd(self.menu_cmd)))
        app.add_handler(CommandHandler("backup", self._wrap_cmd(self.backup_cmd)))
        app.add_handler(CommandHandler("code", self._wrap_cmd(self.code_cmd)))
        app.add_handler(CommandHandler("why", self._wrap_cmd(self.why_cmd)))
        app.add_handler(CommandHandler("market", self._wrap_cmd(self.market_cmd)))
        app.add_handler(CommandHandler("help", self._wrap_cmd(self.help_cmd)))
        app.add_handler(CommandHandler("screen", self._wrap_cmd(self.screen_cmd)))
        app.add_handler(CommandHandler("daytrade", self._wrap_cmd(self.daytrade_cmd)))
        app.add_handler(CommandHandler("overnight", self._wrap_cmd(self.overnight_cmd)))
        app.add_handler(CommandHandler("portfolio", self._wrap_cmd(self.portfolio_cmd)))
        app.add_handler(CommandHandler("watch", self._wrap_cmd(self.watch_cmd)))
        app.add_handler(CommandHandler("flow", self._wrap_cmd(self.flow_cmd)))
        app.add_handler(CommandHandler("card", self._wrap_cmd(self.card_cmd)))
        app.add_handler(CommandHandler("chips", self._wrap_cmd(self.chips_cmd)))
        app.add_handler(CommandHandler("fund", self._wrap_cmd(self.fund_cmd)))
        app.add_handler(CommandHandler("industry", self._wrap_cmd(self.industry_cmd)))
        app.add_handler(CommandHandler("buy", self._wrap_cmd(self.buy_cmd)))
        app.add_handler(CommandHandler("sell", self._wrap_cmd(self.sell_cmd)))
        app.add_handler(CallbackQueryHandler(self.on_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self.on_voice))
        app.add_handler(MessageHandler(filters.PHOTO, self.on_photo))
        app.add_handler(MessageHandler(filters.Document.IMAGE, self.on_document))

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
