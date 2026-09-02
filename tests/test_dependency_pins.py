# -*- coding: utf-8 -*-
"""相依版本必須釘死，且三處 Python 版本要一致。

浮動版本會讓「昨天好的、今天壞的」無從追查；Dockerfile 用 3.11 而
runtime.txt 用 3.12 時，本機測過的行為不保證等於部署後的行為。
"""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


def _parse_pins(text):
    pins = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            pytest.fail(f"未釘死版本：{line}")
        name, version = line.split("==", 1)
        pins[name.strip().lower().replace("_", "-")] = version.strip()
    return pins


def test_requirements_are_all_pinned():
    pins = _parse_pins(_read("requirements.txt"))
    assert pins, "requirements.txt 不該是空的"
    for name, version in pins.items():
        assert re.match(r"^\d+(\.\d+)*", version), f"{name} 版本格式怪異：{version}"


def test_lock_is_all_pinned():
    pins = _parse_pins(_read("requirements.lock"))
    assert len(pins) > len(_parse_pins(_read("requirements.txt")))


def test_lock_covers_every_direct_dependency():
    """鎖檔漂移最常見的樣子：加了直接相依卻忘記重新產生鎖檔。"""
    direct = _parse_pins(_read("requirements.txt"))
    lock = _parse_pins(_read("requirements.lock"))
    missing = sorted(set(direct) - set(lock))
    assert missing == [], f"鎖檔缺少直接相依：{missing}"


def test_lock_versions_match_requirements():
    direct = _parse_pins(_read("requirements.txt"))
    lock = _parse_pins(_read("requirements.lock"))
    mismatched = {
        name: (version, lock[name])
        for name, version in direct.items()
        if lock.get(name) != version
    }
    assert mismatched == {}, f"鎖檔與 requirements.txt 版本不一致：{mismatched}"


def test_critical_packages_are_pinned():
    """這幾個的大版本跳動會直接打壞出圖與指標計算。"""
    pins = _parse_pins(_read("requirements.txt"))
    for name in ("numpy", "pandas", "matplotlib", "python-telegram-bot", "requests"):
        assert name in pins, f"{name} 必須釘死版本"


def test_pillow_is_locked_because_matplotlib_renders_through_it():
    lock = _parse_pins(_read("requirements.lock"))
    assert "pillow" in lock


def _runtime_python():
    return _read("runtime.txt").strip().replace("python-", "")


def test_runtime_declares_a_full_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+", _runtime_python())


def test_dockerfile_python_matches_runtime():
    major_minor = ".".join(_runtime_python().split(".")[:2])
    dockerfile = _read("Dockerfile")
    found = re.search(r"^FROM python:(\d+\.\d+)", dockerfile, re.MULTILINE)
    assert found, "Dockerfile 找不到 FROM python:<版本>"
    assert found.group(1) == major_minor, (
        f"Dockerfile 用 {found.group(1)}，runtime.txt 用 {major_minor}"
    )


def test_workflows_python_matches_runtime():
    major_minor = ".".join(_runtime_python().split(".")[:2])
    wf_dir = os.path.join(ROOT, ".github", "workflows")
    seen = 0
    for name in sorted(os.listdir(wf_dir)):
        if not name.endswith((".yml", ".yaml")):
            continue
        text = _read(os.path.join(".github", "workflows", name))
        for version in re.findall(r"python-version:\s*'?\"?([\d.]+)'?\"?", text):
            seen += 1
            assert version == major_minor, f"{name} 用 {version}，runtime.txt 用 {major_minor}"
    assert seen > 0, "workflow 沒宣告 python-version"


def test_dockerfile_installs_the_lock():
    dockerfile = _read("Dockerfile")
    assert "requirements.lock" in dockerfile
    assert "pip install --no-cache-dir -r requirements.lock" in dockerfile


def test_render_installs_the_lock():
    assert "requirements.lock" in _read("render.yaml")


def test_workflows_install_the_lock():
    wf_dir = os.path.join(ROOT, ".github", "workflows")
    for name in sorted(os.listdir(wf_dir)):
        if not name.endswith((".yml", ".yaml")):
            continue
        text = _read(os.path.join(".github", "workflows", name))
        if "pip install" not in text:
            continue
        assert "requirements.lock" in text, f"{name} 沒裝鎖檔"


def test_installed_versions_match_the_lock():
    """跑測試的環境要就是鎖住的那組，否則測到的不是會部署的東西。

    系統 Python 可能混著 OS 套件，所以只比對直接相依。
    """
    from importlib import metadata

    direct = _parse_pins(_read("requirements.txt"))
    drift = {}
    for name, want in direct.items():
        try:
            got = metadata.version(name)
        except metadata.PackageNotFoundError:
            drift[name] = (want, "未安裝")
            continue
        if got != want:
            drift[name] = (want, got)
    assert drift == {}, f"環境與鎖檔不一致：{drift}"
