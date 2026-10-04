# -*- coding: utf-8 -*-
"""ensure_market_db 復原：wal/shm 一併處理、優先救 .corrupt-* biaoke≥1700。"""
import os
import sqlite3
import zipfile

import pytest

from db_recover import (
    best_corrupt_restore,
    completeness_counts,
    ensure_market_db_recoverable,
    has_sidecars,
    is_richer_completeness,
    move_db_with_sidecars,
    private_row_total,
    quarantine_db,
    remove_sidecars,
    restore_corrupt_to_path,
    sidecar_paths,
)


def _make_db(
    path: str,
    *,
    biaoke_n: int = 0,
    private_n: int = 0,
    junk: bool = False,
) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if junk:
        with open(path, "wb") as f:
            f.write(b"not-a-sqlite-file" * 5000)
        return
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE daily_quotes (date TEXT, stock_id TEXT)")
    conn.execute(
        "CREATE TABLE biaoke_posts ("
        "id TEXT PRIMARY KEY, kind TEXT, date TEXT, time TEXT, text TEXT)"
    )
    for i in range(int(biaoke_n)):
        conn.execute(
            "INSERT INTO biaoke_posts(id, kind, date, time, text) VALUES (?,?,?,?,?)",
            (f"p{i}", "post", "20260901", "09:00", "x"),
        )
    # 加幾則 reply，確認計數不含 reply
    conn.execute(
        "INSERT INTO biaoke_posts(id, kind, date, time, text) VALUES (?,?,?,?,?)",
        ("r1", "reply", "20260901", "09:01", "y"),
    )
    if int(private_n) > 0:
        conn.execute(
            "CREATE TABLE user_holdings ("
            "user_id TEXT, stock_id TEXT, PRIMARY KEY(user_id, stock_id))"
        )
        for i in range(int(private_n)):
            conn.execute(
                "INSERT INTO user_holdings VALUES (?,?)",
                (f"u{i}", f"233{i % 10}"),
            )
    conn.commit()
    conn.close()


def _write_wal_shm(db_path: str) -> None:
    wal, shm = sidecar_paths(db_path)
    with open(wal, "wb") as f:
        f.write(b"fake-wal" * 100)
    with open(shm, "wb") as f:
        f.write(b"fake-shm" * 10)


def test_quarantine_moves_wal_and_shm(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    _make_db(db, biaoke_n=3)
    _write_wal_shm(db)
    assert has_sidecars(db)

    dest = quarantine_db(db, tag="111")
    assert dest.endswith(".corrupt-111")
    assert os.path.isfile(dest)
    assert not os.path.isfile(db)
    assert not has_sidecars(db)
    assert os.path.isfile(f"{dest}-wal")
    assert os.path.isfile(f"{dest}-shm")


def test_strip_orphan_wal_shm_makes_db_readable(tmp_path):
    """新庫＋舊 wal 會讓 quick_check 紅；清 sidecar 後應可讀。"""
    db = str(tmp_path / "wayne_market.db")
    _make_db(db, biaoke_n=1705)
    # 好人庫被錯位 wal 汙染：sqlite 開到壞 wal 可能失敗
    _write_wal_shm(db)

    # 先確認有 sidecar；清掉後 ensure 應走 sidecar_strip／current
    assert has_sidecars(db)
    result = ensure_market_db_recoverable(db, allow_release=False)
    assert result["ok"] is True
    assert result["biaoke_n"] >= 1700
    assert not has_sidecars(db)
    assert result["source"] in ("sidecar_strip", "current")


def test_prefer_corrupt_with_biaoke_over_empty_current(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    # 正式路徑：空 Release 形（可讀但無飆大）
    _make_db(db, biaoke_n=0)
    # 舊庫備份：完整 overlay
    corrupt = f"{db}.corrupt-999"
    _make_db(corrupt, biaoke_n=1722)

    best = best_corrupt_restore(db, min_biaoke=1700)
    assert best == corrupt

    result = ensure_market_db_recoverable(db, allow_release=False)
    assert result["ok"] is True
    assert result["source"] == "corrupt"
    assert result["biaoke_n"] >= 1700
    assert os.path.isfile(db)
    # 空本尊應被另存，corrupt 移回正式路徑
    assert not os.path.isfile(corrupt)


def test_restore_corrupt_clears_live_sidecars(tmp_path):
    db = str(tmp_path / "wayne_market.db")
    _make_db(db, junk=True)
    _write_wal_shm(db)
    corrupt = f"{db}.corrupt-42"
    _make_db(corrupt, biaoke_n=1709)
    _write_wal_shm(corrupt)

    assert restore_corrupt_to_path(corrupt, db)
    assert os.path.isfile(db)
    # 正式路徑 sidecar 應來自 corrupt 搬過來的；至少 db 可讀
    from import_health import db_quick_check_ok

    # 搬過來的 fake wal 可能害 quick_check；ensure 路徑會再清
    remove_sidecars(db)
    assert db_quick_check_ok(db, min_bytes=1)
    assert not has_sidecars(db)


def test_ensure_quarantines_junk_then_installs_release(tmp_path, monkeypatch):
    db = str(tmp_path / "wayne_market.db")
    _make_db(db, junk=True)
    _write_wal_shm(db)

    # 假 Release：zip 內一顆可讀庫（biaoke=0）
    release_db = tmp_path / "release" / "wayne_market.db"
    release_db.parent.mkdir()
    _make_db(str(release_db), biaoke_n=0)
    zpath = tmp_path / "rel.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(release_db, arcname="wayne_market.db")

    def _fake_retrieve(url, dest):
        import shutil

        shutil.copy2(zpath, dest)
        return dest, {}

    monkeypatch.setenv("WAYNE_DB_PATH", db)
    result = ensure_market_db_recoverable(db, allow_release=True, urlretrieve=_fake_retrieve)
    assert result["ok"] is True
    assert result["source"] == "release"
    assert not has_sidecars(db)
    # 壞本尊＋sidecar 已隔離
    corrupts = [p for p in os.listdir(tmp_path) if "corrupt" in p and not p.endswith(("-wal", "-shm"))]
    assert corrupts


def test_move_db_with_sidecars_keeps_sqlite_names(tmp_path):
    src = str(tmp_path / "a.db")
    dest = str(tmp_path / "b.db")
    _make_db(src, biaoke_n=2)
    _write_wal_shm(src)
    move_db_with_sidecars(src, dest)
    assert os.path.isfile(dest)
    assert os.path.isfile(f"{dest}-wal")
    assert not os.path.isfile(src)
    assert not os.path.isfile(f"{src}-wal")


def test_main_ensure_market_db_uses_recoverable(monkeypatch, tmp_path):
    """main.ensure_market_db 必須走 db_recover，不再只 shutil.move .db。"""
    import main

    db = str(tmp_path / "wayne_market.db")
    _make_db(db, biaoke_n=0)
    corrupt = f"{db}.corrupt-1"
    _make_db(corrupt, biaoke_n=1710)
    monkeypatch.setenv("WAYNE_DB_PATH", db)
    monkeypatch.setattr("config.get_db_path", lambda: db)

    main.ensure_market_db()
    from import_health import db_quick_check_ok
    from db_recover import biaoke_post_count

    assert db_quick_check_ok(db, min_bytes=1)
    assert biaoke_post_count(db) >= 1700


def test_salvage_biaoke_from_corrupt_without_replacing_db(tmp_path):
    from db_recover import salvage_biaoke_from_corrupts

    db = str(tmp_path / "wayne_market.db")
    _make_db(db, biaoke_n=0)
    corrupt = f"{db}.corrupt-77"
    _make_db(corrupt, biaoke_n=1720)
    # 正式路徑留下可讀空表；corrupt 不整檔覆蓋也能救回
    out = salvage_biaoke_from_corrupts(db)
    assert out["after"] >= 1700
    assert out["before"] == 0
    assert os.path.isfile(corrupt)  # 不准刪 corrupt


def test_salvage_private_tables_from_corrupt(tmp_path):
    from db_recover import private_row_total, salvage_private_from_corrupts

    db = str(tmp_path / "wayne_market.db")
    _make_db(db, biaoke_n=0)
    corrupt = f"{db}.corrupt-88"
    _make_db(corrupt, biaoke_n=1720)
    conn = sqlite3.connect(corrupt)
    conn.execute(
        "CREATE TABLE user_holdings (user_id TEXT, stock_id TEXT, PRIMARY KEY(user_id, stock_id))"
    )
    conn.execute("INSERT INTO user_holdings VALUES ('u1','2330')")
    conn.execute("INSERT INTO user_holdings VALUES ('u2','2317')")
    conn.execute(
        "CREATE TABLE tg_actor_pending (user_id TEXT PRIMARY KEY, payload TEXT)"
    )
    conn.execute("INSERT INTO tg_actor_pending VALUES ('u1','x')")
    conn.commit()
    conn.close()

    assert private_row_total(db) == 0
    out = salvage_private_from_corrupts(db)
    assert out["after"] >= 3
    assert private_row_total(db) >= 3
    assert os.path.isfile(corrupt)


def test_readable_db_never_replaced_by_release(tmp_path, monkeypatch):
    """可讀正式庫（即使 biaoke 空）不准再被空 Release 整檔蓋掉。"""
    db = str(tmp_path / "wayne_market.db")
    _make_db(db, biaoke_n=0)
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("install_release_db must not run on readable db")

    monkeypatch.setattr("db_recover.install_release_db", _boom)
    result = ensure_market_db_recoverable(db, allow_release=True)
    assert result["ok"] is True
    assert called["n"] == 0
    assert os.path.isfile(db)


def test_force_biaoke_baseline_seeds_archive(tmp_path):
    from db_recover import force_biaoke_baseline

    db = str(tmp_path / "wayne_market.db")
    _make_db(db, biaoke_n=0)
    out = force_biaoke_baseline(db)
    assert out["ok"] is True
    assert int(out["biaoke_n"]) >= 1700
    assert out["source"] in ("seed", "salvage", "corrupt", "already")


def test_seeded_db_format_latest_focus_has_locked_intro(tmp_path):
    """seed 後空白進場必須產出鎖定結構，不准空字串當修好。"""
    from biaoke_digest import format_latest_focus
    from biaoke_desk import upsert_biaoke_posts
    from db_recover import force_biaoke_baseline

    db = str(tmp_path / "wayne_market.db")
    _make_db(db, biaoke_n=0)
    out = force_biaoke_baseline(db)
    assert out["ok"] is True
    # 盤中 overlay：10/3 19:20 台虹／PTFE（archive 底圖沒有這則）
    upsert_biaoke_posts(
        db,
        [
            {
                "id": "1851oct3",
                "n": 99999,
                "date": "2026-10-03",
                "time": "19:20",
                "kind": "post",
                "tags": ["台虹", "PTFE", "ASIC"],
                "text": (
                    "1. 大盤：台虹當 2nd supplier，PTFE 轉 Hybrid，M9/M10 CCL。"
                    "2. 族群：散熱到 InP 再到 PCB/CCL、ASIC、CPO/FAU。"
                    "3. ASIC 全鏈創意世芯聯發科。InP 聯亞。FAU 大立光。CPO 台積訊芯。"
                    "該怎麼做先等回測，偏熱先不追。"
                ),
            }
        ],
    )
    html = format_latest_focus(db)
    assert html
    assert html.startswith("<b>飆大現在在講</b>")
    assert "最新" in html
    assert "10/3" in html or "19:20" in html
    assert "<b>大盤</b>" in html
    assert "台虹" in html
    assert "PTFE" in html or "Hybrid" in html or "CCL" in html
    assert "直接打字或語音" in html
    assert "<b>還能問</b>" in html


def test_boot_force_seed_calls_ingest():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"),
        encoding="utf-8",
    ).read()
    assert "ingest_public_posts" in src
    assert "開機立刻抓文" in src
    assert "private_row_total" in src
    ingest_src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "biaoke_ingest.py"),
        encoding="utf-8",
    ).read()
    assert "_time.sleep(5)" in ingest_src
    assert "_time.sleep(90)" not in ingest_src


def test_ensure_always_force_seeds_for_private_even_when_biaoke_ok():
    """biaoke 已 ≥1700 仍要 force_seed（ATTACH 救私人），不准跳過。"""
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py"),
        encoding="utf-8",
    ).read()
    # 舊寫法：biaoke 夠就只 record、不 force → 私人永遠空
    assert "force_seed_biaoke_baseline()" in src
    chunk = src[src.find("def ensure_market_db") : src.find("def _biaoke_ready")]
    assert "force_seed_biaoke_baseline()" in chunk
    assert 'if int(result.get("biaoke_n") or 0) < 1700:' not in chunk


def test_main_wires_recoverable_and_retry_loop():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_src = open(os.path.join(root, "main.py"), encoding="utf-8").read()
    recover_src = open(os.path.join(root, "db_recover.py"), encoding="utf-8").read()
    assert "ensure_market_db_recoverable" in main_src
    assert "start_market_db_recovery_loop" in main_src
    assert "start_early_biaoke_seed" in main_src
    assert "force_seed_biaoke_baseline" in main_src
    assert "force_biaoke_baseline" in recover_src
    assert "_biaoke_ready" in main_src
    assert "move_db_with_sidecars" in recover_src
    assert "best_corrupt_restore" in recover_src
    assert "salvage_biaoke_from_corrupts" in recover_src
    assert "salvage_private_from_corrupts" in recover_src
    assert "PRIVATE_USER_TABLES" in recover_src
    assert "completeness_counts" in recover_src
    assert "_post_release_seed_and_salvage" in recover_src
    assert "quarantine_early" in recover_src
    # 舊坑：只 shutil.move .db、不管 -wal/-shm
    assert "shutil.move(path, corrupt)" not in main_src


def test_completeness_compare_biaoke_and_private():
    assert is_richer_completeness(1722, 0, 0, 0) is True
    assert is_richer_completeness(0, 5, 0, 0) is True
    assert is_richer_completeness(100, 1, 200, 0) is True  # 私人較多
    assert is_richer_completeness(100, 0, 200, 5) is False


def test_junk_with_rich_corrupt_never_leaves_empty(tmp_path, monkeypatch):
    """壞本尊＋較完整 .corrupt：不准留下空 biaoke／空私人（也不准空 Release 蓋掉）。"""
    db = str(tmp_path / "wayne_market.db")
    _make_db(db, junk=True)
    _write_wal_shm(db)
    corrupt = f"{db}.corrupt-rich"
    _make_db(corrupt, biaoke_n=1722, private_n=7)

    release_db = tmp_path / "release" / "wayne_market.db"
    release_db.parent.mkdir()
    _make_db(str(release_db), biaoke_n=0, private_n=0)
    zpath = tmp_path / "rel.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(release_db, arcname="wayne_market.db")

    called = {"n": 0}

    def _fake_retrieve(url, dest):
        called["n"] += 1
        import shutil

        shutil.copy2(zpath, dest)
        return dest, {}

    result = ensure_market_db_recoverable(
        db, allow_release=True, urlretrieve=_fake_retrieve
    )
    assert result["ok"] is True
    assert result["source"] == "corrupt"
    assert int(result["biaoke_n"]) >= 1700
    assert int(result.get("private_n") or 0) >= 7
    assert private_row_total(db) >= 7
    # 有可開且較完整的 corrupt → 不准走空 Release
    assert called["n"] == 0
    assert "guard_empty_after_release" not in (result.get("actions") or [])


def test_release_rebuild_seeds_and_salvages_corrupt(tmp_path, monkeypatch):
    """本尊壞、無可開完整 corrupt：Release 後必須 seed 1709＋從 corrupt merge 私人。"""
    db = str(tmp_path / "wayne_market.db")
    _make_db(db, junk=True)

    # corrupt：quick_check 過不了的假檔不算；另放一顆可 SELECT 的低 biaoke＋私人
    # （整檔門檻 1700 不夠 → 走 Release，再 ATTACH salvage＋seed）
    corrupt = f"{db}.corrupt-partial"
    _make_db(corrupt, biaoke_n=12, private_n=4)

    release_db = tmp_path / "release" / "wayne_market.db"
    release_db.parent.mkdir()
    _make_db(str(release_db), biaoke_n=0, private_n=0)
    zpath = tmp_path / "rel.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(release_db, arcname="wayne_market.db")

    def _fake_retrieve(url, dest):
        import shutil

        shutil.copy2(zpath, dest)
        return dest, {}

    result = ensure_market_db_recoverable(
        db, allow_release=True, urlretrieve=_fake_retrieve
    )
    assert result["ok"] is True
    assert result["source"] == "release"
    actions = list(result.get("actions") or [])
    assert "release_install" in actions
    assert any("post_release_seed" in a or a.startswith("seed:") for a in actions) or any(
        "post_release" in a for a in actions
    )
    # seed 1709 底圖
    assert int(result["biaoke_n"]) >= 1700
    # 私人從 partial corrupt merge 回來
    assert int(result.get("private_n") or 0) >= 4
    assert private_row_total(db) >= 4
    # 鎖死：不准雙空
    assert not (
        int(result["biaoke_n"]) == 0 and int(result.get("private_n") or 0) == 0
    )


def test_pre_swap_compare_prefers_richer_corrupt(tmp_path):
    """換庫前比較：空／少的本尊 vs 較完整 corrupt → 救 corrupt。"""
    db = str(tmp_path / "wayne_market.db")
    _make_db(db, biaoke_n=3, private_n=0)
    corrupt = f"{db}.corrupt-cmp"
    _make_db(corrupt, biaoke_n=1710, private_n=9)
    cur_b, cur_p = completeness_counts(db)
    cor_b, cor_p = completeness_counts(corrupt)
    assert is_richer_completeness(cor_b, cor_p, cur_b, cur_p)
    best = best_corrupt_restore(db, min_biaoke=1700)
    assert best == corrupt
    result = ensure_market_db_recoverable(db, allow_release=False)
    assert result["source"] == "corrupt"
    assert int(result["biaoke_n"]) >= 1700
    assert int(result.get("private_n") or 0) >= 9


def test_unit_tests_stub_isin_universe_offline(monkeypatch):
    """單元測不准連打 isin.twse；否則 smoke 會被 3×25s 累積卡死。"""
    import universe

    # conftest autouse 已 stub；呼叫應立刻回空、不准真 HTTP
    assert universe.fetch_isin_universe() == []
