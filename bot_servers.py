"""
WayneBot Telegram 操作層
- 兩排主選單（輸入列旁邊四格鍵盤圖示）；直立式不再重複主選單按鈕
- 打股票代號 → 介紹圖（上半資訊、下半高低導航）＋決策卡；完整橫式導航按圖下按鈕
- 海選 / 當沖 / 隔日沖 / 持股 / 觀察 / 資金 / 連買區
"""
from __future__ import annotations

import asyncio
import gc
import logging
import os
import struct
import tempfile
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

# Render 免費方案冷啟＋行情庫索引期間，第一檔查詢常超過 45s。
_CARD_BUILD_TIMEOUT = float(os.getenv("WAYNE_CARD_BUILD_TIMEOUT", "90"))
_CHART_RENDER_TIMEOUT = float(os.getenv("WAYNE_CHART_RENDER_TIMEOUT", "120"))
# 介紹圖／決策卡與導航圖同一逾時。醒機時 matplotlib 冷啟，60s 會只送到介紹圖。
_LOOKUP_PNG_TIMEOUT = float(os.getenv("WAYNE_LOOKUP_PNG_TIMEOUT", str(_CHART_RENDER_TIMEOUT)))

from config import (
    get_charts_dir,
    get_db_path,
    get_telegram_config,
    skip_chart_warmup,
    skip_telegram_polling,
    telegram_uid_allowed,
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
from ai_trader import format_ai_desk_html, run_ai_desk
from chips import generate_chips_image
from intent_router import (
    NEEDS_STOCK,
    no_cost_honest_html,
    parse_intent,
    sell_honest_html,
)

logger = logging.getLogger(__name__)


def _normalize_menu_text(text: str) -> str:
    """主選單按鈕文字正規化（全形、空白）。"""
    t = unicodedata.normalize("NFKC", (text or "").strip())
    return t.replace("\u3000", "").strip()


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
    return name or sid or "決策卡"


def _photo_sell_caption(base: str, card: dict | None, *, fallback: str = "當日K＋籌碼價量") -> str:
    """圖說：有如何賣就寫在圖底下；沒有就不硬塞網頁走勢／點縮圖講解。"""
    cap = str(base or "").strip() or str(fallback or "").strip()
    if not card:
        return cap
    try:
        from sell_discipline import attach_sell, sell_note_short

        if not str(card.get("sell_action") or "").strip():
            attach_sell(card)
        short = sell_note_short(card)
    except Exception:
        return cap
    if not short:
        return cap
    note = f"Ai建議　{html_escape(short)}"
    return f"{cap}\n{note}" if cap else note


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

HELP_TOPICS = {
    "guide": (
        "<b>WayneBot 使用說明</b>\n"
        "點訊息下方分類鈕看細節，按 <b>✕</b> 收合。\n"
        "「圖文」一共 8 張，<b>一次只出一張</b>。按「第 2 張」換頁，這一張會換成下一張。\n"
        "\n"
        "<b>第一次用，先做這三步</b>\n"
        "1　點輸入列旁邊的鍵盤圖示（<b>四格那顆 ⌨️</b>），叫出兩排按鈕（不見就打 /menu）\n"
        "2　<b>直接打代號</b>看圖，例如 "
        + LOOKUP_CODE_EXAMPLES_HTML
        + "（不要先按「刷新」）。股票四碼、ETF 可含 L／R／A。海選名單仍只有股票／KY\n"
        "3　兩張圖出來後，<b>籌碼／營收／產業／K線／導航圖</b>在圖下面，不在右側四格鍵盤\n"
        "\n"
        "<b>主選單在哪？</b>\n"
        "不在訊息最下面。漢堡在輸入列左邊，四格鍵盤圖示在右邊。點四格展開兩排。\n"
        "打完字若只剩英文鍵盤，再點一次四格 ⌨️。也可打 /menu。\n"
        "也可打股名：撞名或國字打不準會列出相近的請你點，不會猜錯就出圖。\n"
        "打 /help 或按「說明」看本頁。要圖就點下方「圖文」。\n"
        "\n"
        "<b>兩排按鈕（左→右）</b>\n"
        "第一排：<b>說明</b>｜<b>海選</b>｜<b>持股</b>｜<b>觀察</b>｜<b>刷新</b>｜<b>回報</b>\n"
        "第二排：<b>大盤</b>｜<b>資金</b>｜<b>當沖</b>｜<b>隔日沖</b>｜<b>AI倉</b>｜<b>連買區</b>\n"
        "點下方「第一排」「第二排」看每顆怎麼用。畫面怪按第一排最右「回報」。\n"
        "打「精簡選單」只留第一週常用六顆；「完整選單」恢復十二顆。\n"
        "\n"
        "<b>挑股認哪一欄（最重要）</b>\n"
        "早報／海選優先認<b>黃金買點</b>（這一欄以前叫「起漲」）：獲利格剛離開 0，或還在 <b>0.x%</b> 綠底。認表、按表操課，不認圖上紅箭頭。低買高賣。\n"
        "\n"
        "<b>重點觀察</b>（這一欄以前叫「黃金買點」）：還壓在近 60 個日曆天收盤低、獲利還在 0 附近。是叫你注意、觀察，不是已經起漲，也不是立刻買。\n"
        "盤中請打開該檔決策卡對獲利格。名單是官方收盤掃的，不是盤中即時。\n"
        "\n"
        "<b>查某一檔</b>\n"
        "打股名或代號會<b>一次出兩張圖</b>：<b>介紹圖</b>（上半資訊、下半180日高低導航）→ 決策卡。完整橫式導航按圖下<b>導航圖</b>。\n"
        "\n"
        "圖下方（查完才出現，不是主選單那兩排）：\n"
        "• <b>籌碼</b>　三大法人買賣超圖\n"
        "• <b>營收</b>　月營收、季報毛利\n"
        "• <b>產業</b>　一張圖卡：同業中位＋本產業法人；股名旁公開細項小框（沒有就不畫）\n"
        "• <b>報導</b>　近 7 日 Google 新聞則數（有真數才出現）。點數字開搜尋自己讀；則數變多不是賣訊、不進海選\n"
        "• <b>K線</b>　開這一檔圖：一進先鎖定即時日K＋成交量。可自己改 15 分／60 分，或五日／十日／月線／季線。高低卡／獲利不會帶過去。興櫃沒這檔就不出現\n"
        "• <b>觀察</b>　加入自選（還沒買）\n"
        "• <b>記買入</b>　記真實持股，接著打 <code>張數 價格</code>，例 <code>1 68.5</code>；零股請寫 <code>200股 631.6</code>\n"
        "\n"
        "介紹圖粉紅「紀律」＝先別追／有持股先出一點，<b>不是買訊</b>。如何賣：最高價＝20日高對最高溫，不自動賣。細節看「查股」。\n"
        "名稱撞名、國字打不準、KY 沒寫對：會列出相近的；藍字＝奇摩，左邊＝看這檔，右 <b>➕</b>＝觀察。讀音猜中也要點確認才出圖。\n"
        "\n"
        "<b>海選怎麼轉 LINE</b>\n"
        "海選＝依最近一次官方收盤掃全市場，按一次等 2～5 分鐘，勿連按。\n"
        "興櫃：說明頁或海選底下按「興櫃」（也可打「興櫃」／「興櫃海選」）。用櫃買官方日均價跑黃金買點／重點觀察，不進上市櫃海選桶。\n"
        "• 左鍵（代號＋股名）＝看這檔完整圖\n"
        "• 右 <b>➕</b>＝加入觀察\n"
        "• 股名右「開 LINE・傳這檔」＝只傳這一檔，開手機 LINE 選聯絡人\n"
        "• 區底「一鍵傳 LINE」＝整區開啟 LINE，再選要傳給誰（不要複製貼上）\n"
        "靠近 20 日收盤高會標「少追」，不是叫立刻買。當沖／隔日沖請按主選單那兩顆。\n"
        "\n"
        "<b>三種清單不要搞混</b>\n"
        "• <b>觀察</b>＝自選，還沒買\n"
        "• <b>持股</b>＝你手記的真實買入（成交／復盤在持股頁下方）\n"
        "• <b>AI倉</b>＝假錢對照組（也可打 AI模擬倉）；50 萬切 3 等份，平常最多 1 份，超跌才第 2 份，第 3 份留現金；頁上 <b>AI操盤</b> 立刻跑一輪，<b>進化</b>只調倍數、不改黃金買點\n"
        "打「持倉」會開 <b>持股</b>（手記）。「持倉報告／模擬持倉」才是 AI倉。\n"
        "\n"
        "<b>每日時間（台灣）</b>\n"
        "06:30 早上海選（對美股）\n"
        "12:45 尾盤可切（現價旁寫今早名單價與漲跌差；這則不轉 LINE）\n"
        "16:30 官方收盤寫庫（齊了發一則，不是海選；興櫃日均價寫獨立表，不混上市櫃）\n"
        "20:00 晚間海選＋AI 模擬買（不推播）\n"
        "台股休市當日（國定假或北市全日／上午停班）不寄 06:30 海選與 12:45 尾盤。\n"
        "盤中查股用證交所即時價（不寫庫）。13:30～16:30 融合前若即時價空白，會用奇摩參考價；16:30 後以庫內官方收盤為準。\n"
        "\n"
        "<b>資料正確性</b>\n"
        "庫內日 K 只寫官方融合後的收盤；盤中即時價與奇摩僅供查股顯示，不寫進資料庫。\n"
        "你挑股認黃金買點欄：若名單上的檔，打開決策卡獲利格不是剛離零，請按回報或貼給偉權。\n"
        "\n"
        "<b>兩人各自看</b>\n"
        "已經是偉權與哥哥兩個帳號，不必再分享邀請。持股／觀察／AI倉各看各的。不要拉進同一個群組。\n"
        "06:30 早報各寄一份。https://t.me/WC_ai_trade_bot\n"
        "\n"
        "<b>完全新手小詞典</b>\n"
        "• <b>張</b>：台股一張＝1000 股。記買入打「1 68.5」＝買 1 張、每股 68.5 元\n"
        "• <b>觀察</b>：自選清單，還沒真的買\n"
        "• <b>持股</b>：你有手記買入的才會出現\n"
        "• <b>刷新</b>：第一排右二，刷新上一檔決策卡；也可打「決策卡」或「刷新上一檔」\n"
        "• <b>決策卡</b>：一張圖看這檔近期高低點與量，不是叫你立刻買\n"
        "• <b>海選</b>：電腦掃全市場的候選名單；低買高賣、按表操課\n"
        "• <b>黃金買點</b>：獲利格剛離開 0，或還在 0.x% 綠底（以前叫起漲）\n"
        "• <b>重點觀察</b>：還壓在近 60 個日曆天收盤低。注意觀察，不是立刻買\n"
        "• <b>AI倉</b>：假錢照紀律買的對照組，不是你口袋裡的股票；平常最多 1 檔，不買滿\n"
        "• <b>回報</b>：畫面怪或按鈕有問題，打字或傳截圖給偉權\n"
        "\n"
        "<b>按錯了怎麼辦</b>\n"
        "亂按沒關係。下面幾條最常見；更完整請點下方「按錯」。\n"
        "• 一打開先按了「刷新」：還沒查過就直接打代號。打「決策卡」也是同一顆。\n"
        "• 「當沖」沒名單：週末／收盤後本來就空；改看「海選」或「隔日沖」。平日 09:00–13:30 才有當沖。\n"
        "• 「海選」等很久：那是掃全市場，不是查某一檔；不要連按。\n"
        "• 「觀察」跟「持股」搞混：觀察＝還沒買；持股＝按過記買入才會在。\n"
        "• 「持股」跟「AI倉」搞混：持股＝你手記的；AI倉＝假錢對照組。\n"
        "• 找不到「產業」：在圖下面那一排，不在右側 ⌨️。\n"
        "• 連買選到一半按錯：改按別顆就取消；再按「連買區」重來。\n"
        "• 「回報」按下去又反悔：改按其他按鈕即可，不會送出。\n"
        "• 找不到股票：打股名即可，撞名或國字打不準會列出請你點；再打一次代號最準（ETF 含 0050、00631L、00981A）。\n"
        "• 主選單不見：點輸入列旁邊四格鍵盤圖示 ⌨️，或打 /menu。\n"
        "• 畫面怪、數字怪：按第一排最右「回報」，打字或傳截圖。不用給程式密鑰、不用給機器人密碼。\n"
        "\n"
        "<b>提醒</b>\n"
        "這是輔助看盤工具，不是下單系統；名單是候選，不保證獲利。有問題找偉權。"
    ),
    "row1": (
        "<b>第一排按鈕（左→右）</b>\n"
        "\n"
        "<b>① 說明</b>\n"
        "• 是什麼：本說明頁。點訊息下方分類鈕看總覽／查股／圖文／第一排／第二排／連買／記買入／按錯。\n"
        "• 怎麼用：按主選單「說明」，或打 /help。按 <b>✕</b> 收合。\n"
        "• 亂了：先看「按錯」；還是怪就按最右「回報」。\n"
        "\n"
        "<b>② 海選</b>\n"
        "• 是什麼：依最近一次官方收盤掃全市場的佈局名單（黃金買點、重點觀察、優先看、周帶量等）。\n"
        "• 怎麼用：按一次等 2～5 分鐘，完成後分類推送；勿連按以免排隊。\n"
        "• 自動版：平日 06:30 寄黃金買點／重點觀察（沒檔也寫今日沒有）、優先看／周帶量（有名單才寄）；12:45 有尾盤可切版。\n"
        "• 注意：不是盤中即時掃描；當沖／隔日沖要另按主選單按鈕。興櫃請按說明頁或海選底下「興櫃」（也可打「興櫃海選」／「興櫃名單」；獨立名單，不混進上市櫃海選）。\n"
        "\n"
        "<b>③ 持股</b>\n"
        "• 是什麼：你自己手記的真實買入，不是觀察、也不是 AI 模擬倉。打「持倉」也來這裡。\n"
        "• 怎麼用：按進去看清單；每檔可「賣出」、點股名看圖。\n"
        "• 成交／復盤：持股頁下方。成交＝手記買賣紀錄，復盤＝對照昨收怎麼走。\n"
        "• 記買入：查股後按「記買入」，再打 <code>張數 價格</code>，例 <code>1 68.5</code>。\n"
        "• AI倉：模擬帳戶在第二排右二，不要跟手記持股搞混。平常最多 1 份，超跌才第 2 份，第 3 份留現金。\n"
        "\n"
        "<b>④ 觀察</b>\n"
        "• 是什麼：自選清單，還沒買也可以先放。\n"
        "• 怎麼加：海選或查股旁的 <b>➕</b>，或打股名查詢後按「觀察」。\n"
        "• 頁上按鈕：上排看這檔／籌碼；下排買入／刪（移出觀察）。\n"
        "• 藍字股名：連到奇摩走勢（開網頁，不帶大圖預覽）。\n"
        "\n"
        "<b>⑤ 刷新</b>\n"
        "• 是什麼：盤中刷新「上一檔」的高低決策卡，不用重打代號。也可打「決策卡」或「刷新上一檔」。\n"
        "• 怎麼用：先打一次股名或代號看圖，之後盤中常按這顆刷新即時現價、量排名。\n"
        "• 沒反應：還沒查過任何股，會請你先打代號或從觀察清單點一檔。\n"
        "• 注意：這是單檔快捷鍵，不是海選黃金買點名單。\n"
        "\n"
        "<b>⑥ 回報</b>\n"
        "• 是什麼：把畫面怪、按鈕錯、數字不對告訴偉權（文字或截圖）。\n"
        "• 怎麼用：按下去，接著打字或傳手機截圖。記下來後會轉給偉權。\n"
        "• 不用給：不用程式密鑰、不用機器人密碼、也不用另外傳話筒編號。\n"
        "• 要取消：改按其他按鈕即可，不會送出。"
    ),
    "row2": (
        "<b>第二排按鈕（左→右）</b>\n"
        "\n"
        "<b>① 大盤</b>\n"
        "• 是什麼：加權指數、漲跌家數、三大法人、台指期日盤／夜盤、美股上一收盤與盤後期貨，並附橫式日K。美股休市會寫日期與原因（例如勞動節），並附上一收盤日數字。台股國定假看證交所年曆；颱風看人事行政總處：北市全日或上午停班才休市。前一晚 19:00–22:00 公告、23:00 前播出；沒公告則當日 04:30 前補發。\n"
        "• 怎麼用：隨時按；只讀庫內資料，不會觸發匯入或改寫行情。庫沒夜盤時會讀期交所盤後（只顯示）。\n"
        "• 跟海選：早報／海選第一則就是白話大盤總覽；這頁給你看數字與圖。\n"
        "\n"
        "<b>② 資金</b>\n"
        "• 是什麼：盤後「產業輪動」＋三大法人買賣超張數。\n"
        "• 怎麼用：看哪幾族法人加碼、族內代表股；當佈局參考，不是下單訊號。\n"
        "• 不是什麼：不含你的持股／觀察；也不是分點、也不是論壇消息。\n"
        "\n"
        "<b>③ 當沖</b>\n"
        "• 是什麼：盤中即時複核的當沖候選（漲幅約 2%～8.5%）。\n"
        "• 怎麼用：平日 <b>09:00–13:30</b> 按；列出保險進場、停利、停損參考價。\n"
        "• 收盤後／週末：按了不會出名單。改看「海選」或「隔日沖」，不要連按當沖。\n"
        "• 會是空的：美股隔夜大跌、恐慌指數高時故意不列，避免硬沖。\n"
        "\n"
        "<b>④ 隔日沖</b>\n"
        "• 是什麼：尾盤佈局、隔日沖候選名單。\n"
        "• 怎麼用：平日 <b>09:00–13:30</b> 按，看保險買進價與明早目標價。\n"
        "• 收盤後按：只顯示強勢收盤候選，供明天開盤參考，不是叫你收盤再買。\n"
        "\n"
        "<b>⑤ AI倉</b>\n"
        "• 是什麼：長期照紀律買的對照組（假錢 50 萬切 3 等份：平常最多 1 份，超跌才第 2 份抄低，第 3 份留現金），用來對照你手記持股，不是真下單。\n"
        "• 怎麼用：按進去看現金／持倉／停損停利；點股名看這檔介紹圖與決策卡。\n"
        "• AI操盤：在 AI倉 頁訊息下方，立刻依海選跑一輪模擬買賣（不推播）。\n"
        "• 跟持股：持股＝你手記的真實買入；AI倉＝假錢對照組，不會傳到偉權改碼對話。「持倉報告／模擬持倉」才開這裡。\n"
        "\n"
        "<b>⑥ 連買區</b>\n"
        "• 是什麼：官方法人連續買超名單（不是下單訊號）。\n"
        "• 怎麼用：先選<b>上市櫃</b>或<b>興櫃</b>（選了另一個就不會同時出現）。上市櫃再選外資／投信／外資+投信，再點天數。\n"
        "• 興櫃沒有官方法人表，不算連買天。按鈕只在訊息下面，輸入列維持兩排主選單，不要找第二套相同按鈕。\n"
        "• 名單：代號、股名、N 日連買張數與佔成交％；點股名看出完整圖，按籌碼核對。\n"
        "• 鍵盤被收掉時打 /menu 可重新釘住兩排。畫面怪按第一排最右「回報」。\n"
        "圖文在說明頁下方分類鈕。"
    ),
    "market": (
        "<b>大盤按鈕</b>\n"
        "第二排最左。這頁沒有再往下點的子按鈕，看完數字與橫式日K即可。\n"
        "\n"
        "顯示加權現價／收盤與漲跌點、開高低／振幅、量增減、漲跌家數、三大法人、距月線／年高，台指期日盤／夜盤，以及美股上一收盤／盤後期貨／恐慌指數／台積美股，並附橫式日K圖（對齊個股導航圖）。\n"
        "美股若當日沒開（NYSE 年曆，例如感恩節、勞動節），會寫日期與原因，並附上一收盤日數字；不是沒資料就空白，也不會假裝還在交易。\n"
        "台股國定假／補假看證交所開休市表。颱風休市以人事行政總處為準：只有台北市宣布全日或上午停班，集中市場才休市；僅下午停班仍開市。前一晚 19:00–22:00 公告（23:00 前播出），沒公告則當天 04:30 前補發（05:00 前播出）；機器人 22:15（週日也抓）、05:10 與 06:30 各讀一次該頁。\n"
        "\n"
        "若庫內沒有台指期夜盤，會讀期交所最新盤後（只顯示、不寫資料庫）。\n"
        "<b>只讀</b>：不把盤中即時價寫進資料庫、不影響 16:30 自動融合或 06:30 早報。"
    ),
    "ai": (
        "<b>AI 模擬倉與自動買進</b>\n"
        "\n"
        "<b>在哪裡？</b>\n"
        "主選單第二排右二 <b>AI倉</b>（也可打 AI倉／AI模擬倉）。「持倉報告／模擬持倉」也來這裡。\n"
        "\n"
        "<b>這頁按鈕</b>\n"
        "• 持倉股名＝查這檔介紹圖／決策卡（圖下可再要導航圖）\n"
        "• <b>AI操盤</b>：立刻依海選跑一輪模擬買賣（不推播）\n"
        "• <b>進化</b>：看目前編碼與近況日誌（倉位倍數、哪類少買）\n"
        "• <b>AI倉</b> 本身：只看模擬帳戶現況（不買賣）\n"
        "\n"
        "<b>自動買進</b>\n"
        "• 平日 <b>20:00</b> 雲端會：① 寫晚間海選快照 ② 讓你的 AI 依海選紀律模擬買進／賣出\n"
        "• 不會推播到 Telegram，所以你不會收到通知——這是正常的。\n"
        "• 隔天自己按主選單 AI倉 看有沒有成交、持了哪些檔。\n"
        "• 16:30 盤後融合成功時，伺服器也會順便為每位使用者各跑一輪（同樣不推播）。\n"
        "\n"
        "<b>模擬規則（簡要）</b>\n"
        "• 每人本金 50 萬虛擬，切 3 等份。平常最多用 1 份；大盤超跌才動第 2 份抄低。第 3 份永遠留現金\n"
        "• 優先黃金買點；第二份只買重點觀察／黃金買點。當沖不隔夜；靠近20日高、美股逆風不買；停損約 -7%、停利約 +8%\n"
        "• 這是對照組，不會動你的真實持股，也不會真的下單，也不會自動改程式。\n"
        "• 這不是證券 App 裡的量化積木，也不能把這支程式塞進手機下單軟體。\n"
        "\n"
        "<b>進化怎麼做（對未來量化積木）</b>\n"
        "• 表面：AI倉仍只顯示模擬買進／賣出與持倉。\n"
        "• 背後：每一輪把勝率寫進庫，只調單筆倍數與哪類海選少買；週五收盤後寄一則進化回報。\n"
        "• 進場規則鎖死高低卡黃金買點，進化不會改這條，也不會自己重寫程式。\n"
        "• 將來接到富邦＝你用手把回報裡的條件打進積木。WayneBot 不會幫你下單。\n"
        "\n"
        "<b>跟真實持股的差別</b>\n"
        "• <b>持股</b>＝你手動記的買入\n"
        "• <b>AI模擬倉</b>＝假錢對照組（每人一套，家人也各看各的）"
    ),
    "decision": (
        "<b>刷新</b>\n"
        "第一排右二。盤中刷新「上一檔」的高低決策卡與即時價量。打「決策卡」或「刷新上一檔」也行。\n"
        "\n"
        "• 還沒查過任何股：會請你先打代號，或從觀察清單點一檔。\n"
        "• 已查過：盤中重複按這顆即可更新，不必重打代號。\n"
        "• 跟海選不同：海選是全市場昨收掃描；這顆是單檔盤中工具。\n"
        "• 第一次用請直接打代號，例如 "
        + LOOKUP_CODE_EXAMPLES_HTML
        + "，不要先按這顆。"
    ),
    "menu": (
        "<b>主選單在哪？</b>\n"
        "不在訊息最下面，在輸入列旁邊<b>四格鍵盤圖示 ⌨️</b>展開的兩排按鈕。\n"
        "\n"
        "<b>第一次用</b>：先叫出兩排 → 直接打代號看圖（股票或 ETF）→ 圖下方看籌碼／營收／產業。\n"
        "\n"
        "<b>第一排</b>：說明／海選／持股／觀察／刷新／<b>回報</b>\n"
        "<b>第二排</b>：大盤／資金／當沖／隔日沖／AI倉／<b>連買區</b>\n"
        "打「精簡選單」只留第一週常用六顆；「完整選單」恢復十二顆。\n"
        "\n"
        "手機打完字若只看到英文鍵盤：點輸入列旁邊<b>四格 ⌨️</b> 叫回兩排；或打 /menu 強制更新。\n"
        "訊息上的「➕」「說明」仍附在最後一則（Telegram 規定）；換頁主功能請用右側 ⌨️ 兩排。\n"
        "完整分類說明請按主選單「說明」，或看本頁導覽下方各分類鈕。"
    ),
    "screen": (
        "<b>海選怎麼用</b>\n"
        "週一～五台灣 06:30 用昨收＋美股收盤／盤後寄出；12:45 再寄尾盤可切（對照今早名單，現價旁寫今早價與漲跌差；這則不轉 LINE）。\n"
        "台股休市當日（國定假或北市全日／上午停班），不寄今早海選、也不寄尾盤可切。\n"
        "晚間 20:00 只記台股收盤名單、不寄。【雙時段】＝晚間＋今早都在。\n"
        "06:30 早報第一則是大盤狀況（美股＋台指期夜盤＋白話連動），接著寄黃金買點／重點觀察（沒檔也寫今日沒有）／優先看／周帶量（優先看沒名單就跳過）；半年高／站上季線／止跌請按主選單「海選」看完整。\n"
        "海選＝依最近一次官方收盤掃的<b>佈局</b>名單，不是盤中即時掃描。\n"
        "\n"
        "<b>這頁按鈕</b>\n"
        "• 左鍵（代號＋股名）＝看這檔完整圖\n"
        "• 右 <b>➕</b>＝加入觀察\n"
        "• 藍字股名＝奇摩走勢\n"
        "\n"
        "<b>轉 LINE 都是開手機 LINE 選聯絡人</b>\n"
        "• 股名右「開 LINE・傳這檔」＝只傳這一檔\n"
        "• 區底「一鍵傳 LINE」＝整區一次開 LINE，再選要傳給誰\n"
        "不要複製文字再貼。當沖／隔日沖的「傳 LINE」同一套。\n"
        "（主選單「刷新」＝單檔盤中刷新，不是整區黃金買點名單。打「決策卡」也是這顆。）\n"
        "\n"
        "<b>當沖／隔日沖不在晨間海選推播</b>，請按主選單「當沖」「隔日沖」。\n"
        "靠近 20 日收盤高會標<b>少追</b>。低買高賣：黃金買點／重點觀察只認決策卡表，不認圖上紅箭頭。\n"
        "興櫃不混進這份名單。說明頁或海選底下按「興櫃」（也可打「興櫃」）。\n"
        "其餘檔同樣是一檔一塊完整卡片。不是立即下單清單。\n"
        "美股看現金收盤；收盤後再看盤後。大跌會在 06:30 先單獨通知一則。\n"
        "隔日會用庫內收盤對昨天名單復盤；弱的類別只讓 AI 模擬倉少買。"
    ),
    "daytrade": (
        "<b>當沖怎麼用</b>\n"
        "保險進場＝不要追過當日收盤；第一停利＝+3% 先出一部分；衝頂＝+6%；保險停損＝當日均價跌破先走。\n"
        "只在平日 <b>09:00–13:30 盤中</b> 按才有意義（即時複核漲幅 2%～8.5%）；收盤後、週末、台股休市按不會出名單。\n"
        "沒名單時改看「隔日沖」（尾盤佈局明早）或「海選」（長線佈局），不要連按當沖。\n"
        "隔夜美股逆風（收盤或盤後大跌、恐慌指數高）時這頁會空，避免開盤缺口硬沖。\n"
        "\n"
        "<b>這頁按鈕</b>\n"
        "• 左鍵（代號＋股名）＝現價＋圖\n"
        "• 右 <b>➕</b>＝加入觀察\n"
        "• 藍字股名＝奇摩。不是保證獲利。"
    ),
    "overnight": (
        "<b>隔日沖怎麼用</b>\n"
        "保險買進＝尾盤昨收附近、不要摸高；明早開高目標 +3.5%～+4.8%；衝頂 +7%；保險防守＝開盤與均價較低者，跌破先走。\n"
        "進場參考時段＝平日 <b>09:00–13:30</b>（尾盤前）；收盤後按只顯示強勢收盤候選，供明早開盤參考，不是叫你再買。\n"
        "週末、還沒開盤或台股休市想看名單，按這顆比按「當沖」有用。\n"
        "\n"
        "<b>這頁按鈕</b>\n"
        "• 左鍵（代號＋股名）＝現價＋圖\n"
        "• 右 <b>➕</b>＝加入觀察\n"
        "• 藍字股名＝奇摩。"
    ),
    "portfolio": (
        "<b>持股怎麼用</b>\n"
        "這裡只顯示你手記的真實買入，不是觀察、也不是 AI 模擬倉。記買入：選股→記買入→打 <code>張數 價格</code>。\n"
        "\n"
        "<b>這頁按鈕（由上到下對應該檔）</b>\n"
        "• 左＝股名，看這檔介紹圖／決策卡（圖下可再要導航圖）\n"
        "• <b>賣出</b>＝記賣出張數與價格\n"
        "• <b>成交</b>＝你手記的買賣紀錄\n"
        "• <b>復盤</b>＝對照昨收怎麼走\n"
        "• <b>AI倉</b>＝假錢對照組現況（不買賣）；主選單第二排右二也有。50 萬切 3 等份，不買滿\n"
        "\n"
        "<b>自動買進</b>：盤後融合成功與每晚 20:00 雲端會自動模擬買，但<b>不推播</b>；請按主選單 <b>AI倉</b> 查看。AI 規則寫在「第一排」那頁。"
    ),
    "watch": (
        "<b>觀察怎麼用</b>\n"
        "自選清單，還沒買也可以加。空的很正常。\n"
        "加入：打股名或海選／當沖旁的 <b>➕</b>。\n"
        "\n"
        "<b>這頁按鈕（每檔兩排，避免手機擠成一排四顆）</b>\n"
        "• 上排：左＝股名看這檔　右＝<b>籌碼</b>\n"
        "• 下排：<b>買入</b>＝記真實持股　<b>刪</b>＝移出觀察\n"
        "藍字股名＝奇摩走勢（只開網頁，不帶預覽大圖）。"
    ),
    "stock": (
        "<b>查股頁（圖下方按鈕）</b>\n"
        "打股名或按看這檔：一次出介紹圖、決策卡（相簿）。介紹圖下半已有 180 日高低導航；要完整橫式再按圖下「導航圖」。\n"
        "籌碼／營收／產業／K線／導航圖按<b>圖下方</b>按鈕，不是右側 ⌨️ 主選單。\n"
        "\n"
        "<b>圖下方這一排</b>\n"
        "• <b>導航圖</b>：再要一次完整 180 日高低導航（不同顏色箭頭）\n"
        "• <b>籌碼</b>：三大法人買賣超圖\n"
        "• <b>營收</b>：月營收、季報毛利\n"
        "• <b>產業</b>：一張圖卡（同業中位＋本產業法人）；股名旁有公開細項小框，沒抓到不畫\n"
        "• <b>K線</b>：開這一檔圖，先進日K＋成交量，可改 15 分／60 分／五日／十日／月線／季線。高低卡不會帶過去\n"
        "• <b>觀察</b>：加入自選（還沒買）\n"
        "• <b>記買入</b>：記真實持股，接著打 <code>張數 價格</code>\n"
        "\n"
        "<b>介紹圖粉紅「紀律」（先別追／先出一點）</b>\n"
        "先講現在怎樣，再講怎麼做。不是買訊。\n"
        "\n"
        "• 現在高點跟熱度都退了 → 先別追、也先別加碼；有持股就先出一點\n"
        "• 現在價到高了、熱度沒跟上 → 先出一點、不要追\n"
        "• 現在很熱但價沒過前高 → 先出一點、不要追高\n"
        "• 現在高點跟熱度都沒了 → 這波先當結束；有持股就先出一點\n"
        "\n"
        "已經連好幾天貼在高檔：先不要追。有持股考慮先出。剛貼到高檔：先看、先別追。\n"
        "\n"
        "<b>如何賣</b>（作者公開、不是買訊、不自動賣）\n"
        "最高價＝20日高，對最高溫。同步再脫離＝準備減碼；不同步＝直接減碼。\n"
        "只標在介紹圖／決策卡／持股／AI倉，不改海選名單。\n"
        "\n"
        "<b>介紹圖／決策卡先看這些</b>\n"
        "• 股號旁：當日 K 縮圖＋連漲／連跌＋開高低\n"
        "• 獲利＝從近60個日曆天收盤低算上來（貼20日低不歸零）；距60根低是另外一欄\n"
        "• 溫度＝20日收盤位置＋月乖離。溫度≥80 且創歷史新高要注意（少追）\n"
        "• 升降溫「最低溫＋價未新低」＝低檔背離；「降溫＋價溫背離」＝價創新高但溫度已降，少追\n"
        "• 表頭「今日態度」第二行只講這張20日表的數字和底色（先等／別追／先看表），不是下單指令\n"
        "• 月K一句掛徽章：還在往上／已走空／在整理。跟表上「月乖離」（離20日線）不是同一條尺。不是買訊，不改海選\n"
        "• 表頭量能：近480／120／60日量前10會亮短窗；介紹圖寫「60日第7 · 120日第25」。表格最右欄永遠是120日量排名\n"
        "• 預警欄：K20高＝收盤靠近20日高且偏熱；K20低＝貼近20日低或月線乖離轉負。沒訊號時仍會露出高低（20高／10低），不藏表\n"
        "• 外資／投信／自營／法人當日張數＋連買連賣；完整法人格按籌碼\n"
        "• 本益／淨值／殖利率、融資融券餘額（張與使用率）＝官方有數才上卡；沒有真分點就不會出現主力成本\n"
        "• 高低導航橫式：價格列＝20高／20高脫離／20低／20低脫離／60低；量能列才有量能異常、警告、月波動低\n"
        "• 產業說明＝一張圖卡：官方產業別＋同業月營收／毛利率中位＋本產業法人連買／連賣；股名旁公開細項小框（沒抓到不畫）；不是內幕\n"
        "• 海選靠近 20 日收盤高＝少追，排後面；高低卡才是少賠主軸\n"
        "• 隔夜美股＝現金收盤＋收盤後盤後（台積美股／那斯達克期貨續勢），盤中期貨不看；大跌 06:30 會先通知。只過濾逆風，不拿來追高"
    ),
    "chips": (
        "<b>籌碼按鈕</b>\n"
        "查完一檔後，按<b>圖下方「籌碼」</b>（不在右側 ⌨️）。\n"
        "\n"
        "三大法人買賣超（張）。紅＝買超、綠＝賣超。\n"
        "籌碼佔量＝法人合計買賣超÷當日成交量。"
    ),
    "fund": (
        "<b>營收按鈕</b>\n"
        "查完一檔後，按<b>圖下方「營收」</b>（不在右側 ⌨️）。\n"
        "\n"
        "官方月營收與季報。本益／淨值／殖利率、融資融券餘額（張、使用率）有官方數才一併顯示；沒有就不畫。\n"
        "同業對照請按旁邊的「產業」。"
    ),
    "industry": (
        "<b>產業按鈕</b>\n"
        "查完一檔後，按<b>圖下方「產業」</b>（不在右側 ⌨️）。\n"
        "也可打 /industry 代號。\n"
        "\n"
        "會先送一張圖卡：官方產業別、這檔月營收／毛利率、同業中位數、本產業法人張數。\n"
        "股名旁若有公開細項（例如代工、記憶體製造），用小框標；沒抓到就不畫，不留空白。\n"
        "圖卡出不來才改送文字。進場仍看高低卡，不要因為同業敘事追高。"
    ),
    "buy": (
        "<b>記買入</b>\n"
        "選好股票後打價格即可（預設 1 張）：<code>68.5</code>\n"
        "\n"
        "多張：<code>2 68.5</code>\n"
        "也可 <code>2330 1 500</code>（代號 張數 價格）。\n"
        "\n"
        "打完會進「持股」。要取消就改按其他按鈕。\n"
        "一張＝1000 股。零股請寫 <code>200股 631.6</code>，不要只打 2（會被當成 2 張）。\n"
        "觀察頁的「買入」跟這顆一樣。"
    ),
    "pick": (
        "<b>查某一檔</b>\n"
        "直接打股名或代號，例如 <b>南亞</b>、"
        + LOOKUP_CODE_EXAMPLES_HTML
        + "。\n"
        "股票四碼、ETF 可含 L／R／A（正2／反1／主動）。海選名單仍只有股票／KY，但查股收 ETF。\n"
        "\n"
        "不要先按「刷新」——那顆只刷新上一檔。打「決策卡」也是同一顆。\n"
        "一次出兩張圖：介紹圖（上半資訊、下半180日高低導航）→ 決策卡。完整橫式導航按圖下「導航圖」。\n"
        "找不到：撞名或國字打不準會列出相近的請你點；再打代號最準。"
    ),
    "flow": (
        "<b>資金移動怎麼用</b>\n"
        "主選單第二排「資金」。這頁沒有再往下點的子按鈕，看完數字即可。\n"
        "\n"
        "盤後資金輪動：同一交易日依產業把三大法人張數加總，對照前一日。熱 3 族＋族內代表股當佈局參考。\n"
        "個股區塊是外資／投信買賣超與短線熱股，不含你的持股或觀察（各走自己的選單）。\n"
        "只看官方法人＋價量，不抓分點、不抓論壇。法人也會幌，輪動不單獨當訊號。"
    ),
    "streak": (
        "<b>連買區怎麼用</b>\n"
        "主選單第二排「連買區」。\n"
        "\n"
        "<b>第一步</b>：先選並點<b>上市櫃</b>或<b>興櫃</b>（選了另一個就消失，不會兩顆一直留著）。\n"
        "興櫃沒有官方法人買賣超表，不能算連買天。\n"
        "\n"
        "<b>第二步（上市櫃）</b>：點訊息下方三顆\n"
        "• <b>外資</b>＝外資連續買超\n"
        "• <b>投信</b>＝投信連續買超\n"
        "• <b>外資+投信</b>＝同一天兩家都買超才算一天\n"
        "\n"
        "<b>第三步</b>：點連買天數（只列出剛好有股票的天數）。\n"
        "不要找「上市／上櫃」分開的按鈕。點 6 就只看剛好連買 6 天的股票。\n"
        "按鈕只在這則訊息下面；輸入列維持兩排主選單，不再複製同一排。\n"
        "\n"
        "<b>選到一半按錯了</b>\n"
        "改按主選單其他按鈕就取消；要重來再按「連買區」。也可打 /menu。\n"
        "\n"
        "<b>名單按鈕</b>\n"
        "• 股名＝一般查股（介紹圖／決策卡；圖下可再要導航圖）\n"
        "• <b>籌碼</b>＝核對官方法人表\n"
        "每檔顯示代號、股名、N 日連買幾張、佔 N 日總成交％。"
    ),
    "oops": (
        "<b>按錯了怎麼辦</b>\n"
        "亂按沒關係。下面每一條都能把你導回來。\n"
        "\n"
        "<b>一打開先按了「刷新」</b>\n"
        "還沒查過就<b>直接打代號</b>，例如 "
        + LOOKUP_CODE_EXAMPLES_HTML
        + "。\n"
        "\n"
        "<b>「當沖」沒名單</b>\n"
        "週末／收盤後本來就空。改看「海選」或「隔日沖」，不要連按當沖。\n"
        "平日 09:00–13:30 才有當沖名單。\n"
        "\n"
        "<b>「海選」等很久</b>\n"
        "那是掃全市場，要 2～5 分鐘，不是查某一檔。不要連按。查某一檔請打代號。\n"
        "\n"
        "<b>三種清單搞混</b>\n"
        "• 觀察＝自選，還沒買\n"
        "• 持股＝你按過記買入的才會在\n"
        "• AI倉＝假錢對照組，不是你口袋裡的股票；平常最多 1 檔，不買滿\n"
        "\n"
        "<b>找不到「產業／籌碼／營收」</b>\n"
        "查完一檔，按鈕在<b>圖下面那一排</b>，不在右側 ⌨️ 主選單。\n"
        "\n"
        "<b>連買選到一半按錯</b>\n"
        "先選上市櫃或興櫃，上市櫃再選外資／投信／外資+投信，再點天數。中途改按別顆就取消；再按「連買區」重來。\n"
        "興櫃沒有官方法人表，不算連買天。按鈕只在訊息下面。\n"
        "\n"
        "<b>「回報」按下去又反悔</b>\n"
        "改按其他按鈕即可，不會送出。不用給程式密鑰、不用給機器人密碼。\n"
        "\n"
        "<b>想問怎麼賣</b>\n"
        "直接打代號看出完整圖。圖底下會寫如何賣（最高價＝20日高對最高溫）。也可以打「2330怎麼賣」。沒有官方新聞跌因欄，不編故事。\n"
        "\n"
        "<b>找不到股票</b>\n"
        "打股名即可（南亞會列出南亞／南亞科）。國字打錯、同音、KY 沒打對，也會猜相近的請你點，不會直接出圖。再打代號最準（ETF 含 0050、00631L、00981A）。\n"
        "\n"
        "<b>主選單不見</b>\n"
        "點輸入列旁邊四格鍵盤圖示 ⌨️，或打 /menu。\n"
        "\n"
        "<b>畫面怪、數字怪、按鈕錯了</b>\n"
        "按第一排最右「回報」，打字或傳截圖給偉權。"
    ),
}

# 主選單十二顆：第一週常用在第一排；當沖／隔日沖／AI倉／連買區在第二排後面。
MENU_BTN_MARKET = "大盤"
MENU_BTN_STREAK = "連買區"
MENU_BTN_AI = "AI倉"
MENU_BTN_REPORT = "回報"
MENU_BTN_CARD = "刷新"
MENU_BTN_CARD_ALIASES = (MENU_BTN_CARD, "刷新上一檔", "決策卡")
MENU_BTN_BACK_MAIN = "回主選單"
MENU_BTN_BACK_STEP = "上一步"
MENU_BTN_NEXT_PAGE = "下一批"
MENU_BTN_PREV_PAGE = "上一批"
MENU_ROW1 = (
    "說明",
    "海選",
    "持股",
    "觀察",
    MENU_BTN_CARD,
    MENU_BTN_REPORT,
)
MENU_ROW2 = (
    MENU_BTN_MARKET,
    "資金",
    "當沖",
    "隔日沖",
    MENU_BTN_AI,
    MENU_BTN_STREAK,
)
MENU_COMPACT_ROWS = (
    ("說明", "海選", "持股"),
    ("觀察", MENU_BTN_CARD, MENU_BTN_REPORT),
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
MENU_LAYOUT_VERSION = "14"
MAX_PICK_INLINE_ROWS = 8

# 輸入列左邊三條槓（Telegram BotCommand）。查股請直接打代號，不必先點選單。
TELEGRAM_BOT_COMMANDS = (
    ("menu", "回到主選單（下方兩排）"),
    ("market", "大盤指數與風險"),
    ("help", "使用說明"),
    ("screen", "海選"),
    ("portfolio", "持股"),
    ("watch", "觀察"),
    ("flow", "資金移動"),
    ("industry", "產業說明"),
    ("start", "開始"),
)


from tg_layout import chunk_telegram_html, chunk_telegram_text


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
        self._last_card: Dict[str, str] = {}
        self._lookup_ctx: Dict[str, dict] = {}
        # actor_key（chat_id:uid）隔離，避免同機多用戶互相刪訊息／搶快取
        self._menu_fade_msgs: Dict[str, list] = {}
        self._lookup_fade_msgs: Dict[str, list] = {}
        # actor_key → pack_id → 海選分類訊息（一鍵傳 LINE 後整段收起）
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
            uid = uid or WayneTelegramBot._uid_from_message(message)
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
        """一鍵傳 LINE 的「生成中」進度；完成後刪除，不動含 LINE 鈕的完成訊息。"""
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
        """海選該分類的貼紙＋文字塊：傳 LINE 備好後整段消失。"""
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

    def _touch_user(self, uid: str, display_name: str = "") -> None:
        if not telegram_uid_allowed(uid):
            return
        try:
            touch_tg_user(self.db_path, uid, display_name)
        except Exception:
            logger.debug("touch_tg_user failed uid=%s", uid, exc_info=True)

    def _touch_from_update(self, update: Update) -> str:
        user = update.effective_user
        uid = str(getattr(user, "id", "") or "")
        if uid:
            self._touch_user(uid, getattr(user, "first_name", "") or "")
        return uid

    async def _reject_stranger(self, update: Update) -> bool:
        """陌生人按開始只回「這是私人 Bot」，不進 tg_users、不做事。"""
        user = getattr(update, "effective_user", None)
        uid = str(getattr(user, "id", "") or "")
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
            self._touch_from_update(update)
            return await handler(update, context)

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
            "三大法人表興櫃沒有就不顯示。有日均價序列就出介紹圖／高低卡（圖下可再要導航圖）。"
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
        kb.append([self._q("stock")])
        self._pending[self._pending_actor(message, uid=uid)] = "dcard"
        await message.reply_html(
            "這顆會刷新<b>上一檔</b>。你這邊還沒查過股票，所以沒有上一檔。\n"
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
        uid = str(uid or "")
        if not uid:
            return False
        db = getattr(self, "db_path", None) or ""
        if not db:
            return False
        try:
            from wayne_db import get_cached_data

            row = get_cached_data(f"tg_menu_compact:{uid}", db)
            return str((row or {}).get("content") or "") == "1"
        except Exception:
            return False

    def _set_menu_compact(self, uid: str, on: bool) -> None:
        uid = str(uid or "")
        db = getattr(self, "db_path", None) or ""
        if not uid or not db:
            return
        from wayne_db import set_cached_data

        set_cached_data(
            f"tg_menu_compact:{uid}",
            "menu",
            "1" if on else "0",
            db_path=db,
        )
        self._invalidate_menu_layout(uid)

    def _reply_menu(self, uid: str = ""):
        """預設十二顆兩排；精簡模式每人六顆（第一週常用）。"""
        if self._menu_compact_on(uid):
            rows = [[KeyboardButton(t) for t in row] for row in MENU_COMPACT_ROWS]
            placeholder = "打股名／代號；「完整選單」恢復十二顆"
        else:
            rows = [
                [KeyboardButton(t) for t in MENU_ROW1],
                [KeyboardButton(t) for t in MENU_ROW2],
            ]
            placeholder = "打股名／代號，或按「刷新」"
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
        safe = str(code or "").strip()[:6] or "x"
        who = str(uid or "0").strip()[:16]
        tag = f"{who}_{int(time.time() * 1000)}"
        return os.path.join(charts_dir, f"{safe}_{kind}_{tag}.png")

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
        compact = self._menu_compact_on(uid)
        if compact:
            text = (
                "精簡六顆已掛上。打「完整選單」恢復十二顆。點輸入列旁邊四格 ⌨️。"
                if silent
                else "精簡六顆：說明／海選／持股／觀察／刷新／回報。打「完整選單」恢復十二顆。"
            )
        else:
            text = (
                "兩排已更新：第一排說明…回報，第二排大盤…連買區。點輸入列旁邊四格 ⌨️。"
                if silent
                else "主選單已掛上（輸入列旁邊四格鍵盤圖示展開兩排；第一排最右回報）。打「精簡選單」可收成六顆。"
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

    def _streak_uni_inline(self):
        from buy_streak import MARKET_ALL, MARKET_EM, UNI_BTN

        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(UNI_BTN[MARKET_ALL], callback_data="fb:uni:ALL"),
                    InlineKeyboardButton(UNI_BTN[MARKET_EM], callback_data="fb:uni:EM"),
                ],
                [InlineKeyboardButton("回主選單", callback_data="fb:home")],
            ]
        )

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
                [
                    InlineKeyboardButton("上一步", callback_data="fb:back:uni"),
                    InlineKeyboardButton("回主選單", callback_data="fb:home"),
                ],
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
                [
                    InlineKeyboardButton("上一步", callback_data="fb:back:uni"),
                    InlineKeyboardButton("回主選單", callback_data="fb:home"),
                ],
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
        self._pending[actor] = "fbuy:uni"
        await self._streak_send_step(
            message,
            "<b>連買區域</b>\n"
            "先選<b>上市櫃</b>或<b>興櫃</b>（點訊息下方按鈕；選了另一個就不會同時出現）。\n"
            "• <b>上市櫃</b>＝上市＋上櫃，官方法人買賣超可算連買天\n"
            "• <b>興櫃</b>＝沒有官方法人表，不能算外資／投信連買",
            inline=self._streak_uni_inline(),
        )

    async def _streak_show_kind(self, message, uid: str, actor: str, market: str = "ALL") -> None:
        from buy_streak import MARKET_ALL, MARKET_EM

        market = str(market or MARKET_ALL).strip().upper() or MARKET_ALL
        if market == MARKET_EM:
            await self._streak_show_emerging(message, uid, actor)
            return
        self._pending[actor] = f"fbuy:kind:{MARKET_ALL}"
        await self._streak_send_step(
            message,
            "<b>連買區域 · 上市櫃</b>\n"
            "已選上市櫃。再選哪一種連買（點訊息下方按鈕）。\n"
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
        await message.reply_html("已回到兩排主選單。", reply_markup=self._reply_menu(uid))

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
        except Exception as e:
            logger.exception("連買名單失敗 kind=%s market=%s", kind, market)
            await self._delete_message(status)
            await self._streak_send_step(
                message,
                f"連買名單讀取失敗：{html_escape(e)}",
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
        except Exception as e:
            logger.exception("連買清單失敗")
            await self._delete_message(status)
            await message.reply_html(f"連買清單失敗：{html_escape(e)}")
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
        """網頁版把 ❓ 畫成紅圈問號，看起來像壞掉；改用「說明」二字。"""
        return InlineKeyboardButton("說明", callback_data=f"?:{topic}")

    def _help_nav_keyboard(self, active: str = "guide"):
        """說明頁分類導覽；active 僅供日後標示，目前各鈕皆可點。"""
        _ = active
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("總覽", callback_data="?:guide"),
                    InlineKeyboardButton("查股", callback_data="?:stock"),
                    InlineKeyboardButton("圖文", callback_data="?:pics"),
                ],
                [
                    InlineKeyboardButton("第一排", callback_data="?:row1"),
                    InlineKeyboardButton("第二排", callback_data="?:row2"),
                    InlineKeyboardButton("連買", callback_data="?:streak"),
                ],
                [
                    InlineKeyboardButton("記買入", callback_data="?:buy"),
                    InlineKeyboardButton("興櫃", callback_data="em:go"),
                    InlineKeyboardButton("按錯", callback_data="?:oops"),
                    InlineKeyboardButton("✕", callback_data="hx"),
                ],
            ]
        )

    async def _reply_help_topic(self, message, topic: str = "guide", *, edit_target=None) -> None:
        body = HELP_TOPICS.get(topic) or HELP_TOPICS["guide"]
        kb = self._help_nav_keyboard(topic)
        chunks = chunk_telegram_html(body)
        text = chunks[0] if chunks else body
        if edit_target is not None and hasattr(edit_target, "edit_text"):
            try:
                await edit_target.edit_text(
                    text,
                    parse_mode="HTML",
                    reply_markup=kb,
                    disable_web_page_preview=True,
                )
                return
            except Exception:
                logger.debug("說明頁原地更新失敗，改發新訊息", exc_info=True)
        actor = self._actor_key(message)
        await self._dismiss_help_msgs(actor)
        sent_msgs = []
        for i, chunk in enumerate(chunks):
            msg = await message.reply_html(
                chunk,
                reply_markup=kb if i == len(chunks) - 1 else None,
                disable_web_page_preview=True,
            )
            sent_msgs.append(msg)
        if sent_msgs:
            self._help_msgs[actor] = sent_msgs

    def _keyboard(self):
        """錯誤／提示改釘回兩排主選單。直立式「說明／主選單」已廢。"""
        return self._reply_menu()

    def _hub_keyboard(
        self,
        code: str,
        topic: str = "stock",
        *,
        em: bool = False,
        news: dict | None = None,
    ):
        """興櫃四顆一排：產業／觀察／記買入／說明。上市櫃最多三顆一排；導航圖按需。"""
        c = str(code).strip()[:6]
        news = news or {}
        news_label = str(news.get("label") or "").strip()
        news_url = _http_url(news.get("url") or "")
        k_url = ""
        if not em:
            try:
                from stock_links import kline_page_url

                k_url = _http_url(kline_page_url(c, getattr(self, "db_path", None)))
            except Exception:
                k_url = ""
        nav = InlineKeyboardButton("導航圖", callback_data=f"g:{c}")
        actions = [
            InlineKeyboardButton("觀察", callback_data=f"w:{c}"),
            InlineKeyboardButton("記買入", callback_data=f"b:{c}"),
            self._q(topic),
        ]
        if em:
            return InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("產業", callback_data=f"n:{c}"),
                        InlineKeyboardButton("觀察", callback_data=f"w:{c}"),
                        InlineKeyboardButton("記買入", callback_data=f"b:{c}"),
                        self._q(topic),
                    ]
                ]
            )
        top = [InlineKeyboardButton("產業", callback_data=f"n:{c}")]
        if news_label and news_url:
            top.append(InlineKeyboardButton(news_label[:16], url=news_url))
        if k_url:
            top.append(InlineKeyboardButton("K線", url=k_url))
        listed = [
            InlineKeyboardButton("籌碼", callback_data=f"h:{c}"),
            InlineKeyboardButton("營收", callback_data=f"f:{c}"),
        ]
        if len(top) >= 3:
            listed.append(nav)
            return InlineKeyboardMarkup([top, listed, actions])
        if len(top) >= 2:
            top.append(nav)
            return InlineKeyboardMarkup([top, listed, actions])
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("籌碼", callback_data=f"h:{c}"),
                    InlineKeyboardButton("營收", callback_data=f"f:{c}"),
                    InlineKeyboardButton("產業", callback_data=f"n:{c}"),
                ],
                [nav, actions[0], actions[1]],
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

    def _screening_section_keyboard(
        self,
        line_pack_id: str = None,
        include_menu: bool = False,
        picks=None,
    ):
        """海選整區：左鍵看這檔；區底開 LINE 選聯絡人。"""
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
        if line_pack_id:
            line_url = self._line_open_url(line_pack_id)
            if line_url:
                rows.append(
                    [InlineKeyboardButton("一鍵傳 LINE", url=line_url)]
                )
        if include_menu:
            rows.append(
                [
                    self._q("screen"),
                    InlineKeyboardButton("興櫃", callback_data="em:go"),
                ]
            )
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
        if line_pack_id:
            line_url = self._line_open_url(line_pack_id)
            if line_url:
                rows.append([InlineKeyboardButton("開 LINE 選聯絡人", url=line_url)])
        tail = []
        if include_menu or rows:
            tail.append(self._q(topic))
        if tail:
            rows.append(tail)
        if not rows:
            return None
        return InlineKeyboardMarkup(rows)

    def _persist_bucket_line_pack(self, bucket_key: str, rows: list) -> None:
        if not rows:
            return
        try:
            from import_health import latest_complete_quote_date
            from screening_engine import build_line_bucket_packs, build_line_stock_bodies
            from screen_sessions import upsert_line_pack, upsert_line_stocks

            as_of = latest_complete_quote_date(self.db_path) or self.screener.get_latest_trading_date()
            packs = build_line_bucket_packs({bucket_key: rows}, as_of, self.db_path)
            if packs:
                upsert_line_pack(self.db_path, as_of, packs[0])
            bodies = build_line_stock_bodies({bucket_key: rows}, as_of, self.db_path)
            if bodies:
                upsert_line_stocks(self.db_path, as_of, bodies)
        except Exception:
            logger.exception("寫入 %s LINE 稿失敗", bucket_key)

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
                ]
            )
        rows.append([self._q("stock")])
        return InlineKeyboardMarkup(rows) if rows else None

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
                self._q("ai"),
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
        kb.append([self._q("portfolio")])
        return InlineKeyboardMarkup(kb)

    async def _send_trade_journal(self, message, uid: str, *, review: bool = False) -> None:
        fn = format_user_review_html if review else format_user_trades_html
        html = await asyncio.to_thread(fn, self.db_path, uid)
        parts = chunk_telegram_html(html)
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

    def _remember_line_share(self, result: Optional[Dict[str, Any]] = None, body: str = ""):
        """海選 LINE 稿已寫入 sqlite；不再用程序記憶體快取，避免多用戶互相覆蓋。"""
        _ = result, body

    def _load_line_share_packs(self) -> List[Dict[str, str]]:
        try:
            from screen_sessions import load_line_packs

            return load_line_packs(self.db_path) or []
        except Exception:
            return []

    async def _reply_line_share(self, message, result: Optional[Dict[str, Any]] = None):
        if result is not None:
            self._remember_line_share(result)
        packs = self._load_line_share_packs()
        if not packs:
            await message.reply_text("目前沒有可傳 LINE 的三段。請先按一次「海選」。")
            return
        await message.reply_text("每段一顆鈕。按下去會開啟手機 LINE，再選要傳給誰。")
        for p in packs:
            label = str(p.get("label") or p.get("title") or "開 LINE 選聯絡人")
            await message.reply_text(
                label,
                disable_web_page_preview=True,
                reply_markup=self._line_open_keyboard(
                    p.get("id") or "",
                    label="開 LINE 選聯絡人",
                ),
            )

    def _send_line_share(self, chat_id: str, result: Optional[Dict[str, Any]] = None):
        """保留三段整包稿（手動 fw:s）；日常海選改走每檔按鈕。"""
        if result is not None:
            self._remember_line_share(result)
        packs = self._load_line_share_packs()
        if not packs:
            return
        self._send_plain(chat_id, "每段一顆鈕。按下去會開啟手機 LINE，再選要傳給誰。")
        for p in packs:
            label = str(p.get("label") or p.get("title") or "開 LINE 選聯絡人")
            self._send_plain(
                chat_id,
                label,
                reply_markup=self._line_open_keyboard(
                    p.get("id") or "",
                    label="開 LINE 選聯絡人",
                ),
            )

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
        if result.get("line_share_packs") or result.get("line_share"):
            self._remember_line_share(result)

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
                payload["reply_markup"] = self._reply_menu().to_dict()
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

    def _line_open_url(self, pack_id: str) -> str:
        from config import get_public_base_url

        return f"{get_public_base_url()}/line/{pack_id}"

    def _line_open_rows(self):
        from line_hop import LINE_PACKS

        return [
            [InlineKeyboardButton(label, url=self._line_open_url(pid))]
            for pid, label, _title in LINE_PACKS
        ]

    def _line_open_keyboard(self, pack_id: str = "", label: str = ""):
        pid = str(pack_id or "").strip()
        if pid:
            text = str(label or "").strip() or "開 LINE 選聯絡人"
            return InlineKeyboardMarkup(
                [[InlineKeyboardButton(text, url=self._line_open_url(pid))]]
            )
        from line_hop import LINE_PACKS

        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(lab, url=self._line_open_url(xid))]
                for xid, lab, _title in LINE_PACKS
            ]
        )

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
        if result.get("line_share_packs") or result.get("line_share"):
            self._remember_line_share(result)
        return ok

    def _send_stock_card_by_code(self, chat_id: str, code: str, name: str = ""):
        if not code:
            return
        from wayne_navigator import generate_card_with_chart

        try:
            packed = generate_card_with_chart(code, self.db_path, self.charts_dir)
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
            "<b>WayneBot</b>\n"
            "主選單在輸入列旁邊<b>四格鍵盤圖示 ⌨️</b>展開的兩排（不附在訊息最下面）。\n"
            "\n"
            "<b>第一次用，先做這三步</b>\n"
            "1　點輸入列旁邊四格 ⌨️ 叫出兩排（不見就打 /menu）\n"
            "2　直接打代號看圖，例如 "
            + LOOKUP_CODE_EXAMPLES_HTML
            + "（不要先按「刷新」）\n"
            "3　籌碼／營收／產業／K線／導航圖在圖下面，不在右側四格鍵盤\n"
            "\n"
            "詳情按第一排「說明」，或打 /help。圖文在說明頁下方「圖文」。亂了按第一排最右「回報」。\n"
            "這是私人 Bot，只認指定帳號。偉權與哥哥已各用各的，持股各看各的。不必再分享邀請。\n",
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

    async def menu_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        self._touch_user(uid, getattr(update.effective_user, "first_name", "") or "")
        await self._force_reply_menu(update.message, uid)

    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        await self._enter_main_menu(update.message, uid)
        await self._reply_help_topic(update.message, "guide")

    @staticmethod
    def _message_is_photo(message) -> bool:
        """真的是圖訊息才算。MagicMock.photo 不能當真。"""
        photo = getattr(message, "photo", None)
        return isinstance(photo, (list, tuple)) and len(photo) > 0

    def _picture_guide_keyboard(self, page: int, n: int):
        page = int(page)
        n = max(1, int(n))
        nav = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    f"✦ ← 第 {page} 張",
                    callback_data=f"pg:{page}-{page - 1}",
                )
            )
        if page + 1 < n:
            nav.append(
                InlineKeyboardButton(
                    f"第 {page + 2} 張 → ✦",
                    callback_data=f"pg:{page}-{page + 1}",
                )
            )
        rows = [nav] if nav else []
        help_kb = self._help_nav_keyboard("pics")
        rows.extend(list(help_kb.inline_keyboard))
        return InlineKeyboardMarkup(rows)

    async def _show_picture_guide_page(
        self, message, page: int, *, edit: bool, from_page: int | None = None
    ) -> None:
        """一次只渲正在看的那一張。換頁直接換靜態圖，不再送滑頁 GIF。"""
        from telegram import InputMediaPhoto

        from picture_guide import PAGE_SLUGS, ensure_page

        charts = getattr(self, "charts_dir", None)
        dest = os.path.join(str(charts or "data/charts"), "picture_guide")
        n = len(PAGE_SLUGS)
        page = max(0, min(int(page), n - 1))
        slug = PAGE_SLUGS[page]
        try:
            path = await asyncio.to_thread(ensure_page, slug, dest)
        except Exception:
            logger.exception("圖文說明產圖失敗 page=%s", page)
            path = ""
        if not path or not os.path.isfile(path):
            await message.reply_html(
                "圖文說明暫時產不出來。請先看文字「總覽」。",
                reply_markup=self._help_nav_keyboard("guide"),
            )
            return
        kb = self._picture_guide_keyboard(page, n)
        _ = from_page
        with open(path, "rb") as fh:
            if edit:
                try:
                    await message.edit_media(
                        media=InputMediaPhoto(media=fh, caption=""),
                        reply_markup=kb,
                    )
                    return
                except Exception:
                    logger.debug("圖文換頁原地更新失敗，改發新訊息", exc_info=True)
                    try:
                        await message.delete()
                    except Exception:
                        pass
                    fh.seek(0)
            await message.reply_photo(photo=fh, reply_markup=kb)

    async def _send_picture_guide(self, message) -> None:
        """說明頁「圖文」：一次一張，鍵盤換頁。"""
        status = await message.reply_text("正在產出圖文說明（一次一張，共 8 張）…")
        try:
            await self._show_picture_guide_page(message, 0, edit=False)
        except Exception:
            logger.exception("圖文說明送出失敗")
            await message.reply_html(
                "圖文說明送出失敗，請稍後再按一次「圖文」，或先看文字總覽。",
                reply_markup=self._help_nav_keyboard("guide"),
            )
        finally:
            try:
                await status.delete()
            except Exception:
                pass

    @staticmethod
    def _format_elapsed(sec: int) -> str:
        sec = max(0, int(sec))
        m, s = divmod(sec, 60)
        return f"{m}:{s:02d}" if m else f"{s} 秒"

    @staticmethod
    def _screening_spinner(sec: int) -> str:
        icons = ("⏳", "🔄", "📊", "🔍")
        return icons[(max(0, sec) // 3) % len(icons)]

    @staticmethod
    def _screening_progress_bar(sec: int, *, width: int = 10) -> str:
        # 約 5 分鐘跑滿，讓使用者感受在推進（非真實百分比）
        pct = min(1.0, max(0, sec) / 300.0)
        filled = int(round(pct * width))
        return "▓" * filled + "░" * (width - filled)

    @classmethod
    def _screening_progress_text(cls, elapsed_sec: int, *, done: bool = False) -> str:
        if done:
            return "✅ 海選完成，正在推送分類名單…"
        if elapsed_sec <= 0:
            return (
                "⏳ 海選開始：載入資料、掃描全市場…\n"
                "約需 2～5 分鐘，完成後會依序推送黃金買點／重點觀察等分類。\n"
                "請勿重複按，以免排隊。"
            )
        spin = cls._screening_spinner(elapsed_sec)
        bar = cls._screening_progress_bar(elapsed_sec)
        return (
            f"{spin} 海選進行中　已 {cls._format_elapsed(elapsed_sec)}\n"
            f"{bar}\n"
            "仍在掃描全市場，完成後會自動推送。"
        )

    async def _run_manual_screening(self, message):
        """手動海選：進度提示 + 逾時保護 + 完成後提示當沖可用。"""
        actor = self._actor_key(message)
        if actor in self._screening_running:
            await message.reply_text(
                "海選進行中，請稍候完成後再按。",
                reply_markup=self._reply_menu(),
            )
            return
        async with self._screening_gate:
            if self._screening_global_owner and self._screening_global_owner != actor:
                await message.reply_html(
                    "海選正在掃描全市場（可能是你或家人剛按的），約 2～5 分鐘。\n"
                    "完成後你再按一次「海選」讀快取即可；名單是同一份，"
                    "不會和對方的持股／觀察／連買混在一起。",
                    reply_markup=self._reply_menu(),
                )
                return
            self._screening_global_owner = actor
        self._screening_running.add(actor)
        await self._dismiss_menu_transients(actor)
        hub = self._reply_menu()
        # 進度泡泡絕不可掛 ReplyKeyboard：刪掉時許多客戶端會把兩排主選單一起收掉。
        status = await message.reply_text(self._screening_progress_text(0))
        stop = asyncio.Event()
        t0 = time.monotonic()

        async def _tick():
            while not stop.is_set():
                elapsed = int(time.monotonic() - t0)
                try:
                    await status.edit_text(self._screening_progress_text(elapsed))
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
                await status.edit_text(self._screening_progress_text(0, done=True))
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
        except Exception as e:
            logger.exception("海選失敗")
            await message.reply_text(
                f"海選失敗：{e}\n"
                "請到 Render Logs 搜「四大選股失敗」；或稍後再按「海選」。",
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

    async def _send_card_share_groups(self, message, items: list) -> bool:
        """把介紹圖／決策卡送到話筒，方便長按轉 LINE。一組最多 10 張。"""
        from telegram import InputMediaPhoto

        if not items:
            return False
        lead = "圖可長按分享。文字請按下一則「開 LINE 選聯絡人」"
        sent_any = False
        i = 0
        first_group = True
        while i < len(items):
            sid = str((items[i] or {}).get("stock_id") or "")
            chunk = [items[i]]
            i += 1
            while (
                i < len(items)
                and str((items[i] or {}).get("stock_id") or "") == sid
                and len(chunk) < 10
            ):
                chunk.append(items[i])
                i += 1
            handles = []
            try:
                media = []
                for rec in chunk:
                    path = str((rec or {}).get("path") or "")
                    cap = str((rec or {}).get("caption") or "")
                    if not self._png_looks_ok(path, min_bytes=8_000, min_w=200, min_h=200):
                        continue
                    fh = open(path, "rb")
                    handles.append(fh)
                    caption = None
                    if not media:
                        caption = cap
                        if first_group:
                            caption = f"{lead}\n{cap}" if cap else lead
                    media.append(
                        InputMediaPhoto(
                            media=fh,
                            caption=(caption[:1024] if caption else None),
                        )
                    )
                first_group = False
                if len(media) >= 2:
                    await message.reply_media_group(media=media)
                    sent_any = True
                elif len(media) == 1:
                    await message.reply_photo(photo=media[0].media, caption=media[0].caption)
                    sent_any = True
            except Exception:
                logger.exception("傳 LINE 卡片相簿失敗")
            finally:
                for fh in handles:
                    try:
                        fh.close()
                    except Exception:
                        pass
        return sent_any

    async def _send_line_rich_bucket(self, message, bucket_key: str):
        """舊 lp: 鈕仍可生成圖；完成後給「開 LINE 選聯絡人」，不丟複製稿。"""
        from import_health import latest_complete_quote_date
        from line_rich_pack import (
            bucket_stock_rows,
            bucket_title,
            build_bucket_rich_pack,
            share_card_files,
        )
        from screen_sessions import upsert_line_pack

        bucket_key = str(bucket_key or "").strip()
        title = bucket_title(bucket_key)
        hub = self._reply_menu()
        actor = self._actor_key(message)
        as_of = latest_complete_quote_date(self.db_path) or self.screener.get_latest_trading_date()
        rows = await asyncio.to_thread(bucket_stock_rows, self.db_path, bucket_key, as_of)
        if not rows:
            await message.reply_text(
                f"【{title}】尚無名單。請先按主選單「海選」。",
                reply_markup=hub,
            )
            return

        n = len(rows)
        status = await message.reply_text(
            f"正在生成【{title}】{n} 檔介紹圖／決策卡…"
        )
        self._track_line_pack_status(actor, status)

        try:
            manifest = await asyncio.to_thread(
                build_bucket_rich_pack,
                self.db_path,
                bucket_key,
                as_of,
                self.charts_dir,
            )
        except Exception as exc:
            logger.exception("LINE 圖文包生成失敗 bucket=%s", bucket_key)
            await status.edit_text(
                f"⚠️ 【{title}】生成失敗：{html_escape(str(exc)[:200])}\n請稍後再試一次。"
            )
            await self._pin_reply_menu(message)
            return
        if manifest.get("error") and not manifest.get("line_text"):
            err = str(manifest.get("error") or "生成失敗")
            errs = manifest.get("errors") or []
            if errs:
                err += "\n" + "\n".join(errs[:3])
            await status.edit_text(f"⚠️ 【{title}】{err}")
            await self._pin_reply_menu(message)
            return

        line_body = str(manifest.get("line_text") or "").strip()
        if line_body:
            upsert_line_pack(
                self.db_path,
                as_of,
                {
                    "id": bucket_key,
                    "title": f"傳 {title} 到 LINE",
                    "label": f"開 LINE・{title}",
                    "text": line_body,
                },
            )

        done_n = int(manifest.get("count") or 0)
        warn = ""
        errs = manifest.get("errors") or []
        if errs:
            warn = f"\n（{len(errs)} 檔略過：{html_escape(errs[0][:80])}）"

        await self._dismiss_line_pack_status(actor)

        cards = share_card_files(self.charts_dir, manifest)
        album_ok = await self._send_card_share_groups(message, cards)
        line_kb = self._line_open_keyboard(bucket_key, label="開 LINE 選聯絡人")
        if album_ok:
            await message.reply_html(
                f"✅ <b>【{html_escape(title)}】</b>　{done_n} 檔介紹圖／決策卡。{warn}\n"
                "按下方會開啟手機 LINE，再選要傳給誰。",
                reply_markup=line_kb,
                disable_web_page_preview=True,
            )
        else:
            await message.reply_html(
                f"✅ <b>【{html_escape(title)}】</b>　{done_n} 檔已備。{warn}\n"
                "按下方會開啟手機 LINE，再選要傳給誰。",
                reply_markup=line_kb,
                disable_web_page_preview=True,
            )
        await self._pin_reply_menu(message)

    @staticmethod
    def _scratch_chart_path(charts_dir: str, code: str, kind: str, uid: str = "") -> str:
        """每人每次出圖用獨立檔名，避免哥哥／偉權同時查同一檔互相覆蓋。"""
        safe = str(code or "").strip()[:6] or "x"
        who = str(uid or "0").strip()[:16]
        tag = f"{who}_{int(time.time() * 1000)}"
        return os.path.join(charts_dir, f"{safe}_{kind}_{tag}.png")

    @staticmethod
    def _chart_progress_text(
        elapsed_sec: int,
        *,
        sent: list | None = None,
        current: str = "",
    ) -> str:
        """查股進度：跟實際階段同步，不要只停在 0 秒。"""
        labels = {"glance": "介紹圖", "card": "決策卡", "chart": "導航圖", "table": "讀高低卡", "album": "一次送出"}
        order = ("glance", "card")
        sent_ks = [str(k) for k in (sent or [])]
        elapsed = WayneTelegramBot._format_elapsed(elapsed_sec)
        now = labels.get(str(current or ""), "")
        if not now:
            now = next((labels[k] for k in order if k not in sent_ks), "出圖")
        done = [labels[k] for k in order if k in sent_ks]
        rest = [labels[k] for k in order if k not in sent_ks and labels[k] != now]
        lines = [f"查股進行中　已 {elapsed}", f"現在：{now}"]
        if done:
            lines.append("已畫：" + "、".join(done))
        if rest:
            lines.append("接著：" + "、".join(rest))
        lines.append("兩張齊了一次送出")
        return "\n".join(lines)

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
    def _chart_png_looks_ok(path: str) -> bool:
        """併發產圖偶發殘缺檔（只有標題、中間全白）；送出前擋掉。"""
        return WayneTelegramBot._png_looks_ok(path, min_bytes=48_000, min_w=500, min_h=900)

    async def screen_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._run_manual_screening(update.message)

    async def emerging_screen_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await self._run_emerging_screening(update.message)

    async def _run_emerging_screening(self, message):
        """興櫃獨立海選：不跟上市櫃海選搶同一把鎖、不寫進上市櫃快取。"""
        hub = self._reply_menu()
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
                "興櫃海選逾時。請稍後再按「興櫃」，或打「興櫃海選」。",
                reply_markup=hub,
            )
            return
        except Exception:
            logger.exception("興櫃海選失敗")
            await message.reply_text("興櫃海選失敗。請稍後再按「興櫃」，或打「興櫃海選」。", reply_markup=hub)
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
                "請等盤後同步櫃買「興櫃股票當日行情表」後再按「興櫃」。",
                reply_markup=hub,
                disable_web_page_preview=True,
            )
            return
        await self._reply_screening_payload(message, result)
        await message.reply_html(
            f"以上是<b>興櫃</b>獨立名單（官方日均價 {html_escape(str(result.get('as_of') or ''))}，"
            f"掃描 {n} 檔）。上市櫃請按主選單「海選」。",
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
        if rows:
            await asyncio.to_thread(self._persist_bucket_line_pack, bucket_key, rows)

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
            is_tw_equity_session,
            overnight_list_heading,
            tw_session_phase,
        )

        uid = str(getattr(getattr(message, "from_user", None), "id", "") or "")
        actor = self._actor_key(message, uid=uid)
        if not hasattr(self, "_trade_running"):
            self._trade_running = set()
        if actor in self._trade_running:
            await message.reply_text(
                f"{menu_label}進行中，請稍候完成後再按。",
                reply_markup=self._reply_menu(),
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
                    reply_markup=self._reply_menu(),
                )
                return
            if live_bucket == "overnight" and not is_tw_equity_session():
                effective_live_bucket = None
                display_title, effective_subtitle = overnight_list_heading(phase)
            try:
                rows = await asyncio.wait_for(asyncio.to_thread(loader), timeout=45.0)
            except asyncio.TimeoutError:
                await message.reply_text(
                    f"⚠️ {menu_label}查詢逾時（名單讀取較久）。"
                    "請稍後再按一次；若持續發生請回報。",
                    reply_markup=self._reply_menu(),
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
                        reply_markup=self._reply_menu(),
                    )
                else:
                    await message.reply_html(
                        f"<b>{display_title}</b>\n"
                        f"<i>昨收掃描後此桶無候選，或盤中複核後無符合標的。</i>",
                        reply_markup=self._reply_menu(),
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
                reply_markup=self._reply_menu(),
            )
        except Exception as e:
            logger.exception("%s 查詢失敗", live_bucket)
            await message.reply_text(
                f"{menu_label}查詢失敗：{e}\n請稍後再按一次主選單「{menu_label}」。",
                reply_markup=self._reply_menu(),
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
            title="⚡ 當沖候選（盤中即時）",
            subtitle="盤中即時複核：只列此刻漲幅 2%～8.5% 的標的；現價旁小字＝報價時間。保險進≤昨收；+3% 先出一部分；+6% 衝頂；均價跌破先走。",
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
        except Exception as e:
            logger.exception("大盤專頁失敗")
            await self._delete_message(status)
            await message.reply_text(f"大盤讀取失敗：{e}", reply_markup=self._keyboard())
            return
        parts = chunk_telegram_html(html)
        if not parts:
            await self._delete_message(status)
            await message.reply_text(
                "大盤資料暫時讀不到，請稍後再試。",
                reply_markup=self._keyboard(),
            )
            return
        try:
            for i, part in enumerate(parts):
                kb = InlineKeyboardMarkup([[self._q("market")]]) if i == len(parts) - 1 else None
                await message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)
            await self._send_market_kline(message, live=live_quote)
        except Exception as e:
            logger.exception("大盤 HTML 送出失敗")
            plain = html.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
            await message.reply_text(
                f"大盤顯示失敗，改純文字：\n{plain[:3500]}",
                reply_markup=self._keyboard(),
            )
        finally:
            await self._delete_message(status)

    async def _send_market_kline(self, message, *, live=None) -> None:
        """大盤專頁附圖：加權日 K（淺底）。"""
        from config import skip_chart_warmup

        if skip_chart_warmup():
            return
        wait = None
        try:
            wait = await message.reply_text("日K圖產製中…")
        except Exception:
            pass
        os.makedirs(self.charts_dir, exist_ok=True)
        chart_path = os.path.join(self.charts_dir, f"twii_kline_{int(time.time() * 1000)}.png")
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
        if wait is not None:
            try:
                await wait.delete()
            except Exception:
                pass
        if not path or not self._chart_png_looks_ok(path):
            return
        cap = "加權指數日K（K棒・MA5/20/60・量・KD）"
        try:
            with open(path, "rb") as f:
                await message.reply_photo(
                    photo=f,
                    caption=cap,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[self._q("market")]]),
                )
        except Exception:
            logger.exception("大盤日K圖送出失敗")

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
        except Exception as e:
            logger.exception("資金移動失敗")
            await self._delete_message(status)
            await update.message.reply_text(f"資金移動失敗：{e}", reply_markup=self._keyboard())
            return
        await self._delete_message(status)
        parts = chunk_telegram_html(html)
        for i, part in enumerate(parts):
            kb = InlineKeyboardMarkup([[self._q("flow")]]) if i == len(parts) - 1 else None
            await update.message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)

    async def _send_portfolio(self, message, uid: str):
        holdings = get_user_portfolio(self.db_path, uid)
        mine = self.portfolio_engine.format_holdings_html(holdings)
        parts = chunk_telegram_html(mine)
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
            "industry": "產業說明：請先選一檔。會送一張圖卡，用官方營收／毛利跟同業比。",
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
                await self._send_industry(update.message, last)
                return
            await self._prompt_pick(update.message, uid, "industry")
            return
        await self._send_industry(update.message, args[0].strip())

    async def _send_industry(self, message, code: str):
        from industry_brief import format_industry_html
        from industry_card import render_industry_png

        code = str(code).strip()
        hits = lookup_stocks(self.db_path, code)
        em = self._hit_is_emerging(code, hits)
        uid = str(getattr(getattr(message, "from_user", None), "id", "") or "0")
        png_path = self._scratch_chart_path(self.charts_dir, code, "industry", uid)

        def _build():
            return render_industry_png(code, self.db_path, png_path, allow_fetch=True, max_fetch=1)

        try:
            out = await asyncio.to_thread(_build)
        except Exception as e:
            logger.exception("產業說明圖失敗 code=%s", code)
            out = ""
            err = e
        else:
            err = None
        if out and os.path.isfile(out):
            try:
                with open(out, "rb") as f:
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
        except Exception as e:
            logger.exception("產業說明失敗 code=%s", code)
            html = f"產業說明失敗：{html_escape(err or e)}"
        await message.reply_html(
            html, reply_markup=self._hub_keyboard(code, em=em), disable_web_page_preview=True
        )

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
            await self._send_industry(message, code)
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
        if kind == "streak":
            await self.streak_cmd(upd, ctx)
            return
        if kind == "ai":
            await self._send_ai_desk_view(message, uid)
            return
        if kind == "help":
            await self.help_cmd(upd, ctx)
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
        uid = str(update.effective_user.id)
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
        if text == MENU_BTN_BACK_MAIN:
            await self._restore_main_menu(update.message, uid)
            return
        if text in (MENU_BTN_STREAK, "連買區域", "外資連買區域"):
            logger.info("主選單：連買區 uid=%s", uid)
            await self.streak_cmd(update, context)
            return
        if text in MENU_COMPACT_ALIASES:
            self._pending.pop(actor, None)
            self._set_menu_compact(uid, True)
            await self._force_reply_menu(update.message, uid)
            return
        if text in MENU_FULL_ALIASES:
            self._pending.pop(actor, None)
            self._set_menu_compact(uid, False)
            await self._force_reply_menu(update.message, uid)
            return
        if text in ("選單", "主選單") or text.lower().lstrip("/") == "menu":
            self._pending.pop(actor, None)
            await self.menu_cmd(update, context)
            return
        if text in ("說明", "幫助") or text.lower().lstrip("/") == "help":
            self._pending.pop(actor, None)
            await self.help_cmd(update, context)
            return
        if text == "圖文":
            self._pending.pop(actor, None)
            await self._send_picture_guide(update.message)
            return
        if text == "選股":
            self._pending.pop(actor, None)
            await update.message.reply_html(
                HELP_TOPICS["pick"],
                reply_markup=InlineKeyboardMarkup([[self._q("stock")]]),
            )
            return
        if text in ("資金", "資金移動") or text.lower().lstrip("/") == "flow":
            logger.info("主選單：資金 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.flow_cmd(update, context)
            return
        if text == MENU_BTN_MARKET or text.lower().lstrip("/") == "market":
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
            if pending == "report":
                self._pending.pop(actor, None)
                await self._commit_issue_report(
                    update.message, uid, body=raw, photo_file_id=""
                )
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
        """語音／音檔 → 聽寫 → 同一條 on_text。不編新聞。"""
        if not update.message:
            return
        if await self._reject_stranger(update):
            return
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
        except Exception as exc:
            logger.exception("voice stt failed")
            try:
                await wait.delete()
            except Exception:
                pass
            await update.message.reply_html(
                f"聽寫失敗：{html_escape(str(exc)[:180])}"
            )
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
            await self._send_industry(message, code)
            return True
        return False

    async def _send_ai_desk_view(self, message, uid: str):
        """只顯示模擬倉現況，不執行買賣。"""
        from ai_trader import ai_desk_positions

        self._touch_user(uid)
        try:
            html = await asyncio.to_thread(format_ai_desk_html, self.portfolio_engine, uid)
            positions = await asyncio.to_thread(ai_desk_positions, self.portfolio_engine, uid)
            parts = chunk_telegram_html(html)
            for i, part in enumerate(parts):
                kb = self._ai_desk_keyboard(positions) if i == len(parts) - 1 else None
                await message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)
        except Exception as e:
            logger.exception("AI 模擬倉顯示失敗")
            await message.reply_text(f"AI 模擬倉顯示失敗：{e}", reply_markup=self._keyboard())

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
            parts = chunk_telegram_html(html)
            for i, part in enumerate(parts):
                kb = self._ai_desk_keyboard(positions) if i == len(parts) - 1 else None
                await message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)
        except Exception as e:
            logger.exception("AI 進化回報失敗")
            await message.reply_text(f"AI 進化回報失敗：{e}", reply_markup=self._keyboard())

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
                    f"<i>本次沒有新成交（候選 {ai.get('candidates') or 0} 檔）。平常最多 1 檔、超跌才第 2 檔，第 3 份留現金；或名單被高低卡／美股濾掉。</i>"
                )
            if ai.get("bought"):
                bits.append("<b>本次買進</b>\n" + "\n".join(html_escape(x) for x in ai["bought"]))
            if ai.get("sold"):
                bits.append("<b>本次賣出</b>\n" + "\n".join(html_escape(x) for x in ai["sold"]))
            if ai.get("lesson"):
                bits.append("進化：" + html_escape(ai["lesson"]))
            parts = chunk_telegram_html("\n\n".join(bits))
            from ai_trader import ai_desk_positions

            positions = await asyncio.to_thread(
                ai_desk_positions, self.portfolio_engine, uid
            )
            for i, part in enumerate(parts):
                kb = self._ai_desk_keyboard(positions) if i == len(parts) - 1 else None
                await message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)
        except Exception as e:
            logger.exception("AI 操盤失敗")
            await message.reply_text(f"AI 操盤失敗：{e}", reply_markup=self._keyboard())
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
        wait_msg = None
        if not skip_wait_msg:
            try:
                wait_msg = await message.reply_text("決策卡產製中…")
                self._track_lookup_fade(actor, wait_msg, "wait")
            except Exception:
                pass
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
            await message.reply_html(
                f"⚠️ {html_escape(code)} 尚無足夠日K，無法出導航圖。",
                reply_markup=hub,
                disable_web_page_preview=True,
            )
            return
        wait = None
        try:
            wait = await message.reply_text("導航圖產製中（180日）…")
        except Exception:
            pass
        os.makedirs(self.charts_dir, exist_ok=True)
        chart_path = os.path.join(self.charts_dir, f"{code}_nav_{int(time.time() * 1000)}.png")
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
        if wait is not None:
            try:
                await wait.delete()
            except Exception:
                pass
        if not path or not self._chart_png_looks_ok(path):
            await message.reply_html(
                "導航圖產出失敗，請稍後再按一次「導航圖」。",
                reply_markup=hub,
                disable_web_page_preview=True,
            )
            return
        cap = "180日高低導航：實心＝當日觸發；空心＝接近。高點紫／低點青綠，點開可放大。"
        for attempt in range(3):
            try:
                with open(path, "rb") as f:
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

    async def _send_card_to(self, message, code: str, uid: str = ""):
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
        actor = self._actor_key(message, uid=uid or self._uid_from_message(message))
        lock = self._lookup_locks.setdefault(actor, asyncio.Lock())
        if lock.locked():
            await message.reply_text("上一檔還在出圖，請稍候再查。")
            return
        async with lock:
            await self._send_card_to_locked(message, code, uid, actor, hits)

    async def _send_card_to_locked(
        self,
        message,
        code: str,
        uid: str,
        actor: str,
        hits: list,
    ):
        lookup_faded = False
        sent_any = False
        is_em = self._hit_is_emerging(code, hits)
        wait_msg = None
        progress_stop = asyncio.Event()
        progress_task = None
        op_t0 = time.monotonic()
        self._op_state_map()[actor] = {"sent": [], "current": "table", "t0": op_t0}
        try:
            wait_msg = await message.reply_text(
                self._chart_progress_text(0, current="table")
            )
            self._track_lookup_fade(actor, wait_msg, "wait")
        except Exception:
            wait_msg = None
        news_stats = None
        try:
            from stock_news import fetch_stock_news_stats

            name0 = ""
            if hits:
                name0 = str(hits[0].get("stock_name") or "")
            news_stats = await asyncio.wait_for(
                asyncio.to_thread(
                    fetch_stock_news_stats, self.db_path, code, name0
                ),
                timeout=5.0,
            )
        except Exception:
            news_stats = None
        hub = self._hub_keyboard(code, em=is_em, news=news_stats)

        live_rt = None
        if not is_em:
            try:
                live_rt = await asyncio.wait_for(
                    asyncio.to_thread(self._prefetch_mis_quote, code, hits),
                    timeout=6.0,
                )
            except Exception:
                live_rt = None

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
                    with open(path, "rb") as f:
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
                        )
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
            req_tag = f"{uid_key or '0'}_{int(time.time() * 1000)}"
            glance_path = os.path.join(self.charts_dir, f"{code}_glance_{req_tag}.png")
            card_path_f = os.path.join(self.charts_dir, f"{code}_card_{req_tag}.png")
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
            render_plan = [
                ("glance", _render_glance, _LOOKUP_PNG_TIMEOUT, glance_cap, None),
                ("card", lambda: render_decision_card_png(card, card_path_f), _LOOKUP_PNG_TIMEOUT, card_cap, hub),
            ]
            kind_labels = {"glance": "介紹圖", "card": "決策卡"}
            sent_kinds: list[str] = []
            ready_items: list = []

            # 兩張畫完一次送相簿；180 日導航改圖下「導航圖」。
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
        """兩張一次送，Telegram 一則兩個縮圖。圖說不講義。"""
        from telegram import InputMediaPhoto

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
                fh = open(path, "rb")
                handles.append(fh)
                if not media:
                    if album_cap:
                        media.append(
                            InputMediaPhoto(media=fh, caption=album_cap[:1024], parse_mode="HTML")
                        )
                    else:
                        media.append(InputMediaPhoto(media=fh))
                else:
                    media.append(InputMediaPhoto(media=fh))
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
        data = q.data or ""
        if data.startswith("cat:") or data.startswith("noop"):
            hints = {
                "revenue_cross": "優先看：營收轉強 × 量價突破",
                "leave_zero": "黃金買點：獲利格剛離零且趨勢向上（按表，不是每個紅箭頭低點）",
                "golden_buy": "重點觀察：60低超跌（注意觀察，不是今天必買）",
                "select_01": "周帶量：短線轉強，靠近20日高少追",
                "select_02": "站上季線：昨收在季線下、今日站上",
                "select_03": "止跌：月低附近有人接、量沒死",
                "day_trade": "當沖：進場 / 停利 / 停損",
                "overnight": "隔日沖：尾盤佈局",
            }
            await q.answer(hints.get(data.split(":", 1)[-1], "分類標記")[:200])
            return
        if data.startswith("lp:"):
            await q.answer("正在準備 LINE…")
            await self._send_line_rich_bucket(q.message, data[3:].strip())
            return
        if data.startswith("rw:"):
            await self._remove_watch_clicked(q, data[3:].strip())
            return
        if data.startswith("fb:"):
            await self._handle_buy_streak_callback(q, uid, data)
            return
        if data.startswith("pg:"):
            from picture_guide import parse_guide_callback

            try:
                from_page, page = parse_guide_callback(data)
            except ValueError:
                await q.answer("頁碼不對")
                return
            if page < 0 or page > 20:
                await q.answer("沒有這一張")
                return
            await q.answer(f"換成第 {page + 1} 張")
            await self._show_picture_guide_page(
                q.message, page, edit=True, from_page=from_page
            )
            return
        if data == "em:go":
            await q.answer("興櫃海選開始")
            await self._run_emerging_screening(q.message)
            return
        await q.answer()
        if data == "fw:s":
            await self._reply_line_share(q.message)
            return
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
            topic = data[2:] or "guide"
            if topic in ("pics", "book"):
                try:
                    from picture_guide import PAGE_SLUGS

                    await q.answer(f"圖文 1／{len(PAGE_SLUGS)}")
                except Exception:
                    pass
                is_photo = self._message_is_photo(q.message)
                if is_photo:
                    await self._show_picture_guide_page(q.message, 0, edit=True)
                else:
                    await self._send_picture_guide(q.message)
                return
            if self._message_is_photo(q.message):
                try:
                    await q.message.delete()
                except Exception:
                    pass
                await self._reply_help_topic(q.message, topic)
                return
            if topic == "menu":
                uid = str(q.from_user.id)
                self._invalidate_menu_layout(uid)
                await self._refresh_reply_menu(q.message, uid=uid, silent=True)
                await self._reply_help_topic(q.message, "menu", edit_target=q.message)
                return
            await self._reply_help_topic(q.message, topic, edit_target=q.message)
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
        if data.startswith("k:"):
            uid = str(q.from_user.id)
            try:
                await self._send_card_to(q.message, data[2:], uid)
            except Exception:
                logger.exception("callback 查股失敗")
                try:
                    await q.message.reply_text(
                        f"{data[2:]} 出圖失敗，請再打一次代號。"
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
            await self._send_industry(q.message, data[2:].strip())
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
            await self._run_manual_screening(q.message)
        elif data == "daytrade":
            await self._run_trade_bucket(
                q.message,
                bucket_key="day_trade",
                live_bucket="daytrade",
                title="⚡ 當沖候選（盤中即時）",
                subtitle="盤中即時複核：只列此刻漲幅 2%～8.5% 的標的；現價旁小字＝報價時間。保險進≤昨收；+3% 先出一部分；+6% 衝頂；均價跌破先走。",
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
