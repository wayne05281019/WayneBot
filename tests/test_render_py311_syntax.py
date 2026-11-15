# -*- coding: utf-8 -*-
"""擋 3.12 專屬 f-string（巢狀同引號等）；Render 曾鎖 PYTHON_VERSION=3.11.0。

正式機已改 3.12.10（與 .python-version／runtime.txt／CI 對齊），這支守門仍留：
避免再寫出 3.11 會炸、舊快取／誤設版本又擋 import 的寫法。
taiwan_market 炸＝加權日K寫不進庫，波浪位階回「行情模組異常」。
3.12 的 compile() 抓不到，所以用 3.12 tokenizer 模擬 3.11 的字串切法逐檔掃。
"""
import io
import os
import sys
import tokenize

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "waynebot_cache"}


def _repo_py_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for name in sorted(files):
            if name.endswith(".py"):
                yield os.path.join(base, name)


def _quote(tok_str):
    body = tok_str.lstrip("rRbBuUfF")
    for q in ('"""', "'''", '"', "'"):
        if body.startswith(q):
            return q
    return ""


def py311_fstring_problems(src):
    """[(行號, 原因)]：3.12 parse 得過、3.11 會 SyntaxError 的 f-string 寫法。

    3.11 先把整個 f-string 當一般字串切：碰到外層引號就斷，運算式不准有反斜線／#，
    單引號字串不准跨行。巢狀 f-string 的字面段也算外層的運算式。
    """
    out = []
    stack = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.FSTRING_END:
            if stack:
                stack.pop()
            continue
        outers = stack[:-1] if tok.type == tokenize.FSTRING_MIDDLE else stack
        if outers:
            line = tok.start[0]
            if tok.type == tokenize.COMMENT:
                out.append((line, "f-string 運算式內有 # 註解"))
            elif tok.type in (tokenize.NL, tokenize.NEWLINE):
                if any(len(q) == 1 for q in outers):
                    out.append((line, "單引號 f-string 運算式跨行"))
            elif "\\" in tok.string:
                out.append((line, "f-string 運算式內有反斜線"))
            else:
                clash = next((q for q in outers if q in tok.string), "")
                if clash:
                    out.append((line, f"f-string 運算式內重用外層引號 {clash}"))
        if tok.type == tokenize.FSTRING_START:
            stack.append(_quote(tok.string))
    return out


def test_repo_sources_parse_on_render_python311():
    problems = []
    n = 0
    for path in _repo_py_files():
        n += 1
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        rel = os.path.relpath(path, ROOT)
        if sys.version_info >= (3, 12):
            for line, why in py311_fstring_problems(src):
                problems.append(f"{rel}:{line} {why}")
        else:
            try:
                compile(src, rel, "exec", dont_inherit=True)
            except SyntaxError as exc:
                problems.append(f"{rel}:{exc.lineno} {exc.msg}")
    assert n > 100, f"只掃到 {n} 個 .py，路徑不對"
    assert problems == [], "Render（3.11）import 會 SyntaxError：\n" + "\n".join(problems)


# 每一筆都用真 3.11.18 compile 對過：bad＝3.11 SyntaxError、ok＝3.11 可編譯
_BAD = [
    "b={'k':1}\nx = f'{b['k']}'\n",
    'b={"k":1}\nx = f"{b["k"]}"\n',
    "b={'avg':0.5}\nx = f\"隔日{str(f'{b['avg']:+.1f}%')}\"\n",
    "x=1\ny = f\"{f'{f\"{x}\"}'}\"\n",
    "a=['1','2']\ny = f\"{'\\n'.join(a)}\"\n",
    'a=1\ny = f"""{a # c\n}"""\n',
    'a=1\ny = f"{a +\n 1}"\n',
    "y = f'''{'''a'''}'''\n",
    'y = f"{\'say "hi"\'}"\n',
    "x=1\ny = f\"{f'a\\tb{x}'}\"\n",
    'x=1.0\nw=5\ny = f"{x:{f"{w}"}}"\n',
]

_OK = [
    "b={'k':1}\nx = f\"{b['k']}\"\n",
    "b={'avg':0.5}\nnext_pct = f\"{b['avg']:+.1f}%\"\nx = f\"隔日{str(next_pct)}\"\n",
    "x=1\ny = f\"{f'{x}'}\"\n",
    "a=1\ny = f\"line\\n{a}\"\n",
    'a=1\ny = f"""{a +\n 1}"""\n',
    "b={'k':1}\ny = f'''{b['k']}'''\n",
    'x=3.2\nw=8\ny = f"{x:>{w}.1f}"\n',
    "x=3\na=True\ny = f\"{x:{'>' if a else '<'}10}\"\n",
    "x=1\ny = rf\"\\d{x}\"\n",
    "a=1\nb={'k':2}\ny = f\"{a}\" + f'{b[\"k\"]}'\n",
]


@pytest.mark.skipif(sys.version_info < (3, 12), reason="3.12 tokenizer 才切 f-string")
@pytest.mark.parametrize("src", _BAD)
def test_scanner_flags_py312_only_fstrings(src):
    compile(src, "<case>", "exec")
    assert py311_fstring_problems(src), src


@pytest.mark.skipif(sys.version_info < (3, 12), reason="3.12 tokenizer 才切 f-string")
@pytest.mark.parametrize("src", _OK)
def test_scanner_allows_py311_fstrings(src):
    compile(src, "<case>", "exec")
    assert py311_fstring_problems(src) == [], src


@pytest.mark.skipif(sys.version_info < (3, 12), reason="3.12 tokenizer 才切 f-string")
def test_scanner_catches_taiwan_market_backtest_line():
    """#921 仍炸的那行（同一盤勢隔日）：掃得到；修後的寫法掃不到。"""
    old = (
        "def f(b, _m, _page_b):\n"
        "    return f\"{_m(b['bucket'])}　隔日{_page_b(f'{b['avg_next_pct']:+.1f}%')}"
        "（勝{b['hit_rate']:.0%}）\"\n"
    )
    new = (
        "def f(b, _m, _page_b):\n"
        "    next_pct = f\"{b['avg_next_pct']:+.1f}%\"\n"
        "    return f\"{_m(b['bucket'])}　隔日{_page_b(next_pct)}（勝{b['hit_rate']:.0%}）\"\n"
    )
    assert py311_fstring_problems(old)
    assert py311_fstring_problems(new) == []
