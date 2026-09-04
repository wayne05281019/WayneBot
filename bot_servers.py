"""
WayneBot Telegram 操作層
- 兩排主選單（輸入框右側 ⌨️）；直立式不再重複主選單按鈕
- 打股票代號 → 決策卡 + 高低導航圖 + 籌碼表
- 海選 / 當沖 / 隔日沖 / 持股 / 觀察 / 資金 / 連買區
"""
from __future__ import annotations

import asyncio
import gc
import logging
import os
import struct
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

# Render 免費方案冷啟＋行情庫索引期間，第一檔查詢常超過 45s。
_CARD_BUILD_TIMEOUT = float(os.getenv("WAYNE_CARD_BUILD_TIMEOUT", "90"))
_CHART_RENDER_TIMEOUT = float(os.getenv("WAYNE_CHART_RENDER_TIMEOUT", "120"))
# 介紹圖／決策卡與導航圖同一逾時。醒機時 matplotlib 冷啟，60s 會只送到介紹圖。
_LOOKUP_PNG_TIMEOUT = float(os.getenv("WAYNE_LOOKUP_PNG_TIMEOUT", str(_CHART_RENDER_TIMEOUT)))

from config import get_charts_dir, get_db_path, get_telegram_config, skip_chart_warmup
from wayne_db import (
    init_database,
    get_user_portfolio,
    add_to_watchlist,
    remove_from_watchlist,
    lookup_stocks,
    touch_tg_user,
)
from trade_journal import (
    ensure_user_trade_logs,
    format_user_review_html,
    format_user_trades_html,
    parse_lots_price,
    record_buy,
    record_sell,
)
from screening_engine import ScreeningEngine
from portfolio_engine import PortfolioEngine
from ai_trader import format_ai_desk_html, run_ai_desk
from chips import generate_chips_image

logger = logging.getLogger(__name__)


def _normalize_menu_text(text: str) -> str:
    """主選單按鈕文字正規化（全形、空白）。"""
    t = unicodedata.normalize("NFKC", (text or "").strip())
    return t.replace("\u3000", "").strip()


def html_escape(val) -> str:
    return (
        str(val if val is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _photo_sell_caption(base: str, card: dict | None, *, fallback: str = "當日K＋籌碼價量") -> str:
    """圖說：有如何賣就寫在圖底下，縮圖也能看到。"""
    cap = str(base or "").strip() or fallback
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
    return f"{cap}\n紀律　{html_escape(short)}"


def _glance_photo_caption(base: str, card: dict | None) -> str:
    """介紹圖說明：有如何賣就寫在第一張圖底下。"""
    return _photo_sell_caption(base, card)


def _sell_holdings_prompt(code: str, lots=None) -> str:
    """賣出手記持股：帶現有張數／股數，零股不要讓人以為是 0張。"""
    head = f"賣出 {code}。"
    if lots is not None:
        try:
            from tg_layout import holdings_qty_text

            head += f"現有 {holdings_qty_text(lots)}。"
        except Exception:
            pass
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

HELP_TOPICS = {
    "guide": (
        "<b>WayneBot 使用說明</b>\n"
        "下面依<b>分類</b>說明每個按鈕怎麼用；點訊息下方分類鈕可看該頁細節，按 <b>✕</b> 收合。\n"
        "\n"
        "<b>一、主選單在哪？</b>\n"
        "不在訊息最下面。點輸入框<b>右邊 ⌨️</b> 展開<b>兩排</b>按鈕；打完字若只剩英文鍵盤，再點一次 ⌨️。\n"
        "也可打 /menu 重新釘選單；打 /help 或按「說明」看本頁。\n"
        "\n"
        "<b>二、第一排按鈕</b>\n"
        "左→右：<b>決策卡</b>、<b>當沖</b>、<b>持股</b>、<b>觀察</b>、<b>海選</b>。\n"
        "點下方 <b>第一排</b> 可看每一顆的意義與操作步驟。\n"
        "\n"
        "<b>三、第二排按鈕</b>\n"
        "左→右：<b>隔日沖</b>、<b>資金</b>、<b>說明</b>、<b>連買區</b>、<b>大盤</b>。\n"
        "點下方 <b>第二排</b> 可看每一顆的意義與操作步驟。\n"
        "\n"
        "<b>四、AI 模擬自動買進</b>\n"
        "不在主選單上。路徑：<b>持股</b> → 訊息下方 <b>AI模擬倉</b>／<b>AI操盤</b>。\n"
        "每晚 20:00 雲端會依海選自動模擬買賣（不推播）；要看結果請按 AI模擬倉。點下方 <b>AI</b> 看完整說明。\n"
        "\n"
        "<b>五、打股名或代號（例：南亞、2324）</b>\n"
        "會依序出：現價漲跌 → 決策卡圖 → 介紹圖。圖下方還有：\n"
        "• <b>籌碼</b>：三大法人買賣超圖\n"
        "• <b>營收</b>：月營收、季報毛利\n"
        "• <b>產業</b>：同業中位數＋這族法人，講人話\n"
        "• <b>觀察</b>：加入自選\n"
        "• <b>導航圖</b>：180 日高低導航（較慢，要再看才按）\n"
        "• <b>記買入</b>：記真實持股，接著打 <code>張數 價格</code>，例 <code>1 68.5</code>\n"
        "名稱撞名時，藍字股名＝奇摩；按鈕左邊＝看這檔，右 <b>➕</b>＝觀察。\n"
        "\n"
        "<b>六、海選名單裡的按鈕</b>\n"
        "• 左鍵（代號＋股名）＝看這檔完整圖\n"
        "• <b>➕</b>＝加入觀察\n"
        "• <b>開 LINE・傳這檔</b>／區底 <b>一鍵傳 LINE</b>：開 LINE 帶文字；長圖長按儲存再貼\n"
        "• 靠近 20 日收盤高會標<b>少追</b>，不是叫立刻買\n"
        "\n"
        "<b>七、持股頁按鈕</b>\n"
        "• 股名鍵＝看這檔　• <b>賣出</b>＝打張數與價格　• <b>AI模擬倉</b>＝看模擬現況　• <b>AI操盤</b>＝依海選跑一輪模擬買賣（不推播）\n"
        "\n"
        "<b>八、觀察頁按鈕</b>\n"
        "• 股名鍵＝看這檔　• <b>籌碼</b>　• <b>買入</b>（同記買入）　• <b>刪</b>＝移出觀察\n"
        "\n"
        "<b>九、每日時間（台灣）</b>\n"
        "06:30 早上海選寄出（對美股）｜12:45 尾盤可切版｜16:30 官方收盤寫庫｜20:00 晚間海選＋AI 模擬買（不推播）\n"
        "盤中查股用 MIS（不寫庫）；13:30～16:30 融合前若 MIS 空白，查股會用 Yahoo 參考價，16:30 後以庫內官方收盤為準。\n"
        "\n"
        "<b>十、資料正確性（最重要）</b>\n"
        "庫內日 K 只寫官方融合後的收盤；盤中 MIS 與 Yahoo 僅供查股顯示，不寫進 sqlite。\n"
        "假 K、週末殘列、漲跌幅與前日收盤不符，啟動與 16:30 融合後會自動清掉或重算。\n"
        "\n"
        "<b>十一、多人使用（家人各用各的）</b>\n"
        "每人用自己的 Telegram 帳號跟 Bot <b>私聊</b>：持股、觀察、成交、連買 wizard、查股出圖檔名都<b>各看各的</b>，不會刪到對方訊息。\n"
        "海選／大盤／資金／連買名單是全市場同一份；若家人正在跑海選，你再按只會共用那一次掃描，不會啟第二趟拖慢彼此。\n"
        "\n"
        "<b>十二、提醒</b>\n"
        "這是輔助看盤工具，不是下單系統；名單是候選，不保證獲利。有問題找偉權。\n"
        "\n"
        "<b>十三、完全新手小詞典</b>\n"
        "• <b>張</b>：台股一張＝1000 股；記買入時打「1 68.5」＝買 1 張、每股 68.5 元\n"
        "• <b>觀察</b>：只是自選清單，還沒真的買\n"
        "• <b>持股</b>：你有手記買入的才會出現\n"
        "• <b>決策卡</b>：一張圖看這檔近期高低點與量，不是叫你立刻買\n"
        "• <b>海選</b>：電腦掃全市場的候選名單；低買高賣、按表操課，不是每個低點都買\n"
        "• <b>按表</b>：起漲＝獲利剛離零且趨勢向上；黃金買點＝60低超跌觀察。CaryBot 紅箭頭不是下單訊號"
    ),
    "row1": (
        "<b>第一排按鈕（左→右）</b>\n"
        "\n"
        "<b>① 決策卡</b>\n"
        "• <b>是什麼</b>：盤中刷新「上一檔」的高低決策卡，不用重打代號。\n"
        "• <b>怎麼用</b>：先打一次股名或代號看圖，之後盤中常按這顆刷新 MIS 現價、量排名。\n"
        "• <b>沒反應</b>：若還沒查過任何股，會請你先打代號或從觀察清單點一檔。\n"
        "• <b>注意</b>：這是單檔快捷鍵，不是海選起漲名單。\n"
        "\n"
        "<b>② 當沖</b>\n"
        "• <b>是什麼</b>：盤中即時複核的當沖候選（漲幅約 2%～8.5%）。\n"
        "• <b>怎麼用</b>：平日 <b>09:00–13:30</b> 按；列出保險進場、停利、停損參考價。\n"
        "• <b>收盤後</b>：按了不會出名單（沒有 MIS 盤中價）。\n"
        "• <b>會是空的</b>：美股隔夜大跌、VIX 高時故意不列，避免硬沖。\n"
        "\n"
        "<b>③ 持股</b>\n"
        "• <b>是什麼</b>：你自己手記的<b>真實買入</b>，不是觀察、也不是 AI 模擬倉。\n"
        "• <b>怎麼用</b>：按進去看清單；每檔可「賣出」、點股名看決策卡。\n"
        "• <b>記買入</b>：查股後按「記買入」，再打 <code>張數 價格</code>，例 <code>1 68.5</code>。\n"
        "• <b>AI 在這裡</b>：訊息最下方有 <b>AI模擬倉</b>、<b>AI操盤</b>（見「AI」說明）。\n"
        "\n"
        "<b>④ 觀察</b>\n"
        "• <b>是什麼</b>：自選清單，還沒買也可以先放。\n"
        "• <b>怎麼加</b>：海選或查股旁的 <b>➕</b>，或直接打股名查詢後按「觀察」。\n"
        "• <b>怎麼刪</b>：進觀察頁，該檔按「刪」。\n"
        "• <b>藍字股名</b>：連到奇摩走勢（開網頁，不帶大圖預覽）。\n"
        "\n"
        "<b>⑤ 海選</b>\n"
        "• <b>是什麼</b>：依<b>昨收</b>掃全市場的佈局名單（起漲、優先看、周帶量等）。\n"
        "• <b>怎麼用</b>：按一次等 2～5 分鐘，完成後分類推送；勿連按以免排隊。\n"
        "• <b>自動版</b>：平日 06:30 會自動寄一版給家人；12:45 有尾盤可切版。\n"
        "• <b>注意</b>：不是盤中即時掃描；當沖／隔日沖要另按第二排按鈕。"
    ),
    "row2": (
        "<b>第二排按鈕（左→右）</b>\n"
        "\n"
        "<b>① 隔日沖</b>\n"
        "• <b>是什麼</b>：尾盤佈局、隔日沖候選名單。\n"
        "• <b>怎麼用</b>：平日 <b>09:00–13:30</b> 按，看保險買進價與明早目標價。\n"
        "• <b>收盤後按</b>：只顯示強勢收盤候選，供明天開盤參考，不是叫你收盤再買。\n"
        "\n"
        "<b>② 資金</b>\n"
        "• <b>是什麼</b>：盤後「產業輪動」＋三大法人買賣超張數。\n"
        "• <b>怎麼用</b>：看哪幾族法人加碼、族內代表股；當佈局參考，不是下單訊號。\n"
        "• <b>不是什麼</b>：不含你的持股／觀察；也不是分點、也不是論壇消息。\n"
        "\n"
        "<b>③ 說明</b>\n"
        "• 就是本說明頁；可分類點下方按鈕看細節。\n"
        "\n"
        "<b>④ 連買區</b>\n"
        "• 先選<b>外資</b>／<b>投信</b>／<b>外資+投信</b>（點訊息下方按鈕）。\n"
        "• 再選上市或上櫃，再點連買天數（有 25 天就會出現 25）。\n"
        "• 名單顯示代號、股名、N 日連買張數與佔成交％；點股名看出完整圖，按籌碼核對。\n"
        "• 鍵盤被收掉時打 /menu 可重新釘住兩排。\n"
        "\n"
        "<b>⑤ 大盤</b>\n"
        "• <b>是什麼</b>：加權指數、月線廣度、法人合計、Regime 燈號，外加美股隔夜快取。\n"
        "• <b>怎麼用</b>：隨時按；只讀庫內資料，不會觸發匯入或改寫行情。\n"
        "• <b>跟海選</b>：海選桶權重已依 Regime+／regime 自動調整；這頁讓你看「為什麼今天偏積極或保守」。"
    ),
    "market": (
        "<b>大盤按鈕</b>\n"
        "次排最右。顯示加權現價／收盤與漲跌點、開高低／振幅、量增減、漲跌家數、三大法人、距月線／年高，並附淺底日K圖。\n"
        "若有庫內美股隔夜快取，會附道瓊／標普／費半與 VIX。\n"
        "<b>只讀</b>：不觸發 Yahoo/TWSE 抓取、不寫 sqlite、不影響 16:30 自動融合或 06:30 早報。"
    ),
    "ai": (
        "<b>AI 模擬倉與自動買進</b>\n"
        "\n"
        "<b>在哪裡？</b>\n"
        "主選單<b>沒有</b> AI 按鈕。請按 <b>持股</b>，訊息最下方會看到：\n"
        "• <b>AI模擬倉</b>：只看模擬帳戶現況（不買賣）\n"
        "• <b>AI操盤</b>：立刻依海選跑一輪模擬買賣\n"
        "\n"
        "<b>自動買進（你問的這個）</b>\n"
        "• 平日 <b>20:00</b> 雲端會：① 寫晚間海選快照 ② 讓<b>你的</b> AI 依海選紀律模擬買進／賣出\n"
        "• <b>不會推播</b>到 Telegram，所以你不會收到通知——這是正常的。\n"
        "• 隔天自己按 <b>持股 → AI模擬倉</b> 看有沒有成交、持了哪些檔。\n"
        "• 16:30 盤後融合成功時，伺服器也會順便為每位使用者各跑一輪（同樣不推播）。\n"
        "\n"
        "<b>模擬規則（簡要）</b>\n"
        "• 每人本金 50 萬虛擬、最多同時 3 檔，從海選佈局桶挑（起漲、黃金買點、隔日沖等）\n"
        "• 貼月高（少追）、美股電子逆風的不買；停損約 -7%、停利約 +8%\n"
        "• 這是<b>模擬</b>，不會動你的真實持股，也不會真的下單。\n"
        "\n"
        "<b>跟真實持股的差別</b>\n"
        "• <b>持股</b>＝你手動記的買入　• <b>AI模擬倉</b>＝你專屬的虛擬帳戶（每人一套，家人也各看各的）。"
    ),
    "decision": (
        "<b>決策卡按鈕</b>\n"
        "主選單第一顆。盤中刷新上一檔的高低決策卡與 MIS 價量。\n"
        "用法：先查過一檔股，之後盤中重複按此鈕即可更新，不必重打代號。\n"
        "與「海選」不同：海選是全市場昨收掃描，決策卡是單檔盤中工具。"
    ),
    "menu": (
        "<b>主選單在哪？</b>　不在訊息最下面，在<b>輸入框右側 ⌨️</b>展開的兩排按鈕。\n"
        "<b>第一排</b>：決策卡／當沖／持股／觀察／海選\n"
        "<b>第二排</b>：隔日沖／資金／說明／連買區／<b>大盤</b>（次排最右）\n"
        "手機打完字若只看到英文鍵盤：點輸入框<b>右邊 ⌨️</b> 叫回兩排；或打 /menu 強制更新。\n"
        "訊息上的「➕」「說明」仍附在最後一則（Telegram 規定）；換頁主功能請用右側 ⌨️ 兩排。\n"
        "完整分類說明請按主選單「說明」，或看本頁導覽下方各分類鈕。"
    ),
    "screen": (
        "<b>海選怎麼用</b>\n"
        "週一～五台灣 06:30 用昨收＋美股收盤／盤後寄出；12:45 再寄尾盤可切（對照今早名單）。\n"
        "晚間 20:00 只記台股收盤名單、不寄。【雙時段】＝晚間＋今早都在。\n"
        "海選＝昨收<b>佈局</b>名單（起漲、優先看、周帶量等），不是盤中即時掃描。"
        "每區底部按<b>一鍵傳 LINE</b>：背景生成整區文字＋一張長圖，按鈕會開啟 LINE 並帶入文字摘要；長圖在同一頁長按儲存後貼到 LINE 即可。\n"
        "（主選單<b>決策卡</b>＝單檔盤中刷新，不是整區起漲名單。）\n"
        "股名右「開 LINE・傳這檔」直跳 LINE；區底「傳本區」轉整段。<b>當沖／隔日沖不在晨間海選推播</b>，請按主選單「當沖」「隔日沖」。\n"
        "靠近 20 日收盤高會標<b>少追</b>。低買高賣是生存法則：起漲／黃金買點只認決策卡表，不認圖上紅箭頭。\n"
        "藍字股名＝奇摩。下面按鈕：左＝代號＋股名（看圖）；右➕＝觀察。\n"
        "其餘檔同樣是一檔一塊完整卡片。不是立即下單清單。\n"
        "美股看現金收盤；收盤後再看盤後。大跌會在 06:30 先單獨通知一則。\n"
        "隔日會用庫內收盤對昨天名單復盤；弱的類別只讓 AI 模擬倉少買。"
    ),
    "daytrade": (
        "<b>當沖怎麼用</b>\n"
        "保險進場＝不要追過當日收盤；第一停利＝+3% 先出一部分；衝頂＝+6%；保險停損＝當日均價跌破先走。\n"
        "只在平日 <b>09:00–13:30 盤中</b> 按才有意義（MIS 即時複核漲幅 2%～8.5%）；收盤後按不會出名單。\n"
        "隔夜美股逆風（收盤或盤後大跌、VIX 高）時這頁會空，避免開盤缺口硬沖。\n"
        "藍字＝奇摩；左鍵代號＋股名＝現價＋圖；➕＝觀察。不是保證獲利。"
    ),
    "overnight": (
        "<b>隔日沖怎麼用</b>\n"
        "保險買進＝尾盤昨收附近、不要摸高；明早開高目標 +3.5%～+4.8%；衝頂 +7%；保險防守＝開盤與均價較低者，跌破先走。\n"
        "進場參考時段＝平日 <b>09:00–13:30</b>（尾盤前）；收盤後按只顯示強勢收盤候選，供明早開盤參考，不是叫你再買。\n"
        "藍字＝奇摩；左鍵代號＋股名＝現價＋圖；➕＝觀察。"
    ),
    "portfolio": (
        "<b>持股怎麼用</b>\n"
        "這裡只顯示你手記的真實買入，不是觀察、也不是 AI 模擬倉。記買入：選股→記買入→打 <code>張數 價格</code>。\n"
        "\n"
        "<b>訊息下方按鈕</b>\n"
        "• 股名＝看這檔決策卡　• <b>賣出</b>＝記賣出張數與價格\n"
        "• <b>AI模擬倉</b>＝看 50 萬虛擬帳戶現況（不買賣）\n"
        "• <b>AI操盤</b>＝立刻依海選跑一輪模擬買賣\n"
        "\n"
        "<b>自動買進</b>：每晚 20:00 雲端會自動模擬買，但<b>不推播</b>；請按 AI模擬倉查看。詳見說明頁「AI」。"
    ),
    "watch": (
        "<b>觀察怎麼用</b>\n"
        "自選清單，還沒買也可以加。空的很正常。\n"
        "加入：打股名或海選旁的 ➕。刪除：觀察頁該檔按「刪」。\n"
        "藍字股名＝奇摩走勢（只開網頁，不帶預覽大圖）。"
    ),
    "stock": (
        "<b>單檔第一眼建議看這些</b>\n"
        "打股名或按看這檔：先現價／漲跌，再決策卡 → 介紹圖；要 180 日導航按「導航圖」；籌碼／產業另按下方按鈕。\n"
        "1 股號旁當日 K 縮圖＋收盤連漲／連跌＋開高低\n"
        "2 獲利＝近60個日曆日收盤低（與 CaryBot 同；貼20日低不歸零）；距60根低是另外一欄\n"
        "3 溫度＝20日收盤位置＋月乖離；溫度計是領先指標。"
        "創歷史新高且溫度≥80要注意（少追）。"
        "升降溫「最低溫＋價未新低」＝低檔背離；「降溫＋價溫背離」＝價創新高但溫度已降，少追。表頭「今日態度」只認表、不是下單。\n"
        "   表頭量能：近480／120／60日量前10會亮短窗；介紹圖寫「60日第7 · 120日第25」。表格最右欄永遠是120日量排名。\n"
        "4 預警欄：K20高＝RSV≥70且收盤靠近20日高（≥95%）；K20低＝貼20低或月乖離轉負。"
        "預警為 No 時仍會露出高低（20高／10低），不藏表\n"
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
        "看這檔後按下方「產業」，或打 /industry 代號。用官方月營收、季報毛利率跟同業中位數比，再加上這族法人張數。\n"
        "這是落後的公開數字，幫你看懂這族，不是內幕。少賠仍看高低卡：靠近 20 日收盤高少追。"
    ),
    "buy": (
        "<b>記買入</b>\n"
        "選好股票後打價格即可（預設 1 張）：<code>68.5</code>\n"
        "多張：<code>2 68.5</code>；也可 <code>2330 1 500</code>（代號 張數 價格）。"
    ),
    "pick": "請打股名或代號，例如 <b>南亞</b>、<b>2324</b>。",
    "flow": (
        "<b>資金移動怎麼用</b>\n"
        "盤後資金輪動：同一交易日依產業把三大法人張數加總，對照前一日。熱 3 族＋族內代表股當佈局參考。\n"
        "個股區塊是外資／投信買賣超與短線熱股，不含你的持股或觀察（各走自己的選單）。\n"
        "只看官方法人＋價量，不抓分點、不抓論壇。法人也會幌，輪動不單獨當訊號。"
    ),
    "streak": (
        "<b>連買區怎麼用</b>\n"
        "主選單次排「連買區」。先選要看哪一種：<b>外資</b>、 <b>投信</b>、或<b>外資+投信</b>（同一天兩家都買超才算）。\n"
        "點訊息下方按鈕選<b>外資</b>／<b>投信</b>／<b>外資+投信</b>。\n"
        "再選<b>上市</b>或<b>上櫃</b>，再點連買天數。\n"
        "天數只列出「剛好有股票」的連買天數（最長會標在訊息裡）；點 6 就只看剛好連買 6 天的股票。\n"
        "每檔顯示代號、股名、N 日連買幾張、佔 N 日總成交％。點股名＝一般查股；按<b>籌碼</b>核對官方法人表。"
    ),
}

# 主選單兩排各五格：次排最右＝大盤專頁（只讀）；連買區取代舊「選單」。
MENU_BTN_MARKET = "大盤"
MENU_BTN_STREAK = "連買區"
MENU_BTN_BACK_MAIN = "回主選單"
MENU_BTN_BACK_STEP = "上一步"
MENU_BTN_NEXT_PAGE = "下一批"
MENU_BTN_PREV_PAGE = "上一批"
# 版面改版時遞增，讓舊客戶端自動強制刷新一次。
# v6：進度／暫態泡泡也不掛 ReplyKeyboard（刪進度時鍵盤會一起沒）。
# v7：次排「連買區」取代「選單」。
# v8：版面過期必「新發」帶 ReplyKeyboard 的訊息（edit 無法換兩排按鈕）。
MENU_LAYOUT_VERSION = "8"
MAX_PICK_INLINE_ROWS = 8


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
        # actor → 查股進行到哪（介紹圖／決策卡／導航），進度泡泡跟這裡同步
        self._lookup_op_state: Dict[str, dict] = {}
        self._pending_locks: Dict[str, asyncio.Lock] = {}
        self._screening_running: set[str] = set()
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

    @staticmethod
    def _uid_from_message(message) -> str:
        user = getattr(message, "from_user", None)
        return str(getattr(user, "id", "") or "")

    def _touch_user(self, uid: str, display_name: str = "") -> None:
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

    def _wrap_cmd(self, handler):
        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
            self._touch_from_update(update)
            return await handler(update, context)

        return wrapped

    def _remember_card(self, uid: str, code: str) -> None:
        c = str(code or "").strip()
        if uid and c:
            self._last_card[uid] = c

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
            "盤中<b>決策卡</b>：打代號或股名。"
            "會用證交所 MIS 即時價量重算格子（含 120日量排名）。"
            "也可點下面觀察清單。",
            reply_markup=InlineKeyboardMarkup(kb),
        )

    async def decision_card_btn(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        status = await self._transient_status(update.message, "決策卡產製中…")
        try:
            await self._enter_main_menu(update.message, uid)
            last = self._last_card.get(uid)
            if last:
                await self._send_decision_card_quick(update.message, last, uid, skip_wait_msg=True)
            else:
                await self._prompt_decision_card(update.message, uid)
        finally:
            await self._delete_message(status)

    def _reply_menu(self):
        """兩排各五格：左→右依常用順序；次排最右＝大盤。"""
        rows = [
            [
                KeyboardButton("決策卡"),
                KeyboardButton("當沖"),
                KeyboardButton("持股"),
                KeyboardButton("觀察"),
                KeyboardButton("海選"),
            ],
            [
                KeyboardButton("隔日沖"),
                KeyboardButton("資金"),
                KeyboardButton("說明"),
                KeyboardButton(MENU_BTN_STREAK),
                KeyboardButton(MENU_BTN_MARKET),
            ],
        ]
        try:
            return ReplyKeyboardMarkup(
                rows,
                resize_keyboard=True,
                is_persistent=True,
                input_field_placeholder="打股名／代號，或按「決策卡」",
            )
        except TypeError:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True)

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
        for text in ("兩排主選單在輸入框右側 ⌨️。", "·"):
            try:
                pin = await message.reply_text(text, reply_markup=self._reply_menu())
                self._menu_pin_msgs[actor] = pin
                return
            except Exception:
                continue
        try:
            pin = await message.reply_text("主選單", reply_markup=self._reply_menu())
            self._menu_pin_msgs[actor] = pin
        except Exception:
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
        text = (
            "兩排已更新：次排「連買區」＋「大盤」。點輸入框右側 ⌨️。"
            if silent
            else "主選單已掛上（輸入框右側 ⌨️ 兩排；次排「連買區」＋最右「大盤」）。"
        )
        try:
            pin = await message.reply_text(text, reply_markup=self._reply_menu())
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

    def _streak_nav_row(self, *, back_step: bool = False):
        row = []
        if back_step:
            row.append(KeyboardButton(MENU_BTN_BACK_STEP))
        row.append(KeyboardButton(MENU_BTN_BACK_MAIN))
        return row

    def _streak_kind_keyboard(self):
        from buy_streak import KIND_BTN

        rows = [
            [KeyboardButton(KIND_BTN["foreign"]), KeyboardButton(KIND_BTN["trust"])],
            [KeyboardButton(KIND_BTN["both"])],
            self._streak_nav_row(back_step=False),
        ]
        try:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)
        except TypeError:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True)

    def _streak_market_keyboard(self):
        rows = [
            [KeyboardButton("上市"), KeyboardButton("上櫃")],
            self._streak_nav_row(back_step=True),
        ]
        try:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)
        except TypeError:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True)

    def _streak_days_keyboard(self, days: list[int]):
        rows = []
        row = []
        for n in days:
            row.append(KeyboardButton(str(n)))
            if len(row) == 5:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append(self._streak_nav_row(back_step=True))
        try:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)
        except TypeError:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True)

    def _streak_stocks_keyboard(self, rows_data, *, has_prev: bool, has_next: bool):
        rows = []
        pair = []
        for item in rows_data:
            pair.append(KeyboardButton(f"{item.stock_id} {item.name}".strip()[:28]))
            if len(pair) == 2:
                rows.append(pair)
                pair = []
        if pair:
            rows.append(pair)
        nav = []
        if has_prev:
            nav.append(KeyboardButton(MENU_BTN_PREV_PAGE))
        if has_next:
            nav.append(KeyboardButton(MENU_BTN_NEXT_PAGE))
        if nav:
            rows.append(nav)
        rows.append(self._streak_nav_row(back_step=True))
        try:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)
        except TypeError:
            return ReplyKeyboardMarkup(rows, resize_keyboard=True)

    def _streak_kind_inline(self):
        from buy_streak import KIND_BTN

        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(KIND_BTN["foreign"], callback_data="fb:k:foreign"),
                    InlineKeyboardButton(KIND_BTN["trust"], callback_data="fb:k:trust"),
                ],
                [InlineKeyboardButton(KIND_BTN["both"], callback_data="fb:k:both")],
                [InlineKeyboardButton("回主選單", callback_data="fb:home")],
            ]
        )

    def _streak_market_inline(self, kind: str):
        k = str(kind or "").strip() or "foreign"
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("上市", callback_data=f"fb:m:{k}:TW"),
                    InlineKeyboardButton("上櫃", callback_data=f"fb:m:{k}:TWO"),
                ],
                [
                    InlineKeyboardButton("上一步", callback_data="fb:back:kind"),
                    InlineKeyboardButton("回主選單", callback_data="fb:home"),
                ],
            ]
        )

    def _streak_days_inline(self, kind: str, market: str, days: list[int]):
        k = str(kind or "").strip()
        m = str(market or "").strip()
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
                InlineKeyboardButton("上一步", callback_data=f"fb:back:mkt:{k}"),
                InlineKeyboardButton("回主選單", callback_data="fb:home"),
            ]
        )
        return InlineKeyboardMarkup(rows)

    def _streak_pick_inline(self, rows_data):
        kb = []
        for item in rows_data:
            c = str(item.stock_id).strip()[:6]
            kb.append(
                [
                    InlineKeyboardButton(f"{c} {item.name}".strip()[:22], callback_data=f"k:{c}"),
                    InlineKeyboardButton("籌碼", callback_data=f"h:{c}"),
                ]
            )
        return InlineKeyboardMarkup(kb) if kb else None

    async def _streak_send_step(
        self, message, html: str, *, inline, reply_kb, tray_hint: str
    ) -> None:
        """精靈步驟：訊息下方 Inline（一定看得到）＋再掛 ReplyKeyboard（輸入區鍵盤）。

        Telegram 一則訊息只能帶一種 markup，所以拆兩則；桌面版常把 Reply 鍵盤收起，
        只靠 Reply 會以為「沒按鈕」。
        """
        await message.reply_html(html, reply_markup=inline, disable_web_page_preview=True)
        try:
            await message.reply_text(tray_hint, reply_markup=reply_kb)
        except Exception:
            logger.exception("連買精靈 ReplyKeyboard 補掛失敗")

    async def streak_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        actor = self._actor_key(update.message, uid=uid)
        self._pending.pop(actor, None)
        await self._dismiss_menu_transients(actor)
        await self._start_buy_streak(update.message, uid)

    async def _start_buy_streak(self, message, uid: str) -> None:
        actor = self._actor_key(message, uid=uid)
        self._pending[actor] = "fbuy:kind"
        await self._streak_send_step(
            message,
            "<b>連買區域</b>\n"
            "先選要看哪一種連買（點訊息下方按鈕）。\n"
            "• <b>外資</b>＝外資連續買超\n"
            "• <b>投信</b>＝投信連續買超\n"
            "• <b>外資+投信</b>＝同一天兩家都買超，再連起來算天數",
            inline=self._streak_kind_inline(),
            reply_kb=self._streak_kind_keyboard(),
            tray_hint="也可點輸入區鍵盤：外資／投信／外資+投信",
        )

    async def _restore_main_menu(self, message, uid: str) -> None:
        actor = self._actor_key(message, uid=uid)
        self._pending.pop(actor, None)
        await message.reply_html("已回到兩排主選單。", reply_markup=self._reply_menu())

    async def _ask_streak_market(self, message, uid: str, actor: str, kind: str) -> None:
        from buy_streak import KIND_LABEL

        self._pending[actor] = f"fbuy:mkt:{kind}"
        await self._streak_send_step(
            message,
            f"<b>{KIND_LABEL.get(kind, kind)}</b>\n請點下面按鈕選 <b>上市</b> 或 <b>上櫃</b>。",
            inline=self._streak_market_inline(kind),
            reply_kb=self._streak_market_keyboard(),
            tray_hint="也可點輸入區鍵盤：上市／上櫃",
        )

    async def _handle_buy_streak(
        self, message, uid: str, pending: str, text: str, *, actor: str
    ) -> bool:
        from buy_streak import (
            KIND_LABEL,
            MARKET_LABEL,
            PAGE_SIZE,
            find_row,
            format_list_html,
            format_stock_html,
            load_snapshot,
            page_bounds,
            parse_days,
            parse_kind,
            parse_market,
            parse_stock_code,
        )

        parts = (pending or "").split(":")
        if not parts or parts[0] != "fbuy":
            return False

        if text == MENU_BTN_BACK_MAIN:
            await self._restore_main_menu(message, uid)
            return True
        if text == MENU_BTN_BACK_STEP:
            step = parts[1] if len(parts) > 1 else "kind"
            if step in ("kind",):
                await self._start_buy_streak(message, uid)
            elif step == "mkt":
                await self._start_buy_streak(message, uid)
            elif step == "days":
                kind = parts[2] if len(parts) > 2 else ""
                await self._ask_streak_market(message, uid, actor, kind)
            elif step == "pick":
                kind = parts[2] if len(parts) > 2 else ""
                market = parts[3] if len(parts) > 3 else ""
                await self._streak_show_days(message, uid, actor, kind, market)
            else:
                await self._start_buy_streak(message, uid)
            return True

        step = parts[1] if len(parts) > 1 else "kind"
        if step == "kind":
            kind = parse_kind(text)
            if not kind:
                self._pending[actor] = "fbuy:kind"
                await self._streak_send_step(
                    message,
                    "請選 <b>外資</b>、<b>投信</b> 或 <b>外資+投信</b>。",
                    inline=self._streak_kind_inline(),
                    reply_kb=self._streak_kind_keyboard(),
                    tray_hint="也可點輸入區鍵盤：外資／投信／外資+投信",
                )
                return True
            await self._ask_streak_market(message, uid, actor, kind)
            return True

        if step == "mkt":
            kind = parts[2] if len(parts) > 2 else ""
            market = parse_market(text)
            if not market:
                await self._ask_streak_market(message, uid, actor, kind)
                return True
            await self._streak_show_days(message, uid, actor, kind, market)
            return True

        if step == "days":
            kind = parts[2] if len(parts) > 2 else ""
            market = parts[3] if len(parts) > 3 else ""
            days = parse_days(text)
            if days is None:
                self._pending[actor] = f"fbuy:days:{kind}:{market}"
                await self._streak_send_step(
                    message,
                    "請點天數（訊息下方或輸入區鍵盤）。",
                    inline=self._streak_days_inline(kind, market, []),
                    reply_kb=self._streak_days_keyboard([]),
                    tray_hint="也可點輸入區鍵盤上的天數",
                )
                return True
            await self._streak_show_stocks(message, uid, actor, kind, market, days, offset=0)
            return True

        if step == "pick":
            kind = parts[2] if len(parts) > 2 else ""
            market = parts[3] if len(parts) > 3 else ""
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
                if len(hits) == 1:
                    code = str(hits[0]["stock_id"])
            if not code:
                self._pending[actor] = f"fbuy:pick:{kind}:{market}:{days}:{offset}"
                await message.reply_html(
                    "請點鍵盤上的股票，或打代號。",
                    disable_web_page_preview=True,
                )
                return True
            snap = await asyncio.to_thread(load_snapshot, self.db_path, kind, market)
            row = find_row(snap, days, code)
            if row:
                recap = (
                    f"<b>{KIND_LABEL.get(kind, kind)} {days} 天 · "
                    f"{MARKET_LABEL.get(market, market)}</b>\n"
                    f"{format_stock_html(row, kind, self.db_path)}\n"
                    "下面是一般查股內容；按籌碼可核對官方法人表。"
                )
                await message.reply_html(
                    recap,
                    reply_markup=self._hub_keyboard(code),
                    disable_web_page_preview=True,
                )
            self._pending[actor] = f"fbuy:pick:{kind}:{market}:{days}:{offset}"
            await self._send_card_to(message, code, uid)
            return True

        return False

    async def _handle_buy_streak_callback(self, q, uid: str, data: str) -> None:
        """連買精靈 Inline 按鈕：訊息下方一定看得到，不依賴桌面版 Reply 鍵盤托盤。"""
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
        if op == "kind" or (op == "back" and len(parts) > 2 and parts[2] == "kind"):
            await self._start_buy_streak(q.message, uid)
            return
        if op == "back" and len(parts) > 2 and parts[2] == "mkt":
            kind = parts[3] if len(parts) > 3 else ""
            await self._ask_streak_market(q.message, uid, actor, kind)
            return
        if op == "k" and len(parts) > 2:
            kind = parts[2]
            if kind not in ("foreign", "trust", "both"):
                await self._start_buy_streak(q.message, uid)
                return
            await self._ask_streak_market(q.message, uid, actor, kind)
            return
        if op == "m" and len(parts) > 3:
            kind = parts[2]
            market = parts[3]
            if market not in ("TW", "TWO"):
                await self._ask_streak_market(q.message, uid, actor, kind)
                return
            await self._streak_show_days(q.message, uid, actor, kind, market)
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

    async def _streak_show_days(self, message, uid: str, actor: str, kind: str, market: str) -> None:
        from buy_streak import KIND_LABEL, MARKET_LABEL, load_snapshot

        status = await self._transient_status(message, "整理連買名單…")
        try:
            snap = await asyncio.wait_for(
                asyncio.to_thread(load_snapshot, self.db_path, kind, market),
                timeout=25.0,
            )
        except Exception as e:
            logger.exception("連買名單失敗 kind=%s market=%s", kind, market)
            await self._delete_message(status)
            await message.reply_html(
                f"連買名單讀取失敗：{html_escape(e)}",
                reply_markup=self._streak_market_inline(kind),
                disable_web_page_preview=True,
            )
            self._pending[actor] = f"fbuy:mkt:{kind}"
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
        if not days:
            await self._streak_send_step(
                message,
                f"<b>{KIND_LABEL.get(kind, kind)} · {MARKET_LABEL.get(market, market)}</b>\n"
                f"截至 {as_of_s}。目前沒有連續買超 2 天以上的股票。",
                inline=self._streak_market_inline(kind),
                reply_kb=self._streak_market_keyboard(),
                tray_hint="請改選上市／上櫃，或回主選單",
            )
            self._pending[actor] = f"fbuy:mkt:{kind}"
            return
        await self._streak_send_step(
            message,
            f"<b>{KIND_LABEL.get(kind, kind)} · {MARKET_LABEL.get(market, market)}</b>\n"
            f"截至 {as_of_s} 官方籌碼。目前最長 <b>{snap.max_days}</b> 天。\n"
            "請點下面天數（或輸入區鍵盤）；名單是「剛好連買這麼多天」（不是以上）。\n"
            f"<b>可選天數</b>（有股票才列出）：{' '.join(str(n) for n in days)}",
            inline=self._streak_days_inline(kind, market, days),
            reply_kb=self._streak_days_keyboard(days),
            tray_hint=f"可選天數：{' '.join(str(n) for n in days[:12])}"
            + (" …" if len(days) > 12 else ""),
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
        from buy_streak import PAGE_SIZE, format_list_html, load_snapshot, page_bounds

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
        await message.reply_html(
            html,
            reply_markup=self._streak_pick_inline(chunk),
            disable_web_page_preview=True,
        )
        await message.reply_text(
            "點上面股名或這排鍵盤看完整圖；籌碼可核對。",
            reply_markup=self._streak_stocks_keyboard(chunk, has_prev=has_prev, has_next=has_next),
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
                    InlineKeyboardButton("AI", callback_data="?:ai"),
                ],
                [
                    InlineKeyboardButton("第一排", callback_data="?:row1"),
                    InlineKeyboardButton("第二排", callback_data="?:row2"),
                    InlineKeyboardButton("記買入", callback_data="?:buy"),
                ],
                [InlineKeyboardButton("✕", callback_data="hx")],
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
        """不再附直立式「說明／主選單」——兩排鍵盤已有說明，重複會讓人按錯。"""
        return None

    def _hub_keyboard(self, code: str, topic: str = "stock"):
        """手機閱讀：每列最多三顆，常用放第一排。"""
        c = str(code).strip()[:6]
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("籌碼", callback_data=f"h:{c}"),
                    InlineKeyboardButton("營收", callback_data=f"f:{c}"),
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

    def _screening_section_keyboard(self, line_pack_id: str = None, include_menu: bool = False):
        """海選整區：一鍵生成每檔介紹圖／決策卡／籌碼／產業說明，再傳 LINE。"""
        rows = []
        if line_pack_id:
            rows.append(
                [InlineKeyboardButton("一鍵傳 LINE", callback_data=f"lp:{line_pack_id}")]
            )
        if include_menu:
            rows.append([self._q("screen")])
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
                rows.append([InlineKeyboardButton("傳 LINE", url=line_url)])
        tail = []
        if include_menu or rows:
            tail.append(self._q(topic))
        if tail:
            rows.append(tail)
        if not rows:
            return self._keyboard()
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

    def _ai_desk_keyboard(self):
        """AI 模擬倉專用鍵盤：不含真實持股賣出列，避免與手記持股混淆。"""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("AI操盤", callback_data="ai_run"),
                    self._q("ai"),
                ],
                [self._q("portfolio")],
            ]
        )

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

    def _parse_buy_text(self, text: str, code: str = "") -> tuple:
        """回傳 (code, lots, price) 或 (None, None, None)。"""
        parts = text.split()
        if not code and len(parts) >= 3:
            raw, lots_s, price_s = parts[0], parts[1], parts[2]
            hits = lookup_stocks(self.db_path, raw)
            code = hits[0]["stock_id"] if hits else raw
            try:
                return code, float(lots_s), float(price_s)
            except ValueError:
                return None, None, None
        lots, price = parse_lots_price(text, default_lots=1.0)
        if lots is None or price is None or not code:
            return None, None, None
        return code, lots, price

    def _parse_sell_text(self, text: str, code: str = "") -> tuple:
        """回傳 (code, lots, price)；lots=0 表示全賣。"""
        parts = text.split()
        if not code and len(parts) >= 3:
            raw, lots_s, price_s = parts[0], parts[1], parts[2]
            hits = lookup_stocks(self.db_path, raw)
            code = hits[0]["stock_id"] if hits else raw
            try:
                return code, float(lots_s), float(price_s)
            except ValueError:
                return None, None, None
        lots, price = parse_lots_price(text, price_only_sell_all=True)
        if price is None or not code:
            return None, None, None
        return code, float(lots or 0), price

    def _screening_payload(self, result: Dict[str, Any]) -> List[Dict[str, Any]]:
        from screening_engine import format_screening_payload

        parts = result.get("payload")
        if parts:
            return parts
        return format_screening_payload(
            result.get("results") or {}, result.get("as_of") or result.get("date") or ""
        )

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
        await message.reply_text("三段各有一顆鈕。按下去會開啟 LINE，再自己選要傳給誰。")
        for p in packs:
            await message.reply_text(
                p.get("text") or "",
                disable_web_page_preview=True,
                reply_markup=self._line_open_keyboard(p.get("id") or ""),
            )

    def _send_line_share(self, chat_id: str, result: Optional[Dict[str, Any]] = None):
        """保留三段整包稿（手動 fw:s）；日常海選改走每檔按鈕。"""
        if result is not None:
            self._remember_line_share(result)
        packs = self._load_line_share_packs()
        if not packs:
            return
        self._send_plain(chat_id, "整段夜盤／起漲／當沖稿（可選）：")
        for p in packs:
            self._send_plain(
                chat_id,
                p.get("text") or "",
                reply_markup=self._line_open_keyboard(p.get("id") or ""),
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
            fid = self._cat_sticker_id(part.get("mark_key") or "")
            if fid and callable(getattr(message, "reply_sticker", None)):
                try:
                    sticker_msg = await message.reply_sticker(sticker=fid)
                    self._track_screening_msg(actor, pack_id, sticker_msg)
                except Exception:
                    logger.exception("分類貼紙傳送失敗")
            chunks = chunk_telegram_html(part.get("html") or "", 3500)
            if not chunks:
                continue
            for j, chunk in enumerate(chunks):
                is_last_chunk = j == len(chunks) - 1
                is_last_part = i == last
                kb = self._screening_section_keyboard(
                    line_pack_id=part.get("line_pack_id") if is_last_chunk else None,
                    include_menu=is_last_part and is_last_chunk,
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
                payload["reply_markup"] = self._reply_menu().to_dict()
            requests.post(url, json=payload, timeout=20)
        except Exception as e:
            logger.error("send_html: %s", e)

    def _line_open_url(self, pack_id: str) -> str:
        from config import get_public_base_url

        return f"{get_public_base_url()}/line/{pack_id}"

    def _line_open_rows(self):
        from line_hop import LINE_PACKS

        return [
            [InlineKeyboardButton(label, url=self._line_open_url(pid))]
            for pid, label, _title in LINE_PACKS
        ]

    def _line_open_keyboard(self, pack_id: str = ""):
        from line_hop import LINE_PACKS

        if pack_id:
            for pid, label, _title in LINE_PACKS:
                if pid == pack_id:
                    return InlineKeyboardMarkup(
                        [[InlineKeyboardButton(label, url=self._line_open_url(pid))]]
                    )
        return InlineKeyboardMarkup(self._line_open_rows())

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
                is_last_chunk = j == len(chunks) - 1
                is_last_part = i == last
                kb = self._screening_section_keyboard(
                    line_pack_id=part.get("line_pack_id") if is_last_chunk else None,
                    include_menu=is_last_part and is_last_chunk,
                )
                self._send_html(
                    self.chat_id,
                    chunk,
                    extra_keyboard=kb,
                    attach_menu=False,
                )
            _t.sleep(0.25)
        if result.get("line_share_packs") or result.get("line_share"):
            self._remember_line_share(result)

    def _send_stock_card_by_code(self, chat_id: str, code: str, name: str = ""):
        if not code:
            return
        from wayne_navigator import generate_card_with_chart, generate_chart, generate_decision_card

        try:
            packed = generate_card_with_chart(code, self.db_path, self.charts_dir)
            html = packed[0]
            card_img = packed[1] if len(packed) > 1 else ""
            chart_path = packed[2] if len(packed) > 2 else ""
            glance = packed[3] if len(packed) > 3 else ""
        except Exception:
            html = generate_decision_card(code, self.db_path)
            card_img = ""
            chart_path = generate_chart(
                code,
                name,
                self.db_path,
                self._scratch_chart_path(self.charts_dir, code, "nav", str(chat_id)),
            )
            glance = ""
        if glance:
            cap = f"{html_escape(code)}"
            self._send_photo(chat_id, glance, caption=cap)
        for path in self._card_photo_paths(card_img):
            self._send_photo(chat_id, path, caption=f"{html_escape(code)} 高低決策卡")
        last_kb = self._hub_keyboard(code)
        if chart_path:
            self._send_photo(
                chat_id,
                chart_path,
                caption=f"{html_escape(code)} 高低導航：價格列20高／脫離／20低／60低；紫▲量能異常與紅▲警告只在量能列",
                reply_markup=last_kb,
            )
        elif glance:
            self._send_photo(chat_id, glance, caption=f"{html_escape(code)}", reply_markup=last_kb)
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
        uid = str(update.effective_user.id)
        self._touch_user(uid, getattr(update.effective_user, "first_name", "") or "")
        await update.message.reply_html(
            "<b>WayneBot</b>\n"
            "主選單在<b>輸入框右側 ⌨️</b>展開的兩排（不附在訊息最下面）。\n"
            "<b>第一次用？</b>先按第二排「說明」→ 總覽，或打 /help。\n"
            "盤中常看決策卡請按首排最左 <b>決策卡</b>（會記上一檔，再按就刷新）。\n"
            "看加權與 Regime 請按次排最右 <b>大盤</b>。\n"
            "打 <b>南亞</b> 或 <b>2324</b> 看單檔完整圖。左下也可按 /menu。\n"
            "次排 <b>連買區</b> 查外資／投信／兩家皆買。不熟按鈕請按 <b>說明</b>。",
        )
        await self._force_reply_menu(update.message, str(update.effective_user.id))

    async def menu_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        self._touch_user(uid, getattr(update.effective_user, "first_name", "") or "")
        await self._force_reply_menu(update.message, uid)

    async def help_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = str(update.effective_user.id)
        await self._enter_main_menu(update.message, uid)
        await self._reply_help_topic(update.message, "guide")

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
                "約需 2～5 分鐘，完成後會依序推送起漲／黃金買點等分類。\n"
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

    async def _send_line_rich_bucket(self, message, bucket_key: str):
        """起漲等：背景生成圖文包；完成後收起海選區塊與進度訊息，只留 LINE 鈕。"""
        from import_health import latest_complete_quote_date
        from line_rich_pack import (
            bucket_stock_rows,
            bucket_title,
            build_bucket_rich_pack,
            line_rich_hop_url,
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
                f"【{title}】尚無名單。請先按主選單「海選」，或等明早 06:30 自動推送。",
                reply_markup=hub,
            )
            return

        n = len(rows)
        # 進度泡泡不掛 ReplyKeyboard：完成後會刪，刪了兩排會跟著沒。
        status = await message.reply_text(
            f"正在背景生成【{title}】{n} 檔圖文…\n"
            "完成後會開 LINE 讓你選聯絡人；這裡的進度訊息會自動收起。"
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
        hop_url = line_rich_hop_url(bucket_key)
        line_btn = InlineKeyboardMarkup(
            [[InlineKeyboardButton("一鍵傳 LINE・選聯絡人", url=hop_url)]]
        )
        done_n = int(manifest.get("count") or 0)
        warn = ""
        errs = manifest.get("errors") or []
        if errs:
            warn = f"\n（{len(errs)} 檔略過：{html_escape(errs[0][:80])}）"

        # 收起海選該區塊＋生成進度（魔法消失）
        await self._dismiss_screening_section(actor, bucket_key)
        await self._dismiss_line_pack_status(actor)

        await message.reply_html(
            f"✅ <b>【{html_escape(title)}】</b>　{done_n} 檔已備好。{warn}\n"
            "按下方按鈕：\n"
            "① 開 LINE → <b>選聯絡人</b> → 送出文字總彙整\n"
            "② 同一頁下載全區長圖貼上（每檔文字後接圖表）",
            reply_markup=line_btn,
            disable_web_page_preview=True,
        )
        # Inline 鈕訊息無法同時掛 ReplyKeyboard；刪進度後再釘兩排。
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
        labels = {"glance": "介紹圖", "card": "決策卡", "chart": "導航圖", "table": "讀高低卡"}
        order = ("glance", "card", "chart")
        sent_ks = [str(k) for k in (sent or [])]
        elapsed = WayneTelegramBot._format_elapsed(elapsed_sec)
        now = labels.get(str(current or ""), "")
        if not now:
            now = next((labels[k] for k in order if k not in sent_ks), "出圖")
        done = [labels[k] for k in order if k in sent_ks]
        rest = [labels[k] for k in order if k not in sent_ks and labels[k] != now]
        lines = [f"查股進行中　已 {elapsed}", f"現在：{now}"]
        if done:
            lines.append("已送：" + "、".join(done))
        if rest:
            lines.append("接著：" + "、".join(rest))
        lines.append("順序：介紹圖 → 決策卡 → 導航圖")
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
        from screening_engine import _stock_card_html
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

        cards = [_stock_card_html(r, i + 1) for i, r in enumerate(rows)]
        head = f"<b>{title}</b>\n<i>{subtitle}</i>\n────────────────"
        if cards and live_skipped:
            body = (
                head
                + "\n<i>⚠️ 盤中 MIS 暫時無法複核，以下為昨收候選（請自行確認現價與漲幅）。</i>\n"
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
            is_tw_equity_session,
            overnight_list_heading,
            tw_session_phase,
        )

        uid = str(getattr(getattr(message, "from_user", None), "id", "") or "")
        # 進度泡泡不掛 ReplyKeyboard，否則 delete 時兩排主選單會被客戶端收掉。
        status = await message.reply_text(status_text)
        await self._enter_main_menu(message, uid)
        phase = tw_session_phase()
        display_title = title
        effective_live_bucket = live_bucket
        effective_subtitle = subtitle
        if live_bucket == "daytrade" and not is_tw_equity_session():
            try:
                await message.reply_html(
                    f"<b>{title}</b>\n<i>{daytrade_closed_message(phase)}</i>",
                    reply_markup=self._reply_menu(),
                )
            finally:
                try:
                    await status.delete()
                except Exception:
                    pass
            return
        if live_bucket == "overnight" and not is_tw_equity_session():
            effective_live_bucket = None
            display_title, effective_subtitle = overnight_list_heading(phase)
        try:
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
                        "請按主選單「海選」執行後再查；會用盤中 MIS 現價複核。</i>",
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
            subtitle="盤中 MIS 複核：只列此刻漲幅 2%～8.5% 的標的；現價旁小字＝報價時間。保險進≤昨收；+3% 先出一部分；+6% 衝頂；均價跌破先走。",
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
            subtitle="盤中 MIS 複核：只列此刻漲幅≥2.5% 的標的；現價旁小字＝報價時間。尾盤保險買進；明早開高+3.5～4.8%；防守跌破先走。",
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
                return format_taiwan_market_page_html(self.db_path, live=live, snap=snap), live

            html, live_quote = await asyncio.wait_for(asyncio.to_thread(_build), timeout=25.0)
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
                asyncio.to_thread(build_market_kline_chart, chart_path, live=live),
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
            await update.message.reply_text(
                "資金頁載入逾時（盤中 MIS 較慢），請 30 秒後再按一次「資金」。",
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
        if not args:
            await update.message.reply_text("用法：/chips 2330")
            return
        uid = str(update.effective_user.id)
        code = args[0].strip()
        chip_img = await asyncio.to_thread(
            generate_chips_image,
            code,
            self.db_path,
            self._scratch_chart_path(self.charts_dir, code, "chips", uid),
        )
        if chip_img:
            with open(chip_img, "rb") as f:
                await update.message.reply_photo(photo=f, caption="籌碼（張）", reply_markup=self._hub_keyboard(code))
        else:
            await update.message.reply_html("查無籌碼", reply_markup=self._keyboard())

    async def fund_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        args = context.args or []
        if not args:
            await update.message.reply_text("用法：/fund 2330")
            return
        from fundamentals import format_fundamentals_html

        # 按鈕／指令路徑只讀庫，不跑全市場 sync（那會卡死整機；交給盤後流水線）。
        code = args[0].strip()
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
        uid = str(update.effective_user.id)
        if len(args) < 3:
            await update.message.reply_text(
                "請輸入：代號 張數 價格\n例如：2330 1 500\n"
                "或先按「記買入」再打價格：68.5",
                reply_markup=self._keyboard(),
            )
            return
        code, lots, price = self._parse_buy_text(" ".join(args))
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
        code, lots, price = self._parse_sell_text(" ".join(args))
        if not code:
            code, lots, price = args[0], float(args[1]), float(args[2])
        msg = await asyncio.to_thread(record_sell, self.db_path, uid, code, lots, price)
        await update.message.reply_text(msg, reply_markup=self._keyboard())

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        raw_msg = update.message.text or ""
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
        if text == MENU_BTN_BACK_MAIN:
            await self._restore_main_menu(update.message, uid)
            return
        if text in (MENU_BTN_STREAK, "連買區域", "外資連買區域"):
            logger.info("主選單：連買區 uid=%s", uid)
            await self.streak_cmd(update, context)
            return
        if text in ("選單", "主選單") or text.lower().lstrip("/") == "menu":
            self._pending.pop(actor, None)
            await self.menu_cmd(update, context)
            return
        if text in ("說明", "幫助") or text.lower().lstrip("/") == "help":
            self._pending.pop(actor, None)
            await self.help_cmd(update, context)
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
            await self.flow_cmd(update, context)
            return
        if text == MENU_BTN_MARKET or text.lower().lstrip("/") == "market":
            logger.info("主選單：大盤 uid=%s", uid)
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
        if text == "決策卡":
            logger.info("主選單：決策卡 uid=%s", uid)
            await self.decision_card_btn(update, context)
            return
        if text == "海選":
            logger.info("主選單：海選 uid=%s", uid)
            self._pending.pop(actor, None)
            await self.screen_cmd(update, context)
            return
        if text == "持股":
            logger.info("主選單：持股 uid=%s", uid)
            await self.portfolio_cmd(update, context)
            return
        if text == "觀察":
            logger.info("主選單：觀察 uid=%s", uid)
            await self.watch_cmd(update, context)
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
            pending = self._pending.pop(actor, "")
            if pending in ("card", "dcard", "chips", "fund", "industry", "watch"):
                handled = await self._handle_pending_pick(update.message, uid, pending, text, actor=actor)
                if handled:
                    return
            if pending == "sell" or pending.startswith("sell:"):
                code = pending.split(":", 1)[1] if pending.startswith("sell:") else ""
                parsed_code, lots, price = self._parse_sell_text(text, code)
                if parsed_code is None:
                    self._pending[actor] = pending or "sell"
                    await update.message.reply_text(
                        "請輸入：價格（全賣）　例如：72\n或：張數 價格　例如：1 72\n"
                        "也可：代號 張數 價格　例如：2330 1 520",
                        reply_markup=self._keyboard(),
                    )
                    return
                msg = await asyncio.to_thread(
                    record_sell, self.db_path, uid, parsed_code, lots, price
                )
                await update.message.reply_text(msg, reply_markup=self._keyboard())
                return
            if pending == "buy" or pending.startswith("buy:"):
                code = pending.split(":", 1)[1] if pending.startswith("buy:") else ""
                parsed_code, lots, price = self._parse_buy_text(text, code)
                if parsed_code is None:
                    self._pending[actor] = pending or "buy"
                    await update.message.reply_text(
                        "請輸入：價格（1張）　例如：68.5\n或：張數 價格　例如：2 68.5\n"
                        "也可：代號 張數 價格　例如：2330 1 500",
                        reply_markup=self._keyboard(),
                    )
                    return
                hits = lookup_stocks(self.db_path, parsed_code)
                name = hits[0]["stock_name"] if hits else parsed_code
                msg = await asyncio.to_thread(
                    record_buy, self.db_path, uid, parsed_code, name, lots, price
                )
                await update.message.reply_text(msg, reply_markup=self._keyboard())
                return
        logger.info("收到文字 uid=%s 字數=%s", uid, len(text))
        try:
            hits = lookup_stocks(self.db_path, text)
            if len(hits) == 1:
                code = str(hits[0]["stock_id"])
                logger.info("名稱查詢命中 %s -> %s", text, code)
                await self._reply_card(update, code)
                return
            if len(hits) > 1:
                await update.message.reply_html(
                    self._hits_list_html(hits),
                    reply_markup=self._hits_keyboard(hits),
                    disable_web_page_preview=True,
                )
                return
            await update.message.reply_text(
                "找不到這檔。請打代號或名稱（如 南亞、2330）。",
                reply_markup=self._keyboard(),
            )
        except Exception:
            logger.exception("查詢失敗")
            await update.message.reply_text(
                "查詢失敗。雲端可能還沒有日K，或出圖逾時。請先按 /start，稍後再試。",
                reply_markup=self._keyboard(),
            )

    async def _handle_pending_pick(
        self, message, uid: str, pending: str, text: str, *, actor: str = ""
    ) -> bool:
        actor = actor or self._pending_actor(message, uid=uid)
        hits = lookup_stocks(self.db_path, text.split()[0].strip())
        if not hits:
            self._pending[actor] = pending
            await message.reply_text("找不到這檔。請打南亞或 2330。", reply_markup=self._keyboard())
            return True
        if len(hits) > 1:
            self._pending[actor] = pending
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
        self._touch_user(uid)
        try:
            html = await asyncio.to_thread(format_ai_desk_html, self.portfolio_engine, uid)
            parts = chunk_telegram_html(html)
            for i, part in enumerate(parts):
                kb = self._ai_desk_keyboard() if i == len(parts) - 1 else None
                await message.reply_html(part, reply_markup=kb, disable_web_page_preview=True)
        except Exception as e:
            logger.exception("AI 模擬倉顯示失敗")
            await message.reply_text(f"AI 模擬倉顯示失敗：{e}", reply_markup=self._keyboard())

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
                    f"<i>本次沒有新成交（候選 {ai.get('candidates') or 0} 檔）。已滿 3 檔或名單被高低卡／美股濾掉。</i>"
                )
            if ai.get("bought"):
                bits.append("<b>本次買進</b>\n" + "\n".join(html_escape(x) for x in ai["bought"]))
            if ai.get("sold"):
                bits.append("<b>本次賣出</b>\n" + "\n".join(html_escape(x) for x in ai["sold"]))
            if ai.get("lesson"):
                bits.append("進化：" + html_escape(ai["lesson"]))
            parts = chunk_telegram_html("\n\n".join(bits))
            for i, part in enumerate(parts):
                kb = self._ai_desk_keyboard() if i == len(parts) - 1 else None
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
                        html_escape(f"收盤　{t}　Yahoo（16:30 融合後以官方庫為準）")
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
        live_rt = await asyncio.to_thread(self._prefetch_mis_quote, code, hits)
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

                        attach_main_cost(card, self.db_path, fetch=True)
                    except Exception:
                        pass
                    card.pop("_ohlc", None)
                return card

            card = await asyncio.wait_for(asyncio.to_thread(_build_card), timeout=20)
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
                timeout=25,
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
                            generated_at=card.get("generated_at") or card.get("live_time"),
                        )
                    live_note = f"（{clock_line}）" if clock_line else "（盤中即時）"
                with open(card_path, "rb") as f:
                    await message.reply_photo(
                        photo=f,
                        caption=_photo_sell_caption(f"高低決策卡{live_note}", card, fallback="高低決策卡"),
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
        hub = self._hub_keyboard(code)
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
        cap = "180日高低導航：實心＝當日觸發；空心＝接近；粉紅／綠底上的箭頭會自動加深"
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
        hub = self._hub_keyboard(code)
        cap_links = ""
        try:
            from stock_links import yahoo_urls

            web, mobile = yahoo_urls(code, self.db_path)
            cap_links = f'<a href="{web}">網頁走勢</a>　<a href="{mobile}">技術線</a>'
        except Exception:
            cap_links = ""

        live_rt = await asyncio.to_thread(self._prefetch_mis_quote, code, hits)

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
                        logger.exception("送圖失敗 kind=%s path=%s attempt=%s", kind, path, attempt + 1)
            return False

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

        sent_any = False
        hub_on = False

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
                generate_chart,
                render_decision_card_png,
                render_first_glance_png,
            )

            def _build_card():
                engine = NavigatorEngine(self.db_path)
                card = engine.get_decision_card(
                    code, lookback=20, merge_live=True, live_quote=live_rt
                )
                if isinstance(card, dict):
                    try:
                        from broker_points import attach_main_cost

                        attach_main_cost(card, self.db_path, fetch=True)
                    except Exception:
                        pass
                ohlc = card.pop("_ohlc", None) if isinstance(card, dict) else None
                return card, ohlc

            def _build_tape():
                try:
                    return build_tape(
                        self.db_path, code, merge_live=True, live_quote=live_rt
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
                await message.reply_html(
                    f"⚠️ {html_escape(card.get('error'))}",
                    reply_markup=hub,
                    disable_web_page_preview=True,
                )
                return
            os.makedirs(self.charts_dir, exist_ok=True)
            uid_key = uid or self._uid_from_message(message)
            req_tag = f"{uid_key or '0'}_{int(time.time() * 1000)}"
            glance_path = os.path.join(self.charts_dir, f"{code}_glance_{req_tag}.png")
            card_path_f = os.path.join(self.charts_dir, f"{code}_card_{req_tag}.png")
            chart_path_f = os.path.join(self.charts_dir, f"{code}_{req_tag}.png")
            ohlc = card.get("_ohlc")
            card.pop("_ohlc", None)
            self._cache_lookup_ctx(uid_key, code, ohlc)

            def _render_chart():
                return generate_chart(
                    code, "", self.db_path, chart_path_f, ohlc, already_normalized=True
                )

            def _render_glance():
                return render_first_glance_png(code, card, tape, glance_path, self.db_path)

            glance_cap = _glance_photo_caption(cap_links or "當日K＋籌碼價量", card)
            card_cap = _photo_sell_caption("高低決策卡", card, fallback="高低決策卡")
            render_plan = [
                ("glance", _render_glance, _LOOKUP_PNG_TIMEOUT, glance_cap, None),
                ("card", lambda: render_decision_card_png(card, card_path_f), _LOOKUP_PNG_TIMEOUT, card_cap, None),
                (
                    "chart",
                    _render_chart,
                    _CHART_RENDER_TIMEOUT,
                    "180日高低導航：實心＝當日觸發；空心＝接近；粉紅／綠底上的箭頭會自動加深",
                    hub,
                ),
            ]
            kind_labels = {"glance": "介紹圖", "card": "決策卡", "chart": "導航圖"}
            sent_kinds: list[str] = []

            # 畫完一張就先送；進度泡泡跟階段走，第一張送出也不刪，等人看到三張齊。
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
                if not path:
                    gc.collect()
                    continue
                ok = await send_photo(path, caption, markup, kind=kind)
                if ok and markup is hub:
                    hub_on = True
                if ok:
                    sent_any = True
                    sent_kinds.append(kind)
                    st = self._op_state_map().setdefault(actor, {"sent": [], "current": ""})
                    st["sent"] = list(sent_kinds)
                    st["current"] = ""
                    logger.info("查股階段已送 %s code=%s", sent_kinds, code)
                    if wait_msg is not None:
                        nxt = next((k for k, *_ in render_plan if k not in sent_kinds), "")
                        st["current"] = nxt
                        try:
                            await wait_msg.edit_text(
                                self._chart_progress_text(
                                    int(time.monotonic() - op_t0),
                                    sent=sent_kinds,
                                    current=nxt,
                                )
                            )
                        except Exception:
                            pass
                gc.collect()

            if sent_any and not hub_on:
                if len(sent_kinds) >= len(render_plan):
                    done_txt = "點縮圖可放大。籌碼／產業／觀察按這排。"
                else:
                    miss = [kind_labels[k] for k, *_ in render_plan if k not in sent_kinds]
                    done_txt = (
                        f"已送 {len(sent_kinds)}/{len(render_plan)} 張"
                        f"（缺：{'、'.join(miss)}）。請再打一次代號補圖。"
                    )
                await message.reply_html(done_txt, reply_markup=hub, disable_web_page_preview=True)
            elif not sent_any:
                from wayne_navigator import generate_decision_card

                html = await asyncio.to_thread(generate_decision_card, code, self.db_path)
                await message.reply_html(
                    f"圖片產出失敗，改送文字版（{html_escape(code)}）。\n{html}",
                    reply_markup=hub,
                    disable_web_page_preview=True,
                )
                if not lookup_faded:
                    lookup_faded = True
                    await self._dismiss_lookup_fades(actor)
        except asyncio.TimeoutError:
            logger.exception("看這檔出圖逾時 code=%s", code)
            if not sent_any:
                await message.reply_html(
                    "圖產製逾時（雲端較慢或剛醒機）。請再打一次 2454；"
                    "若仍卡住請回報。",
                    reply_markup=hub,
                    disable_web_page_preview=True,
                )
            else:
                await message.reply_html("後面的圖逾時。可用下面按鈕繼續。", reply_markup=hub, disable_web_page_preview=True)
        except Exception:
            logger.exception("看這檔出圖失敗 code=%s", code)
            if not sent_any:
                try:
                    from wayne_navigator import generate_decision_card

                    html = await asyncio.to_thread(generate_decision_card, code, self.db_path)
                except Exception:
                    html = f"查詢 {html_escape(code)} 失敗。"
                await message.reply_html(html, reply_markup=hub, disable_web_page_preview=True)
        finally:
            progress_stop.set()
            if progress_task is not None:
                progress_task.cancel()
            await _clear_wait()
            await self._dismiss_lookup_fades(actor, roles={"ack", "wait", "header"})
            self._op_state_map().pop(actor, None)
        uid = uid or self._uid_from_message(message)
        self._remember_card(uid, code)
        try:
            await self._pin_reply_menu(message)
        except Exception:
            logger.debug("查股後重釘主選單失敗", exc_info=True)

    async def _send_lookup_album(self, message, items: list) -> bool:
        """三張一次送，Telegram 會顯示一張大圖＋縮圖，不佔三則訊息。"""
        from telegram import InputMediaPhoto

        if len(items) < 2:
            return False
        handles = []
        try:
            media = []
            first_cap = str(items[0][2] or "").strip()
            album_cap = "介紹／決策／導航　點縮圖可放大"
            if first_cap:
                album_cap = f"{first_cap}\n{album_cap}"
            for kind, path, _caption, _markup in items:
                min_h = 900 if kind == "chart" else 500
                if not self._png_looks_ok(path, min_h=min_h):
                    continue
                fh = open(path, "rb")
                handles.append(fh)
                if not media:
                    media.append(
                        InputMediaPhoto(media=fh, caption=album_cap[:1024], parse_mode="HTML")
                    )
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
        self._touch_user(uid, getattr(q.from_user, "first_name", "") or "")
        data = q.data or ""
        if data.startswith("cat:") or data.startswith("noop"):
            hints = {
                "revenue_cross": "優先看：營收轉強 × 量價突破",
                "leave_zero": "起漲：獲利格剛離零且趨勢向上（按表，不是每個紅箭頭低點）",
                "golden_buy": "黃金買點：60低超跌觀察（按表操課，不是今天必買）",
                "select_01": "周帶量：短線轉強，貼月高少追",
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
            await self._send_card_to(q.message, data[2:], uid)
            return
        if data.startswith("h:"):
            code = data[2:].strip()
            uid = str(q.from_user.id)
            chip_img = await asyncio.to_thread(
                generate_chips_image,
                code,
                self.db_path,
                self._scratch_chart_path(self.charts_dir, code, "chips", uid),
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
            from fundamentals import format_fundamentals_html

            code = data[2:].strip()
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
            actor = self._actor_key(q.message, uid=uid)
            self._pending[actor] = f"buy:{code}"
            await q.message.reply_text(
                f"記買入 {code}。請輸入：價格（1張）\n例如：68.5 或 2 68.5",
                reply_markup=self._keyboard(),
            )
            return
        if data.startswith("x:"):
            uid = str(q.from_user.id)
            code = data[2:].strip()
            actor = self._actor_key(q.message, uid=uid)
            self._pending[actor] = f"sell:{code}"
            lots = None
            try:
                from wayne_db import get_user_portfolio

                for h in get_user_portfolio(self.db_path, uid) or []:
                    if str(h.get("stock_code") or h.get("stock_id") or "") == code:
                        lots = float(h.get("shares") or 0)
                        break
            except Exception:
                lots = None
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
        if data == "screen":
            await self._run_manual_screening(q.message)
        elif data == "daytrade":
            await self._run_trade_bucket(
                q.message,
                bucket_key="day_trade",
                live_bucket="daytrade",
                title="⚡ 當沖候選（盤中即時）",
                subtitle="盤中 MIS 複核：只列此刻漲幅 2%～8.5% 的標的；現價旁小字＝報價時間。保險進≤昨收；+3% 先出一部分；+6% 衝頂；均價跌破先走。",
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
                subtitle="盤中 MIS 複核：只列此刻漲幅≥2.5% 的標的；現價旁小字＝報價時間。尾盤保險買進；明早開高+3.5～4.8%；防守跌破先走。",
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
                    [
                        BotCommand("menu", "回到主選單（下方兩排）"),
                        BotCommand("market", "大盤指數與風險"),
                        BotCommand("start", "開始"),
                        BotCommand("help", "使用說明"),
                        BotCommand("screen", "海選"),
                        BotCommand("portfolio", "持股"),
                        BotCommand("watch", "觀察"),
                        BotCommand("flow", "資金移動"),
                        BotCommand("industry", "產業說明"),
                    ]
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
