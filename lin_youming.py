"""林友銘 Drive 影音登錄骨架（獨立於 huang_youtube）。

用途：
- 登錄雲端資料夾／已知 mp4 file id
- 本機路徑約定、抽影格／whisper 參數預設
- **不准**寫進 huang_* 表；**非買訊**；不上話筒／不改黃金買點

完整 ingest 管線可後續接；本檔先鎖 Drive id 與命名規則。
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

# 雲端「林友銘」資料夾（使用者提供）
LIN_DRIVE_FOLDER_ID_DEFAULT = "1SIJ_PBvu6-Sck3YGMA0X9MUJM9Po0cKj"

# 已驗證可 gdown 的歷史片（MMDD林友銘.mp4 → ymd）
LIN_DRIVE_KNOWN_IDS: Dict[str, str] = {
    # 使用者 2026-11-27：1126林友銘.mp4（約 286MB）
    "20261126": "1BIzlyfparN_OiSc6WWB-9bCfoWBpKBrw",
}

# 本機落檔根（與 huang 分開）
LIN_LOCAL_ROOT = Path(
    os.environ.get("LIN_LOCAL_ROOT") or (Path(__file__).resolve().parent / "data" / "lin_youming")
)

# 口播／影格關鍵（吸收用；非買訊）
_TEACH_PATTERNS = (
    (r"0\s*\.?\s*382|0\s*\.?\s*38", "fib382"),
    (r"0\s*\.?\s*5(?!\d)|0\s*\.?\s*50", "fib50"),
    (r"0\s*\.?\s*618|0\s*\.?\s*6xx|黃金切割", "fib618"),
    (r"0\s*\.?\s*75", "fib75"),
    (r"0\s*\.?\s*786", "fib786"),
    (r"1\s*\.?\s*382", "ext1382"),
    (r"1\s*\.?\s*444|1\s*\.?\s*44", "ext1444"),
    (r"1\s*\.?\s*618|1\s*\.?\s*68", "ext1618"),
    (r"奔走\s*B|奔走創高", "running_b"),
    (r"失敗\s*C", "failed_c"),
    (r"①\s*④|1\s*4.*重疊|重疊", "overlap_14"),
    (r"③.*最短|第三.*最短", "wave3_shortest"),
    (r"年線", "annual_ma"),
    (r"季線", "quarter_ma"),
    (r"半年線", "half_year_ma"),
)

_NAME_YMD_RE = re.compile(r"(?P<mmdd>\d{3,4})\s*林友銘", re.I)


def drive_folder_id() -> str:
    return (
        os.getenv("LIN_DRIVE_FOLDER_ID") or LIN_DRIVE_FOLDER_ID_DEFAULT or ""
    ).strip()


def parse_drive_name_ymd(name: str, *, year_hint: int | None = None) -> str:
    """``1126林友銘.mp4`` → ``20261126``（缺年份用 year_hint 或台北今年）。"""
    raw = str(name or "").strip()
    m = _NAME_YMD_RE.search(raw)
    if not m:
        return ""
    mmdd = m.group("mmdd")
    if len(mmdd) == 3:
        mmdd = "0" + mmdd
    if len(mmdd) != 4 or not mmdd.isdigit():
        return ""
    y = int(year_hint) if year_hint else int(datetime.now(TAIPEI).strftime("%Y"))
    return f"{y}{mmdd}"


def drive_file_ids_map() -> Dict[str, str]:
    """ymd → Drive file id。env ``LIN_DRIVE_FILE_IDS``＝``20261126=id,...``。"""
    out = dict(LIN_DRIVE_KNOWN_IDS)
    raw = (os.getenv("LIN_DRIVE_FILE_IDS") or "").strip()
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(k) == 8 and k.isdigit() and v:
            out[k] = v
    return out


def resolve_drive_file_id(as_of_ymd: str) -> str:
    ymd = str(as_of_ymd or "").replace("-", "")[:8]
    if not ymd:
        return ""
    return str(drive_file_ids_map().get(ymd) or "").strip()


def local_mp4_path(as_of_ymd: str, *, filename: str = "") -> Path:
    ymd = str(as_of_ymd or "").replace("-", "")[:8]
    LIN_LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    if filename:
        return LIN_LOCAL_ROOT / filename
    mmdd = ymd[4:] if len(ymd) == 8 else ymd
    return LIN_LOCAL_ROOT / f"{mmdd}林友銘.mp4"


def extract_teach_tags(text: str) -> list[str]:
    blob = str(text or "")
    out: list[str] = []
    for pat, tag in _TEACH_PATTERNS:
        if re.search(pat, blob):
            if tag not in out:
                out.append(tag)
    return out


def notes_dir() -> Path:
    return Path(__file__).resolve().parent / "docs" / "expert_notes" / "林友銘"
