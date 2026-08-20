#!/usr/bin/env python3
"""Profile Kokoro's text and inference costs on the UNO Q.

This intentionally does not play audio. It compares one full synthesis call
with repeated clause calls and with pre-phonemized input. It also reports cold
versus warm inference so model/session startup is not confused with the
steady-state cost.
"""

from __future__ import annotations

import argparse
import re
import time
from pathlib import Path


DEFAULT_TEXT = (
    "Hello. This is a test of chunked speech generation. "
    "Each clause should start playing while the next one is still being generated. "
    "Let's see how natural the pacing feels."
)


def split_clauses(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]


def render(kokoro, text: str, voice: str, *, is_phonemes: bool = False, speed: float = 1.0) -> tuple[float, float]:
    started = time.perf_counter()
    samples, sample_rate = kokoro.create(
        text,
        voice=voice,
        speed=speed,
        is_phonemes=is_phonemes,
    )
    elapsed = time.perf_counter() - started
    duration = len(samples) / sample_rate
    return elapsed, duration


def report(label: str, elapsed: float, duration: float) -> None:
    print(f"{label}: {elapsed:.2f}s generation, {duration:.2f}s audio, RTF {elapsed / duration:.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="kokoro-v1.0.onnx")
    parser.add_argument("--voices", default="voices-v1.0.bin")
    parser.add_argument("--voice", default="af_bella")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--warmups", type=int, default=1, help="Warmup calls before steady-state measurements")
    parser.add_argument("--repeats", type=int, default=1, help="Repeats for steady-state full-text measurements")
    parser.add_argument("--speeds", default="", help="Optional comma-separated speed sweep, e.g. 1.25,1.5,2.0")
    parser.add_argument("--skip-clauses", action="store_true")
    args = parser.parse_args()

    try:
        from kokoro_onnx import Kokoro
        from kokoro_onnx.tokenizer import Tokenizer
    except ImportError as exc:
        print("Kokoro dependencies are missing; activate the Kokoro virtual environment first.")
        print(f"Import error: {exc}")
        return 2

    model = Path(args.model).expanduser()
    voices = Path(args.voices).expanduser()
    if not model.exists() or not voices.exists():
        print(f"Missing model or voices file: {model}, {voices}")
        return 2
    if args.repeats < 1 or args.warmups < 0:
        print("--repeats must be >= 1 and --warmups must be >= 0")
        return 2

    clauses = split_clauses(args.text)
    print(f"Model: {model}")
    print(f"Voice: {args.voice}")
    print(f"Text: {len(clauses)} clauses, {len(args.text.split())} words")

    tokenizer = Tokenizer()
    phoneme_started = time.perf_counter()
    phonemes = tokenizer.phonemize(args.text)
    phoneme_elapsed = time.perf_counter() - phoneme_started
    print(f"Phonemization: {phoneme_elapsed:.3f}s, {len(phonemes)} phoneme characters")

    kokoro = Kokoro(str(model), str(voices))

    cold_elapsed, cold_duration = render(kokoro, args.text, args.voice)
    report("Cold full text", cold_elapsed, cold_duration)

    for index in range(args.warmups):
        render(kokoro, "Warm up.", args.voice)
        print(f"Warmup {index + 1}/{args.warmups} complete")

    full_results = []
    for index in range(args.repeats):
        elapsed, duration = render(kokoro, args.text, args.voice)
        full_results.append((elapsed, duration))
        report(f"Warm full text {index + 1}", elapsed, duration)

    prephon_elapsed, prephon_duration = render(kokoro, phonemes, args.voice, is_phonemes=True)
    report("Warm pre-phonemized full text", prephon_elapsed, prephon_duration)
    print(f"Phonemization saved approximately {max(0.0, full_results[-1][0] - prephon_elapsed):.3f}s on this run")

    if not args.skip_clauses:
        clause_total_elapsed = 0.0
        clause_total_duration = 0.0
        print("\nPer-clause steady-state calls")
        for index, clause in enumerate(clauses, start=1):
            elapsed, duration = render(kokoro, clause, args.voice)
            clause_total_elapsed += elapsed
            clause_total_duration += duration
            report(f"Clause {index}", elapsed, duration)
        report("Clause calls total", clause_total_elapsed, clause_total_duration)
        print(f"Clause-call overhead versus one warm full call: {clause_total_elapsed - full_results[-1][0]:.2f}s")

    if args.speeds:
        print("\nSpeed sweep (changes audio duration; may not change model compute time)")
        for raw_speed in args.speeds.split(","):
            speed = float(raw_speed.strip())
            elapsed, duration = render(kokoro, args.text, args.voice, speed=speed)
            report(f"Speed {speed:g}", elapsed, duration)

    print("\nInterpretation: focus first on warm full text versus pre-phonemized full text.")
    print("If pre-phonemization saves only milliseconds, the ONNX session is the bottleneck.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
