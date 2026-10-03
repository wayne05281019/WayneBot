# -*- coding: utf-8 -*-
"""行情庫損毀／wal-shm 錯位時的復原。

碟滿後 quick_check 失敗會把 wayne_market.db 搬成 .corrupt-*。
若只搬 .db、留下 -wal／-shm，Release 裝回後會套到舊 WAL → 永遠讀不到。
救回順序：清 sidecar → 可開且 biaoke≥1700 的 .corrupt-* → 再 Release。
不准刪私人表／silent 落檔／官方 OHLC（整檔搬移或整檔覆蓋，不做 DELETE）。
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import tempfile
import time
import zipfile
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger("WayneBot.db_recover")

# 與 biaoke_archive.ARCHIVE_BASELINE_N 對齊；避免循環 import 寫死常數。
MIN_BIAOKE_RESTORE = 1700


def sidecar_paths(db_path: str) -> Tuple[str, str]:
    return f"{db_path}-wal", f"{db_path}-shm"


def has_sidecars(db_path: str) -> bool:
    wal, shm = sidecar_paths(db_path)
    return os.path.isfile(wal) or os.path.isfile(shm)


def remove_sidecars(db_path: str) -> List[str]:
    """刪掉錯位的 -wal／-shm。回傳已刪路徑。"""
    removed: List[str] = []
    for side in sidecar_paths(db_path):
        if not os.path.isfile(side):
            continue
        try:
            os.remove(side)
            removed.append(side)
        except OSError:
            logger.exception("無法刪除 sidecar %s", side)
    return removed


def move_db_with_sidecars(src: str, dest: str) -> None:
    """把 .db 與同名 -wal／-shm 一起搬到 dest（SQLite 才認得出）。"""
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.isfile(src):
        shutil.move(src, dest)
    for suffix in ("-wal", "-shm"):
        s = f"{src}{suffix}"
        d = f"{dest}{suffix}"
        if os.path.isfile(s):
            try:
                shutil.move(s, d)
            except OSError:
                logger.exception("搬移 sidecar 失敗 %s → %s，改刪", s, d)
                try:
                    os.remove(s)
                except OSError:
                    pass


def quarantine_db(db_path: str, *, tag: Optional[str] = None) -> Optional[str]:
    """把壞庫（含 sidecar）搬成 path.corrupt-TS。沒有本尊則只清 sidecar。"""
    if not os.path.isfile(db_path):
        remove_sidecars(db_path)
        return None
    stamp = tag or str(int(time.time()))
    dest = f"{db_path}.corrupt-{stamp}"
    # 避免撞名
    n = 0
    while os.path.exists(dest):
        n += 1
        dest = f"{db_path}.corrupt-{stamp}-{n}"
    move_db_with_sidecars(db_path, dest)
    # 正式路徑上不准留殘 sidecar
    remove_sidecars(db_path)
    return dest


def biaoke_post_count(db_path: str) -> int:
    """主文筆數（不含 reply）。讀不到回 0。"""
    if not db_path or not os.path.isfile(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path, timeout=2.0)
        try:
            hit = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='biaoke_posts'"
            ).fetchone()
            if not hit:
                return 0
            row = conn.execute(
                "SELECT COUNT(*) FROM biaoke_posts "
                "WHERE IFNULL(kind,'post')!='reply'"
            ).fetchone()
            return int((row or [0])[0] or 0)
        finally:
            conn.close()
    except Exception:
        return 0


def list_corrupt_candidates(db_path: str) -> List[str]:
    """同目錄下 path.corrupt-* 本尊（不含其 -wal／-shm）。"""
    parent = os.path.dirname(db_path) or "."
    base = os.path.basename(db_path)
    prefix = f"{base}.corrupt-"
    out: List[str] = []
    try:
        names = os.listdir(parent)
    except OSError:
        return []
    for name in names:
        if not name.startswith(prefix):
            continue
        if name.endswith("-wal") or name.endswith("-shm"):
            continue
        cand = os.path.join(parent, name)
        if os.path.isfile(cand):
            out.append(cand)
    return out


def _candidate_readable(cand: str, check) -> bool:
    """corrupt 可讀才整檔救回；先清它自己的錯位 wal/shm 再驗。"""
    if check(cand):
        return True
    if has_sidecars(cand):
        remove_sidecars(cand)
        return bool(check(cand))
    return False


def best_corrupt_restore(
    db_path: str,
    *,
    min_biaoke: int = MIN_BIAOKE_RESTORE,
    quick_check=None,
) -> Optional[str]:
    """可 quick_check 且 biaoke 主文 ≥ min 的最佳 .corrupt-*。"""
    from import_health import db_quick_check_ok

    check = quick_check or (lambda p: db_quick_check_ok(p, min_bytes=1))
    ranked: List[Tuple[int, float, str]] = []
    for cand in list_corrupt_candidates(db_path):
        if not _candidate_readable(cand, check):
            continue
        n = biaoke_post_count(cand)
        if n < int(min_biaoke):
            continue
        try:
            mtime = os.path.getmtime(cand)
        except OSError:
            mtime = 0.0
        ranked.append((n, mtime, cand))
    if not ranked:
        return None
    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return ranked[0][2]


def _shared_columns(
    conn: sqlite3.Connection,
    main_table: str,
    *,
    src_schema: str,
    src_table: str,
) -> List[str]:
    main_cols = [str(r[1]) for r in conn.execute(f"PRAGMA table_info({main_table})")]
    # ATTACH schema 要用 PRAGMA schema.table_info(name)，不能 table_info(schema.name)
    src_cols = {
        str(r[1])
        for r in conn.execute(f"PRAGMA {src_schema}.table_info({src_table})")
    }
    return [c for c in main_cols if c in src_cols]


def salvage_biaoke_from_corrupts(
    db_path: str,
    *,
    min_gain: int = 1,
) -> dict:
    """正式庫可讀但 biaoke 空／偏少時：ATTACH 各 .corrupt-* 把 biaoke 列 INSERT OR IGNORE 回來。

    不用整檔覆蓋（保留已裝好的官方柱）；也不刪 corrupt。
    quick_check 紅但仍能 SELECT 的 corrupt 也試。
    """
    from biaoke_desk import ensure_biaoke_posts_table

    ensure_biaoke_posts_table(db_path)
    try:
        from biaoke_neurons import ensure_neuron_hits_table

        ensure_neuron_hits_table(db_path)
    except Exception:
        pass
    before = biaoke_post_count(db_path)
    merged = 0
    sources: List[str] = []
    for cand in list_corrupt_candidates(db_path):
        if has_sidecars(cand):
            remove_sidecars(cand)
        n = biaoke_post_count(cand)
        if n < int(min_gain):
            continue
        alias = "bk_salvage"
        try:
            conn = sqlite3.connect(db_path, timeout=30.0)
            try:
                conn.execute(f"ATTACH DATABASE ? AS {alias}", (cand,))
                hit = conn.execute(
                    f"SELECT 1 FROM {alias}.sqlite_master "
                    "WHERE type='table' AND name='biaoke_posts'"
                ).fetchone()
                if not hit:
                    conn.execute(f"DETACH DATABASE {alias}")
                    continue
                cols = _shared_columns(
                    conn, "biaoke_posts", src_schema=alias, src_table="biaoke_posts"
                )
                if cols:
                    col_list = ", ".join(cols)
                    cur = conn.execute(
                        f"INSERT OR IGNORE INTO biaoke_posts ({col_list}) "
                        f"SELECT {col_list} FROM {alias}.biaoke_posts"
                    )
                    merged += int(cur.rowcount or 0)
                try:
                    nh = conn.execute(
                        f"SELECT 1 FROM {alias}.sqlite_master "
                        "WHERE type='table' AND name='biaoke_neuron_hits'"
                    ).fetchone()
                    if nh:
                        ncols = _shared_columns(
                            conn,
                            "biaoke_neuron_hits",
                            src_schema=alias,
                            src_table="biaoke_neuron_hits",
                        )
                        if ncols:
                            nlist = ", ".join(ncols)
                            conn.execute(
                                f"INSERT OR IGNORE INTO biaoke_neuron_hits ({nlist}) "
                                f"SELECT {nlist} FROM {alias}.biaoke_neuron_hits"
                            )
                except sqlite3.Error:
                    pass
                conn.commit()
                conn.execute(f"DETACH DATABASE {alias}")
                sources.append(os.path.basename(cand))
            finally:
                conn.close()
        except Exception:
            logger.exception("ATTACH 救 biaoke 失敗 cand=%s", cand)
    after = biaoke_post_count(db_path)
    return {
        "before": before,
        "after": after,
        "merged_rows": merged,
        "sources": sources,
    }


def table_row_count(db_path: str, table: str) -> int:
    if not db_path or not os.path.isfile(db_path) or not table:
        return 0
    try:
        conn = sqlite3.connect(db_path, timeout=2.0)
        try:
            hit = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not hit:
                return 0
            row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
            return int((row or [0])[0] or 0)
        finally:
            conn.close()
    except Exception:
        return 0


def private_row_counts(db_path: str) -> dict:
    """PRIVATE_USER_TABLES 各表列數（只回數字，不含 uid／內容）。"""
    from wayne_db import PRIVATE_USER_TABLES

    out: dict = {}
    for table in PRIVATE_USER_TABLES:
        n = table_row_count(db_path, table)
        if n:
            out[table] = n
    return out


def private_row_total(db_path: str) -> int:
    return int(sum(private_row_counts(db_path).values()))


def salvage_private_from_corrupts(db_path: str) -> dict:
    """從 .corrupt-* ATTACH 救回 PRIVATE_USER_TABLES（持股／觀察／AI倉／pending／tg…）。

    INSERT OR IGNORE；不刪 corrupt；不把 uid 寫進 log（只記表名＋列數）。
    """
    from wayne_db import PRIVATE_USER_TABLES

    before = private_row_total(db_path)
    merged_by_table: dict = {}
    sources: List[str] = []
    for cand in list_corrupt_candidates(db_path):
        if has_sidecars(cand):
            remove_sidecars(cand)
        if private_row_total(cand) <= 0:
            continue
        alias = "priv_salvage"
        try:
            conn = sqlite3.connect(db_path, timeout=30.0)
            try:
                conn.execute(f"ATTACH DATABASE ? AS {alias}", (cand,))
                src_tables = {
                    str(r[0])
                    for r in conn.execute(
                        f"SELECT name FROM {alias}.sqlite_master WHERE type='table'"
                    )
                }
                main_tables = {
                    str(r[0])
                    for r in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                for table in PRIVATE_USER_TABLES:
                    if table not in src_tables:
                        continue
                    if table not in main_tables:
                        ddl = conn.execute(
                            f"SELECT sql FROM {alias}.sqlite_master "
                            "WHERE type='table' AND name=?",
                            (table,),
                        ).fetchone()
                        if not ddl or not ddl[0]:
                            continue
                        try:
                            conn.execute(str(ddl[0]))
                            main_tables.add(table)
                        except sqlite3.Error:
                            logger.exception("建立私人表失敗 table=%s", table)
                            continue
                    cols = _shared_columns(
                        conn, table, src_schema=alias, src_table=table
                    )
                    if not cols:
                        continue
                    col_list = ", ".join(f'"{c}"' for c in cols)
                    try:
                        cur = conn.execute(
                            f'INSERT OR IGNORE INTO "{table}" ({col_list}) '
                            f'SELECT {col_list} FROM {alias}."{table}"'
                        )
                        got = int(cur.rowcount or 0)
                        if got > 0:
                            merged_by_table[table] = int(
                                merged_by_table.get(table, 0)
                            ) + got
                    except sqlite3.Error:
                        logger.exception("合併私人表失敗 table=%s", table)
                conn.commit()
                conn.execute(f"DETACH DATABASE {alias}")
                sources.append(os.path.basename(cand))
            finally:
                conn.close()
        except Exception:
            logger.exception("ATTACH 救私人表失敗 cand=%s", cand)
    after = private_row_total(db_path)
    return {
        "before": before,
        "after": after,
        "merged_by_table": merged_by_table,
        "sources": sources,
    }


def restore_corrupt_to_path(corrupt_path: str, db_path: str) -> bool:
    """把選定的 .corrupt-*（含 sidecar）移回正式路徑。"""
    if not corrupt_path or not os.path.isfile(corrupt_path):
        return False
    # 正式路徑若還有東西，先另存，避免蓋掉
    if os.path.isfile(db_path) or has_sidecars(db_path):
        quarantine_db(db_path)
    remove_sidecars(db_path)
    move_db_with_sidecars(corrupt_path, db_path)
    return os.path.isfile(db_path)


def install_release_db(
    db_path: str,
    *,
    url: Optional[str] = None,
    urlretrieve=None,
) -> bool:
    """下載 Release 到暫存、quick_check 通過才換上；換上前清 sidecar。"""
    import urllib.request

    from config import get_github_release_url
    from import_health import db_quick_check_ok

    retrieve = urlretrieve or urllib.request.urlretrieve
    release_url = url or get_github_release_url()
    tmpdir = tempfile.mkdtemp(prefix="wayne-db-")
    zpath = os.path.join(tmpdir, "db.zip")
    try:
        logger.info("下載公開 Release 行情庫（可能要幾分鐘）")
        retrieve(release_url, zpath)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(tmpdir)
        found = None
        for root, _, files in os.walk(tmpdir):
            for name in files:
                if name.endswith(".db"):
                    cand = os.path.join(root, name)
                    if found is None or os.path.getsize(cand) > os.path.getsize(found):
                        found = cand
        if not found:
            logger.warning("Release zip 內找不到 .db")
            return False
        if not db_quick_check_ok(found, min_bytes=1):
            logger.error("Release .db quick_check 失敗，拒裝")
            return False
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        # 寫到同目錄暫存再 replace，縮短無庫窗口
        staging = f"{db_path}.staging-{int(time.time())}"
        shutil.copy2(found, staging)
        if not db_quick_check_ok(staging, min_bytes=1):
            logger.error("staging quick_check 失敗，拒裝")
            try:
                os.remove(staging)
            except OSError:
                pass
            return False
        if os.path.isfile(db_path) or has_sidecars(db_path):
            quarantine_db(db_path)
        remove_sidecars(db_path)
        os.replace(staging, db_path)
        remove_sidecars(db_path)
        logger.info("已安裝行情庫 %.0f MB", os.path.getsize(db_path) / 1e6)
        return db_quick_check_ok(db_path, min_bytes=1)
    except Exception:
        logger.exception("下載／安裝行情庫失敗")
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _ensure_biaoke_posts_columns(db_path: str) -> None:
    """CREATE IF NOT EXISTS 補不了缺欄；Release／半套表要 ALTER 才能 seed。"""
    needed = (
        ("n", "INTEGER NOT NULL DEFAULT 0"),
        ("date", "TEXT NOT NULL DEFAULT ''"),
        ("time", "TEXT NOT NULL DEFAULT ''"),
        ("parent", "TEXT NOT NULL DEFAULT ''"),
        ("layer", "INTEGER NOT NULL DEFAULT 0"),
        ("kind", "TEXT NOT NULL DEFAULT 'post'"),
        ("tags", "TEXT NOT NULL DEFAULT '[]'"),
        ("text", "TEXT NOT NULL DEFAULT ''"),
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
    )
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        cols = {
            str(r[1]) for r in conn.execute("PRAGMA table_info(biaoke_posts)")
        }
        if not cols:
            return
        for name, decl in needed:
            if name in cols:
                continue
            conn.execute(f'ALTER TABLE biaoke_posts ADD COLUMN "{name}" {decl}')
        conn.commit()
    finally:
        conn.close()


def force_biaoke_baseline(
    db_path: str,
    *,
    min_biaoke: int = MIN_BIAOKE_RESTORE,
) -> dict:
    """強制讓 biaoke 主文 ≥ min：先 corrupt 救回，再 seed_biaoke_archive。

    失敗不吞——回傳 ok／error／biaoke_n／steps，供 /health 與 log。
    """
    from import_health import db_quick_check_ok

    steps: List[str] = []
    out = {
        "ok": False,
        "biaoke_n": 0,
        "seeded_rows": 0,
        "source": "",
        "error": "",
        "steps": steps,
    }
    if not db_path or not os.path.isfile(db_path):
        out["error"] = "db_missing"
        return out
    if not db_quick_check_ok(db_path, min_bytes=1):
        out["error"] = "db_unreadable"
        return out

    n = biaoke_post_count(db_path)
    out["biaoke_n"] = n
    out["private_n"] = private_row_total(db_path)

    def _finish(source: str, *, ok: bool, error: str = "") -> dict:
        # 無論 biaoke 是否已夠，都嘗試從 corrupt 救私人表（Release 常把私人洗空）
        priv = salvage_private_from_corrupts(db_path)
        out["private_n"] = int(priv.get("after") or 0)
        out["private_merged"] = dict(priv.get("merged_by_table") or {})
        if int(priv.get("after") or 0) > int(priv.get("before") or 0):
            steps.append(
                f"private:{priv.get('before')}->{priv.get('after')}"
            )
        out["biaoke_n"] = biaoke_post_count(db_path)
        out.update(ok=ok, source=source, error=error)
        return out

    if n >= int(min_biaoke):
        return _finish("already", ok=True)

    # 1) corrupt 整檔（更完整 overlay／自回／私人）
    best = best_corrupt_restore(db_path, min_biaoke=min_biaoke)
    if best and biaoke_post_count(best) > n:
        steps.append(f"restore:{os.path.basename(best)}")
        if restore_corrupt_to_path(best, db_path):
            remove_sidecars(db_path)
            if db_quick_check_ok(db_path, min_bytes=1):
                n = biaoke_post_count(db_path)
                out["biaoke_n"] = n
                if n >= int(min_biaoke):
                    return _finish("corrupt", ok=True)
            else:
                steps.append("restore_unreadable")
        else:
            steps.append("restore_failed")

    # 2) ATTACH salvage biaoke（保留官方柱）
    if biaoke_post_count(db_path) < int(min_biaoke):
        salv = salvage_biaoke_from_corrupts(db_path)
        steps.append(f"salvage:{salv.get('before')}->{salv.get('after')}")
        n = int(salv.get("after") or 0)
        out["biaoke_n"] = n
        if n >= int(min_biaoke):
            return _finish("salvage", ok=True)

    # 3) 強制種 archive_1709（先補齊缺欄，Release 空表／舊 schema 常缺 n／tags）
    try:
        from biaoke_archive import load_bundled_archive, seed_biaoke_archive
        from biaoke_desk import ensure_biaoke_posts_table

        ensure_biaoke_posts_table(db_path)
        _ensure_biaoke_posts_columns(db_path)
        blob = load_bundled_archive()
        archive_n = int(blob.get("n") or 0)
        posts = [r for r in (blob.get("posts") or []) if not r.get("club")]
        steps.append(f"archive_bundle:n={archive_n}:posts={len(posts)}")
        if not posts:
            return _finish("seed", ok=False, error="archive_1709_empty")
        seeded = int(seed_biaoke_archive(db_path) or 0)
        out["seeded_rows"] = seeded
        steps.append(f"seed_rows={seeded}")
        n = biaoke_post_count(db_path)
        out["biaoke_n"] = n
        if n >= int(min_biaoke):
            return _finish("seed", ok=True)
        return _finish(
            "seed", ok=False, error=f"seed_below_min:n={n}:seeded={seeded}"
        )
    except Exception as exc:
        logger.exception("force_biaoke_baseline seed 失敗")
        out["biaoke_n"] = biaoke_post_count(db_path)
        return _finish("seed", ok=False, error=f"seed_exception:{exc}")


def ensure_market_db_recoverable(
    db_path: Optional[str] = None,
    *,
    min_biaoke: int = MIN_BIAOKE_RESTORE,
    allow_release: bool = True,
    urlretrieve=None,
) -> dict:
    """確保正式路徑可讀；優先救回含飆大底圖的 .corrupt-*。

    回傳狀態給測試／log：ok / source / biaoke_n / actions。
    """
    from config import get_db_path
    from import_health import db_quick_check_ok

    path = db_path or get_db_path()
    actions: List[str] = []
    result = {
        "ok": False,
        "path": path,
        "source": "",
        "biaoke_n": 0,
        "actions": actions,
    }

    def _ok() -> bool:
        return bool(path and os.path.isfile(path) and db_quick_check_ok(path, min_bytes=1))

    def _enrich_and_return(source: str) -> dict:
        """可讀後一律合併 corrupt 的私人表；不准留空私人本。"""
        n = biaoke_post_count(path)
        priv = salvage_private_from_corrupts(path)
        if int(priv.get("after") or 0) > int(priv.get("before") or 0):
            actions.append(
                f"private:{priv.get('before')}->{priv.get('after')}"
            )
        result.update(
            ok=True,
            source=source,
            biaoke_n=n,
            private_n=int(priv.get("after") or 0),
            private_merged=dict(priv.get("merged_by_table") or {}),
        )
        return result

    # 1) 已可讀且飆大底圖夠 → 仍救私人，不准 Release 蓋掉
    if _ok():
        n = biaoke_post_count(path)
        if n >= int(min_biaoke):
            return _enrich_and_return("current")
        actions.append("current_ok_low_biaoke")
    else:
        # 2) 錯位 wal/shm：先清再驗
        if os.path.isfile(path) and has_sidecars(path):
            removed = remove_sidecars(path)
            if removed:
                actions.append("stripped_sidecars")
            if _ok():
                n = biaoke_post_count(path)
                if n >= int(min_biaoke):
                    return _enrich_and_return("sidecar_strip")
                actions.append("sidecar_strip_ok_low_biaoke")

    # 3) 優先從 .corrupt-* 整檔救回（含 overlay／自回／私人；不准空 Release 蓋完整庫）
    current_n = biaoke_post_count(path) if os.path.isfile(path) else 0
    current_priv = private_row_total(path) if os.path.isfile(path) else 0
    best = best_corrupt_restore(path, min_biaoke=min_biaoke)
    if best:
        best_n = biaoke_post_count(best)
        best_priv = private_row_total(best)
        richer = (best_n > current_n) or (best_priv > current_priv)
        if (not _ok()) or richer:
            actions.append(f"restore_corrupt:{os.path.basename(best)}")
            if restore_corrupt_to_path(best, path):
                if has_sidecars(path):
                    remove_sidecars(path)
                    actions.append("strip_after_corrupt_restore")
                if _ok():
                    return _enrich_and_return("corrupt")
            actions.append("restore_corrupt_failed")

    # 3b) 本尊可讀但 biaoke 仍少：ATTACH 合併 corrupt overlay（不丟 corrupt、不蓋官方柱）
    if _ok() and biaoke_post_count(path) < int(min_biaoke):
        salv = salvage_biaoke_from_corrupts(path)
        if int(salv.get("after") or 0) > int(salv.get("before") or 0):
            actions.append(
                f"salvage_biaoke:{salv.get('before')}->{salv.get('after')}"
            )
            n = int(salv.get("after") or 0)
            if n >= int(min_biaoke):
                return _enrich_and_return("salvage")

    # 4) 現況已可讀 → 留給 seed／合併私人，**禁止**再 Release 整檔蓋掉
    if _ok():
        return _enrich_and_return("current")

    # 5) 本尊真的不可讀：才准 Release；裝完立刻從所有 .corrupt-* 合併 biaoke＋私人
    if os.path.isfile(path) or has_sidecars(path):
        dest = quarantine_db(path)
        if dest:
            actions.append(f"quarantine:{os.path.basename(dest)}")
        else:
            actions.append("quarantine_sidecars_only")

    if not allow_release:
        result.update(ok=_ok(), source="none", biaoke_n=biaoke_post_count(path))
        return result

    if install_release_db(path, urlretrieve=urlretrieve):
        actions.append("release_install")
        salv = salvage_biaoke_from_corrupts(path)
        if int(salv.get("after") or 0) > int(salv.get("before") or 0):
            actions.append(
                f"post_release_biaoke:{salv.get('before')}->{salv.get('after')}"
            )
        return _enrich_and_return("release")

    actions.append("release_failed")
    result.update(ok=False, source="none", biaoke_n=0)
    return result
