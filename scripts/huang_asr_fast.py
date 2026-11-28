#!/usr/bin/env python3
"""Fast Huang film ASR via faster-whisper (local host tool; not a phone path).

Judge default = faster-whisper **small**/int8 on 16 kHz mono wav.
Bench (contended): fw-small int8 ≫ openai-whisper small-on-mp4 (~4–8× wall);
full ~48 min film targets ~3–6 min vs 20–40+ min.

Quality gate (do not loosen):
- language=zh; beam_size=1; vad_filter=True; condition_on_previous_text=False
- Default model=small (chrono stock expects). tiny only via --model for draft.
- Fail if too short / mush markers / <2 structure keys → exit 2 (escalate / frames).
- One ASR process at a time on this 4-core box.
- Never invent quotes; phone_sync still blocked_until_gate.
- Do NOT add to requirements.lock / CI.

Deps (local only):
  pip install 'faster-whisper==1.1.1' 'av==12.3.0'
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STRUCTURE_KEYS = (
    "台積",
    "加權",
    "台指",
    "波浪",
    "整理",
    "反彈",
    "破線",
    "A波",
    "B波",
    "C波",
    "第五",
    "群創",
    "華邦",
    "南亞",
    "震盪",
    "記憶體",
)

# Known ASR mush from tiny/bad runs — escalate if spam
MUSH_RE = re.compile(r"其護戰|請互站|黃培說|推生|更聖波浪|請鼓掌首創")


def extract_wav(media: Path, wav: Path) -> None:
    subprocess.check_call(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(media),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def default_out(media: Path) -> Path:
    digits = "".join(ch for ch in media.stem if ch.isdigit())[:4]
    if len(digits) == 4:
        return media.with_name(f"{digits}_transcript.txt")
    return media.with_suffix(".txt")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("media", type=Path, help="mp4/wav path")
    ap.add_argument("-o", "--output", type=Path, help="transcript .txt path")
    ap.add_argument(
        "--model",
        default="small",
        choices=("tiny", "base", "small"),
        help="judge default small; tiny=draft only",
    )
    ap.add_argument("--compute", default="int8", choices=("int8", "int8_float16", "float32"))
    ap.add_argument(
        "--min-chars",
        type=int,
        default=12000,
        help="quality floor for ~45–50 min film (~small length)",
    )
    ap.add_argument("--keep-wav", action="store_true")
    ap.add_argument("--no-vad", action="store_true")
    args = ap.parse_args()

    media = args.media
    if not media.exists():
        print(f"missing media: {media}", file=sys.stderr)
        return 1
    out = args.output or default_out(media)

    wav_path: Path | None = None
    audio = media
    tmp_wav: Path | None = None
    if media.suffix.lower() in {".mp4", ".mkv", ".mov", ".m4a", ".mp3"}:
        if args.keep_wav:
            wav_path = media.with_suffix(".wav")
        else:
            tmp_wav = Path(tempfile.mkstemp(prefix="huang_asr_", suffix=".wav")[1])
            wav_path = tmp_wav
        t_ex = time.time()
        extract_wav(media, wav_path)
        print(f"wav_extract_secs={time.time() - t_ex:.1f} -> {wav_path}")
        audio = wav_path

    from faster_whisper import WhisperModel

    t0 = time.time()
    model = WhisperModel(
        args.model,
        device="cpu",
        compute_type=args.compute,
        cpu_threads=4,
    )
    segments, info = model.transcribe(
        str(audio),
        language="zh",
        beam_size=1,
        vad_filter=not args.no_vad,
        condition_on_previous_text=False,
        initial_prompt="黃培碩 台股 台積電 加權 台指期 費半 那指 波浪 群創 華邦 南亞科 記憶體",
    )
    lines = [s.text.strip() for s in segments if s.text and s.text.strip()]
    text = "\n".join(lines) + "\n"
    out.write_text(text, encoding="utf-8")
    dt = time.time() - t0
    hits = [k for k in STRUCTURE_KEYS if k in text]
    mush_n = len(MUSH_RE.findall(text))
    print(
        f"ok model={args.model}/{args.compute} secs={dt:.1f} chars={len(text)} "
        f"lang={info.language} structure_hits={len(hits)} mush={mush_n} out={out}"
    )
    if tmp_wav is not None:
        try:
            tmp_wav.unlink(missing_ok=True)
        except OSError:
            pass

    fail = False
    if len(text) < args.min_chars:
        print(f"quality_gate_fail short chars={len(text)}<{args.min_chars}", file=sys.stderr)
        fail = True
    if len(hits) < 2:
        print(f"quality_gate_fail structure hits={hits}", file=sys.stderr)
        fail = True
    if mush_n >= 8:
        print(f"quality_gate_fail mush_spam n={mush_n}", file=sys.stderr)
        fail = True
    return 2 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
