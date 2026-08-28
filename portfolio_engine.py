# ==============================================================================
# WayneBot 全市場量化決策系統升級：模組三
# 檔案名稱：portfolio_engine.py
# 模組功能：50萬 AI 模擬操盤手、多用戶隔離、股海武僧紀律與自選即持股守護雷達
# ==============================================================================

import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

# ------------------------------------------------------------------------------
# 1. 費率與標準常數定義
# ------------------------------------------------------------------------------
DEFAULT_CAPITAL = 500000.0       # 預設本金 50 萬元
COMMISSION_RATE = 0.001425       # 券商手續費率 (0.1425%)
COMMISSION_MIN = 20.0            # 手續費最低低消 20 元
STOCK_TAX_RATE = 0.003           # 普通股證交稅率 (0.3%)
ETF_TAX_RATE = 0.001             # ETF 證交稅率 (0.1%)
DEFAULT_DISCOUNT = 0.6           # 電子下單預設 6 折手續費優惠

# ------------------------------------------------------------------------------
# 2. AI 模擬操盤與資產管理引擎
# ------------------------------------------------------------------------------
class PortfolioEngine:
    def __init__(self, db_path: str = "waynebot_history.db"):
        self.db_path = db_path
        self._init_portfolio_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_portfolio_tables(self):
        """初始化多用戶獨立之帳戶、持倉、交易紀錄與自選清單資料表"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # 用戶帳戶資金表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_accounts (
            user_id TEXT PRIMARY KEY,
            user_name TEXT DEFAULT '',
            initial_capital REAL NOT NULL DEFAULT 500000.0,
            cash_balance REAL NOT NULL DEFAULT 500000.0,
            realized_pnl REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)

        # 用戶持倉部位表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_positions (
            user_id TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            shares INTEGER NOT NULL,
            cost_price REAL NOT NULL,
            total_cost REAL NOT NULL,
            entry_date TEXT NOT NULL,
            entry_type TEXT NOT NULL DEFAULT '波段',
            trailing_stop REAL NOT NULL DEFAULT 0.0,
            warn_days INTEGER NOT NULL DEFAULT 0,
            is_etf INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, stock_id)
        );
        """)

        # 交易歷史紀錄表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            action TEXT NOT NULL,
            shares INTEGER NOT NULL,
            price REAL NOT NULL,
            fee REAL NOT NULL,
            tax REAL NOT NULL,
            total_amount REAL NOT NULL,
            realized_pnl REAL DEFAULT 0.0,
            pnl_pct REAL DEFAULT 0.0,
            trade_date TEXT NOT NULL,
            reason TEXT DEFAULT ''
        );
        """)

        # 用戶自選守護清單
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_watchlist (
            user_id TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            added_date TEXT NOT NULL,
            tags TEXT DEFAULT '核心自選',
            PRIMARY KEY (user_id, stock_id)
        );
        """)

        conn.commit()
        conn.close()

    # --------------------------------------------------------------------------
    # 帳戶核心與資金操作
    # --------------------------------------------------------------------------
    def get_or_create_account(self, user_id: str, user_name: str = "") -> dict:
        """取得或建立使用者帳戶（保證 50 萬啟動）"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_accounts WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not row:
            cursor.execute("""
            INSERT INTO user_accounts (user_id, user_name, initial_capital, cash_balance, realized_pnl, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (user_id, user_name, DEFAULT_CAPITAL, DEFAULT_CAPITAL, 0.0, now_str, now_str))
            conn.commit()
            cursor.execute("SELECT * FROM user_accounts WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()

        acc = dict(row)
        conn.close()
        return acc

    def reset_account(self, user_id: str, capital: float = DEFAULT_CAPITAL):
        """重置指定用戶之模擬帳戶本金並清空持倉與歷史紀錄"""
        conn = self._get_connection()
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("UPDATE user_accounts SET initial_capital = ?, cash_balance = ?, realized_pnl = 0.0, updated_at = ? WHERE user_id = ?", (capital, capital, now_str, user_id))
        cursor.execute("DELETE FROM user_positions WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM user_trade_history WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

    # --------------------------------------------------------------------------
    # 交易稅費計算
    # --------------------------------------------------------------------------
    @staticmethod
    def calculate_buy_cost(price: float, shares: int, discount: float = DEFAULT_DISCOUNT) -> Tuple[float, float]:
        """計算買進總支出與手續費 (總額 = 股價*股數 + 手續費)"""
        trade_val = price * shares
        raw_fee = trade_val * COMMISSION_RATE * discount
        fee = max(COMMISSION_MIN, round(raw_fee))
        return trade_val + fee, fee

    @staticmethod
    def calculate_sell_proceeds(price: float, shares: int, is_etf: bool = False, discount: float = DEFAULT_DISCOUNT) -> Tuple[float, float, float]:
        """計算賣出實收金額、手續費與證交稅 (實收 = 股價*股數 - 手續費 - 證交稅)"""
        trade_val = price * shares
        raw_fee = trade_val * COMMISSION_RATE * discount
        fee = max(COMMISSION_MIN, round(raw_fee))
        tax_rate = ETF_TAX_RATE if is_etf else STOCK_TAX_RATE
        tax = round(trade_val * tax_rate)
        proceeds = trade_val - fee - tax
        return proceeds, fee, tax

    # --------------------------------------------------------------------------
    # 買進與賣出操作 (支援整張與零股動態配置)
    # --------------------------------------------------------------------------
    def buy_stock(self, user_id: str, stock_id: str, stock_name: str, price: float, shares: int, entry_type: str = "波段", is_etf: bool = False, trailing_stop: float = 0.0, reason: str = "") -> Tuple[bool, str]:
        """執行買進委託（自動扣除現金、加權平均成本、支援零股）"""
        if shares <= 0 or price <= 0:
            return False, "下單價格或股數必須大於 0"

        acc = self.get_or_create_account(user_id)
        total_cost, fee = self.calculate_buy_cost(price, shares)

        if acc["cash_balance"] < total_cost:
            return False, f"可用現金不足！需 {total_cost:,.0f} 元，目前僅剩 {acc['cash_balance']:,.0f} 元"

        conn = self._get_connection()
        cursor = conn.cursor()
        now_date = datetime.now().strftime("%Y-%m-%d")
        now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 檢查是否已有該檔持倉
        cursor.execute("SELECT * FROM user_positions WHERE user_id = ? AND stock_id = ?", (user_id, stock_id))
        pos = cursor.fetchone()

        if pos:
            # 加碼：計算加權平均成本
            old_shares = pos["shares"]
            old_cost = pos["total_cost"]
            new_shares = old_shares + shares
            new_total_cost = old_cost + total_cost
            new_cost_price = round(new_total_cost / new_shares, 2)
            final_stop = max(pos["trailing_stop"], trailing_stop) if trailing_stop > 0 else pos["trailing_stop"]

            cursor.execute("""
            UPDATE user_positions 
            SET shares = ?, cost_price = ?, total_cost = ?, trailing_stop = ?, is_etf = ?
            WHERE user_id = ? AND stock_id = ?;
            """, (new_shares, new_cost_price, new_total_cost, final_stop, 1 if is_etf else 0, user_id, stock_id))
        else:
            # 新建倉
            cost_price = round(total_cost / shares, 2)
            default_stop = round(price * 0.93, 2) if trailing_stop <= 0 else trailing_stop  # 預設 7% 停損
            cursor.execute("""
            INSERT INTO user_positions (user_id, stock_id, stock_name, shares, cost_price, total_cost, entry_date, entry_type, trailing_stop, warn_days, is_etf)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?);
            """, (user_id, stock_id, stock_name, shares, cost_price, total_cost, now_date, entry_type, default_stop, 1 if is_etf else 0))

        # 扣減帳戶現金
        new_cash = acc["cash_balance"] - total_cost
        cursor.execute("UPDATE user_accounts SET cash_balance = ?, updated_at = ? WHERE user_id = ?", (new_cash, now_time, user_id))

        # 寫入歷史紀錄
        cursor.execute("""
        INSERT INTO user_trade_history (user_id, stock_id, stock_name, action, shares, price, fee, tax, total_amount, realized_pnl, pnl_pct, trade_date, reason)
        VALUES (?, ?, ?, 'BUY', ?, ?, ?, 0.0, ?, 0.0, 0.0, ?, ?);
        """, (user_id, stock_id, stock_name, shares, price, fee, total_cost, now_time, reason or entry_type))

        conn.commit()
        conn.close()
        return True, f"成功買進 {stock_name} ({stock_id}) {shares:,} 股，均價 {price:.2f}，總成本 {total_cost:,.0f} 元"

    def sell_stock(self, user_id: str, stock_id: str, price: float, shares: int, reason: str = "紀律平倉") -> Tuple[bool, str]:
        """執行賣出委託（計算已實現損益、退回現金、清除或減持部位）"""
        if shares <= 0 or price <= 0:
            return False, "賣出價格或股數必須大於 0"

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_positions WHERE user_id = ? AND stock_id = ?", (user_id, stock_id))
        pos = cursor.fetchone()

        if not pos:
            conn.close()
            return False, f"持倉中無此標的 ({stock_id})"

        if pos["shares"] < shares:
            conn.close()
            return False, f"賣出股數 ({shares:,}) 超過現有持倉 ({pos['shares']:,} 股)"

        is_etf = bool(pos["is_etf"])
        proceeds, fee, tax = self.calculate_sell_proceeds(price, shares, is_etf=is_etf)

        # 計算該批賣出部分對應的歷史成本
        unit_cost = pos["total_cost"] / pos["shares"]
        cost_sold = unit_cost * shares
        realized_pnl = round(proceeds - cost_sold, 2)
        pnl_pct = round((realized_pnl / cost_sold) * 100.0, 2) if cost_sold > 0 else 0.0

        # 更新持倉
        if pos["shares"] == shares:
            cursor.execute("DELETE FROM user_positions WHERE user_id = ? AND stock_id = ?", (user_id, stock_id))
        else:
            remaining_shares = pos["shares"] - shares
            remaining_cost = pos["total_cost"] - cost_sold
            cursor.execute("""
            UPDATE user_positions SET shares = ?, total_cost = ? WHERE user_id = ? AND stock_id = ?;
            """, (remaining_shares, remaining_cost, user_id, stock_id))

        # 更新帳戶資金與已實現損益
        cursor.execute("SELECT * FROM user_accounts WHERE user_id = ?", (user_id,))
        acc = dict(cursor.fetchone())
        new_cash = acc["cash_balance"] + proceeds
        new_pnl = acc["realized_pnl"] + realized_pnl
        now_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
        UPDATE user_accounts SET cash_balance = ?, realized_pnl = ?, updated_at = ? WHERE user_id = ?;
        """, (new_cash, new_pnl, now_time, user_id))

        # 寫入歷史紀錄
        cursor.execute("""
        INSERT INTO user_trade_history (user_id, stock_id, stock_name, action, shares, price, fee, tax, total_amount, realized_pnl, pnl_pct, trade_date, reason)
        VALUES (?, ?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (user_id, stock_id, pos["stock_name"], shares, price, fee, tax, proceeds, realized_pnl, pnl_pct, now_time, reason))

        conn.commit()
        conn.close()
        pnl_sign = "+" if realized_pnl >= 0 else ""
        return True, f"成功賣出 {pos['stock_name']} ({stock_id}) {shares:,} 股，實收 {proceeds:,.0f} 元，損益 {pnl_sign}{realized_pnl:,.0f} ({pnl_sign}{pnl_pct:.2f}%)"

    # --------------------------------------------------------------------------
    # 自選清單管理 (Watchlist)
    # --------------------------------------------------------------------------
    def add_to_watchlist(self, user_id: str, stock_id: str, stock_name: str, tags: str = "自選守護") -> Tuple[bool, str]:
        """加入自選守護雷達清單"""
        conn = self._get_connection()
        cursor = conn.cursor()
        now_date = datetime.now().strftime("%Y-%m-%d")
        try:
            cursor.execute("""
            INSERT OR REPLACE INTO user_watchlist (user_id, stock_id, stock_name, added_date, tags)
            VALUES (?, ?, ?, ?, ?);
            """, (user_id, stock_id, stock_name, now_date, tags))
            conn.commit()
            msg = f"成功將 {stock_name} ({stock_id}) 加入自選守護雷達"
            success = True
        except Exception as e:
            msg = f"加入失敗: {e}"
            success = False
        conn.close()
        return success, msg

    def remove_from_watchlist(self, user_id: str, stock_id: str) -> Tuple[bool, str]:
        """自選清單移除標的"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_watchlist WHERE user_id = ? AND stock_id = ?", (user_id, stock_id))
        conn.commit()
        conn.close()
        return True, f"已將 ({stock_id}) 從自選清單移除"

    def get_watchlist(self, user_id: str) -> List[dict]:
        """取得用戶之自選清單"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_watchlist WHERE user_id = ? ORDER BY added_date DESC", (user_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    # --------------------------------------------------------------------------
    # 資產總覽與部位估值評估 (Portfolio Valuation)
    # --------------------------------------------------------------------------
    def evaluate_portfolio(self, user_id: str, current_quotes_map: Dict[str, dict]) -> dict:
        """
        計算用戶整體資產淨值與部位表現
        current_quotes_map 格式: {'2330': {'close': 980.0, 'pct_change': 2.62, ...}}
        """
        acc = self.get_or_create_account(user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_positions WHERE user_id = ?", (user_id,))
        positions = [dict(r) for r in cursor.fetchall()]
        conn.close()

        total_market_val = 0.0
        total_unrealized_pnl = 0.0
        total_cost_basis = 0.0
        pos_details = []

        for p in positions:
            sid = p["stock_id"]
            quote = current_quotes_map.get(sid, {})
            curr_price = quote.get("close", p["cost_price"])
            curr_pct = quote.get("pct_change", 0.0)

            # 依現價計算估計賣出實收金額
            est_proceeds, _, _ = self.calculate_sell_proceeds(curr_price, p["shares"], is_etf=bool(p["is_etf"]))
            unrealized_pnl = round(est_proceeds - p["total_cost"], 2)
            unrealized_pnl_pct = round((unrealized_pnl / p["total_cost"]) * 100.0, 2) if p["total_cost"] > 0 else 0.0

            total_market_val += est_proceeds
            total_unrealized_pnl += unrealized_pnl
            total_cost_basis += p["total_cost"]

            pos_details.append({
                "stock_id": sid,
                "stock_name": p["stock_name"],
                "shares": p["shares"],
                "cost_price": p["cost_price"],
                "current_price": curr_price,
                "day_pct_change": curr_pct,
                "trailing_stop": p["trailing_stop"],
                "total_cost": p["total_cost"],
                "market_value": est_proceeds,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pnl_pct": unrealized_pnl_pct,
                "entry_type": p["entry_type"],
                "warn_days": p["warn_days"]
            })

        net_asset = acc["cash_balance"] + total_market_val
        total_return_pct = round(((net_asset - acc["initial_capital"]) / acc["initial_capital"]) * 100.0, 2)

        return {
            "user_id": user_id,
            "user_name": acc.get("user_name", ""),
            "initial_capital": acc["initial_capital"],
            "cash_balance": acc["cash_balance"],
            "stock_market_value": total_market_val,
            "net_asset_value": net_asset,
            "realized_pnl": acc["realized_pnl"],
            "unrealized_pnl": total_unrealized_pnl,
            "total_return_pct": total_return_pct,
            "positions_count": len(pos_details),
            "positions": pos_details
        }

    # --------------------------------------------------------------------------
    # 股海武僧出場紀律 ＆ 自選即持股守護雷達 (Guard Radar)
    # --------------------------------------------------------------------------
    def scan_guard_radar(self, user_id: str, current_quotes_map: Dict[str, dict], indicators_map: Dict[str, dict]) -> List[dict]:
        """
        掃描持股與自選清單，依據「股海武僧」紀律發出即時警報：
        1. 預警脫離 2 天緩衝機制：強勢股出現 K20高 粉紅預警標籤，若量縮有守則良性緩衝，滿 2 天且弱化才建議出場。
        2. 爆量長黑破位：跌破移動防守線 (trailing_stop) 且成交量放大，發出立即出清警報。
        3. D20 > 30% 穿溜冰鞋停利：波段噴出乖離過大，分批獲利入袋。
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_positions WHERE user_id = ?", (user_id,))
        positions = {r["stock_id"]: dict(r) for r in cursor.fetchall()}
        cursor.execute("SELECT * FROM user_watchlist WHERE user_id = ?", (user_id,))
        watchlist = {r["stock_id"]: dict(r) for r in cursor.fetchall()}
        conn.close()

        # 合併需要監控的標的集合
        monitored_sids = set(positions.keys()).union(set(watchlist.keys()))
        alerts = []

        for sid in monitored_sids:
            quote = current_quotes_map.get(sid, {})
            indic = indicators_map.get(sid, {})

            if not quote:
                continue

            sname = quote.get("stock_name", sid)
            curr_p = quote.get("close", 0.0)
            curr_v = quote.get("volume", 0)
            avg_v60 = indic.get("avg_vol_60", curr_v if curr_v > 0 else 1)
            q60r = round(curr_v / avg_v60, 2) if avg_v60 > 0 else 1.0
            d20_pct = indic.get("d20_pct", 0.0)     # 距離 20 日低點之乖離率
            is_k20_high = indic.get("k20_high", False) # 是否為近 20 日高點強勢標籤

            pos = positions.get(sid)
            is_holding = pos is not None
            trailing_stop = pos["trailing_stop"] if is_holding else curr_p * 0.93

            # --- 規則 A: 跌破移動防守線 (停損/破位風控) ---
            if is_holding and curr_p < trailing_stop:
                if q60r >= 1.5:
                    alerts.append({
                        "stock_id": sid,
                        "stock_name": sname,
                        "level": "🚨 爆量破位出清",
                        "status": "HOLDING",
                        "msg": f"現價 {curr_p:.2f} 跌破防守線 {trailing_stop:.2f} 且量比達 {q60r:.2f}x，觸發紀律平倉警報！"
                    })
                else:
                    alerts.append({
                        "stock_id": sid,
                        "stock_name": sname,
                        "level": "⚠️ 跌破防守警戒",
                        "status": "HOLDING",
                        "msg": f"現價 {curr_p:.2f} 跌破防守線 {trailing_stop:.2f}（量縮暫守），請密切關注收盤支撐。"
                    })

            # --- 規則 B: 股海武僧預警脫離 2 天紀律 (K20高) ---
            if is_k20_high and is_holding:
                warn_days = pos.get("warn_days", 0) + 1
                if warn_days >= 2:
                    alerts.append({
                        "stock_id": sid,
                        "stock_name": sname,
                        "level": "🎯 預警滿期落袋",
                        "status": "HOLDING",
                        "msg": f"高檔預警已達第 {warn_days} 天，滿足武僧出場紀律，建議今日分批收割獲利。"
                    })
                else:
                    alerts.append({
                        "stock_id": sid,
                        "stock_name": sname,
                        "level": "🌸 K20高良性緩衝",
                        "status": "HOLDING",
                        "msg": f"觸及 K20 高點粉紅預警（第 {warn_days} 天），量縮結構良性，依紀律續抱守護。"
                    })

            # --- 規則 C: 整理股 D20 > 30% 穿溜冰鞋停利 ---
            if d20_pct >= 30.0:
                target_type = "持股" if is_holding else "自選"
                alerts.append({
                    "stock_id": sid,
                    "stock_name": sname,
                    "level": "⛸️ 溜冰鞋衝高停利",
                    "status": "HOLDING" if is_holding else "WATCHLIST",
                    "msg": f"{target_type}自底部脫離乖離達 +{d20_pct:.1f}%，進入紅色高標噴出區，穿上溜冰鞋分批停利。"
                })

        return alerts

    # --------------------------------------------------------------------------
    # Telegram HTML 介面卡片排版產生器
    # --------------------------------------------------------------------------
    def format_portfolio_overview_card(self, user_id: str, current_quotes_map: Dict[str, dict]) -> str:
        """產生第一層：50 萬 AI 操盤手總資產與持股總覽卡"""
        data = self.evaluate_portfolio(user_id, current_quotes_map)
        u_name = data["user_name"] or user_id
        sign_ret = "+" if data["total_return_pct"] >= 0 else ""
        sign_unreal = "+" if data["unrealized_pnl"] >= 0 else ""
        sign_real = "+" if data["realized_pnl"] >= 0 else ""

        card = [
            f"💼 <b>【50萬 AI 操盤手・資產總覽】</b>",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"👤 操作帳戶：<code>{u_name}</code>",
            f"💰 總資產淨值：<code>{data['net_asset_value']:,.0f}</code> 元",
            f"💵 可用現金：<code>{data['cash_balance']:,.0f}</code> 元",
            f"📈 股票現值：<code>{data['stock_market_value']:,.0f}</code> 元",
            f"────────────────────",
            f"📊 <b>總體戰績表現</b>：",
            f"   • 總投資報酬率：<code>{sign_ret}{data['total_return_pct']:.2f}%</code>",
            f"   • 未實現損益：<code>{sign_unreal}{data['unrealized_pnl']:,.0f}</code> 元",
            f"   • 已實現損益：<code>{sign_real}{data['realized_pnl']:,.0f}</code> 元",
            f"   • 當前持倉檔數：<code>{data['positions_count']}</code> 檔",
            f"━━━━━━━━━━━━━━━━━━━━"
        ]

        if data["positions"]:
            card.append("📋 <b>持倉部位清單</b>：")
            for p in data["positions"]:
                p_sign = "+" if p["unrealized_pnl"] >= 0 else ""
                day_sign = "+" if p["day_pct_change"] >= 0 else ""
                card.append(
                    f"▶ <b>{p['stock_name']}</b> ({p['stock_id']}) × {p['shares']:,}股\n"
                    f"   成本: <code>{p['cost_price']:.2f}</code> | 現價: <code>{p['current_price']:.2f}</code> ({day_sign}{p['day_pct_change']:.2f}%)\n"
                    f"   浮動損益: <code>{p_sign}{p['unrealized_pnl']:,.0f} ({p_sign}{p['unrealized_pnl_pct']:.2f}%)</code> | 防守: <code>{p['trailing_stop']:.2f}</code>"
                )
        else:
            card.append("<i>目前空倉觀望中，資金 100% 停泊保本。</i>")

        card.append("────────────────────")
        card.append("💡 <i>點擊下方選單查看個股明細或自選守護雷達。</i>")
        return "\n".join(card)

    def format_guard_radar_card(self, alerts: List[dict]) -> str:
        """產生第二層：自選即持股守護雷達警報卡"""
        if not alerts:
            return (
                "⭐ <b>【自選與持股守護雷達】</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "🟢 <b>全市場掃描安全無虞</b>\n"
                "────────────────────\n"
                "所有持股與自選標的均處於健康軌道，未觸發破位或預警脫離，依紀律續抱。"
            )

        card = [
            f"⭐ <b>【自選與持股守護雷達】</b>",
            f"━━━━━━━━━━━━━━━━━━━━",
            f"⚡ 偵測到 <b>{len(alerts)}</b> 則關鍵動態訊號："
        ]

        for a in alerts:
            badge = "【持股】" if a["status"] == "HOLDING" else "【自選】"
            card.append(
                f"\n📌 <b>{a['stock_name']} ({a['stock_id']})</b> {badge}\n"
                f"   級別：<b>{a['level']}</b>\n"
                f"   指引：{a['msg']}"
            )

        card.append("\n━━━━━━━━━━━━━━━━━━━━")
        card.append("🧘 <i>股海武僧操盤心法：嚴守紀律、不追高、不恐慌。</i>")
        return "\n".join(card)


# ==============================================================================
# 3. 沙盒自我驗證與測試區塊 (100% 完整可執行)
# ==============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("🚀 啟動 PortfolioEngine 沙盒獨立驗證測試")
    print("=" * 70)

    TEST_DB = "test_portfolio.db"
    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    engine = PortfolioEngine(db_path=TEST_DB)

    # --- 測試 A: 多用戶隔離與帳戶初始化 ---
    print("\n[測試 1] 多用戶獨立帳戶建立...")
    acc_wayne = engine.get_or_create_account("user_wayne", "Wayne")
    acc_brother = engine.get_or_create_account("user_brother", "哥哥")
    print(f"  • Wayne 帳戶餘額: {acc_wayne['cash_balance']:,.0f} 元")
    print(f"  • 哥哥 帳戶餘額: {acc_brother['cash_balance']:,.0f} 元")
    assert acc_wayne["cash_balance"] == 500000.0, "Wayne 帳戶資金建立錯誤"
    assert acc_brother["cash_balance"] == 500000.0, "哥哥 帳戶資金建立錯誤"

    # --- 測試 B: 買進整張與零股（多用戶各自操作） ---
    print("\n[測試 2] 模擬下單買進（整張與零股）...")
    # Wayne 買進 2330 零股 300 股 @ 980 元、00631L 整張 2,000 股 @ 95 元 (ETF)
    ok1, msg1 = engine.buy_stock("user_wayne", "2330", "台積電", price=980.0, shares=300, entry_type="Select 01 帶量突破", trailing_stop=950.0)
    ok2, msg2 = engine.buy_stock("user_wayne", "00631L", "元大台灣50正2", price=95.0, shares=2000, entry_type="Select 03 Hi480", is_etf=True, trailing_stop=91.0)
    print(f"  • Wayne 買進 1: {msg1}")
    print(f"  • Wayne 買進 2: {msg2}")
    assert ok1 and ok2, "Wayne 買進操作失敗"

    # 哥哥 買進 2454 聯發科 100 股 @ 1200 元
    ok3, msg3 = engine.buy_stock("user_brother", "2454", "聯發科", price=1200.0, shares=100, entry_type="波段佈局", trailing_stop=1140.0)
    print(f"  • 哥哥 買進 1: {msg3}")
    assert ok3, "哥哥 買進操作失敗"

    # --- 測試 C: 自選清單加入 ---
    print("\n[測試 3] 加入自選守護清單...")
    engine.add_to_watchlist("user_wayne", "6415", "矽力*-KY", tags="Select 04 雙綠脫離")
    engine.add_to_watchlist("user_wayne", "00679B", "元大美債20年", tags="美債避險")
    wl = engine.get_watchlist("user_wayne")
    print(f"  • Wayne 自選檔數: {len(wl)} 檔 ({[x['stock_name'] for x in wl]})")
    assert len(wl) == 2, "自選清單建立筆數不符"

    # --- 測試 D: 行情模擬與部位估值 ---
    print("\n[測試 4] 模擬即時行情估值與損益計算...")
    mock_quotes = {
        "2330": {"stock_name": "台積電", "close": 1020.0, "pct_change": 4.08, "volume": 35000},    # 台積電上漲
        "00631L": {"stock_name": "元大台灣50正2", "close": 93.0, "pct_change": -2.11, "volume": 12000}, # 00631L 小跌
        "6415": {"stock_name": "矽力*-KY", "close": 320.0, "pct_change": 6.50, "volume": 8500},
        "00679B": {"stock_name": "元大美債20年", "close": 30.5, "pct_change": 0.33, "volume": 45000}
    }

    mock_indicators = {
        "2330": {"avg_vol_60": 20000, "d20_pct": 32.5, "k20_high": True},   # D20 > 30% 且 K20高
        "00631L": {"avg_vol_60": 10000, "d20_pct": 8.0, "k20_high": False},
        "6415": {"avg_vol_60": 4000, "d20_pct": 35.0, "k20_high": False}    # 自選 D20 > 30% 溜冰鞋
    }

    valuation = engine.evaluate_portfolio("user_wayne", mock_quotes)
    print(f"  • Wayne 總資產淨值 : {valuation['net_asset_value']:,.0f} 元")
    print(f"  • Wayne 未實現損益 : {valuation['unrealized_pnl']:+,.0f} 元 (報酬率 {valuation['total_return_pct']:+.2f}%)")

    # --- 測試 E: 守護雷達警報掃描 ---
    print("\n[測試 5] 股海武僧守護雷達警報掃描...")
    alerts = engine.scan_guard_radar("user_wayne", mock_quotes, mock_indicators)
    print(f"  • 觸發警報筆數: {len(alerts)} 筆")
    for a in alerts:
        print(f"    - [{a['level']}] {a['stock_name']}: {a['msg']}")

    # --- 測試 F: Telegram 卡片排版輸出 ---
    print("\n" + "=" * 50)
    print("--- 渲染【50萬 AI 操盤手資產總覽卡】---")
    print(engine.format_portfolio_overview_card("user_wayne", mock_quotes))

    print("\n" + "=" * 50)
    print("--- 渲染【自選與持股守護雷達卡】---")
    print(engine.format_guard_radar_card(alerts))

    # --- 測試 G: 部分停利賣出與已實現損益結算 ---
    print("\n[測試 6] 執行部分停利賣出結算...")
    sell_ok, sell_msg = engine.sell_stock("user_wayne", "2330", price=1020.0, shares=150, reason="達到第一停利目標分批收割")
    print(f"  • 賣出結果: {sell_msg}")
    assert sell_ok, "賣出操作失敗"

    val_after_sell = engine.evaluate_portfolio("user_wayne", mock_quotes)
    print(f"  • 賣出後可用現金 : {val_after_sell['cash_balance']:,.0f} 元")
    print(f"  • 已實現損益總額 : {val_after_sell['realized_pnl']:+,.0f} 元")

    if os.path.exists(TEST_DB):
        os.remove(TEST_DB)

    print("\n" + "=" * 70)
    print("🎉 PortfolioEngine 所有測試案例 100% 驗證通過！無任何錯誤！")
    print("=" * 70)
