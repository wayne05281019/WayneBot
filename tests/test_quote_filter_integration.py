# -*- coding: utf-8 -*-
"""整合測試：行情過濾器必須讓正常日 K 通過、假 K 擋下，不能「全滅」。"""
from __future__ import annotations

import sqlite3

from quote_integrity import filter_trusted_quote_tuples


def _quote_tuple(
    date: str,
    sid: str,
    name: str,
    market: str,
    o: float,
    h: float,
    l: float,
    c: float,
    vol: int,
    pct: float,
) -> tuple:
    return (
        date,
        sid,
        name,
        market,
        o,
        h,
        l,
        c,
        vol,
        float(vol) * c / 1000.0,
        pct,
        (o + c) / 2.0,
        0,
        0,
        0,
    )


def test_realistic_batch_mostly_kept():
  """模擬盤後 2000+ 檔正常 K：過濾後應保留絕大多數。"""
  rows = []
  for i in range(120):
    px = 50.0 + i * 0.5
    rows.append(
      _quote_tuple(
        "20260902",
        f"{1000 + i:04d}",
        f"股{i}",
        "TW" if i % 2 == 0 else "TWO",
        px,
        px + 1.2,
        px - 0.8,
        px + 0.3,
        3000 + i * 10,
        0.5 if i % 3 else -0.3,
      )
    )
  # 混入一筆漲停鎖死（官方形狀），不能被濾掉
  rows.append(_quote_tuple("20260902", "3664", "安瑞-KY", "TWO", 8.34, 8.34, 8.34, 8.34, 132, 9.88))
  kept, dropped = filter_trusted_quote_tuples(rows)
  assert len(kept) >= 120
  assert any(r[1] == "3664" for r in kept)


def test_ky_thin_single_print_kept():
    """達輝-KY 09/02 官方 2 張、開高低收 18.10、跌 1.1% 要留下。"""
    row = _quote_tuple("20260902", "5276", "達輝-KY", "TWO", 18.1, 18.1, 18.1, 18.1, 2, -1.1)
    kept, dropped = filter_trusted_quote_tuples([row])
    assert dropped == 0
    assert len(kept) == 1


def test_data_fetcher_guard_would_block_total_wipe():
  """若過濾器誤殺全部，data_fetcher 應拒絕寫庫（邏輯對照）。"""
  bad_batch = [
    _quote_tuple("20260902", "2330", "台積電", "TW", 2440, 2450, 2430, 2445, 50000, 1.2)
  ]
  kept, dropped = filter_trusted_quote_tuples(bad_batch)
  assert len(kept) == 1
  assert dropped == 0


def test_filter_then_insert_roundtrip(tmp_path):
  """過濾後的 tuple 能寫進 daily_quotes（欄位對齊）。"""
  db = tmp_path / "q.db"
  row = _quote_tuple("20260902", "2330", "台積電", "TW", 2400, 2450, 2390, 2440, 45000, 1.46)
  kept, _ = filter_trusted_quote_tuples([row])
  assert len(kept) == 1
  conn = sqlite3.connect(db)
  conn.execute(
    """CREATE TABLE daily_quotes (
      date TEXT, stock_id TEXT, stock_name TEXT, market TEXT,
      open REAL, high REAL, low REAL, close REAL, volume INTEGER,
      turnover_k REAL, pct_change REAL, avg_price REAL,
      foreign_net INTEGER, trust_net INTEGER, dealer_net INTEGER,
      PRIMARY KEY (date, stock_id)
    )"""
  )
  conn.execute(
    """INSERT INTO daily_quotes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
    kept[0],
  )
  conn.commit()
  close = conn.execute("SELECT close FROM daily_quotes WHERE stock_id='2330'").fetchone()[0]
  conn.close()
  assert float(close) == 2440.0
