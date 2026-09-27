# -*- coding: utf-8 -*-
"""季報 latest 標籤：不准 MAX(year)×MAX(season) 拼出不存在的季。"""
from __future__ import annotations

import os
import sqlite3
import tempfile

from emerging_quotes import ensure_emerging_table
from import_health import MIN_EM, MIN_TWO, MIN_TW, audit_import, inventory_payload
from wayne_db import ensure_core_schema


def test_audit_latest_quarter_uses_same_row_not_max_cross():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ensure_core_schema(path)
        ensure_emerging_table(path)
        conn = sqlite3.connect(path)
        for i in range(MIN_TW):
            conn.execute(
                """INSERT INTO daily_quotes
                (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
                VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,10,0,0)""",
                ("20260924", f"{1000+i:04d}", "TW", "TW"),
            )
        for i in range(MIN_TWO):
            conn.execute(
                """INSERT INTO daily_quotes
                (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
                VALUES (?,?,?,?,10,11,9,10,1000,10,0.5,10,50,0,0)""",
                ("20260924", f"{6000+i:04d}", "TWO", "TWO"),
            )
        for i in range(MIN_EM):
            conn.execute(
                """INSERT INTO emerging_quotes
                (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,source)
                VALUES (?,?,?,?,10,11,9,10,0.185,1,0,10,'t')""",
                ("20260924", f"{7000+i:04d}", "EM", "EM"),
            )
        # 2025Q4 + 2026Q2：舊寫法 MAX(year),MAX(season) 會拼出假 2026Q4
        conn.execute(
            """INSERT INTO quarterly_income
            (stock_id,year,season,stock_name,market,revenue,gross_profit,gross_margin_pct,operating_income,net_income,eps)
            VALUES ('2330',2025,4,'台積','TW',1,1,1,1,1,1)"""
        )
        conn.execute(
            """INSERT INTO quarterly_income
            (stock_id,year,season,stock_name,market,revenue,gross_profit,gross_margin_pct,operating_income,net_income,eps)
            VALUES ('2454',2026,2,'聯發','TW',1,1,1,1,1,1)"""
        )
        conn.commit()
        conn.close()
        health = audit_import(path, "20260924")
        assert health["latest_quarter"] == "2026Q2"
        assert health["em"] == MIN_EM
        # inventory 有 1MB 下限；小測庫只驗 payload 組裝鍵（mock 過 quick_check）
        from unittest.mock import patch

        with patch("import_health.db_quick_check_ok", return_value=True):
            inv = inventory_payload(path)
        assert inv["quotes"]["em"] == MIN_EM
        assert inv["emerging_quotes"]["latest_n"] == MIN_EM
        assert "em_rows" in inv["monthly_revenue"]
    finally:
        os.remove(path)
