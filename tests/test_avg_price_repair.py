# -*- coding: utf-8 -*-
"""櫃買均價歷史修復。"""


def test_repair_bad_avg_prices_fixes_share_count(tmp_path, monkeypatch):
    import sqlite3

    from data_fetcher import DataFetcher
    from wayne_db import ensure_core_schema

    db = str(tmp_path / "t.db")
    ensure_core_schema(db)
    conn = sqlite3.connect(db)
    conn.execute(
        """
        INSERT INTO daily_quotes
        (date,stock_id,stock_name,market,open,high,low,close,volume,turnover_k,pct_change,avg_price,foreign_net,trust_net,dealer_net)
        VALUES ('20260902','3693','營邦','TWO',627,654,626,642,2060,1324240,2.88,2060000,0,0,0)
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(DataFetcher, "_ensure_database_ready", lambda self: None)
    rep = DataFetcher(db_path=db, github_release_url="").repair_bad_avg_prices(since="20260901")
    assert rep["fixed"] == 1
    conn = sqlite3.connect(db)
    avg = conn.execute(
        "SELECT avg_price FROM daily_quotes WHERE stock_id='3693'"
    ).fetchone()[0]
    conn.close()
    assert 640 <= avg <= 645
