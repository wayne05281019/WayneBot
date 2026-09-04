# ==============================================================================
# WayneBot 全市場量化決策系統升級：模組三 - AI 模擬操盤手 ＆ 自選守護引擎
# 檔案名稱：portfolio_engine.py
# 核心功能：50萬本金模擬、多用戶隔離、股海武僧出場紀律、自選即持股守護雷達
# ==============================================================================

import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any


class PortfolioEngine:
    """WayneBot 投資組合與自選股守護核心引擎"""

    DEFAULT_CAPITAL = 500000.0  # 初始本金 50 萬元 TWD
    FEE_RATE = 0.001425         # 券商手續費率 0.1425% (未計折扣低消依實算)
    TAX_RATE_STOCK = 0.003      # 股票證交稅 0.3%
    TAX_RATE_ETF = 0.001        # ETF 證交稅 0.1%

    def __init__(self, db_path: str = None):
        try:
            from config import get_db_path
            default_db = get_db_path()
        except Exception:
            default_db = os.getenv("WAYNE_DB_PATH") or os.getenv("DB_PATH") or "data/wayne_market.db"
        self.db_path = db_path or default_db
        self._init_portfolio_tables()

    def _get_connection(self) -> sqlite3.Connection:
        """取得 SQLite 連線並啟用 WAL 模式以提升併發效能"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_portfolio_tables(self) -> None:
        """初始化多用戶資產、持倉、自選與交易日誌資料表"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # 1. 用戶資金表 (支援多用戶 Telegram user_id 隔離)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_funds (
            user_id TEXT PRIMARY KEY,
            cash REAL NOT NULL,
            initial_capital REAL NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)

        # 2. 用戶持倉表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_positions (
            user_id TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            shares INTEGER NOT NULL,
            cost_price REAL NOT NULL,
            highest_price REAL NOT NULL,
            buy_date TEXT NOT NULL,
            warning_days INTEGER DEFAULT 0,
            strategy_type TEXT DEFAULT 'MOMENTUM',
            PRIMARY KEY (user_id, stock_id)
        );
        """)

        # 3. 用戶自選守護表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_watchlists (
            user_id TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            entry_target REAL DEFAULT 0.0,
            defense_price REAL DEFAULT 0.0,
            added_at TEXT NOT NULL,
            PRIMARY KEY (user_id, stock_id)
        );
        """)

        # 4. 交易日誌表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            date TEXT NOT NULL,
            stock_id TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            action TEXT NOT NULL,
            shares INTEGER NOT NULL,
            price REAL NOT NULL,
            amount REAL NOT NULL,
            fee REAL NOT NULL,
            tax REAL NOT NULL,
            realized_pnl REAL DEFAULT 0.0,
            pnl_pct REAL DEFAULT 0.0,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)

        conn.commit()
        conn.close()

    # --------------------------------------------------------------------------
    # 資金與用戶初始化
    # --------------------------------------------------------------------------
    def ensure_user_exists(self, user_id: str) -> None:
        """確保用戶存在於資料庫，若無則以 50 萬本金開戶"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM user_funds WHERE user_id = ?", (str(user_id),))
        row = cursor.fetchone()
        if not row:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
            INSERT INTO user_funds (user_id, cash, initial_capital, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """, (str(user_id), self.DEFAULT_CAPITAL, self.DEFAULT_CAPITAL, now_str, now_str))
            conn.commit()
        conn.close()

    def get_cash(self, user_id: str) -> float:
        """取得用戶當前可用現金"""
        self.ensure_user_exists(user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT cash FROM user_funds WHERE user_id = ?", (str(user_id),))
        cash = cursor.fetchone()["cash"]
        conn.close()
        return float(cash)

    def _update_cash(self, conn: sqlite3.Connection, user_id: str, delta: float) -> float:
        """原子更新現金並回傳更新後餘額"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.cursor()
        cursor.execute("""
        UPDATE user_funds 
        SET cash = cash + ?, updated_at = ?
        WHERE user_id = ?
        """, (delta, now_str, str(user_id)))
        cursor.execute("SELECT cash FROM user_funds WHERE user_id = ?", (str(user_id),))
        new_cash = cursor.fetchone()["cash"]
        return float(new_cash)

    # --------------------------------------------------------------------------
    # 交易稅費計算輔助
    # --------------------------------------------------------------------------
    @classmethod
    def calculate_buy_cost(cls, stock_id: str, price: float, shares: int) -> Tuple[float, float]:
        """計算買進總成本與手續費 (手續費低消 20 元)"""
        trade_val = price * shares
        fee = max(20.0, trade_val * cls.FEE_RATE)
        total_cost = trade_val + fee
        return round(total_cost, 2), round(fee, 2)

    @classmethod
    def calculate_sell_proceeds(cls, stock_id: str, price: float, shares: int) -> Tuple[float, float, float]:
        """計算賣出實拿金額、手續費與證交稅 (ETF 稅率 0.1%，一般股票 0.3%)"""
        trade_val = price * shares
        fee = max(20.0, trade_val * cls.FEE_RATE)
        is_etf = str(stock_id).startswith("00") or str(stock_id).startswith("01")
        tax_rate = cls.TAX_RATE_ETF if is_etf else cls.TAX_RATE_STOCK
        tax = trade_val * tax_rate
        net_proceeds = trade_val - fee - tax
        return round(net_proceeds, 2), round(fee, 2), round(tax, 2)

    # --------------------------------------------------------------------------
    # 核心交易執行 (買進 / 賣出)
    # --------------------------------------------------------------------------
    def buy(self, user_id: str, date_str: str, stock_id: str, stock_name: str,
            price: float, shares: int, reason: str = "突破進場", strategy_type: str = "MOMENTUM") -> Dict[str, Any]:
        """
        執行買進操作（支援整張與零股，計入稅費）
        """
        self.ensure_user_exists(user_id)
        stock_id = str(stock_id).strip()
        total_cost, fee = self.calculate_buy_cost(stock_id, price, shares)
        available_cash = self.get_cash(user_id)

        if total_cost > available_cash:
            return {
                "success": False,
                "msg": f"資金不足！需 {total_cost:,.0f} 元，當前現金僅 {available_cash:,.0f} 元"
            }

        conn = self._get_connection()
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 扣減現金
        new_cash = self._update_cash(conn, user_id, -total_cost)

        # 查詢是否已持有該股（加碼攤平或加倉）
        cursor.execute("SELECT * FROM user_positions WHERE user_id = ? AND stock_id = ?", (str(user_id), stock_id))
        pos = cursor.fetchone()

        if pos:
            old_shares = pos["shares"]
            old_cost = pos["cost_price"]
            new_total_shares = old_shares + shares
            # 計算加權平均成本
            avg_cost = round(((old_cost * old_shares) + total_cost) / new_total_shares, 2)
            highest_p = max(pos["highest_price"], price)
            cursor.execute("""
            UPDATE user_positions 
            SET shares = ?, cost_price = ?, highest_price = ?, strategy_type = ?
            WHERE user_id = ? AND stock_id = ?
            """, (new_total_shares, avg_cost, highest_p, strategy_type, str(user_id), stock_id))
        else:
            cursor.execute("""
            INSERT INTO user_positions 
            (user_id, stock_id, stock_name, shares, cost_price, highest_price, buy_date, warning_days, strategy_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, (str(user_id), stock_id, stock_name, shares, price, price, date_str, strategy_type))

        # 寫入交易日誌
        cursor.execute("""
        INSERT INTO trade_logs 
        (user_id, date, stock_id, stock_name, action, shares, price, amount, fee, tax, realized_pnl, pnl_pct, reason, created_at)
        VALUES (?, ?, ?, ?, 'BUY', ?, ?, ?, ?, 0.0, 0.0, 0.0, ?, ?)
        """, (str(user_id), date_str, stock_id, stock_name, shares, price, total_cost, fee, reason, now_str))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "stock_id": stock_id,
            "stock_name": stock_name,
            "shares": shares,
            "price": price,
            "total_cost": total_cost,
            "remaining_cash": new_cash,
            "msg": f"買進成功！{stock_name}({stock_id}) {shares} 股，均價 {price:.2f} 元"
        }

    def sell(self, user_id: str, date_str: str, stock_id: str, price: float,
             shares: Optional[int] = None, reason: str = "紀律出場") -> Dict[str, Any]:
        """
        執行賣出操作（全出或分批出清，計算真實損益與稅費）
        """
        self.ensure_user_exists(user_id)
        stock_id = str(stock_id).strip()

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_positions WHERE user_id = ? AND stock_id = ?", (str(user_id), stock_id))
        pos = cursor.fetchone()

        if not pos:
            conn.close()
            return {"success": False, "msg": f"持倉中無標的 {stock_id}"}

        held_shares = pos["shares"]
        stock_name = pos["stock_name"]
        cost_price = pos["cost_price"]

        sell_shares = held_shares if (shares is None or shares >= held_shares) else shares
        net_proceeds, fee, tax = self.calculate_sell_proceeds(stock_id, price, sell_shares)

        # 計算已實現損益
        cost_basis = cost_price * sell_shares
        realized_pnl = round(net_proceeds - cost_basis, 2)
        pnl_pct = round((realized_pnl / cost_basis) * 100.0, 2) if cost_basis > 0 else 0.0

        # 更新現金
        new_cash = self._update_cash(conn, user_id, net_proceeds)

        # 更新持倉
        if sell_shares >= held_shares:
            cursor.execute("DELETE FROM user_positions WHERE user_id = ? AND stock_id = ?", (str(user_id), stock_id))
        else:
            remaining_shares = held_shares - sell_shares
            cursor.execute("""
            UPDATE user_positions SET shares = ? WHERE user_id = ? AND stock_id = ?
            """, (remaining_shares, str(user_id), stock_id))

        # 寫入交易日誌
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
        INSERT INTO trade_logs 
        (user_id, date, stock_id, stock_name, action, shares, price, amount, fee, tax, realized_pnl, pnl_pct, reason, created_at)
        VALUES (?, ?, ?, ?, 'SELL', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(user_id), date_str, stock_id, stock_name, sell_shares, price, net_proceeds, fee, tax, realized_pnl, pnl_pct, reason, now_str))

        conn.commit()
        conn.close()

        return {
            "success": True,
            "stock_id": stock_id,
            "stock_name": stock_name,
            "sold_shares": sell_shares,
            "price": price,
            "net_proceeds": net_proceeds,
            "realized_pnl": realized_pnl,
            "pnl_pct": pnl_pct,
            "remaining_cash": new_cash,
            "msg": f"賣出成功！{stock_name}({stock_id}) {sell_shares} 股，獲利 {realized_pnl:+,.0f} 元 ({pnl_pct:+.2f}%)"
        }

    # --------------------------------------------------------------------------
    # 自選守護雷達管理
    # --------------------------------------------------------------------------
    def add_watchlist(self, user_id: str, stock_id: str, stock_name: str = "",
                      entry_target: float = 0.0, defense_price: float = 0.0) -> bool:
        """新增或更新自選守護標的"""
        self.ensure_user_exists(user_id)
        stock_id = str(stock_id).strip()
        conn = self._get_connection()
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 若未提供名稱，嘗試從歷史庫查詢
        if not stock_name:
            cursor.execute("SELECT stock_name FROM daily_quotes WHERE stock_id = ? ORDER BY date DESC LIMIT 1", (stock_id,))
            row = cursor.fetchone()
            stock_name = row["stock_name"] if row else stock_id

        cursor.execute("""
        INSERT OR REPLACE INTO user_watchlists (user_id, stock_id, stock_name, entry_target, defense_price, added_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (str(user_id), stock_id, stock_name, entry_target, defense_price, now_str))
        conn.commit()
        conn.close()
        return True

    def remove_watchlist(self, user_id: str, stock_id: str) -> bool:
        """移除自選標的"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_watchlists WHERE user_id = ? AND stock_id = ?", (str(user_id), str(stock_id).strip()))
        affected = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return affected

    def get_watchlist(self, user_id: str) -> List[Dict[str, Any]]:
        """取得用戶全部自選股清單"""
        self.ensure_user_exists(user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_watchlists WHERE user_id = ? ORDER BY added_at DESC", (str(user_id),))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows

    # --------------------------------------------------------------------------
    # 股海武僧出場紀律 ＆ 守護雷達評估
    # --------------------------------------------------------------------------
    def evaluate_exit_signals(self, user_id: str, quotes_map: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        核心出場紀律評估：
        1. 強勢股：K20高預警脫離累積滿 2 天 -> 觸發停利/停損出場
        2. 區間整理股：獲利達到紅色高標（D20 > 30%）-> 溜冰鞋獲利了結
        3. 移動防守線：跌破前波起漲低點或 5MA/10MA 破位 -> 止損退場
        """
        self.ensure_user_exists(user_id)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_positions WHERE user_id = ?", (str(user_id),))
        positions = [dict(r) for r in cursor.fetchall()]

        exit_signals = []

        for pos in positions:
            sid = pos["stock_id"]
            if sid not in quotes_map:
                continue

            q = quotes_map[sid]
            curr_price = float(q.get("close", 0.0))
            if curr_price <= 0:
                continue

            cost_price = pos["cost_price"]
            highest_price = max(pos["highest_price"], curr_price)
            warning_days = pos["warning_days"]
            strategy = pos["strategy_type"]

            # 計算當前浮動損益比率
            pnl_pct = ((curr_price - cost_price) / cost_price) * 100.0 if cost_price > 0 else 0.0

            # 更新歷史最高價
            if curr_price > pos["highest_price"]:
                cursor.execute("UPDATE user_positions SET highest_price = ? WHERE user_id = ? AND stock_id = ?",
                               (curr_price, str(user_id), sid))

            is_warning = q.get("is_k20_warning", False)
            d20_val = q.get("d20", 0.0)

            # 規則 1：強勢股預警脫離累積 2 天
            if is_warning:
                warning_days += 1
                cursor.execute("UPDATE user_positions SET warning_days = ? WHERE user_id = ? AND stock_id = ?",
                               (warning_days, str(user_id), sid))
                if warning_days >= 2:
                    exit_signals.append({
                        "stock_id": sid,
                        "stock_name": pos["stock_name"],
                        "shares": pos["shares"],
                        "current_price": curr_price,
                        "cost_price": cost_price,
                        "pnl_pct": round(pnl_pct, 2),
                        "reason": f"武僧紀律：強勢預警脫離滿 {warning_days} 日，觸發防守出場",
                        "action": "SELL"
                    })
                    continue
            else:
                if warning_days > 0:
                    cursor.execute("UPDATE user_positions SET warning_days = 0 WHERE user_id = ? AND stock_id = ?",
                                   (str(user_id), sid))

            # 規則 2：區間波段股 D20 > 30% 溜冰鞋停利
            if strategy == "RANGE" and d20_val >= 30.0:
                exit_signals.append({
                    "stock_id": sid,
                    "stock_name": pos["stock_name"],
                    "shares": pos["shares"],
                    "current_price": curr_price,
                    "cost_price": cost_price,
                    "pnl_pct": round(pnl_pct, 2),
                    "reason": f"溜冰鞋停利：D20 達 {d20_val:.1f}% 進入超買紅標區間",
                    "action": "SELL"
                })
                continue

            # 規則 3：極限保本與風控停損（跌破成本 -7% 或自高點回撤 8%）
            drawdown_from_peak = ((highest_price - curr_price) / highest_price) * 100.0 if highest_price > 0 else 0.0
            if pnl_pct <= -7.0 or drawdown_from_peak >= 8.5:
                exit_signals.append({
                    "stock_id": sid,
                    "stock_name": pos["stock_name"],
                    "shares": pos["shares"],
                    "current_price": curr_price,
                    "cost_price": cost_price,
                    "pnl_pct": round(pnl_pct, 2),
                    "reason": f"風控停損：跌破防守線 (浮動損益 {pnl_pct:+.1f}%, 高點回撤 {drawdown_from_peak:.1f}%)",
                    "action": "SELL"
                })

        conn.commit()
        conn.close()
        return exit_signals

    # --------------------------------------------------------------------------
    # 帳戶總覽與即時損益結算
    # --------------------------------------------------------------------------
    def get_portfolio_summary(self, user_id: str, quotes_map: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        獲取多用戶獨立的總資產、現金、持股明細與即時未實現損益
        """
        self.ensure_user_exists(user_id)
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT cash, initial_capital FROM user_funds WHERE user_id = ?", (str(user_id),))
        fund = cursor.fetchone()
        cash = fund["cash"]
        initial_cap = fund["initial_capital"]

        cursor.execute("SELECT * FROM user_positions WHERE user_id = ?", (str(user_id),))
        pos_rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        total_market_val = 0.0
        total_cost_basis = 0.0
        positions_detail = []

        for p in pos_rows:
            sid = p["stock_id"]
            shares = p["shares"]
            cost_p = p["cost_price"]
            cost_basis = cost_p * shares

            curr_price = cost_p
            if quotes_map and sid in quotes_map:
                curr_price = float(quotes_map[sid].get("close", cost_p))

            market_val = curr_price * shares
            unrealized_pnl = market_val - cost_basis
            pnl_pct = (unrealized_pnl / cost_basis) * 100.0 if cost_basis > 0 else 0.0

            total_market_val += market_val
            total_cost_basis += cost_basis

            pct_chg = None
            if quotes_map and sid in quotes_map:
                try:
                    pct_chg = quotes_map[sid].get("pct_change")
                    if pct_chg is not None:
                        pct_chg = float(pct_chg)
                except (TypeError, ValueError):
                    pct_chg = None

            positions_detail.append({
                "stock_id": sid,
                "stock_name": p["stock_name"],
                "shares": shares,
                "cost_price": cost_p,
                "current_price": curr_price,
                "market_value": round(market_val, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "warning_days": p["warning_days"],
                "strategy": p["strategy_type"],
                "buy_date": p.get("buy_date") or "",
                "pct_change": pct_chg,
                "stop_price": round(cost_p * 0.93, 2) if cost_p else 0.0,
                "take_price": round(cost_p * 1.08, 2) if cost_p else 0.0,
            })

        total_assets = cash + total_market_val
        total_pnl = total_assets - initial_cap
        total_pnl_pct = (total_pnl / initial_cap) * 100.0 if initial_cap > 0 else 0.0

        return {
            "user_id": user_id,
            "cash": round(cash, 2),
            "initial_capital": round(initial_cap, 2),
            "stock_market_value": round(total_market_val, 2),
            "total_assets": round(total_assets, 2),
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "positions_count": len(positions_detail),
            "positions": positions_detail
        }

    def load_quotes_for(self, stock_ids: List[str], overlay: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
        """只查指定代號的最新收盤，給帳戶市值／漲跌用。"""
        quotes: Dict[str, Dict[str, Any]] = dict(overlay or {})
        need = []
        for raw in stock_ids or []:
            sid = str(raw or "").strip()
            if sid:
                need.append(sid)
        if not need:
            return quotes
        conn = self._get_connection()
        try:
            latest = conn.execute("SELECT MAX(date) FROM daily_quotes").fetchone()
        except sqlite3.OperationalError:
            conn.close()
            return quotes
        latest_d = latest[0] if latest else None
        found = set()
        if latest_d:
            qmarks = ",".join("?" * len(need))
            rows = conn.execute(
                f"SELECT stock_id, stock_name, close, pct_change FROM daily_quotes WHERE date=? AND stock_id IN ({qmarks})",
                (latest_d, *need),
            ).fetchall()
            for r in rows:
                sid = str(r["stock_id"])
                if float(r["close"] or 0) <= 0:
                    continue
                quotes[sid] = {
                    "stock_name": r["stock_name"] or "",
                    "close": float(r["close"] or 0),
                    "pct_change": float(r["pct_change"] or 0),
                    "is_k20_warning": bool((quotes.get(sid) or {}).get("is_k20_warning")),
                    "d20": float((quotes.get(sid) or {}).get("d20") or 0),
                }
                found.add(sid)
        for sid in need:
            if sid in found:
                continue
            row = conn.execute(
                "SELECT stock_name, close, pct_change FROM daily_quotes WHERE stock_id=? ORDER BY date DESC LIMIT 1",
                (sid,),
            ).fetchone()
            if not row or float(row["close"] or 0) <= 0:
                continue
            quotes[sid] = {
                "stock_name": row["stock_name"] or "",
                "close": float(row["close"] or 0),
                "pct_change": float(row["pct_change"] or 0),
                "is_k20_warning": False,
                "d20": 0.0,
            }
        conn.close()
        return quotes

    def format_holdings_html(self, holdings: List[Dict[str, Any]], quotes_map: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
        from tg_layout import (
            html_escape,
            html_last_move,
            html_money,
            html_num_paren,
            html_price,
            html_holdings_qty,
            kv_compact,
            kv_html_compact,
            price_change,
            section_eq,
            _plain_num,
        )

        if not holdings:
            return (
                f"{section_eq('我的持股（手記）')}\n"
                "這頁是「你已經買了」的紀錄，空的代表還沒記過買入。\n"
                "做法：打南亞或 2330 → 按「記買入」→ 輸入 <code>1 68.5</code>（張數 價格）。"
            )
        ids = [str(h.get("stock_code") or h.get("stock_id") or "") for h in holdings]
        quotes_map = self.load_quotes_for(ids, quotes_map)
        sell_notes = {}
        try:
            from sell_discipline import sell_notes_for_stocks

            sell_notes = sell_notes_for_stocks(ids, self.db_path, full=True)
        except Exception:
            sell_notes = {}
        lines = [section_eq("我的持股（手記）"), "自己記的真實買入，不是觀察、也不是 AI 模擬倉。"]
        for h in holdings:
            code = str(h.get("stock_code") or h.get("stock_id") or "")
            name = str(h.get("stock_name") or "")
            lots = float(h.get("shares") or 0)
            cost = float(h.get("cost_price") or 0)
            q = (quotes_map or {}).get(code) or {}
            last = float(q.get("close") or cost or 0)
            pct = q.get("pct_change")
            shares_n = lots * 1000.0
            mkt = last * shares_n
            cost_amt = cost * shares_n
            u_pnl = mkt - cost_amt
            u_pct = (u_pnl / cost_amt * 100.0) if cost_amt else 0.0
            chg = price_change(last, pct) if pct is not None else None
            try:
                from stock_links import html_stock_anchor

                title = html_stock_anchor(code, name, self.db_path)
            except Exception:
                title = f"<code>{html_escape(code)}</code> {html_escape(name)}"
            lines.append(title)
            lines.append(kv_html_compact("張數", html_holdings_qty(lots)))
            lines.append(kv_html_compact("成本", html_price(cost, compact=True)))
            if chg is not None and pct is not None:
                lines.append(kv_html_compact("現價", html_last_move(last, chg, pct, compact=True)))
            else:
                lines.append(kv_html_compact("現價", html_price(last, compact=True)))
            lines.append(kv_html_compact("未實現", html_num_paren(_plain_num(u_pnl, signed=True), u_pct, compact=True)))
            lines.append(kv_html_compact("市值", html_money(mkt, signed=False, compact=True)))
            note = sell_notes.get(code) or ""
            if note:
                lines.append(kv_compact("紀律", note))
            if h is not holdings[-1]:
                lines.append("")
        return "\n".join(lines)


# ==============================================================================
# 單元沙盒自我驗收測試 (Colab / 本地直接執行驗證)
# ==============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("🧪 啟動 PortfolioEngine 模擬操盤與自選守護引擎驗收測試")
    print("=" * 70)

    test_db = "test_waynebot_portfolio.db"
    if os.path.exists(test_db):
        os.remove(test_db)

    engine = PortfolioEngine(db_path=test_db)

    # 1. 測試用戶初始化
    test_user = "user_wayne_01"
    cash_init = engine.get_cash(test_user)
    print(f"1. 用戶開戶初始本金 : {cash_init:,.0f} 元 (預期 500,000)")
    assert cash_init == 500000.0, "初始資金驗證失敗"

    # 2. 測試買進台積電 (2330) 1 張 (1,000 股) @ 1,000 元
    buy_res = engine.buy(
        user_id=test_user,
        date_str="20260829",
        stock_id="2330",
        stock_name="台積電",
        price=100.0,
        shares=1000,
        reason="Select 01 突破新高"
    )
    print(f"2. 買進測試結果       : {buy_res['msg']}")
    assert buy_res["success"] is True, "買進操作失敗"

    # 3. 測試持倉損益結算 (模擬台積電漲至 108 元)
    mock_quotes = {
        "2330": {"close": 108.0, "is_k20_warning": False, "d20": 15.0}
    }
    summary = engine.get_portfolio_summary(test_user, mock_quotes)
    print(f"3. 帳戶總資產結算     : {summary['total_assets']:,.0f} 元 | 總損益: {summary['total_pnl']:+,.0f} ({summary['total_pnl_pct']:+.2f}%)")
    assert summary["positions_count"] == 1, "持倉檔數不符"

    # 4. 測試武僧紀律預警脫離連續 2 日出場
    mock_warning_quotes = {
        "2330": {"close": 107.0, "is_k20_warning": True, "d20": 28.0}
    }
    _ = engine.evaluate_exit_signals(test_user, mock_warning_quotes)  # 第 1 天預警
    exit_signals = engine.evaluate_exit_signals(test_user, mock_warning_quotes)  # 第 2 天預警
    print(f"4. 出場訊號評估       : 偵測到 {len(exit_signals)} 個出場建議 -> {exit_signals[0]['reason']}")
    assert len(exit_signals) == 1, "武僧 2 天出場信號未正確觸發"

    # 5. 測試賣出結算
    sell_res = engine.sell(
        user_id=test_user,
        date_str="20260830",
        stock_id="2330",
        price=107.0,
        reason=exit_signals[0]["reason"]
    )
    print(f"5. 賣出結算結果       : {sell_res['msg']}")
    assert sell_res["success"] is True, "賣出結算失敗"

    # 清理測試庫
    if os.path.exists(test_db):
        os.remove(test_db)

    print("\n✅ 所有單元驗證 100% 通過！可安全替換至 Git 根目錄。")
    print("=" * 70)
