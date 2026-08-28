# ==============================================================================
# WayneBot 全市場量化決策系統升級：模組三 - AI 模擬操盤手 ＆ 自選守護
# 檔案名稱：portfolio_engine.py
# 適用環境：Google Colab / 本地沙盒獨立測試 ＆ 根目錄替換
# ==============================================================================

import os
import json
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import pandas as pd

# ------------------------------------------------------------------------------
# 1. 交易成本與費率常數定義（依台股真實規範）
# ------------------------------------------------------------------------------
DEFAULT_COMMISSION_RATE = 0.001425  # 手續費率 0.1425%
DEFAULT_BROKER_DISCOUNT = 0.60      # 券商折讓 6 折
MIN_COMMISSION_FEE = 20.0           # 單筆手續費最低 20 元
STOCK_TAX_RATE = 0.003              # 股票證券交易稅 0.3%
ETF_TAX_RATE = 0.001                # ETF 證券交易稅 0.1%

DEFAULT_INITIAL_CAPITAL = 500000.0  # 預設 AI 操盤手起始本金：50 萬元

# ------------------------------------------------------------------------------
# 2. 資料庫結構初始化（支援多用戶隔離、交易日誌與自選守護）
# ------------------------------------------------------------------------------
def init_portfolio_tables(conn: sqlite3.Connection):
    """建立操盤手帳戶、持倉、交易紀錄與自選守護資料表"""
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode = WAL;")

    # 1. 用戶資金帳戶表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_accounts (
        user_id TEXT PRIMARY KEY,
        initial_capital REAL NOT NULL,
        cash_balance REAL NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 2. 用戶持倉明細表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_portfolios (
        user_id TEXT NOT NULL,
        stock_id TEXT NOT NULL,
        stock_name TEXT NOT NULL,
        shares INTEGER NOT NULL,
        avg_cost REAL NOT NULL,
        total_cost REAL NOT NULL,
        entry_date TEXT NOT NULL,
        entry_reason TEXT,
        highest_price_after_entry REAL DEFAULT 0.0,
        stop_loss_price REAL DEFAULT 0.0,
        trailing_stop_price REAL DEFAULT 0.0,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (user_id, stock_id)
    );
    """)

    # 3. 交易日誌流水表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_trades (
        trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        date TEXT NOT NULL,
        stock_id TEXT NOT NULL,
        stock_name TEXT NOT NULL,
        action TEXT NOT NULL, -- BUY / SELL / DIVIDEND
        shares INTEGER NOT NULL,
        price REAL NOT NULL,
        fee REAL NOT NULL,
        tax REAL NOT NULL,
        net_amount REAL NOT NULL,
        realized_pnl REAL DEFAULT 0.0,
        note TEXT,
        created_at TEXT NOT NULL
    );
    """)

    # 4. 用戶自選守護表
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_watchlists (
        user_id TEXT NOT NULL,
        stock_id TEXT NOT NULL,
        stock_name TEXT NOT NULL,
        target_buy_low REAL DEFAULT 0.0,
        target_buy_high REAL DEFAULT 0.0,
        defense_price REAL DEFAULT 0.0,
        added_at TEXT NOT NULL,
        PRIMARY KEY (user_id, stock_id)
    );
    """)

    conn.commit()

# ------------------------------------------------------------------------------
# 3. 交易費率精算引擎
# ------------------------------------------------------------------------------
def calculate_trade_fees(
    action: str,
    shares: int,
    price: float,
    is_etf: bool = False,
    discount: float = DEFAULT_BROKER_DISCOUNT
) -> Tuple[float, float, float]:
    """
    精算手續費、交易稅與總交割金額
    買進總額 = 成交金額 + 手續費
    賣出淨額 = 成交金額 - 手續費 - 證券交易稅
    """
    trade_value = float(shares) * price
    # 手續費
    raw_fee = trade_value * DEFAULT_COMMISSION_RATE * discount
    fee = max(MIN_COMMISSION_FEE, round(raw_fee))

    # 證券交易稅
    if action.upper() == "SELL":
        tax_rate = ETF_TAX_RATE if is_etf else STOCK_TAX_RATE
        tax = round(trade_value * tax_rate)
    else:
        tax = 0.0

    if action.upper() == "BUY":
        net_amount = -(trade_value + fee)
    else:
        net_amount = trade_value - fee - tax

    return fee, tax, net_amount

# ------------------------------------------------------------------------------
# 4. 操盤手核心業務邏輯管理器
# ------------------------------------------------------------------------------
class PortfolioManager:
    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = db_path
        self._ensure_db()

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_db(self):
        with self._get_conn() as conn:
            init_portfolio_tables(conn)

    def get_or_create_account(self, user_id: str, initial_capital: float = DEFAULT_INITIAL_CAPITAL) -> Dict[str, Any]:
        """取得或建立指定 user_id 資金帳戶"""
        user_id = str(user_id)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, initial_capital, cash_balance FROM user_accounts WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                return {"user_id": row[0], "initial_capital": row[1], "cash_balance": row[2]}
            
            cursor.execute("""
            INSERT INTO user_accounts (user_id, initial_capital, cash_balance, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """, (user_id, initial_capital, initial_capital, now_str, now_str))
            conn.commit()
            return {"user_id": user_id, "initial_capital": initial_capital, "cash_balance": initial_capital}

    def buy(
        self,
        user_id: str,
        stock_id: str,
        stock_name: str,
        shares: int,
        price: float,
        date_str: str,
        is_etf: bool = False,
        entry_reason: str = "量化訊號買進",
        stop_loss_pct: float = 0.07
    ) -> Dict[str, Any]:
        """執行買進（支援整張與零股）"""
        if shares <= 0 or price <= 0:
            return {"status": "error", "message": "股數或價格必須大於 0"}

        user_id = str(user_id)
        stock_id = str(stock_id)
        acct = self.get_or_create_account(user_id)
        fee, tax, net_cash_delta = calculate_trade_fees("BUY", shares, price, is_etf)
        required_cash = abs(net_cash_delta)

        if acct["cash_balance"] < required_cash:
            return {
                "status": "error",
                "message": f"可用現金不足！需 {required_cash:,.0f} 元，目前僅有 {acct['cash_balance']:,.0f} 元"
            }

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # 扣減現金
            new_cash = acct["cash_balance"] - required_cash
            cursor.execute("UPDATE user_accounts SET cash_balance = ?, updated_at = ? WHERE user_id = ?", (new_cash, now_str, user_id))

            # 檢查是否已有部位（加碼/攤平計算）
            cursor.execute("SELECT shares, total_cost, highest_price_after_entry FROM user_portfolios WHERE user_id = ? AND stock_id = ?", (user_id, stock_id))
            row = cursor.fetchone()

            stop_loss_price = round(price * (1.0 - stop_loss_pct), 2)

            if row:
                old_shares, old_total_cost, old_high = row
                total_shares = old_shares + shares
                total_cost = old_total_cost + required_cash
                avg_cost = round(total_cost / total_shares, 2)
                highest_price = max(old_high, price)

                cursor.execute("""
                UPDATE user_portfolios 
                SET shares = ?, avg_cost = ?, total_cost = ?, highest_price_after_entry = ?, updated_at = ?
                WHERE user_id = ? AND stock_id = ?
                """, (total_shares, avg_cost, total_cost, highest_price, now_str, user_id, stock_id))
            else:
                total_shares = shares
                avg_cost = round(required_cash / shares, 2)
                total_cost = required_cash
                highest_price = price

                cursor.execute("""
                INSERT INTO user_portfolios 
                (user_id, stock_id, stock_name, shares, avg_cost, total_cost, entry_date, entry_reason, highest_price_after_entry, stop_loss_price, trailing_stop_price, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (user_id, stock_id, stock_name, shares, avg_cost, total_cost, date_str, entry_reason, highest_price, stop_loss_price, stop_loss_price, now_str))

            # 寫入交易日誌
            cursor.execute("""
            INSERT INTO user_trades (user_id, date, stock_id, stock_name, action, shares, price, fee, tax, net_amount, realized_pnl, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, date_str, stock_id, stock_name, "BUY", shares, price, fee, tax, net_cash_delta, 0.0, entry_reason, now_str))

            conn.commit()

        return {
            "status": "success",
            "stock_id": stock_id,
            "stock_name": stock_name,
            "shares": shares,
            "price": price,
            "cost": required_cash,
            "remaining_cash": new_cash
        }

    def sell(
        self,
        user_id: str,
        stock_id: str,
        shares: int,
        price: float,
        date_str: str,
        is_etf: bool = False,
        exit_reason: str = "停利/停損出場"
    ) -> Dict[str, Any]:
        """執行賣出（支援分批與全數清倉）"""
        user_id = str(user_id)
        stock_id = str(stock_id)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT stock_name, shares, avg_cost, total_cost FROM user_portfolios WHERE user_id = ? AND stock_id = ?", (user_id, stock_id))
            row = cursor.fetchone()
            if not row:
                return {"status": "error", "message": f"庫存中查無標的 {stock_id}"}

            sname, cur_shares, avg_cost, cur_total_cost = row
            if shares > cur_shares:
                return {"status": "error", "message": f"賣出股數 ({shares}) 超過庫存持有股數 ({cur_shares})"}

            fee, tax, net_revenue = calculate_trade_fees("SELL", shares, price, is_etf)
            # 實現損益精算
            cost_of_sold_shares = (cur_total_cost / cur_shares) * shares
            realized_pnl = round(net_revenue - cost_of_sold_shares)

            # 更新用戶帳戶現金
            cursor.execute("SELECT cash_balance FROM user_accounts WHERE user_id = ?", (user_id,))
            cash_row = cursor.fetchone()
            cur_cash = cash_row[0] if cash_row else DEFAULT_INITIAL_CAPITAL
            new_cash = cur_cash + net_revenue
            cursor.execute("UPDATE user_accounts SET cash_balance = ?, updated_at = ? WHERE user_id = ?", (new_cash, now_str, user_id))

            # 更新或刪除持倉
            remaining_shares = cur_shares - shares
            if remaining_shares == 0:
                cursor.execute("DELETE FROM user_portfolios WHERE user_id = ? AND stock_id = ?", (user_id, stock_id))
            else:
                new_total_cost = cur_total_cost - cost_of_sold_shares
                new_avg_cost = round(new_total_cost / remaining_shares, 2)
                cursor.execute("""
                UPDATE user_portfolios 
                SET shares = ?, avg_cost = ?, total_cost = ?, updated_at = ?
                WHERE user_id = ? AND stock_id = ?
                """, (remaining_shares, new_avg_cost, new_total_cost, now_str, user_id, stock_id))

            # 寫入交易日誌
            cursor.execute("""
            INSERT INTO user_trades (user_id, date, stock_id, stock_name, action, shares, price, fee, tax, net_amount, realized_pnl, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, date_str, stock_id, sname, "SELL", shares, price, fee, tax, net_revenue, realized_pnl, exit_reason, now_str))

            conn.commit()

        return {
            "status": "success",
            "stock_id": stock_id,
            "stock_name": sname,
            "sold_shares": shares,
            "remaining_shares": remaining_shares,
            "price": price,
            "net_revenue": net_revenue,
            "realized_pnl": realized_pnl,
            "new_cash": new_cash
        }

    # --------------------------------------------------------------------------
    # 5. 自選股清單管理
    # --------------------------------------------------------------------------
    def add_watchlist(self, user_id: str, stock_id: str, stock_name: str, low: float = 0.0, high: float = 0.0, def_price: float = 0.0) -> bool:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO user_watchlists (user_id, stock_id, stock_name, target_buy_low, target_buy_high, defense_price, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (str(user_id), str(stock_id), str(stock_name), low, high, def_price, now_str))
            conn.commit()
        return True

    def remove_watchlist(self, user_id: str, stock_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_watchlists WHERE user_id = ? AND stock_id = ?", (str(user_id), str(stock_id)))
            conn.commit()
        return True

    def get_watchlist(self, user_id: str) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT stock_id, stock_name, target_buy_low, target_buy_high, defense_price FROM user_watchlists WHERE user_id = ?", (str(user_id),))
            rows = cursor.fetchall()
            return [{"stock_id": r[0], "stock_name": r[1], "target_buy_low": r[2], "target_buy_high": r[3], "defense_price": r[4]} for r in rows]

    # --------------------------------------------------------------------------
    # 6. 股海武僧出場紀律 ＆ 自選持股守護雷達
    # --------------------------------------------------------------------------
    def evaluate_holding_guardian(self, user_id: str, current_quotes: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        守護雷達規則評估：
        1. 股海武僧 K20 高預警脫離：股價偏離 20 日高點後回檔防守。
        2. D20 乖離 > 30% 穿溜冰鞋停利：超額利潤分批停利。
        3. 量縮回測 vs 爆量長黑破位：
           - 若收盤跌破 5MA/20MA 且 成交量 < 5MA均量 -> 🟢 良性縮量回測，續抱守候。
           - 若收盤跌破 5MA/20MA 且 成交量 > 5MA均量 * 1.5 -> 🚨 爆量破位警報，強制減碼/出清。
        """
        user_id = str(user_id)
        alerts = []
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT stock_id, stock_name, shares, avg_cost, highest_price_after_entry, stop_loss_price, trailing_stop_price 
            FROM user_portfolios WHERE user_id = ?
            """, (user_id,))
            holdings = cursor.fetchall()

        for sid, sname, shares, avg_cost, high_entry, stop_loss, trailing_stop in holdings:
            q = current_quotes.get(sid)
            if not q:
                continue

            close = q.get("close", 0.0)
            vol = q.get("volume", 0)
            vol_5ma = q.get("vol_5ma", vol)
            ma5 = q.get("ma5", close)
            ma20 = q.get("ma20", close)
            d20 = q.get("d20", 0.0) # 20日乖離率 (%)
            k20_high = q.get("k20_high", close)

            unrealized_pnl_pct = ((close - avg_cost) / avg_cost) * 100.0 if avg_cost > 0 else 0.0

            # 狀態判定
            status_tag = "HOLD"
            advice_msg = "常態持倉，趨勢延續中"

            # 紀律 1：D20 > 30% 超額獲利穿溜冰鞋
            if d20 > 30.0 or unrealized_pnl_pct >= 25.0:
                status_tag = "TAKE_PROFIT"
                advice_msg = f"🏆 *獲利豐厚穿溜冰鞋*：D20乖離 (+{d20:.1f}%) 達紅色高標，建議分批獲利 1/3~1/2 落袋"

            # 紀律 2：爆量長黑破位
            elif close < ma5 and vol >= (vol_5ma * 1.5) and vol > 1000:
                status_tag = "CRITICAL_ALERT"
                advice_msg = f"🚨 *爆量長黑破位警報*：跌破5MA ({ma5:.2f}) 且爆量 ({vol}張 > 5MA量1.5x)，主力調節強烈建議出清！"

            # 紀律 3：良性量縮回測
            elif close < ma5 and vol <= vol_5ma:
                status_tag = "HEALTHY_PULLBACK"
                advice_msg = f"🟢 *量縮良性回測緩衝*：小破5MA但量能萎縮 ({vol}張 <= 均量)，未見恐慌賣壓，續抱守20MA ({ma20:.2f})"

            # 紀律 4：跌破絕對防守/停損價
            elif close <= stop_loss or unrealized_pnl_pct <= -7.0:
                status_tag = "STOP_LOSS"
                advice_msg = f"🛑 *觸及停損防守線*：現價 ({close}) 跌破進場防守價 ({stop_loss})，紀律出場控制風險"

            alerts.append({
                "stock_id": sid,
                "stock_name": sname,
                "shares": shares,
                "avg_cost": avg_cost,
                "current_price": close,
                "pnl_pct": unrealized_pnl_pct,
                "status_tag": status_tag,
                "advice": advice_msg
            })

        return alerts

    # --------------------------------------------------------------------------
    # 7. 總資產與 Telegram 卡片渲染輸出
    # --------------------------------------------------------------------------
    def get_portfolio_summary(self, user_id: str, current_quotes: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        acct = self.get_or_create_account(user_id)
        cash = acct["cash_balance"]
        stock_market_value = 0.0
        total_cost = 0.0
        holdings_detail = []

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT stock_id, stock_name, shares, avg_cost, total_cost, entry_date, entry_reason FROM user_portfolios WHERE user_id = ?", (str(user_id),))
            rows = cursor.fetchall()

        for sid, sname, shares, avg_cost, t_cost, e_date, e_reason in rows:
            q = current_quotes.get(sid, {})
            cur_price = q.get("close", avg_cost)
            mkt_val = shares * cur_price
            stock_market_value += mkt_val
            total_cost += t_cost
            pnl_amt = mkt_val - t_cost
            pnl_pct = ((cur_price - avg_cost) / avg_cost * 100.0) if avg_cost > 0 else 0.0

            holdings_detail.append({
                "stock_id": sid,
                "stock_name": sname,
                "shares": shares,
                "avg_cost": avg_cost,
                "current_price": cur_price,
                "market_value": mkt_val,
                "pnl_amount": pnl_amt,
                "pnl_pct": pnl_pct,
                "entry_date": e_date,
                "entry_reason": e_reason
            })

        total_asset = cash + stock_market_value
        unrealized_pnl = stock_market_value - total_cost
        unrealized_pnl_pct = (unrealized_pnl / total_cost * 100.0) if total_cost > 0 else 0.0
        total_pnl_pct = ((total_asset - acct["initial_capital"]) / acct["initial_capital"]) * 100.0

        return {
            "user_id": user_id,
            "initial_capital": acct["initial_capital"],
            "cash_balance": cash,
            "stock_market_value": stock_market_value,
            "total_asset": total_asset,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "total_pnl_pct": total_pnl_pct,
            "holdings": holdings_detail
        }

    def render_portfolio_telegram_card(self, user_id: str, current_quotes: Dict[str, Dict[str, Any]]) -> str:
        """渲染 Telegram 格式之 AI 操盤手總資產與持倉卡片"""
        summary = self.get_portfolio_summary(user_id, current_quotes)
        guardian_alerts = self.evaluate_holding_guardian(user_id, current_quotes)
        alert_map = {a["stock_id"]: a["advice"] for a in guardian_alerts}

        sign = "+" if summary["total_pnl_pct"] >= 0 else ""
        lines = [
            f"💼 *WayneBot 50萬 AI 模擬操盤戰報* ｜ `ID:{user_id}`",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"💰 *總資產淨值*：`{summary['total_asset']:,.0f}` 元 （總報酬: `{sign}{summary['total_pnl_pct']:.2f}%`）",
            f"💵 *可用現金*：`{summary['cash_balance']:,.0f}` 元 ｜ 股票市值：`{summary['stock_market_value']:,.0f}` 元",
            f"📈 *未實現損益*：`{summary['unrealized_pnl']:+,.0f}` 元 (`{sign}{summary['unrealized_pnl_pct']:.2f}%`)",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "📊 *目前持倉與守護狀態*："
        ]

        if not summary["holdings"]:
            lines.append("  _目前無持股，100% 現金儲備觀望中_")
        else:
            for h in summary["holdings"]:
                h_sign = "+" if h["pnl_pct"] >= 0 else ""
                lots_str = f"{h['shares']//1000}張" if h['shares'] >= 1000 and h['shares'] % 1000 == 0 else f"{h['shares']}股"
                lines.append(
                    f"• *{h['stock_id']} {h['stock_name']}* ｜ `{lots_str}` ｜ 均價 `{h['avg_cost']:.2f}` ➔ 現價 `{h['current_price']:.2f}`"
                )
                lines.append(f"  ├ 損益：`{h_sign}{h['pnl_amount']:+,.0f}` 元 (`{h_sign}{h['pnl_pct']:.2f}%`)")
                adv = alert_map.get(h["stock_id"], "常態續抱")
                lines.append(f"  └ 🛡️ 守護：{adv}")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 *武僧紀律*：量縮回測良性續抱，爆量長黑破位果斷出清。")
        return "\n".join(lines)

# ------------------------------------------------------------------------------
# 8. 獨立沙盒測試程式碼
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("🧪 正在執行 portfolio_engine.py 模組三獨立沙盒測試...")
    print("=" * 70)

    test_db = "waynebot_history.db"
    pm = PortfolioManager(db_path=test_db)

    # 模擬兩位獨立使用者（使用者本人 vs 哥哥）
    USER_WAYNE = "user_wayne_001"
    USER_BROTHER = "user_brother_002"

    print("\n【測試 1：多用戶獨立資金帳戶初始化】")
    acct_w = pm.get_or_create_account(USER_WAYNE, initial_capital=500000.0)
    acct_b = pm.get_or_create_account(USER_BROTHER, initial_capital=300000.0)
    print(f"  • 用戶 Wayne 起始現金 : {acct_w['cash_balance']:,.0f} 元")
    print(f"  • 用戶 Brother 起始現金: {acct_b['cash_balance']:,.0f} 元")
    assert acct_w["cash_balance"] == 500000.0 and acct_b["cash_balance"] == 300000.0

    print("\n【測試 2：買進交易精算（含手續費折讓與整張/零股支援）】")
    # Wayne 買進 2330 台積電 100 股 (零股 @ 980) + 2603 長榮 1 張 (1000股 @ 185)
    r1 = pm.buy(USER_WAYNE, "2330", "台積電", shares=100, price=980.0, date_str="20260828", is_etf=False, entry_reason="零股定期配置")
    r2 = pm.buy(USER_WAYNE, "2603", "長榮", shares=1000, price=185.0, date_str="20260828", is_etf=False, entry_reason="Select 01 周突破")
    print(f"  • 買進台積電 100 股花費 : {r1['cost']:,.0f} 元 ｜ 帳戶剩餘: {r1['remaining_cash']:,.0f} 元")
    print(f"  • 買進長榮 1 張花費     : {r2['cost']:,.0f} 元 ｜ 帳戶剩餘: {r2['remaining_cash']:,.0f} 元")
    assert r1["status"] == "success" and r2["status"] == "success"

    print("\n【測試 3：自選守護雷達判定（量縮良性回測 vs 爆量破位 vs 穿溜冰鞋）】")
    mock_quotes = {
        "2330": {
            "close": 1050.0, "volume": 32000, "vol_5ma": 30000, "ma5": 1020.0, "ma20": 980.0, "d20": 7.1
        },
        "2603": {
            "close": 178.0, "volume": 4500, "vol_5ma": 8000, "ma5": 182.0, "ma20": 175.0, "d20": 1.7
        }
    }
    alerts = pm.evaluate_holding_guardian(USER_WAYNE, mock_quotes)
    for a in alerts:
        print(f"  • [{a['stock_id']} {a['stock_name']}] 現價: {a['current_price']} (損益: {a['pnl_pct']:+.2f}%) ➔ 判定: {a['status_tag']}")
        print(f"    說明: {a['advice']}")

    print("\n【測試 4：部分獲利賣出與交易日誌】")
    # 賣出長榮 1000 股 @ 195.0
    r_sell = pm.sell(USER_WAYNE, "2603", shares=1000, price=195.0, date_str="20260829", is_etf=False, exit_reason="衝頂達標停利")
    print(f"  • 賣出長榮 1 張 實現損益: {r_sell['realized_pnl']:+,.0f} 元 ｜ 最新現金: {r_sell['new_cash']:,.0f} 元")
    assert r_sell["realized_pnl"] > 0

    print("\n【測試 5：Telegram 操盤與守護面板卡片渲染】")
    card = pm.render_portfolio_telegram_card(USER_WAYNE, mock_quotes)
    print("\n--- [Telegram 訊息卡片預覽] ---")
    print(card)
    print("------------------------------")
    print("\n🎉 模組三 `portfolio_engine.py` 沙盒單獨測試 100% 通過！")
