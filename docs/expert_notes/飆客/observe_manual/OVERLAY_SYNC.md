# 飆大 overlay 同步（SYNC-OVERLAY）

目標：把公開主文＋他自己回文＋附圖 URL 補到**今日**，餵 atoms／圖比對。  
邊界：`MISSION_LOCK_20261123.md`；只認他自己；社團不准話筒原文；不准假圖。

## 本機／Render 有碟

```bash
# 預設讀 config.get_db_path()（Render 永久碟 data/wayne_market.db）
python3 scripts/biaoke_sync_overlay_heal.py

# 指定碟＋只補主文（略過自回，較快）
python3 scripts/biaoke_sync_overlay_heal.py --db /opt/render/project/src/data/wayne_market.db --no-replies

# 自訂起日（預設 2026-09-10＝1709 末日）
python3 scripts/biaoke_sync_overlay_heal.py --since 2026-09-10
```

流程：`seed_biaoke_archive`（1709＋git catchup）→ Member-All 深抓 → 討論串自回 → 凍 `overlay_delta.json.gz` → 增量 chart_index → 重抽 atoms。

## 雲端無 Render 碟

- 仍可對公開 API 深抓，寫進本機暫存 DB 後匯出 `overlay_delta.json.gz`（進 git／observe_manual）。
- atoms 會合併：archive_1709 ＋ catchup ＋ **overlay_delta** ＋ DB overlay ＋社團後台。
- 正式碟上線後再跑同一腳本 UPSERT，讓 Render `biaoke_posts` 與 delta 對齊。

## 不准

- 假圖／假柱；把社團原文當公開 overlay
- 搶正式 `TELEGRAM_BOT_TOKEN` getUpdates
- 改黃金買點
