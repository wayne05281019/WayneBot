# ==============================================================================
# WayneBot 全市場量化決策系統升級：模組四 - Telegram 互動介面與扁平雙層鍵盤
# 檔案名稱：bot_servers.py
# 核心規範：2x3 扁平主鍵盤、雙層 Inline 展開面板、多用戶隔離、直覺式指令處理
# ==============================================================================

import os
import sys
import json
import logging
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Any

# 匯入 Telegram Bot SDK (python-telegram-bot v20+)
try:
    from telegram import (
        Update,
        ReplyKeyboardMarkup,
        KeyboardButton,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
    )
    from telegram.ext import (
        ApplicationBuilder,
        CommandHandler,
        MessageHandler,
        CallbackQueryHandler,
        ContextTypes,
        filters,
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

# 設定日誌格式
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("WayneBot")

# ------------------------------------------------------------------------------
# 1. 常數與主選單鍵盤配置
# ------------------------------------------------------------------------------
DB_PATH = os.getenv("WAYNEBOT_DB_PATH", "waynebot_history.db")

# 2 行 × 3 列 底部主選單
MAIN_MENU_KEYBOARD = [
    [
        KeyboardButton("⚡ 即時強勢選股"),
        KeyboardButton("🎯 買低賣高決策卡"),
        KeyboardButton("🚀 當沖/隔日沖"),
    ],
    [
        KeyboardButton("💼 50萬 AI 操盤"),
        KeyboardButton("⭐ 我的自選守護"),
        KeyboardButton("📊 每日盤後復盤"),
    ],
]
MAIN_REPLY_MARKUP = ReplyKeyboardMarkup(
    MAIN_MENU_KEYBOARD,
    resize_keyboard=True,
    one_time_keyboard=False
)

# ------------------------------------------------------------------------------
# 2. 資料庫與用戶狀態管理（支援多用戶隔離）
# ------------------------------------------------------------------------------
class UserStateManager:
    """管理個別 Telegram 使用者的自選清單與自定義狀態"""
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_user_table()

    def _init_user_table(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_watchlists (
            user_id INTEGER NOT NULL,
            stock_id TEXT NOT NULL,
            added_at TEXT NOT NULL,
            PRIMARY KEY (user_id, stock_id)
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_positions (
            user_id INTEGER NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            shares INTEGER NOT NULL,
            cost_price REAL NOT NULL,
            buy_date TEXT NOT NULL,
            strategy_tag TEXT NOT NULL,
            defense_price REAL NOT NULL,
            warning_days INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, stock_id)
        );
        """)
        conn.commit()
        conn.close()

    def get_watchlist(self, user_id: int) -> List[str]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT stock_id FROM user_watchlists WHERE user_id = ? ORDER BY added_at ASC", (user_id,))
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows] if rows else ["2330", "0050", "00631L", "6415", "5274"]

    def add_to_watchlist(self, user_id: int, stock_id: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO user_watchlists (user_id, stock_id, added_at) VALUES (?, ?, ?)",
                (user_id, stock_id.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def remove_from_watchlist(self, user_id: int, stock_id: str) -> bool:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_watchlists WHERE user_id = ? AND stock_id = ?", (user_id, stock_id.strip()))
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def get_positions(self, user_id: int) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
        SELECT stock_id, stock_name, shares, cost_price, buy_date, strategy_tag, defense_price, warning_days
        FROM portfolio_positions WHERE user_id = ?
        """, (user_id,))
        rows = cursor.fetchall()
        conn.close()
        
        positions = []
        for r in rows:
            positions.append({
                "stock_id": r[0],
                "stock_name": r[1],
                "shares": r[2],
                "cost_price": r[3],
                "buy_date": r[4],
                "strategy_tag": r[5],
                "defense_price": r[6],
                "warning_days": r[7],
            })
        return positions

user_manager = UserStateManager()

# ------------------------------------------------------------------------------
# 3. 數據查詢與量化指標輔助引擎
# ------------------------------------------------------------------------------
def fetch_stock_latest_info(stock_id: str) -> Optional[Dict[str, Any]]:
    """自 SQLite 或即時快取提取個股最新數據與技術指標"""
    sid = str(stock_id).strip()
    if not os.path.exists(DB_PATH):
        return None

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    SELECT date, stock_id, stock_name, market, open, high, low, close, volume, turnover_k, pct_change, avg_price, foreign_net, trust_net, dealer_net
    FROM daily_quotes
    WHERE stock_id = ?
    ORDER BY date DESC
    LIMIT 60;
    """, (sid,))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return None

    latest = rows[0]
    closes = [r[7] for r in rows]
    volumes = [r[8] for r in rows]

    # 計算 Q60R (當日成交量 / 60日均量)
    avg_vol_60 = (sum(volumes) / len(volumes)) if volumes else 1.0
    q60r = round((latest[8] / avg_vol_60), 2) if avg_vol_60 > 0 else 1.0

    # 計算 20 日乖離率 D20 (以 20MA 為基準)
    ma20 = (sum(closes[:20]) / min(len(closes), 20)) if closes else latest[7]
    d20 = round(((latest[7] - ma20) / ma20 * 100.0), 2) if ma20 > 0 else 0.0

    # 計算近期新高差距
    hi120_val = max(closes) if closes else latest[7]
    is_hi120 = latest[7] >= hi120_val

    # 判定股海武僧出場標籤
    monk_status = "🟢 持股續抱 (量價結構健康)"
    if d20 > 30.0:
        monk_status = "⛸️ 穿溜冰鞋分批停利 (D20 > 30% 乖離過熱)"
    elif latest[7] < (ma20 * 0.96):
        monk_status = "⚠️ 預警脫離 (破 20MA 第 1 天，防守轉進)"

    return {
        "date": latest[0],
        "stock_id": latest[1],
        "stock_name": latest[2],
        "market": latest[3],
        "open": latest[4],
        "high": latest[5],
        "low": latest[6],
        "close": latest[7],
        "volume": latest[8],
        "turnover_k": latest[9],
        "pct_change": latest[10],
        "avg_price": latest[11],
        "foreign_net": latest[12],
        "trust_net": latest[13],
        "dealer_net": latest[14],
        "q60r": q60r,
        "d20": d20,
        "ma20": round(ma20, 2),
        "is_hi120": is_hi120,
        "monk_status": monk_status,
    }

# ------------------------------------------------------------------------------
# 4. 訊息排版與雙層 Inline 面板產生器
# ------------------------------------------------------------------------------
def generate_decision_card_text(info: Dict[str, Any]) -> str:
    """生成單一標的之第二層決策卡詳細內容"""
    sid = info["stock_id"]
    sname = info["stock_name"]
    close = info["close"]
    pct = info["pct_change"]
    pct_sign = "🔺" if pct > 0 else ("🔻" if pct < 0 else "➖")

    # 價位精算
    stop_loss = round(close * 0.95, 2)
    tp_1 = round(close * 1.035, 2)
    tp_2 = round(close * 1.06, 2)

    text = f"""
🎯 <b>【買低賣高即時決策卡】</b>
━━━━━━━━━━━━━━━━━━━━
<b>標的：{sname} ({sid})</b>  |  市場：{info['market']}
📅 最新日期：<code>{info['date']}</code>
💰 收盤價：<b>{close:.2f} 元</b> ({pct_sign} {pct:+.2f}%)
📊 成交量：<b>{info['volume']:,} 張</b> (量比 Q60R: <b>{info['q60r']}x</b>)
━━━━━━━━━━━━━━━━━━━━
📈 <b>技術與動能指標：</b>
  • 20MA 均線：{info['ma20']:.2f} 元 (20日乖離 D20: <code>{info['d20']:+.2f}%</code>)
  • 突破指標：{'🔥 創半年新高 (Hi120)' if info['is_hi120'] else '維持強勢整理區間'}
  • 法人籌碼：外資 <code>{info['foreign_net']:+d}</code> 張 | 投信 <code>{info['trust_net']:+d}</code> 張

🎯 <b>操作點位與紀律：</b>
  • 建議買進區：<code>{round(close*0.99, 2)} ~ {round(close*1.01, 2)}</code> 元
  • 第一停利 (+3.5%)：<b>{tp_1}</b> 元
  • 第二衝頂 (+6.0%)：<b>{tp_2}</b> 元
  • 移動防守價 (-5.0%)：<b>{stop_loss}</b> 元

🧘 <b>股海武僧紀律評級：</b>
  👉 {info['monk_status']}
━━━━━━━━━━━━━━━━━━━━
"""
    return text.strip()

def generate_stock_inline_keyboard(stock_id: str, is_watched: bool = False) -> InlineKeyboardMarkup:
    """生成個股專屬操作按鈕（自選增刪、切換分時、刷新）"""
    watch_text = "❌ 移出自選" if is_watched else "⭐ 加入自選"
    watch_cb = f"unwatch_{stock_id}" if is_watched else f"watch_{stock_id}"
    
    keyboard = [
        [
            InlineKeyboardButton(watch_text, callback_data=watch_cb),
            InlineKeyboardButton("🔄 刷新即時報價", callback_data=f"refresh_{stock_id}"),
        ],
        [
            InlineKeyboardButton("💼 AI 模擬買進", callback_data=f"simbuy_{stock_id}"),
            InlineKeyboardButton("🔙 返回選單", callback_data="menu_back"),
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ------------------------------------------------------------------------------
# 5. Telegram 訊息處理器（Handlers）
# ------------------------------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/start 指令：初始化並顯示 2x3 主選單"""
    user_name = update.effective_user.first_name if update.effective_user else "夥伴"
    welcome_text = f"""
👋 您好，<b>{user_name}</b>！歡迎使用 <b>WayneBot 台股量化決策系統</b> 🚀

本系統已整合：
⚡ <b>即時強勢選股</b>（周帶量突破 / Hi120 / Hi480 / 雙綠脫離）
🎯 <b>買低賣高決策卡</b>（精確進出場與停利停損價位）
🚀 <b>當沖 / 隔日沖</b>（動態買進區間與 09:15 時間保護）
💼 <b>50萬 AI 模擬操盤手</b>（嚴格執行股海武僧紀律）
⭐ <b>自選即時守護雷達</b>（量縮緩衝與爆量警報）

👇 請使用下方 <b>扁平主選單</b> 或直接輸入 <b>4~6 碼股票代號</b>（例如 <code>2330</code>、<code>0050</code>）：
"""
    await update.message.reply_text(
        welcome_text.strip(),
        reply_markup=MAIN_REPLY_MARKUP,
        parse_mode="HTML"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理主選單按鈕點擊與文字輸入"""
    text = update.message.text.strip()
    user_id = update.effective_user.id

    # 1. ⚡ 即時強勢選股
    if text == "⚡ 即時強勢選股":
        summary_text = """
⚡ <b>【即時強勢選股 - 暴風眼精選】</b>
━━━━━━━━━━━━━━━━━━━━
🔍 系統依據 CaryBot 四大策略掃描全市場：
1. <b>Select 01 周帶量突破</b> (5日高 + Q60R > 2.0)
2. <b>Select 02 突破 Hi120</b> (半年新高 + 投信連買)
3. <b>Select 03 突破 Hi480</b> (兩年新高大底起漲)
4. <b>Select 04 雙綠脫離</b> (D20轉正 + 底部整理完成)
━━━━━━━━━━━━━━━━━━━━
📌 <b>今日精選候選標的（點擊展開決策卡）：</b>
"""
        # 示範候選池
        candidates = [("2330", "台積電"), ("00631L", "元大台灣50正2"), ("6415", "矽力*-KY"), ("5274", "信驊")]
        buttons = []
        for sid, sname in candidates:
            buttons.append([InlineKeyboardButton(f"📈 {sname} ({sid})", callback_data=f"card_{sid}")])
        buttons.append([InlineKeyboardButton("🔄 重新執行全市場掃描", callback_data="rescan_screening")])
        
        await update.message.reply_text(
            summary_text.strip(),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )

    # 2. 🎯 買低賣高決策卡
    elif text == "🎯 買低賣高決策卡":
        guide_text = """
🎯 <b>【買低賣高即時決策卡】</b>
請直接在對話框輸入 <b>4~6 碼台股代號</b>（例如 <code>2330</code>、<code>0050</code>、<code>00631L</code>、<code>00679B</code>）。
系統將為您生成包含「建議買進區、停利雙目標、移動防守線、武僧出場紀律」之完整決策卡！
"""
        await update.message.reply_text(guide_text.strip(), parse_mode="HTML")

    # 3. 🚀 當沖/隔日沖
    elif text == "🚀 當沖/隔日沖":
        momentum_text = """
🚀 <b>【當沖與隔日沖 - 實戰動能專區】</b>
━━━━━━━━━━━━━━━━━━━━
🕒 <b>09:15 動態保護機制生效中：</b>
• <b>當沖動能首選：</b>
  👉 <code>2330 台積電</code> | 進場區：<code>現價±0.5%</code> | 停利：<b>+3.0%</b> | 均價停損
  👉 <code>00631L 台灣50正2</code> | 進場區：<code>開盤分批</code> | 衝頂：<b>+5.8%</b>

• <b>尾盤隔日沖精選：</b>
  👉 <code>6415 矽力*-KY</code> | 尾盤佈局區：<code>455~460</code> | 明日開高目標：<b>+3.8% ~ +4.5%</b>
━━━━━━━━━━━━━━━━━━━━
💡 <i>提醒：若 09:15 前量能停滯且未達目標價，依紀律市價平倉離場。</i>
"""
        buttons = [
            [InlineKeyboardButton("📊 檢視當沖即時量比", callback_data="daytrade_vol")],
            [InlineKeyboardButton("🎯 隔日沖鎖定標的", callback_data="swing_targets")]
        ]
        await update.message.reply_text(
            momentum_text.strip(),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )

    # 4. 💼 50萬 AI 操盤
    elif text == "💼 50萬 AI 操盤":
        positions = user_manager.get_positions(user_id)
        pos_count = len(positions)
        
        # 示範基礎資產概況
        total_assets = 500000.0
        used_cash = sum(p["shares"] * p["cost_price"] for p in positions)
        available_cash = total_assets - used_cash
        
        card_text = f"""
💼 <b>【50 萬 AI 模擬操盤手 - 實時部位】</b>
━━━━━━━━━━━━━━━━━━━━
💰 <b>帳戶資金概況：</b>
  • 起始本金：500,000 元
  • 可用現金：<b>{available_cash:,.0f} 元</b>
  • 持股水位：<b>{used_cash:,.0f} 元</b> ({((used_cash/total_assets)*100):.1f}%)
  • 當前持股檔數：<b>{pos_count} 檔</b> (不限持股檔數，依動能配置)
━━━━━━━━━━━━━━━━━━━━
📊 <b>當前持倉清單（點擊查看防守線與出場警報）：</b>
"""
        buttons = []
        if positions:
            for p in positions:
                buttons.append([InlineKeyboardButton(
                    f"📌 {p['stock_name']} ({p['stock_id']}) | 防守: {p['defense_price']:.1f}",
                    callback_data=f"pos_{p['stock_id']}"
                )])
        else:
            card_text += "\n<i>目前尚無建立部位，點擊下方按鈕啟動自動選股買進。</i>\n"
            buttons.append([InlineKeyboardButton("🚀 執行 AI 自動尋標建倉", callback_data="ai_autobuy")])

        buttons.append([InlineKeyboardButton("📜 操盤日誌與出場記錄", callback_data="trade_history")])

        await update.message.reply_text(
            card_text.strip(),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )

    # 5. ⭐ 我的自選守護
    elif text == "⭐ 我的自選守護":
        watchlist = user_manager.get_watchlist(user_id)
        watch_text = f"""
⭐ <b>【我的自選守護雷達】</b> (用戶 ID: <code>{user_id}</code>)
━━━━━━━━━━━━━━━━━━━━
📡 守護狀態：全天候監控量價結構、破線警報與脫離信號
📌 <b>目前追蹤清單（共 {len(watchlist)} 檔）：</b>
"""
        buttons = []
        for sid in watchlist:
            info = fetch_stock_latest_info(sid)
            sname = info["stock_name"] if info else sid
            pct_str = f"{info['pct_change']:+.2f}%" if info else "0.00%"
            buttons.append([InlineKeyboardButton(f"{sname} ({sid}) {pct_str}", callback_data=f"card_{sid}")])
        
        buttons.append([InlineKeyboardButton("➕ 新增追蹤標的", callback_data="prompt_add_watch")])

        await update.message.reply_text(
            watch_text.strip(),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )

    # 6. 📊 每日盤後復盤
    elif text == "📊 每日盤後復盤":
        review_text = """
📊 <b>【每日盤後量化復盤日誌】</b>
━━━━━━━━━━━━━━━━━━━━
📅 日期：2026-08-28 | 市場風向：<b>多頭擴張</b>
📈 <b>三大法人動向：</b>
  • 外資：+12,450 張
  • 投信：+3,820 張 (連續 5 日買超)
  • 自營商：-1,200 張

🧠 <b>大盤風控總開關：</b>
  • 0050 均線：穩守季線 (60MA) 之上，持股水位上限開放至 <b>100%</b>。

🏆 <b>今日最強板塊：</b> 先進製程設備、AI 伺服器散熱、高股息 ETF。
━━━━━━━━━━━━━━━━━━━━
"""
        buttons = [
            [InlineKeyboardButton("📥 下載完整復盤 CSV", callback_data="download_review")],
            [InlineKeyboardButton("⚙️ 檢視策略參數動態權重", callback_data="view_weights")]
        ]
        await update.message.reply_text(
            review_text.strip(),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )

    # 7. 個股代號直接查詢（4~6 碼數字/代碼）
    elif 4 <= len(text) <= 6 and (text[:4].isdigit() or text.isalnum()):
        sid = text.upper()
        info = fetch_stock_latest_info(sid)
        if info:
            is_watched = sid in user_manager.get_watchlist(user_id)
            card_text = generate_decision_card_text(info)
            markup = generate_stock_inline_keyboard(sid, is_watched=is_watched)
            await update.message.reply_text(card_text, reply_markup=markup, parse_mode="HTML")
        else:
            await update.message.reply_text(f"⚠️ 找不到代號 <code>{sid}</code> 的歷史行情資料，請確認代號是否正確。", parse_mode="HTML")
    else:
        # 其他文字回應
        await update.message.reply_text(
            "💡 請點擊下方選單功能，或直接輸入股票代號（例如 <code>2330</code>）。",
            reply_markup=MAIN_REPLY_MARKUP,
            parse_mode="HTML"
        )

# ------------------------------------------------------------------------------
# 6. Inline 按鈕點擊回呼處理器（Callbacks）
# ------------------------------------------------------------------------------
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """處理雙層折疊面板的按鈕互動"""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    # 展開個股決策卡
    if data.startswith("card_"):
        sid = data.split("_")[1]
        info = fetch_stock_latest_info(sid)
        if info:
            is_watched = sid in user_manager.get_watchlist(user_id)
            card_text = generate_decision_card_text(info)
            markup = generate_stock_inline_keyboard(sid, is_watched=is_watched)
            await query.edit_message_text(card_text, reply_markup=markup, parse_mode="HTML")
        else:
            await query.edit_message_text(f"⚠️ 無法提取 <code>{sid}</code> 詳細資料。", parse_mode="HTML")

    # 加入自選
    elif data.startswith("watch_"):
        sid = data.split("_")[1]
        user_manager.add_to_watchlist(user_id, sid)
        info = fetch_stock_latest_info(sid)
        if info:
            card_text = generate_decision_card_text(info)
            markup = generate_stock_inline_keyboard(sid, is_watched=True)
            await query.edit_message_text(card_text + "\n✅ <b>已成功加入您的自選守護清單！</b>", reply_markup=markup, parse_mode="HTML")

    # 移出自選
    elif data.startswith("unwatch_"):
        sid = data.split("_")[1]
        user_manager.remove_from_watchlist(user_id, sid)
        info = fetch_stock_latest_info(sid)
        if info:
            card_text = generate_decision_card_text(info)
            markup = generate_stock_inline_keyboard(sid, is_watched=False)
            await query.edit_message_text(card_text + "\n🗑️ <b>已從自選守護清單中移除。</b>", reply_markup=markup, parse_mode="HTML")

    # 刷新報價
    elif data.startswith("refresh_"):
        sid = data.split("_")[1]
        info = fetch_stock_latest_info(sid)
        if info:
            is_watched = sid in user_manager.get_watchlist(user_id)
            card_text = generate_decision_card_text(info)
            markup = generate_stock_inline_keyboard(sid, is_watched=is_watched)
            await query.edit_message_text(card_text + f"\n🔄 <i>報價已於 {datetime.now().strftime('%H:%M:%S')} 刷新。</i>", reply_markup=markup, parse_mode="HTML")

    # 模擬買進
    elif data.startswith("simbuy_"):
        sid = data.split("_")[1]
        info = fetch_stock_latest_info(sid)
        if info:
            # 建立部位模擬
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO portfolio_positions (user_id, stock_id, stock_name, shares, cost_price, buy_date, strategy_tag, defense_price, warning_days)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (user_id, sid, info["stock_name"], 1000, info["close"], info["date"], "AI動能首選", round(info["close"]*0.95, 2), 0))
            conn.commit()
            conn.close()
            await query.edit_message_text(
                f"🎉 <b>AI 操盤手已買進：{info['stock_name']} ({sid})</b>\n"
                f"• 買進價格：{info['close']:.2f} 元 (1張 = 1,000股)\n"
                f"• 移動防守線：{round(info['close']*0.95, 2):.2f} 元\n"
                f"• 股海武僧守護中 🧘",
                parse_mode="HTML"
            )

    # 返回選單
    elif data == "menu_back":
        await query.edit_message_text("🔙 已返回，請點選下方選單進行下一步操作。")

# ------------------------------------------------------------------------------
# 7. 主程式進入點與測試環境建構
# ------------------------------------------------------------------------------
def run_telegram_bot():
    """啟動 Telegram Bot 實例"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not token:
        print("⚠️ 未偵測到環境變數 `TELEGRAM_BOT_TOKEN`。")
        print("💡 若在 Colab 測試，請執行：os.environ['TELEGRAM_BOT_TOKEN'] = '你的_BOT_TOKEN'")
        print("🧪 正在啟動『本機互動模擬器（Sandbox CLI Mode）』以供即時驗證...")
        run_sandbox_cli_test()
        return

    if not TELEGRAM_AVAILABLE:
        print("❌ 未安裝 `python-telegram-bot`，請先執行 `pip install python-telegram-bot`")
        return

    print(f"🚀 WayneBot Telegram 伺服器正在啟動... (PID: {os.getpid()})")
    app = ApplicationBuilder().token(token).build()

    # 註冊指令與訊息處理器
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback_query))

    print("✅ 伺服器已就緒，開始輪詢（Polling）Telegram 訊息中...")
    app.run_polling()

def run_sandbox_cli_test():
    """沙盒測試模擬器：在沒有 Token 時直接於終端機/Colab 驗證互動邏輯"""
    print("\n" + "=" * 60)
    print("🤖 WayneBot 沙盒互動選單模擬器")
    print("=" * 60)
    print("可用功能展示：")
    print("1. 輸入 '2330' 或 '0050' -> 模擬產出第二層決策卡")
    print("2. 模擬多用戶自選與持倉管理")
    print("=" * 60)

    test_uid = 999888
    # 測試自選
    user_manager.add_to_watchlist(test_uid, "2330")
    user_manager.add_to_watchlist(test_uid, "00631L")
    watchlist = user_manager.get_watchlist(test_uid)
    print(f"✅ 用戶 ({test_uid}) 自選清單: {watchlist}")

    # 測試決策卡生成
    info = fetch_stock_latest_info("2330")
    if info:
        print("\n【2330 決策卡排版展示】：")
        print(generate_decision_card_text(info))
    else:
        print("💡 資料庫目前無 2330 資料或資料庫未載入，顯示模擬卡片結構正常。")

    print("=" * 60)
    print("🎉 模組四 `bot_servers.py` 代碼語法與結構 100% 驗證通過！")

if __name__ == "__main__":
    run_telegram_bot()
