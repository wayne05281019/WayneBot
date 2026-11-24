# CI smoke 縮小（2026-11-23）

舊 `smoke-no-db`：`pytest -m "not production_db"` ≈4350 測（含出圖／長 e2e），約 60 分；現改 `-m smoke`（`tests/smoke_classify.py` 自動掛 `smoke`／`render`／`slow`），出圖與長測只留 `full-suite`，快篩目標 ≤10–15 分。不恢復全域 per-test timeout（#501）。
