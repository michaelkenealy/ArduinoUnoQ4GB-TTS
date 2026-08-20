#!/usr/bin/env python3
"""Measure Kokoro clause-level generation with pipelined playback."""

from __future__ import annotations

import argparse
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path


DEFAULT_TEXT = (
    "Hello. This is a test of chunked speech generation. "
    "Each clause should start playing while the next one is still being generated. "
    "Let's see how natural the pacing feels."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kokoro-model", default="kokoro-v1.0.onnx")
    parser.add_argument("--voices", default="voices-v1.0.bin")
    parser.add_argument("--voice", default="af_bella")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--player", default="pw-play")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-play", action="store_true")
    args = parser.parse_args()

    try:
        from kokoro_onnx import Kokoro
        import soundfile as sf
    except ImportError as exc:
        print("Kokoro dependencies are missing; activate the Kokoro virtual environment first.")
        print(f"Import error: {exc}")
        return 2

    model = Path(args.kokoro_model).expanduser()
    voices = Path(args.voices).expanduser()
    if not model.exists() or not voices.exists():
        print(f"Missing model or voices file: {model}, {voices}")
        return 2

    clauses = [c.strip() for c in re.split(r"(?<=[.!?])\s+", args.text.strip()) if c.strip()]
    if not clauses:
        print("Text must contain at least one clause")
        return 2

    output_dir = args.output_dir or Path(f"tts-chunks-{datetime.now():%Y%m%d-%H%M%S}")
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"{len(clauses)} clauses; output={output_dir}; voice={args.voice}")
    print("Playback disabled" if args.no_play else f"Player={args.player}")

    kokoro = Kokoro(str(model), str(voices))
    overall_start = time.perf_counter()
    first_play_start: float | None = None
    play_proc: subprocess.Popen[bytes] | None = None
    rows: list[tuple[float, float]] = []

    try:
        for index, clause in enumerate(clauses):
            generation_start = time.perf_counter()
            samples, sample_rate = kokoro.create(clause, voice=args.voice)
            generation_seconds = time.perf_counter() - generation_start
            audio_seconds = len(samples) / sample_rate
            wav_path = output_dir / f"clause-{index + 1:02d}.wav"
            sf.write(str(wav_path), samples, sample_rate)

            # The next clause is generated while the previous Popen plays.
            # Wait here to keep speech sequential and avoid overlap.
            if play_proc is not None:
                if play_proc.wait() != 0:
                    print("Audio player failed")
                    return 1
            play_start = time.perf_counter()
            if not args.no_play:
                play_proc = subprocess.Popen([args.player, str(wav_path)])
                if first_play_start is None:
                    first_play_start = play_start
            else:
                play_proc = None

            rows.append((generation_seconds, audio_seconds))
            print(
                f'Clause {index + 1}/{len(clauses)}: "{clause}" | '
                f'generated {generation_seconds:.2f}s | audio {audio_seconds:.2f}s | '
                f'play-start {play_start - overall_start:.2f}s'
            )

        if play_proc is not None and play_proc.wait() != 0:
            print("Audio player failed")
            return 1
    except FileNotFoundError:
        print(f"Player not found: {args.player}; use --player or --no-play")
        return 2
    except KeyboardInterrupt:
        if play_proc is not None and play_proc.poll() is None:
            play_proc.terminate()
        print("Interrupted")
        return 130

    total_seconds = time.perf_counter() - overall_start
    print("Summary")
    print(f"Total wall-clock: {total_seconds:.2f}s")
    if first_play_start is not None:
        print(f"Time to first playback process: {first_play_start - overall_start:.2f}s")
    print(f"Total generated audio: {sum(audio for _, audio in rows):.2f}s")
    print("Generation RTF by clause: " + ", ".join(f"{generation / audio:.2f}" for generation, audio in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
