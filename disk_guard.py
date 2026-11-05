"""永久碟空間守衛：只刪可重建出圖快取／暫存；話筒功能／查詢數字不動。

使用者鎖死（2026-10-04 改口；2026-11-03 補教具 PNG）：
- 白天：正常用；不准追高 free（舊 2.5GB／2GB 目標取消）
- 緊急：free ≈ 200～300MB 才強制清白名單可重建檔
- 每天台北 00:00：例行清白名單（_lookup_memo／wr_pair_cache／根層 scratch／
  勝率 wr 工作檔／其 .hq.jpg sidecar）
  ＋清過期可重建教具 PNG（open_day_paints；DB 對質列／官方柱／他文不動）
- 絕對不准刪：靜默對質／默默落檔（數字欄）、持股、觀察、AI倉、pending、tg 私人狀態、
  官方柱、飆大必要材料（文＋附圖 aux）、archive_1709、wayne_market.db、.corrupt-*；
  偉權與哥哥兩人資料都留
- 教具 PNG 可重建：從官方柱重渲；只留近窗日檔給話筒熱路徑；舊 force-時分堆叠必清
- 碟緊時不准 VACUUM（暫吃空間會更痛）
- 必要資料（DB＋必要 archive）持續成長：追 durable 用量趨勢，預估撐到緊急線還剩多久；
  跑道低（＜約 30 天或 free＜約 900MB）才推偉權＋哥哥兩支話筒，去重不日刷；
  訊息只講大概能撐多久／現在剩多少／建議考慮加購 Render 碟；不准自作主張買

做法：路徑白名單鎖死；從不對 SQLite 下 DELETE／DROP 私人列；checkpoint 可回收 WAL；
VACUUM 只在 free 夠寬裕時。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("WayneBot.disk_guard")

# 緊急下限：約 200～300MB 才白天強清（2026-10-04 使用者改口；取消 2GB／2.5GB 追趕）
DEFAULT_MIN_FREE_MB = 250
# 保留欄位相容／health 顯示；白天不准用它去 until_free 追趕
DEFAULT_TARGET_FREE_MB = 250
# 白天只做緊急巡檢；午夜另排
DEFAULT_INTERVAL_SEC = 30 * 60
# 可重建出圖快取／暫存：午夜例行全清白名單；白天緊急也全清白名單
DEFAULT_CHART_TTL_SEC = 24 * 60 * 60
DEFAULT_CHARTS_CAP_MB = 400
# VACUUM 至少要有這麼多 free 才考慮（遠高於緊急線）
_VACUUM_MIN_FREE_MB = 1500.0
# 跑道預警：free 低於約 800MB～1GB、或預估＜30 天撐到緊急線 → 推兩支話筒
DEFAULT_WARN_FREE_MB = 900.0
DEFAULT_RUNWAY_WARN_DAYS = 30.0
# durable 快照至少隔這麼久才再記一筆；估計至少要這段跨度才敢談趨勢
_RUNWAY_SNAPSHOT_MIN_GAP_SEC = 6 * 60 * 60
_RUNWAY_HISTORY_MAX = 60
_RUNWAY_MIN_SPAN_DAYS = 2.0
_RUNWAY_MIN_GROWTH_MB_PER_DAY = 0.5
_RUNWAY_STATE_NAME = "disk_runway_state.json"

# 只准清這些 charts 子目錄（相對 charts_dir）
ALLOW_CHART_SUBDIRS: Tuple[str, ...] = (
    "_lookup_memo",
    "wr_pair_cache",
)

# 教具活畫 PNG（可從官方柱重渲）：相對 data_dir；不准動 aux 原文附圖
TEACH_PAINT_DIR_NAME = "biaoke_open_day_paints"
LEVEL_SNAP_DIR_NAME = "biaoke_level_snaps"
# 話筒熱路徑留近 N 個台北曆日的教具圖；更舊只留 DB 數字／對質列
DEFAULT_TEACH_PAINT_KEEP_DAYS = 2
DEFAULT_LEVEL_SNAP_KEEP_DAYS = 14
# 舊 force-{ymd}-{HHMM} 每分一槽：一律可清（已改 force-{ymd} 覆寫）
_OLD_FORCE_MINUTE_RE = re.compile(
    r"^force-(\d{8})-(\d{4})(?:-|\.|$)",
    re.IGNORECASE,
)
_TEACH_YMD_RE = re.compile(
    r"^(?:force-)?(\d{8})(?:-|\.|$)",
    re.IGNORECASE,
)

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
# unique_chart_path：{code}_{kind}_{uid}_{pid}_{ms}_{seq}.png
_SCRATCH_BASENAME_RE = re.compile(
    r"^.+_.+_.+_\d+_\d+_\d+\.(?:png|jpe?g|webp)$",
    re.IGNORECASE,
)
# 勝率工作檔（可重建；正式快取在 wr_pair_cache）：{sid}_wr_{card|vz}_{uid}.jpg
_WR_WORK_BASENAME_RE = re.compile(
    r"^[0-9A-Za-z]{1,8}_wr_(?:card|vz)_\d+\.jpe?g$",
    re.IGNORECASE,
)
# scratch／工作圖旁的 Telegram 再壓 sidecar（可重建）
_HQ_SIDECAR_SUFFIXES = (".png.hq.jpg", ".jpg.hq.jpg", ".jpeg.hq.jpg", ".hq.jpg", ".hq.jpeg")

_started = False
_lock = threading.Lock()
_last_midnight_ymd = ""
_runway_lock = threading.Lock()


def _taipei_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Taipei"))
    except Exception:
        return datetime.now()


def disk_usage_mb(path: str) -> Dict[str, float]:
    """回傳 path 所在磁碟的 total/used/free（MB）。"""
    try:
        usage = shutil.disk_usage(path or ".")
    except OSError as exc:
        return {"total": 0.0, "used": 0.0, "free": 0.0, "error": str(exc)}
    return {
        "total": round(usage.total / (1024 * 1024), 1),
        "used": round(usage.used / (1024 * 1024), 1),
        "free": round(usage.free / (1024 * 1024), 1),
    }


def _runway_state_path(data_dir: str) -> str:
    root = data_dir or "."
    return os.path.join(root, _RUNWAY_STATE_NAME)


def _load_runway_state(path: str) -> Dict[str, Any]:
    if not path or not os.path.isfile(path):
        return {"snapshots": [], "last_alert": None}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError, TypeError):
        return {"snapshots": [], "last_alert": None}
    if not isinstance(raw, dict):
        return {"snapshots": [], "last_alert": None}
    snaps = raw.get("snapshots")
    if not isinstance(snaps, list):
        snaps = []
    return {"snapshots": snaps, "last_alert": raw.get("last_alert")}


def _save_runway_state(path: str, state: Dict[str, Any]) -> None:
    if not path:
        return
    parent = os.path.dirname(path) or "."
    try:
        os.makedirs(parent, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except OSError:
        logger.exception("寫入碟跑道狀態失敗")


def _is_hq_sidecar_of_rebuildable_chart(name: str) -> bool:
    """charts 根層 .hq.jpg 是否掛在可重建 scratch／勝率工作檔旁。"""
    base = os.path.basename(str(name or ""))
    lower = base.lower()
    stem = base
    for suf in _HQ_SIDECAR_SUFFIXES:
        if lower.endswith(suf):
            stem = base[: -len(suf)]
            break
    else:
        return False
    if not stem:
        return False
    # stem 可能仍帶 .png／.jpg
    if _SCRATCH_BASENAME_RE.match(stem):
        return True
    if _WR_WORK_BASENAME_RE.match(stem):
        return True
    # 2330_card_…_1.png.hq.jpg → strip 後已是 scratch；再試補副檔名
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        if _SCRATCH_BASENAME_RE.match(stem + ext) or _WR_WORK_BASENAME_RE.match(
            stem + ext
        ):
            return True
    return False


def measure_durable_mb(
    data_dir: str,
    charts_dir: str = "",
    db_path: str = "",
) -> Dict[str, float]:
    """量 durable（不可重建）用量：DB＋必要 archive／私人／官方柱等；排除白名單快取。"""
    inv = inventory_data_disk(data_dir, charts_dir=charts_dir, db_path=db_path)
    return {
        "durable_mb": float(inv.get("durable_mb") or 0.0),
        "rebuildable_mb": float(inv.get("rebuildable_mb") or 0.0),
    }


def inventory_data_disk(
    data_dir: str,
    charts_dir: str = "",
    db_path: str = "",
    *,
    top_n: int = 20,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """只讀盤點：誰在吃永久碟、哪些是確定可重建可刪。

    不准刪任何檔。class：
    - allowlist：午夜／緊急可清白名單（memo／pair／scratch／wr 工作檔／hq sidecar）
    - teach_purgable：過期教具／位階圖（可從官方柱重渲）
    - teach_hot：近窗教具（話筒熱路徑暫留）
    - db_live：正式庫＋WAL／SHM
    - db_corrupt：.corrupt-* 救援副本（現況規則不准自動刪）
    - archive：1709／club 必要 archive
    - aux：飆大原文附圖
    - other：其餘（含 decade_lab、狀態 JSON…）— 預設當必要，未盤清不准刪
    """
    root = data_dir or "."
    charts = charts_dir or os.path.join(root, "charts")
    dbp = db_path or os.path.join(root, "wayne_market.db")
    dt = now or _taipei_now()
    keep_ymd = _keep_ymd_cutoff(DEFAULT_TEACH_PAINT_KEEP_DAYS, now=dt)
    level_keep_ymd = _keep_ymd_cutoff(DEFAULT_LEVEL_SNAP_KEEP_DAYS, now=dt)

    class_mb: Dict[str, float] = {
        "allowlist": 0.0,
        "teach_purgable": 0.0,
        "teach_hot": 0.0,
        "db_live": 0.0,
        "db_corrupt": 0.0,
        "archive": 0.0,
        "aux": 0.0,
        "other": 0.0,
    }
    class_files: Dict[str, int] = {k: 0 for k in class_mb}
    parts: Dict[str, Dict[str, Any]] = {}
    top_candidates: List[Tuple[float, str, str]] = []
    corrupt_n = 0
    corrupt_files: List[Dict[str, Any]] = []

    def _bump_part(label: str, sz: float, cls: str) -> None:
        slot = parts.setdefault(
            label, {"mb": 0.0, "files": 0, "class": cls}
        )
        slot["mb"] = round(float(slot["mb"]) + sz, 3)
        slot["files"] = int(slot["files"]) + 1
        # 多類混在同一頂層時標 mixed
        if slot.get("class") not in (cls, "mixed") and slot.get("files", 0) > 1:
            slot["class"] = "mixed"

    def _classify(fp: str, name: str) -> str:
        ap = _norm(fp)
        base = os.path.basename(ap)
        low = ap.lower()
        base_l = base.lower()
        if charts and is_allowlisted_deletable(fp, charts):
            return "allowlist"
        if ".corrupt-" in base_l:
            return "db_corrupt"
        if base_l == os.path.basename(dbp).lower() or base_l in (
            os.path.basename(dbp).lower() + "-wal",
            os.path.basename(dbp).lower() + "-shm",
        ):
            return "db_live"
        if base_l.startswith("wayne_market.db"):
            # 含意外副本名
            if ".corrupt-" in base_l:
                return "db_corrupt"
            return "db_live"
        if "archive_1709" in low or "archive_club" in low:
            return "archive"
        if f"/{TEACH_PAINT_DIR_NAME}/" in low.replace("\\", "/") or low.rstrip(
            "/"
        ).endswith(f"/{TEACH_PAINT_DIR_NAME}"):
            if should_delete_teach_paint_file(
                name, keep_ymd=keep_ymd, purge_old_force_minutes=True
            ):
                return "teach_purgable"
            return "teach_hot"
        if f"/{LEVEL_SNAP_DIR_NAME}/" in low.replace("\\", "/") or low.rstrip(
            "/"
        ).endswith(f"/{LEVEL_SNAP_DIR_NAME}"):
            if should_delete_teach_paint_file(
                name, keep_ymd=level_keep_ymd, purge_old_force_minutes=False
            ):
                return "teach_purgable"
            return "teach_hot"
        if "biaoke_aux" in low:
            return "aux"
        return "other"

    def _top_label(fp: str) -> str:
        ap = _norm(fp)
        root_n = _norm(root).rstrip("/")
        if ap == root_n:
            return "."
        if ap.startswith(root_n + "/"):
            rel = ap[len(root_n) + 1 :]
            return rel.split("/", 1)[0] or "."
        return os.path.basename(ap) or "external"

    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
            for name in filenames:
                fp = os.path.join(dirpath, name)
                try:
                    sz = os.path.getsize(fp) / (1024 * 1024)
                except OSError:
                    continue
                cls = _classify(fp, name)
                class_mb[cls] = float(class_mb.get(cls) or 0.0) + sz
                class_files[cls] = int(class_files.get(cls) or 0) + 1
                if cls == "db_corrupt":
                    corrupt_n += 1
                    rel = (
                        _norm(fp)[len(_norm(root)) :].lstrip("/")
                        or os.path.basename(fp)
                    )
                    try:
                        mtime = os.path.getmtime(fp)
                    except OSError:
                        mtime = 0.0
                    corrupt_files.append(
                        {
                            "path": rel,
                            "name": os.path.basename(fp),
                            "mb": round(sz, 2),
                            "mtime": mtime,
                            "sidecar": bool(
                                str(name).endswith("-wal") or str(name).endswith("-shm")
                            ),
                        }
                    )
                _bump_part(_top_label(fp), sz, cls)
                top_candidates.append((sz, _norm(fp)[len(_norm(root)) :].lstrip("/") or os.path.basename(fp), cls))
    except OSError:
        pass

    # DB 在 data_dir 外
    for extra in (dbp, dbp + "-wal", dbp + "-shm"):
        if not extra or not os.path.isfile(extra):
            continue
        ap = _norm(extra)
        if ap.startswith(_norm(root).rstrip("/") + "/") or ap == _norm(root):
            continue
        sz = _file_mb(extra)
        class_mb["db_live"] += sz
        class_files["db_live"] += 1
        _bump_part(os.path.basename(extra), sz, "db_live")
        top_candidates.append((sz, os.path.basename(extra), "db_live"))

    rebuildable = (
        float(class_mb["allowlist"])
        + float(class_mb["teach_purgable"])
    )
    durable = sum(
        float(class_mb[k])
        for k in ("teach_hot", "db_live", "db_corrupt", "archive", "aux", "other")
    )
    top_candidates.sort(key=lambda x: x[0], reverse=True)
    top = [
        {"path": p, "mb": round(sz, 2), "class": cls}
        for sz, p, cls in top_candidates[: max(1, int(top_n))]
        if sz >= 0.05
    ]
    # parts 依 mb 排序
    parts_out = [
        {"name": k, "mb": round(float(v["mb"]), 2), "files": int(v["files"]), "class": v.get("class")}
        for k, v in sorted(parts.items(), key=lambda kv: float(kv[1]["mb"]), reverse=True)
    ]
    # 救援副本：先報「若只留最大 1 份本尊＋其 sidecar，其餘可省多少」——不准這裡真刪
    bodies = [c for c in corrupt_files if not c.get("sidecar")]
    bodies_sorted = sorted(bodies, key=lambda c: (float(c.get("mb") or 0), float(c.get("mtime") or 0)), reverse=True)
    keep_name = str(bodies_sorted[0]["name"]) if bodies_sorted else ""
    keep_prefix = keep_name  # sidecar = keep_name-wal / -shm
    reclaim = 0.0
    reclaim_names: List[str] = []
    for c in corrupt_files:
        nm = str(c.get("name") or "")
        if not keep_name:
            reclaim += float(c.get("mb") or 0)
            reclaim_names.append(nm)
            continue
        if nm == keep_name or nm.startswith(keep_prefix + "-"):
            continue
        reclaim += float(c.get("mb") or 0)
        reclaim_names.append(nm)
    # 同大小本尊（差 <1MB）標可能重複
    size_buckets: Dict[str, List[str]] = {}
    for c in bodies_sorted:
        key = f"{round(float(c.get('mb') or 0)):.0f}"
        size_buckets.setdefault(key, []).append(str(c.get("name") or ""))
    dup_groups = [v for v in size_buckets.values() if len(v) >= 2]

    return {
        "durable_mb": round(durable, 2),
        "rebuildable_mb": round(rebuildable, 2),
        "class_mb": {k: round(float(v), 2) for k, v in class_mb.items()},
        "class_files": class_files,
        "corrupt_n": corrupt_n,
        "corrupt_mb": round(float(class_mb["db_corrupt"]), 2),
        "corrupt_files": sorted(
            corrupt_files, key=lambda c: float(c.get("mb") or 0), reverse=True
        )[:40],
        "corrupt_keep_best": keep_name or None,
        "corrupt_reclaim_if_keep_best_mb": round(reclaim, 2),
        "corrupt_reclaim_names": reclaim_names[:40],
        "corrupt_same_size_groups": dup_groups[:10],
        "parts": parts_out[:40],
        "top": top,
        "teach_keep_ymd": keep_ymd,
        "level_keep_ymd": level_keep_ymd,
        "safe_delete_mb": round(rebuildable, 2),
        "ask_before_delete_mb": round(float(class_mb["db_corrupt"]), 2),
    }


def _corrupt_rank_key(row: Dict[str, Any]) -> Tuple[Any, ...]:
    """救援完整度排序：可讀→biaoke→私人→mtime；大小最後（不准當真理）。"""
    return (
        1 if row.get("readable") else 0,
        1 if row.get("probed") else 0,
        int(row.get("biaoke_n") or 0),
        int(row.get("private_n") or 0),
        float(row.get("mtime") or 0),
        float(row.get("mb") or 0),
    )


_AUDIT_RESULT_NAME = "disk_corrupt_audit_latest.json"
_audit_lock = threading.Lock()
_audit_running = False


def corrupt_audit_result_path(data_dir: str = "", db_path: str = "") -> str:
    try:
        from config import get_db_path
    except Exception:
        get_db_path = lambda: os.path.join("data", "wayne_market.db")  # type: ignore
    dbp = db_path or get_db_path()
    root = data_dir or os.path.dirname(dbp) or "."
    return os.path.join(root, _AUDIT_RESULT_NAME)


def load_corrupt_audit_result(
    data_dir: str = "", db_path: str = ""
) -> Dict[str, Any]:
    path = corrupt_audit_result_path(data_dir=data_dir, db_path=db_path)
    if not os.path.isfile(path):
        return {"ok": False, "ready": False, "error": "no_result_yet", "path": path}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data = dict(data)
            data["ready"] = True
            data["path"] = path
            return data
    except Exception as exc:
        return {"ok": False, "ready": False, "error": f"read:{exc}", "path": path}
    return {"ok": False, "ready": False, "error": "bad_json", "path": path}


def _probe_corrupt_light(cand: str) -> Tuple[bool, int, int]:
    """輕量可讀：能開庫＋計數就當 readable。不准對救援做 PRAGMA quick_check（會卡死 HTTP）。"""
    try:
        from db_recover import completeness_counts
    except Exception:
        return False, 0, 0
    try:
        biaoke_n, priv_n = completeness_counts(cand)
        # 打得開就算可讀；空庫也算探過（biaoke=0）
        return True, int(biaoke_n or 0), int(priv_n or 0)
    except Exception:
        return False, 0, 0


def start_corrupt_audit_async(
    db_path: str = "",
    *,
    data_dir: str = "",
    deep_limit: int = 8,
    max_seconds: float = 240.0,
    names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """背景跑完整度對質，結果寫 data/disk_corrupt_audit_latest.json。不准刪檔。"""
    global _audit_running
    with _audit_lock:
        if _audit_running:
            return {
                "ok": True,
                "started": False,
                "running": True,
                "note": "已有一輪在跑；稍後讀結果檔。",
            }
        _audit_running = True

    out_path = corrupt_audit_result_path(data_dir=data_dir, db_path=db_path)

    def _runner() -> None:
        global _audit_running
        try:
            result = audit_corrupt_copies(
                db_path,
                data_dir=data_dir,
                deep_limit=deep_limit,
                max_seconds=max_seconds,
                names=names,
            )
            result["finished_at"] = time.time()
            result["finished_at_taipei"] = _taipei_now().strftime("%Y-%m-%d %H:%M:%S")
            tmp = out_path + ".tmp"
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False)
            os.replace(tmp, out_path)
        except Exception:
            logger.exception("corrupt audit async 失敗")
        finally:
            with _audit_lock:
                _audit_running = False

    threading.Thread(target=_runner, name="corrupt-audit", daemon=True).start()
    return {
        "ok": True,
        "started": True,
        "running": True,
        "result_path": out_path,
        "deep_limit": int(deep_limit),
        "max_seconds": float(max_seconds),
        "note": "背景對質中；稍後 POST /ops/disk-audit {\"result\":1} 讀結果。未刪。",
    }


def audit_corrupt_copies(
    db_path: str = "",
    *,
    data_dir: str = "",
    deep_limit: int = 8,
    max_seconds: float = 120.0,
    names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """只讀對質：完整度決定留哪份，不是檔案最大。

    1) 先列齊所有 .corrupt-* 大小（不開庫）
    2) 只對「最大 deep_limit 份」做輕量計數（不跑 PRAGMA quick_check）
    3) 排名：可讀 → biaoke → 私人 → mtime；（大小僅並列最後）
    4) 與正式庫比：live 已可讀且完整度不輸 → 備援可大幅刪

    不准刪檔。
    """
    try:
        from config import get_db_path
    except Exception:
        get_db_path = lambda: os.path.join("data", "wayne_market.db")  # type: ignore

    dbp = db_path or get_db_path()
    root = data_dir or os.path.dirname(dbp) or "."
    try:
        from db_recover import MIN_BIAOKE_RESTORE, completeness_counts, list_corrupt_candidates
    except Exception as exc:
        return {"ok": False, "error": f"import:{exc}", "files": []}

    t0 = time.time()
    live_mb = _file_mb(dbp) if dbp and os.path.isfile(dbp) else 0.0
    live_biaoke = live_priv = 0
    live_ok = False
    if dbp and os.path.isfile(dbp):
        try:
            live_biaoke, live_priv = completeness_counts(dbp)
            live_ok = True
        except Exception:
            live_ok = False

    name_filter = {str(n).strip() for n in (names or []) if str(n).strip()}

    # 1) 全列大小
    listed: List[Dict[str, Any]] = []
    for cand in list_corrupt_candidates(dbp):
        name = os.path.basename(cand)
        mb = _file_mb(cand)
        wal_mb = _file_mb(cand + "-wal")
        shm_mb = _file_mb(cand + "-shm")
        try:
            mtime = os.path.getmtime(cand)
        except OSError:
            mtime = 0.0
        listed.append(
            {
                "path": cand,
                "name": name,
                "mb": round(mb, 2),
                "wal_mb": round(wal_mb, 2),
                "shm_mb": round(shm_mb, 2),
                "total_mb": round(mb + wal_mb + shm_mb, 2),
                "mtime": mtime,
                "probed": False,
                "readable": None,
                "biaoke_n": None,
                "private_n": None,
            }
        )

    by_size = sorted(listed, key=lambda r: float(r.get("total_mb") or 0), reverse=True)
    deep_n = max(1, int(deep_limit or 8))
    if name_filter:
        to_probe = [r for r in listed if str(r.get("name") or "") in name_filter]
    else:
        to_probe = by_size[:deep_n]
        # 同大小群抽 1 份（若還沒在 to_probe）
        size_buckets_pre: Dict[int, List[Dict[str, Any]]] = {}
        for r in listed:
            size_buckets_pre.setdefault(int(round(float(r.get("mb") or 0))), []).append(r)
        for _sz, group in size_buckets_pre.items():
            if len(group) < 2:
                continue
            pick = max(group, key=lambda r: float(r.get("mtime") or 0))
            if pick not in to_probe and len(to_probe) < deep_n + 5:
                to_probe.append(pick)

    size_buckets: Dict[int, List[Dict[str, Any]]] = {}
    for r in listed:
        size_buckets.setdefault(int(round(float(r.get("mb") or 0))), []).append(r)

    probed_n = 0
    timed_out = False
    for row in to_probe:
        if (time.time() - t0) >= float(max_seconds):
            timed_out = True
            break
        cand = str(row.get("path") or "")
        readable, biaoke_n, priv_n = _probe_corrupt_light(cand)
        row["probed"] = True
        row["readable"] = bool(readable)
        row["biaoke_n"] = int(biaoke_n)
        row["private_n"] = int(priv_n)
        probed_n += 1

    probed_rows = [r for r in listed if r.get("probed")]
    ranked_probed = sorted(probed_rows, key=_corrupt_rank_key, reverse=True)

    # 最佳救援＝探過的完整度冠軍（不是最大檔）
    best = ranked_probed[0] if ranked_probed else None
    keep_name = str(best["name"]) if best else None

    live_beats_best = False
    if live_ok and best and best.get("readable"):
        live_beats_best = (int(live_biaoke), int(live_priv)) >= (
            int(best.get("biaoke_n") or 0),
            int(best.get("private_n") or 0),
        )
    elif live_ok and (not best or not best.get("readable")):
        live_beats_best = True

    # 建議：live 夠用 → 最多留 1 份完整度最佳備援；否則留最佳救援當救命
    if live_ok and live_biaoke >= int(MIN_BIAOKE_RESTORE):
        recommend_keep = keep_name  # 仍留 1 份備援（完整度最佳）
        recommend_mode = "keep_one_backup"
        reason_zh = (
            f"正式庫可讀且飆大≥{MIN_BIAOKE_RESTORE}（biaoke={live_biaoke} 私人={live_priv}）。"
            f"救援只留完整度最佳 1 份備援（不是最大檔）；其餘可刪。"
        )
    elif keep_name:
        recommend_keep = keep_name
        recommend_mode = "keep_best_rescue"
        reason_zh = (
            "正式庫不夠完整或不可讀時，留完整度最佳救援（可讀→biaoke→私人→時間）；"
            "大小不作主判。"
        )
    else:
        recommend_keep = None
        recommend_mode = "none_probed"
        reason_zh = "尚未探到可讀救援；不准只依檔案大小刪。"

    reclaim = 0.0
    drop: List[str] = []
    for r in listed:
        nm = str(r.get("name") or "")
        if recommend_keep and nm == recommend_keep:
            continue
        reclaim += float(r.get("total_mb") or 0)
        drop.append(nm)

    same_size = [
        [str(x.get("name") or "") for x in grp]
        for grp in size_buckets.values()
        if len(grp) >= 2
    ]
    same_size.sort(key=len, reverse=True)

    dominated = []
    if live_ok:
        for r in probed_rows:
            if not r.get("readable"):
                dominated.append(str(r.get("name") or ""))
                continue
            if int(r.get("biaoke_n") or 0) <= int(live_biaoke) and int(
                r.get("private_n") or 0
            ) <= int(live_priv):
                dominated.append(str(r.get("name") or ""))

    largest = by_size[0] if by_size else None
    largest_is_best = bool(
        largest
        and keep_name
        and str(largest.get("name") or "") == keep_name
    )

    # 回傳：探過的詳列在前，其餘只帶大小
    out_files: List[Dict[str, Any]] = []
    for r in ranked_probed + [x for x in by_size if not x.get("probed")]:
        out_files.append(
            {
                "name": r.get("name"),
                "mb": r.get("mb"),
                "wal_mb": r.get("wal_mb"),
                "shm_mb": r.get("shm_mb"),
                "total_mb": r.get("total_mb"),
                "mtime": r.get("mtime"),
                "probed": bool(r.get("probed")),
                "readable": r.get("readable"),
                "biaoke_n": r.get("biaoke_n"),
                "private_n": r.get("private_n"),
            }
        )

    return {
        "ok": True,
        "root": root,
        "size_is_not_truth": True,
        "probe_mode": "light_counts",
        "rank_rule_zh": "可讀 → biaoke → 私人列 → mtime；（大小最後）",
        "live": {
            "path": os.path.basename(dbp),
            "mb": round(live_mb, 2),
            "readable": live_ok,
            "biaoke_n": int(live_biaoke),
            "private_n": int(live_priv),
            "biaoke_ok": int(live_biaoke) >= int(MIN_BIAOKE_RESTORE),
        },
        "files": out_files,
        "corrupt_n": len(listed),
        "corrupt_total_mb": round(
            sum(float(r.get("total_mb") or 0) for r in listed), 2
        ),
        "deep_limit": deep_n,
        "probed_n": probed_n,
        "timed_out": timed_out,
        "elapsed_s": round(time.time() - t0, 2),
        "largest_file": (largest or {}).get("name"),
        "largest_mb": (largest or {}).get("mb"),
        "largest_is_completeness_best": largest_is_best,
        "keep_best": keep_name,
        "keep_best_score": {
            "readable": (best or {}).get("readable"),
            "biaoke_n": (best or {}).get("biaoke_n"),
            "private_n": (best or {}).get("private_n"),
            "mb": (best or {}).get("mb"),
        }
        if best
        else None,
        "live_beats_best_backup": live_beats_best,
        "recommend_mode": recommend_mode,
        "recommend_keep": recommend_keep,
        "recommend_reason_zh": reason_zh,
        "reclaim_if_follow_recommend_mb": round(reclaim, 2),
        "drop_if_follow_recommend": drop,
        # 相容舊欄位名
        "reclaim_if_keep_best_mb": round(reclaim, 2),
        "drop_if_keep_best": drop,
        "same_size_groups": same_size[:15],
        "dominated_by_live": dominated,
        "note": "只讀對質；未刪。正式庫不刪。最大檔≠最正確。",
    }


def purge_confirmed_rebuildable(
    *,
    data_dir: str = "",
    charts_dir: str = "",
    db_path: str = "",
) -> Dict[str, Any]:
    """立刻刪確定可重建：白名單快取＋過期教具。不碰 DB／corrupt／aux／archive／近窗教具。"""
    return ensure_disk_headroom(
        data_dir=data_dir,
        charts_dir=charts_dir,
        db_path=db_path,
        force=True,
        mode="boot",
    )


def purge_corrupt_copies_keeping(
    db_path: str = "",
    *,
    data_dir: str = "",
    keep_names: Optional[Iterable[str]] = None,
    confirm: bool = False,
) -> Dict[str, Any]:
    """只刪 .corrupt-* 舊救援副本；正式庫永不刪。

    必須 confirm=True，且 keep_names 每份都還在碟上才動手。
    只刪 basename 符合 ``{live}.corrupt-`` 的本尊＋其 -wal／-shm。
    """
    try:
        from config import get_db_path
    except Exception:
        get_db_path = lambda: os.path.join("data", "wayne_market.db")  # type: ignore

    dbp = db_path or get_db_path()
    root = data_dir or os.path.dirname(dbp) or "."
    live_name = os.path.basename(dbp)
    keep = {str(n).strip() for n in (keep_names or []) if str(n).strip()}
    # 正式庫名若誤塞進 keep 也無妨；刪除名單永遠不含它
    keep.discard(live_name)

    out: Dict[str, Any] = {
        "ok": False,
        "deleted": False,
        "live": live_name,
        "keep": sorted(keep),
        "deleted_names": [],
        "deleted_mb": 0.0,
        "kept_ok": [],
        "missing_keep": [],
        "error": "",
    }
    if not confirm:
        out["error"] = "need_confirm"
        return out
    if not keep:
        out["error"] = "need_keep_names"
        return out
    if not dbp or not os.path.isfile(dbp):
        out["error"] = "live_db_missing"
        return out

    try:
        from db_recover import list_corrupt_candidates
    except Exception as exc:
        out["error"] = f"import:{exc}"
        return out

    # 要留的必須先在
    for name in sorted(keep):
        path = os.path.join(root, name)
        if not name.startswith(f"{live_name}.corrupt-"):
            out["error"] = f"keep_not_corrupt:{name}"
            return out
        if not os.path.isfile(path):
            out["missing_keep"].append(name)
    if out["missing_keep"]:
        out["error"] = "missing_keep"
        return out
    out["kept_ok"] = sorted(keep)

    deleted_names: List[str] = []
    deleted_mb = 0.0
    root_abs = os.path.abspath(root)
    for cand in list_corrupt_candidates(dbp):
        name = os.path.basename(cand)
        if name in keep:
            continue
        # 雙保險：必須在 data 目錄、檔名必須是 live.corrupt-*
        if os.path.abspath(os.path.dirname(cand)) != root_abs:
            continue
        if not name.startswith(f"{live_name}.corrupt-"):
            continue
        for path in (cand, cand + "-wal", cand + "-shm"):
            if not os.path.isfile(path):
                continue
            try:
                deleted_mb += _file_mb(path)
                os.remove(path)
                deleted_names.append(os.path.basename(path))
            except OSError:
                logger.exception("刪 corrupt 失敗 path=%s", path)
                out["error"] = f"delete_failed:{os.path.basename(path)}"
                out["deleted_names"] = deleted_names
                out["deleted_mb"] = round(deleted_mb, 2)
                return out

    # 刪後再確認 keep／live 都在
    if not os.path.isfile(dbp):
        out["error"] = "live_vanished_abort"
        out["deleted_names"] = deleted_names
        out["deleted_mb"] = round(deleted_mb, 2)
        return out
    for name in keep:
        if not os.path.isfile(os.path.join(root, name)):
            out["error"] = f"keep_vanished:{name}"
            out["deleted_names"] = deleted_names
            out["deleted_mb"] = round(deleted_mb, 2)
            return out

    remaining = [os.path.basename(c) for c in list_corrupt_candidates(dbp)]
    out.update(
        {
            "ok": True,
            "deleted": True,
            "deleted_names": deleted_names,
            "deleted_n": len([n for n in deleted_names if not n.endswith(("-wal", "-shm"))]),
            "deleted_mb": round(deleted_mb, 2),
            "remaining_corrupt": remaining,
            "remaining_n": len(remaining),
        }
    )
    logger.info(
        "已刪舊救援 corrupt bodies=%s mb=%.1f keep=%s remaining=%s",
        out["deleted_n"],
        out["deleted_mb"],
        sorted(keep),
        remaining,
    )
    return out


def _runway_free_bucket(free_mb: float, warn_free_mb: float, min_free_mb: float) -> str:
    free = float(free_mb)
    if free < float(min_free_mb):
        return "emergency"
    if free < float(warn_free_mb) * 0.6:
        return "lt_warn60"
    if free < float(warn_free_mb):
        return "lt_warn"
    return "ok"


def _runway_days_bucket(days: Optional[float]) -> str:
    if days is None:
        return "unknown"
    d = float(days)
    if d < 7:
        return "lt7"
    if d < 14:
        return "lt14"
    if d < 30:
        return "lt30"
    return "ok"


def estimate_disk_runway(
    *,
    data_dir: str = "",
    charts_dir: str = "",
    db_path: str = "",
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    warn_free_mb: float = DEFAULT_WARN_FREE_MB,
    warn_days: float = DEFAULT_RUNWAY_WARN_DAYS,
    record: bool = True,
    now_ts: Optional[float] = None,
    disk_usage_fn=None,
) -> Dict[str, Any]:
    """追 durable 成長、估撐到緊急線還剩多久；趨勢弱／未知就明講，不准假精準。"""
    try:
        from config import get_charts_dir, get_db_path
    except Exception:
        get_charts_dir = lambda: os.path.join("data", "charts")  # type: ignore
        get_db_path = lambda: os.path.join("data", "wayne_market.db")  # type: ignore

    dbp = db_path or get_db_path()
    charts = charts_dir or get_charts_dir()
    root = data_dir or os.path.dirname(dbp) or os.path.dirname(charts) or "."
    usage_fn = disk_usage_fn or disk_usage_mb
    usage = usage_fn(root)
    free = float(usage.get("free") or 0.0)
    total = float(usage.get("total") or 0.0)
    min_free = float(min_free_mb)
    warn_free = float(warn_free_mb)
    warn_d = float(warn_days)
    ts = float(now_ts if now_ts is not None else time.time())
    inv = inventory_data_disk(root, charts_dir=charts, db_path=dbp, top_n=15)
    durable = float(inv.get("durable_mb") or 0.0)
    sizes = {
        "durable_mb": durable,
        "rebuildable_mb": float(inv.get("rebuildable_mb") or 0.0),
    }

    state_path = _runway_state_path(root)
    with _runway_lock:
        state = _load_runway_state(state_path)
        snaps: List[Dict[str, Any]] = [
            s for s in (state.get("snapshots") or []) if isinstance(s, dict)
        ]
        if record:
            last_ts = float(snaps[-1].get("ts") or 0.0) if snaps else 0.0
            if not snaps or (ts - last_ts) >= float(_RUNWAY_SNAPSHOT_MIN_GAP_SEC):
                snaps.append(
                    {
                        "ts": ts,
                        "durable_mb": durable,
                        "free_mb": round(free, 1),
                        "total_mb": round(total, 1),
                    }
                )
                if len(snaps) > int(_RUNWAY_HISTORY_MAX):
                    snaps = snaps[-int(_RUNWAY_HISTORY_MAX) :]
                state["snapshots"] = snaps
                _save_runway_state(state_path, state)

    growth_mb_per_day: Optional[float] = None
    trend = "unknown"
    runway_days: Optional[float] = None
    headroom = max(0.0, free - min_free)
    if len(snaps) >= 2:
        first = snaps[0]
        last = snaps[-1]
        span_sec = float(last.get("ts") or 0.0) - float(first.get("ts") or 0.0)
        span_days = span_sec / 86400.0 if span_sec > 0 else 0.0
        d_grow = float(last.get("durable_mb") or 0.0) - float(
            first.get("durable_mb") or 0.0
        )
        if span_days >= float(_RUNWAY_MIN_SPAN_DAYS):
            growth_mb_per_day = d_grow / span_days
            if growth_mb_per_day >= float(_RUNWAY_MIN_GROWTH_MB_PER_DAY):
                trend = "growing"
                runway_days = headroom / growth_mb_per_day
            elif growth_mb_per_day <= -float(_RUNWAY_MIN_GROWTH_MB_PER_DAY):
                trend = "shrinking"
                runway_days = None
            else:
                trend = "flat"
                runway_days = None
        else:
            trend = "short_history"

    need_warn = False
    reasons: List[str] = []
    if free < warn_free:
        need_warn = True
        reasons.append("low_free")
    if runway_days is not None and runway_days < warn_d:
        need_warn = True
        reasons.append("short_runway")
    if free < min_free:
        need_warn = True
        reasons.append("emergency")

    level = "ok"
    if need_warn:
        if free < min_free or (runway_days is not None and runway_days < 7):
            level = "critical"
        else:
            level = "warn"

    return {
        "root": root,
        "free_mb": round(free, 1),
        "total_mb": round(total, 1),
        "durable_mb": round(durable, 2),
        "rebuildable_mb": float(sizes.get("rebuildable_mb") or 0.0),
        "min_free_mb": min_free,
        "warn_free_mb": warn_free,
        "warn_days": warn_d,
        "headroom_mb": round(headroom, 1),
        "growth_mb_per_day": (
            round(growth_mb_per_day, 3) if growth_mb_per_day is not None else None
        ),
        "trend": trend,
        "runway_days": round(runway_days, 1) if runway_days is not None else None,
        "need_warn": need_warn,
        "level": level,
        "reasons": reasons,
        "snapshot_n": len(snaps),
        "free_bucket": _runway_free_bucket(free, warn_free, min_free),
        "inventory": inv,
        "days_bucket": _runway_days_bucket(runway_days),
        "state_path": state_path,
        "last_alert": (state.get("last_alert") if isinstance(state, dict) else None),
    }


def format_runway_alert_zh(est: Dict[str, Any]) -> str:
    """短中文：大概能撐多久、現在剩多少、建議考慮加購；不准自作主張買。"""
    free = float(est.get("free_mb") or 0.0)
    min_free = float(est.get("min_free_mb") or DEFAULT_MIN_FREE_MB)
    days = est.get("runway_days")
    trend = str(est.get("trend") or "unknown")
    if days is not None:
        d = float(days)
        if d < 1:
            span = "大概還能撐不到 1 天"
        elif d < 14:
            span = f"大概還能撐約 {d:.0f} 天"
        else:
            weeks = d / 7.0
            span = f"大概還能撐約 {d:.0f} 天（約 {weeks:.0f} 週）"
    elif trend in ("flat", "shrinking"):
        span = "必要資料成長趨勢偏弱／幾乎沒長，撐多久暫時估不準"
    elif trend == "short_history":
        span = "紀錄天數還不夠，撐多久暫時估不準"
    else:
        span = "成長趨勢不明，撐多久暫時估不準"
    return (
        f"⚠️ 永久碟預警：{span}。\n"
        f"現在剩餘約 {free:.0f}MB（緊急線約 {min_free:.0f}MB）。\n"
        f"必要資料會一直長，建議考慮加購 Render 碟；我不會自己買。"
    )


def _runway_alert_signature(est: Dict[str, Any]) -> str:
    return f"{est.get('level')}|{est.get('free_bucket')}|{est.get('days_bucket')}"


def _send_family_plain(text: str) -> int:
    """推偉權＋哥哥兩支話筒；pytest／無 token 略過。"""
    if not text:
        return 0
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    if os.environ.get("WAYNE_DISK_RUNWAY_NOTIFY", "1").strip() in ("0", "false", "no"):
        return 0
    try:
        from config import allowed_telegram_uids, get_telegram_token
    except Exception:
        return 0
    token = get_telegram_token()
    uids = [str(u).strip() for u in allowed_telegram_uids() if str(u).strip()]
    if not token or not uids:
        logger.warning("碟跑道預警沒有 token 或白名單，略過")
        return 0
    import requests

    n = 0
    for cid in uids:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": cid,
                    "text": text,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if int(getattr(resp, "status_code", 0) or 0) == 200:
                n += 1
            else:
                logger.error(
                    "碟跑道預警 Telegram %s", getattr(resp, "status_code", "?")
                )
        except Exception:
            logger.exception("碟跑道預警失敗 uid 略")
    return n


def maybe_push_runway_alert(
    *,
    data_dir: str = "",
    charts_dir: str = "",
    db_path: str = "",
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    warn_free_mb: float = DEFAULT_WARN_FREE_MB,
    warn_days: float = DEFAULT_RUNWAY_WARN_DAYS,
    force: bool = False,
    send_fn=None,
    now_ts: Optional[float] = None,
    disk_usage_fn=None,
) -> Dict[str, Any]:
    """跑道低才推兩人；簽名相同／未惡化就不日刷。"""
    est = estimate_disk_runway(
        data_dir=data_dir,
        charts_dir=charts_dir,
        db_path=db_path,
        min_free_mb=min_free_mb,
        warn_free_mb=warn_free_mb,
        warn_days=warn_days,
        record=True,
        now_ts=now_ts,
        disk_usage_fn=disk_usage_fn,
    )
    out: Dict[str, Any] = {
        "estimate": est,
        "pushed": False,
        "sent": 0,
        "skipped": "",
        "text": "",
    }
    if not est.get("need_warn") and not force:
        out["skipped"] = "ok"
        return out
    sig = _runway_alert_signature(est)
    last = est.get("last_alert") if isinstance(est.get("last_alert"), dict) else None
    last_sig = str((last or {}).get("sig") or "")
    last_ts = float((last or {}).get("ts") or 0.0)
    ts = float(now_ts if now_ts is not None else time.time())
    # 同簽名且 20 小時內已推過 → 去重
    if not force and last_sig == sig and (ts - last_ts) < 20 * 3600:
        out["skipped"] = "dedupe"
        return out
    text = format_runway_alert_zh(est)
    out["text"] = text
    sender = send_fn or _send_family_plain
    sent = int(sender(text) or 0)
    out["sent"] = sent
    out["pushed"] = sent > 0 or send_fn is not None
    # 有自訂 send_fn（測）也記 last_alert，避免測試外漏推
    if out["pushed"] or force:
        state_path = str(est.get("state_path") or "")
        with _runway_lock:
            state = _load_runway_state(state_path)
            state["last_alert"] = {
                "ts": ts,
                "sig": sig,
                "level": est.get("level"),
                "free_mb": est.get("free_mb"),
                "runway_days": est.get("runway_days"),
                "ymd": _taipei_now().strftime("%Y%m%d"),
            }
            # 保留 snapshots
            if "snapshots" not in state:
                state["snapshots"] = []
            _save_runway_state(state_path, state)
        if sent:
            logger.info(
                "碟跑道預警已推 %d 人：free=%.0fMB runway=%s",
                sent,
                float(est.get("free_mb") or 0.0),
                est.get("runway_days"),
            )
    return out


def disk_health_fields(
    *,
    data_dir: str = "",
    db_path: str = "",
    charts_dir: str = "",
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    target_free_mb: float = DEFAULT_TARGET_FREE_MB,
) -> Dict[str, Any]:
    """給 /health：disk free／緊急下限／警訊／跑道。便宜、不碰 SQLite 列。

    不把 serving 變紅（Render 會重開，重開修不了碟滿）；欄位一查就知道。
    """
    try:
        from config import get_charts_dir, get_db_path
    except Exception:
        get_charts_dir = lambda: os.path.join("data", "charts")  # type: ignore
        get_db_path = lambda: os.path.join("data", "wayne_market.db")  # type: ignore

    dbp = db_path or get_db_path()
    charts = charts_dir or get_charts_dir()
    root = data_dir or os.path.dirname(dbp) or "."
    usage = disk_usage_mb(root)
    free = float(usage.get("free") or 0.0)
    min_free = float(min_free_mb)
    target = float(target_free_mb)
    if free <= 0 and usage.get("error"):
        alert = "unknown"
        alert_zh = "磁碟用量讀不到"
    elif free < min_free * 0.5:
        alert = "critical"
        alert_zh = f"碟即將滿：free {free:.0f}MB＜緊急線一半（{min_free * 0.5:.0f}MB）"
    elif free < min_free:
        alert = "below_floor"
        alert_zh = f"碟空位緊急：free {free:.0f}MB＜緊急線 {min_free:.0f}MB（將只清白名單快取）"
    elif free < float(DEFAULT_WARN_FREE_MB):
        alert = "runway_warn"
        alert_zh = f"碟空位偏低：free {free:.0f}MB＜預警線 {DEFAULT_WARN_FREE_MB:.0f}MB"
    else:
        alert = "ok"
        alert_zh = ""
    fields: Dict[str, Any] = {
        "disk_free_mb": free,
        "disk_used_mb": float(usage.get("used") or 0.0),
        "disk_total_mb": float(usage.get("total") or 0.0),
        "disk_min_free_mb": min_free,
        "disk_target_free_mb": target,
        "disk_warn_free_mb": float(DEFAULT_WARN_FREE_MB),
        "disk_ok": free >= min_free,
        "disk_alert": alert,
        "disk_alert_zh": alert_zh,
        "disk_runway_days": None,
        "disk_durable_mb": None,
        "disk_runway_trend": None,
    }
    try:
        est = estimate_disk_runway(
            data_dir=root,
            charts_dir=charts,
            db_path=dbp,
            min_free_mb=min_free,
            record=False,
        )
        fields["disk_runway_days"] = est.get("runway_days")
        fields["disk_durable_mb"] = est.get("durable_mb")
        fields["disk_runway_trend"] = est.get("trend")
        inv = est.get("inventory") if isinstance(est.get("inventory"), dict) else {}
        if inv:
            fields["disk_rebuildable_mb"] = inv.get("rebuildable_mb")
            fields["disk_safe_delete_mb"] = inv.get("safe_delete_mb")
            fields["disk_corrupt_n"] = inv.get("corrupt_n")
            fields["disk_corrupt_mb"] = inv.get("corrupt_mb")
            fields["disk_corrupt_files"] = inv.get("corrupt_files")
            fields["disk_corrupt_keep_best"] = inv.get("corrupt_keep_best")
            fields["disk_corrupt_reclaim_if_keep_best_mb"] = inv.get(
                "corrupt_reclaim_if_keep_best_mb"
            )
            fields["disk_corrupt_same_size_groups"] = inv.get(
                "corrupt_same_size_groups"
            )
            fields["disk_class_mb"] = inv.get("class_mb")
            fields["disk_parts"] = inv.get("parts")
            fields["disk_top"] = inv.get("top")
        if alert == "ok" and est.get("need_warn"):
            fields["disk_alert"] = "runway_warn"
            fields["disk_alert_zh"] = format_runway_alert_zh(est).replace("\n", " ")
    except Exception as exc:
        fields["disk_runway_trend"] = f"err:{exc}"
    return fields


def _norm(path: str) -> str:
    return os.path.abspath(path or "").replace("\\", "/")


def is_allowlisted_deletable(path: str, charts_dir: str) -> bool:
    """路徑是否落在白名單可刪區（只認 charts 下 memo／pair_cache／根層 scratch）。"""
    if not path or not charts_dir:
        return False
    ap = _norm(path)
    root = _norm(charts_dir)
    if not ap.startswith(root.rstrip("/") + "/") and ap != root:
        return False
    # 絕對不准動 DB／WAL／SHM／.corrupt-*（可能是唯一可 salvage 備份）
    base = os.path.basename(ap).lower()
    if base.startswith("wayne_market.db"):
        return False
    if ".corrupt-" in base:
        return False
    # 飆大 archive／corpus 即使誤掛在 charts 下也不動
    low = ap.lower()
    for frag in ("archive_1709", "archive_club", "/corpus/", "corpus_index"):
        if frag in low:
            return False
    rel = ap[len(root) :].lstrip("/")
    if not rel:
        return False
    parts = rel.split("/")
    # 白名單子目錄整樹
    if parts[0] in ALLOW_CHART_SUBDIRS:
        return os.path.isfile(path)
    # 只准 charts 根層可重建圖，不准進 marks／其他子目錄
    if len(parts) == 1:
        name = parts[0]
        if _SCRATCH_BASENAME_RE.match(name):
            return os.path.isfile(path)
        if _WR_WORK_BASENAME_RE.match(name):
            return os.path.isfile(path)
        if _is_hq_sidecar_of_rebuildable_chart(name):
            return os.path.isfile(path)
    return False


def _file_mb(path: str) -> float:
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return 0.0


def _unlink_allowlisted(path: str, charts_dir: str) -> float:
    """只刪白名單檔；否則 0。"""
    if not is_allowlisted_deletable(path, charts_dir):
        return 0.0
    try:
        mb = _file_mb(path)
        os.unlink(path)
        return mb
    except OSError:
        return 0.0


def _iter_allowlisted_files(charts_dir: str) -> Iterable[str]:
    """只列白名單可刪檔。"""
    if not charts_dir or not os.path.isdir(charts_dir):
        return []
    out: List[str] = []
    # 1) 白名單子目錄
    for sub in ALLOW_CHART_SUBDIRS:
        root = os.path.join(charts_dir, sub)
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                fp = os.path.join(dirpath, name)
                if is_allowlisted_deletable(fp, charts_dir):
                    out.append(fp)
    # 2) charts 根層 scratch
    try:
        for name in os.listdir(charts_dir):
            fp = os.path.join(charts_dir, name)
            if os.path.isfile(fp) and is_allowlisted_deletable(fp, charts_dir):
                out.append(fp)
    except OSError:
        pass
    return out


def _rm_empty_allowlist_dirs(charts_dir: str) -> None:
    for sub in ALLOW_CHART_SUBDIRS:
        root = os.path.join(charts_dir, sub)
        if not os.path.isdir(root):
            continue
        try:
            for dirpath, _dn, _fn in os.walk(root, topdown=False):
                if dirpath == root:
                    continue
                try:
                    if not os.listdir(dirpath):
                        os.rmdir(dirpath)
                except OSError:
                    pass
        except OSError:
            pass


def _purge_allowlisted(
    charts_dir: str,
    *,
    older_than: Optional[float] = None,
    all_files: bool = False,
) -> Tuple[int, float]:
    n = 0
    mb = 0.0
    for path in _iter_allowlisted_files(charts_dir):
        if not all_files and older_than is not None:
            try:
                if os.path.getmtime(path) >= float(older_than):
                    continue
            except OSError:
                continue
        freed = _unlink_allowlisted(path, charts_dir)
        if freed > 0:
            n += 1
            mb += freed
    _rm_empty_allowlist_dirs(charts_dir)
    return n, mb


def _purge_allowlisted_until_free(
    charts_dir: str,
    probe: str,
    *,
    want_free_mb: float,
    disk_usage_fn=None,
) -> Tuple[int, float]:
    """緊急時：依 mtime 從舊到新清白名單，直到 free ≥ want 或白名單空。"""
    usage_fn = disk_usage_fn or disk_usage_mb
    n = 0
    mb = 0.0
    paths = sorted(
        _iter_allowlisted_files(charts_dir),
        key=lambda p: os.path.getmtime(p) if os.path.isfile(p) else 0.0,
    )
    for path in paths:
        free = float(usage_fn(probe).get("free") or 0.0)
        if free >= float(want_free_mb):
            break
        freed = _unlink_allowlisted(path, charts_dir)
        if freed > 0:
            n += 1
            mb += freed
    _rm_empty_allowlist_dirs(charts_dir)
    return n, mb


def _enforce_allowlist_cap_mb(charts_dir: str, *, cap_mb: float) -> Tuple[int, float]:
    paths = list(_iter_allowlisted_files(charts_dir))
    total = sum(_file_mb(p) for p in paths)
    if total <= float(cap_mb):
        return 0, 0.0
    paths.sort(key=lambda p: os.path.getmtime(p) if os.path.isfile(p) else 0.0)
    n = 0
    mb = 0.0
    for path in paths:
        if total <= float(cap_mb):
            break
        size = _file_mb(path)
        freed = _unlink_allowlisted(path, charts_dir)
        if freed > 0:
            n += 1
            mb += freed
            total -= size
    return n, mb


def _try_wal_checkpoint(db_path: str) -> str:
    """截 WAL 回收空間；不准 DELETE 任何表。"""
    if not db_path or not os.path.isfile(db_path):
        return "skip"
    try:
        conn = sqlite3.connect(db_path, timeout=30)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
        return "ok"
    except sqlite3.Error as exc:
        return f"fail:{exc}"


def _try_vacuum_if_room(db_path: str, *, free_mb: float) -> str:
    """有足夠剩餘才 VACUUM（不刪列，只重整檔）。碟緊一律 skip。"""
    if not db_path or not os.path.isfile(db_path):
        return "skip"
    if float(free_mb) < float(_VACUUM_MIN_FREE_MB):
        return "skip_below_target"
    try:
        db_mb = os.path.getsize(db_path) / (1024 * 1024)
    except OSError:
        return "skip"
    if free_mb < db_mb * 1.15 + 50:
        return "skip_no_room"
    try:
        conn = sqlite3.connect(db_path, timeout=120)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()
        return "ok"
    except sqlite3.Error as exc:
        return f"fail:{exc}"


def _is_teach_paint_image(name: str) -> bool:
    lower = str(name or "").lower()
    if lower.endswith(".hq.jpg") or lower.endswith(".hq.jpeg"):
        return True
    return any(lower.endswith(suf) for suf in _IMAGE_SUFFIXES)


def _teach_paint_stem(name: str) -> str:
    base = os.path.basename(str(name or ""))
    stem = base
    for suf in (".png.hq.jpg", ".hq.jpg", ".hq.jpeg", ".jpeg", ".jpg", ".png", ".webp"):
        if stem.lower().endswith(suf):
            stem = stem[: -len(suf)]
            break
    return stem


def _teach_paint_ymd(name: str) -> str:
    """檔名取出台北曆日 YYYYMMDD；認不出＝空（保守不刪）。"""
    stem = _teach_paint_stem(name)
    m = _OLD_FORCE_MINUTE_RE.match(stem)
    if m:
        return m.group(1)
    m2 = _TEACH_YMD_RE.match(stem)
    if m2:
        return m2.group(1)
    # level snap：20261030_postid...
    if len(stem) >= 8 and stem[:8].isdigit() and stem[8:9] in ("_", "-"):
        return stem[:8]
    return ""


def _keep_ymd_cutoff(keep_days: int, *, now: Optional[datetime] = None) -> str:
    dt = now or _taipei_now()
    if dt.tzinfo is None:
        pass
    days = max(0, int(keep_days))
    cut = (dt - timedelta(days=days)).strftime("%Y%m%d")
    return cut


def should_delete_teach_paint_file(
    name: str,
    *,
    keep_ymd: str,
    purge_old_force_minutes: bool = True,
) -> bool:
    """可重建教具圖是否該刪。認不出日期＝False（保守）。"""
    if not _is_teach_paint_image(name):
        return False
    stem = _teach_paint_stem(name)
    if purge_old_force_minutes and _OLD_FORCE_MINUTE_RE.match(stem):
        return True
    ymd = _teach_paint_ymd(name)
    if not ymd or len(ymd) != 8:
        return False
    return ymd < str(keep_ymd)


def purge_rebuildable_teach_paints(
    data_dir: str,
    *,
    keep_days: int = DEFAULT_TEACH_PAINT_KEEP_DAYS,
    level_keep_days: int = DEFAULT_LEVEL_SNAP_KEEP_DAYS,
    now: Optional[datetime] = None,
    db_path: str = "",
) -> Dict[str, Any]:
    """清可重建教具／位階快照 PNG；DB 列與飙大 aux 原文附圖絕對不動。

    - 舊 force-{ymd}-{HHMM}* 一律刪（已改一日一槽覆寫）
    - 其餘 open_day_paints：早於 keep_days 的圖刪；話筒要圖時從柱重渲
    - level_snaps 圖：較長保留窗，過期才刪
    """
    root = data_dir or "."
    dt = now or _taipei_now()
    keep_ymd = _keep_ymd_cutoff(keep_days, now=dt)
    level_keep_ymd = _keep_ymd_cutoff(level_keep_days, now=dt)
    stats: Dict[str, Any] = {
        "files": 0,
        "mb": 0.0,
        "keep_ymd": keep_ymd,
        "level_keep_ymd": level_keep_ymd,
        "parts": {},
    }
    deleted_paths: List[str] = []

    def _purge_dir(subdir: str, *, keep: str, old_force: bool) -> Tuple[int, float]:
        path = os.path.join(root, subdir)
        if not os.path.isdir(path):
            return 0, 0.0
        n = 0
        mb = 0.0
        try:
            names = os.listdir(path)
        except OSError:
            return 0, 0.0
        for name in names:
            fp = os.path.join(path, name)
            if not os.path.isfile(fp):
                continue
            if not should_delete_teach_paint_file(
                name, keep_ymd=keep, purge_old_force_minutes=old_force
            ):
                continue
            try:
                sz = os.path.getsize(fp) / (1024 * 1024)
            except OSError:
                sz = 0.0
            try:
                os.unlink(fp)
            except OSError:
                continue
            n += 1
            mb += sz
            deleted_paths.append(fp)
        return n, mb

    n, mb = _purge_dir(TEACH_PAINT_DIR_NAME, keep=keep_ymd, old_force=True)
    stats["parts"]["open_day_paints"] = {"files": n, "mb": round(mb, 2)}
    stats["files"] += n
    stats["mb"] += mb

    n, mb = _purge_dir(LEVEL_SNAP_DIR_NAME, keep=level_keep_ymd, old_force=False)
    stats["parts"]["level_snaps"] = {"files": n, "mb": round(mb, 2)}
    stats["files"] += n
    stats["mb"] += mb

    # 路徑欄指到已刪檔 → 清空字串，下次話筒重渲；不准 DELETE 列
    dbp = db_path or os.path.join(root, "wayne_market.db")
    cleared = 0
    if deleted_paths and dbp and os.path.isfile(dbp):
        try:
            conn = sqlite3.connect(dbp, timeout=30.0)
            try:
                cols = (
                    "chart_path",
                    "tx60_path",
                    "far_path",
                    "near_path",
                    "us_path",
                    "micro_path",
                    "mine_path",
                )
                for fp in deleted_paths:
                    for col in cols:
                        try:
                            cur = conn.execute(
                                f"UPDATE biaoke_open_day_paints SET {col}='' "
                                f"WHERE {col}=?",
                                (fp,),
                            )
                            cleared += int(cur.rowcount or 0)
                        except sqlite3.Error:
                            continue
                    try:
                        cur = conn.execute(
                            "UPDATE biaoke_level_snaps SET chart_path='' "
                            "WHERE chart_path=?",
                            (fp,),
                        )
                        cleared += int(cur.rowcount or 0)
                    except sqlite3.Error:
                        pass
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error:
            logger.exception("教具圖清完後路徑欄清空略過")
    stats["paths_cleared"] = cleared
    stats["mb"] = round(float(stats["mb"]), 2)
    if stats["files"]:
        logger.info(
            "教具可重建圖已清 %d 檔約 %.1fMB（keep≥%s；舊 force-時分全清）",
            stats["files"],
            stats["mb"],
            keep_ymd,
        )
    return stats


def cleanup_rebuildable_charts(
    charts_dir: str,
    *,
    ttl_sec: float = DEFAULT_CHART_TTL_SEC,
    cap_mb: float = DEFAULT_CHARTS_CAP_MB,
    aggressive: bool = False,
    root: str = "",
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    target_free_mb: float = DEFAULT_TARGET_FREE_MB,
    disk_usage_fn=None,
    chase_target: bool = False,
) -> Dict[str, Any]:
    """只清白名單可重建出圖快取。

    aggressive／午夜：白名單全清。
    否則：只清＞TTL；可選 cap。白天不准 chase_target 追高 free。
    """
    charts_dir = charts_dir or ""
    ttl = float(ttl_sec if ttl_sec is not None else DEFAULT_CHART_TTL_SEC)
    usage_fn = disk_usage_fn or disk_usage_mb
    probe = root or charts_dir or "."
    stats: Dict[str, Any] = {
        "charts_dir": charts_dir,
        "ttl_sec": ttl,
        "min_free_mb": float(min_free_mb),
        "target_free_mb": float(target_free_mb),
        "cap_mb": float(cap_mb),
        "allow_subdirs": list(ALLOW_CHART_SUBDIRS),
        "files": 0,
        "mb": 0.0,
        "parts": {},
    }
    if not charts_dir:
        return stats

    if aggressive:
        n, mb = _purge_allowlisted(charts_dir, all_files=True)
        stats["parts"]["allowlist_all"] = {"files": n, "mb": round(mb, 2)}
    else:
        cutoff = time.time() - max(60.0, ttl)
        n, mb = _purge_allowlisted(charts_dir, older_than=cutoff, all_files=False)
        stats["parts"]["allowlist_ttl"] = {"files": n, "mb": round(mb, 2)}
    stats["files"] += n
    stats["mb"] += mb

    n, mb = _enforce_allowlist_cap_mb(
        charts_dir, cap_mb=float(cap_mb) * (0.5 if aggressive else 1.0)
    )
    stats["parts"]["cap_trim"] = {"files": n, "mb": round(mb, 2)}
    stats["files"] += n
    stats["mb"] += mb

    # 白天取消 until_free 追趕；僅緊急／明確 chase 才用
    if chase_target:
        free_now = float(usage_fn(probe).get("free") or 0.0)
        want = float(min_free_mb)
        if free_now < want:
            n, mb = _purge_allowlisted_until_free(
                charts_dir,
                probe,
                want_free_mb=want,
                disk_usage_fn=usage_fn,
            )
            stats["parts"]["until_free"] = {
                "files": n,
                "mb": round(mb, 2),
                "want_free_mb": want,
                "free_before": free_now,
            }
            stats["files"] += n
            stats["mb"] += mb

    stats["mb"] = round(float(stats["mb"]), 2)
    return stats


def ensure_disk_headroom(
    *,
    data_dir: str = "",
    charts_dir: str = "",
    db_path: str = "",
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    target_free_mb: float = DEFAULT_TARGET_FREE_MB,
    force: bool = False,
    mode: str = "",
) -> Dict[str, Any]:
    """開機／白天緊急／午夜例行：清白名單＋可重建教具圖；從不刪私人列。

    - boot：一律清確定可重建白名單（memo／pair／scratch／wr／hq）＋過期教具
      （2026-11-05 使用者鎖：確定可刪就刪，不准乾等緊急線）
    - daytime：free＜預警線或跑道 need_warn → 同上清白名單；否則只清過期教具
    - midnight／emergency：全清白名單＋教具過期圖
    - 不准刪 DB／.corrupt-*／aux／archive／近窗教具；不准追 2.5GB；碟緊不准 VACUUM
    """
    try:
        from config import get_charts_dir, get_db_path
    except Exception:
        get_charts_dir = lambda: os.path.join("data", "charts")  # type: ignore
        get_db_path = lambda: os.path.join("data", "wayne_market.db")  # type: ignore

    charts = charts_dir or get_charts_dir()
    dbp = db_path or get_db_path()
    root = data_dir or os.path.dirname(dbp) or os.path.dirname(charts) or "."
    os.makedirs(charts, exist_ok=True)

    before = disk_usage_mb(root)
    free = float(before.get("free") or 0.0)
    min_free = float(min_free_mb)
    target = float(target_free_mb)
    mode_s = str(mode or "").strip().lower()
    is_midnight = mode_s == "midnight"
    is_boot = mode_s == "boot"
    below_emergency = free < min_free
    below_warn_free = free < float(DEFAULT_WARN_FREE_MB)

    result: Dict[str, Any] = {
        "root": root,
        "before": before,
        "cleaned": False,
        "stats": {},
        "checkpoint": "skip",
        "vacuum": "skip",
        "min_free_mb": min_free,
        "target_free_mb": target,
        "mode": mode_s or ("midnight" if is_midnight else "daytime"),
    }

    # 教具 PNG 可重建：白天也清舊堆（不追高 free、不碰私人／aux／DB 列）
    teach_stats: Dict[str, Any] = {}
    try:
        teach_stats = purge_rebuildable_teach_paints(root, db_path=dbp)
    except Exception:
        logger.exception("教具可重建圖清理失敗")
        teach_stats = {"files": 0, "mb": 0.0, "error": "purge_failed"}

    runway_need = False
    if not (is_midnight or below_emergency or is_boot or below_warn_free):
        # 空間尚可時仍看跑道：短跑道／growing 預警 → 清白名單
        try:
            est = estimate_disk_runway(
                data_dir=root,
                charts_dir=charts,
                db_path=dbp,
                min_free_mb=min_free,
                record=False,
            )
            runway_need = bool(est.get("need_warn"))
            result["runway_precheck"] = {
                "need_warn": runway_need,
                "runway_days": est.get("runway_days"),
                "trend": est.get("trend"),
            }
        except Exception:
            logger.exception("碟跑道預檢失敗")
            runway_need = False

    if is_midnight:
        need = True
        aggressive = True
        reason = "midnight"
    elif below_emergency:
        need = True
        aggressive = True
        reason = "emergency"
    elif is_boot:
        need = True
        aggressive = True
        reason = "boot_safe_purge"
    elif below_warn_free or runway_need:
        need = True
        aggressive = True
        reason = "warn_safe_purge"
    else:
        # 白天：無預警 → 不追白名單、不 VACUUM；仍清教具舊圖＋記跑道
        after_day = disk_usage_mb(root)
        result["after"] = after_day
        result["reason"] = "ok_daytime"
        result["teach_paints"] = teach_stats
        result["cleaned"] = bool(int(teach_stats.get("files") or 0) > 0)
        result["stats"] = {"teach_paints": teach_stats}
        result["freed_mb_approx"] = round(
            float(after_day.get("free") or 0.0) - float(before.get("free") or 0.0), 2
        )
        try:
            result["runway"] = maybe_push_runway_alert(
                data_dir=root,
                charts_dir=charts,
                db_path=dbp,
                min_free_mb=min_free,
            )
        except Exception:
            logger.exception("碟跑道預警失敗")
            result["runway"] = {"skipped": "error"}
        if force and not below_emergency:
            logger.info(
                "磁碟守衛：無預警不追白名單（free %.1f MB）；教具可重建圖清 %s 檔",
                free,
                teach_stats.get("files") or 0,
            )
        return result

    if not need:
        result["after"] = before
        result["reason"] = "ok"
        result["teach_paints"] = teach_stats
        return result

    stats = cleanup_rebuildable_charts(
        charts,
        aggressive=aggressive,
        root=root,
        min_free_mb=min_free,
        target_free_mb=target,
        disk_usage_fn=disk_usage_mb,
        chase_target=below_emergency and not is_midnight,
    )
    stats["teach_paints"] = teach_stats
    stats["files"] = int(stats.get("files") or 0) + int(teach_stats.get("files") or 0)
    stats["mb"] = round(
        float(stats.get("mb") or 0.0) + float(teach_stats.get("mb") or 0.0), 2
    )
    result["cleaned"] = True
    result["stats"] = stats
    result["teach_paints"] = teach_stats
    result["reason"] = reason

    mid = disk_usage_mb(root)
    result["checkpoint"] = _try_wal_checkpoint(dbp)
    free_mid = float(mid.get("free") or 0.0)
    # 碟緊／剛緊急清完：不准 VACUUM
    if free_mid >= float(_VACUUM_MIN_FREE_MB):
        result["vacuum"] = _try_vacuum_if_room(dbp, free_mb=free_mid)
    else:
        result["vacuum"] = "skip_below_target"
    after = disk_usage_mb(root)
    result["after"] = after
    result["freed_mb_approx"] = round(
        float(after.get("free") or 0.0) - float(before.get("free") or 0.0), 2
    )
    try:
        result["runway"] = maybe_push_runway_alert(
            data_dir=root,
            charts_dir=charts,
            db_path=dbp,
            min_free_mb=min_free,
        )
    except Exception:
        logger.exception("碟跑道預警失敗")
        result["runway"] = {"skipped": "error"}
    logger.info(
        "磁碟守衛：free %.1f→%.1f MB（緊急線 %.0f），白名單清 %s 檔／%.2f MB（%s）checkpoint=%s vacuum=%s",
        before.get("free"),
        after.get("free"),
        min_free,
        stats.get("files"),
        stats.get("mb"),
        result["reason"],
        result["checkpoint"],
        result["vacuum"],
    )
    return result


def run_midnight_cache_purge(**kwargs) -> Dict[str, Any]:
    """台北午夜例行：只清白名單快取／scratch。"""
    return ensure_disk_headroom(mode="midnight", force=True, **kwargs)


def _seconds_until_taipei_midnight() -> float:
    now = _taipei_now()
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
    # 若剛好在 00:00～00:01，下一輪仍等明天，避免雙跑；呼叫端用 ymd 去重
    if now.hour == 0 and now.minute < 2:
        return max(30.0, (nxt - now).total_seconds())
    today_mid = now.replace(hour=0, minute=0, second=5, microsecond=0)
    if now < today_mid:
        return max(5.0, (today_mid - now).total_seconds())
    return max(30.0, (nxt - now).total_seconds())


def start_disk_guard(
    *,
    interval_sec: float = DEFAULT_INTERVAL_SEC,
    min_free_mb: float = DEFAULT_MIN_FREE_MB,
    target_free_mb: float = DEFAULT_TARGET_FREE_MB,
) -> None:
    """背景：白天只巡緊急線＋跑道；台北 00:00 例行清白名單。開機呼叫一次即可。"""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    interval = max(60.0, float(interval_sec))

    def _emergency_loop():
        time.sleep(5)
        while True:
            try:
                ensure_disk_headroom(
                    min_free_mb=min_free_mb,
                    target_free_mb=target_free_mb,
                    force=False,
                    mode="daytime",
                )
            except Exception:
                logger.exception("磁碟守衛白天巡檢失敗")
            time.sleep(interval)

    def _midnight_loop():
        global _last_midnight_ymd
        time.sleep(8)
        while True:
            try:
                wait = _seconds_until_taipei_midnight()
                time.sleep(min(wait, 3600.0))
                now = _taipei_now()
                if now.hour != 0:
                    continue
                ymd = now.strftime("%Y%m%d")
                if ymd == _last_midnight_ymd:
                    time.sleep(60)
                    continue
                run_midnight_cache_purge(
                    min_free_mb=min_free_mb,
                    target_free_mb=target_free_mb,
                )
                _last_midnight_ymd = ymd
            except Exception:
                logger.exception("磁碟守衛午夜清快取失敗")
                time.sleep(60)

    threading.Thread(target=_emergency_loop, name="disk-guard-day", daemon=True).start()
    threading.Thread(target=_midnight_loop, name="disk-guard-midnight", daemon=True).start()
    logger.info(
        "磁碟守衛已排程：白天每 %.0f 分只看緊急線 %.0f MB＋跑道預警（free＜%.0fMB／＜%.0f天）；"
        "台北 00:00 例行清白名單（cap %dMB）；不追高 free；不自作主張加購",
        interval / 60.0,
        float(min_free_mb),
        float(DEFAULT_WARN_FREE_MB),
        float(DEFAULT_RUNWAY_WARN_DAYS),
        int(DEFAULT_CHARTS_CAP_MB),
    )
