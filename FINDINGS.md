# Agento — ARM Edge Voice Findings (Arduino UNO Q)

Technical writeup of what was tested and found, for reference and for
anyone else building real-time voice AI on this board. Factual/technical
description only — product/architecture reasoning and decisions live in
[conversation.md](conversation.md) and [PLAN.md](PLAN.md).

## Goal

Run a local, on-device bilingual (English/Spanish) voice tutor/assistant
entirely on an Arduino UNO Q (Qualcomm QRB2210, quad-core Cortex-A53,
Adreno GPU, 4GB LPDDR4 RAM), Debian Linux. Speech-to-text and
text-to-speech run fully on-device; only higher-level reasoning (agent/LLM
calls) is permitted to depend on a network API. Testing surfaced ARM-
platform-specific constraints worth documenting for anyone else targeting
this class of hardware for real-time on-device audio AI.

## Bluetooth microphone input (HFP/SCO) — tested, non-viable

**Setup tested:** Bluetooth headsets/speakers (JBL Focus 500, Bose
portable speaker) as the microphone input path via HFP (Hands-Free
Profile), through PipeWire + WirePlumber + BlueZ on the board's Debian
Linux host (direct shell access, not Arduino App Lab's containerized
Python environment).

**Output (A2DP) worked correctly** once several session/service
configuration issues were resolved:
- The board's default shell-access method does not create a full login
  session for the user account — `loginctl enable-linger <user>` is
  required before a working PipeWire/D-Bus session exists at all.
- WirePlumber's default profile gates Bluetooth audio on an "active"
  logind seat state, which a headless/SSH-style session never has.
  Resolved via WirePlumber's built-in `main-embedded` profile
  (`wireplumber --profile main-embedded`, made persistent via a systemd
  user-service override).
- The board's Debian image runs `lightdm` (a graphical login manager) by
  default, which starts its own independent PipeWire instance and
  registers Bluetooth audio profiles with BlueZ before any other session
  can. This blocks any other PipeWire instance from claiming Bluetooth
  audio (`RegisterProfile() failed: org.bluez.Error.NotPermitted`,
  `sco_listen: listen(): Address already in use`) until `lightdm` is
  stopped/disabled — reasonable on a headless device with no display
  attached and no configured autologin.

**Input (mic) never worked**, despite every software-layer indicator
reporting success: BlueZ negotiates the `headset-head-unit` profile
correctly, PipeWire creates the expected capture node with non-zero,
unmuted volume, and the connection reports `Connected: yes` throughout.

**Root cause**, found via an HCI-level packet capture (`btmon`), not
visible at any higher layer: the Bluetooth controller negotiates and
establishes the eSCO voice link successfully (`HCI Event: Synchronous
Connect Complete`, `Status: Success`, valid eSCO parameters) but **never
transmits a single `SCO Data` packet** over the HCI transport during the
active connection window — confirmed across the full duration of multiple
independent test recordings, on two physically different Bluetooth
peripherals from different manufacturers. Everything else observed during
that window (RFCOMM/AT-command control traffic, vendor diagnostic
telemetry) is present and correctly timed; only the actual audio payload
never appears on the wire.

**Conclusion:** this is a firmware/controller-level failure to deliver
SCO audio over HCI, not a configuration or userspace software bug. It
cannot be fixed by PipeWire, WirePlumber, BlueALSA, or any other
userspace Bluetooth audio stack, since the failure exists below the point
any of them can observe or influence. Independently reconfirmed via three
separate analysis passes over the same capture. Mic input on this board
should be wired (USB or I2S), not Bluetooth.

## TTS model testing (on-device speech synthesis)

Tested on the same board, CPU-only inference (no GPU/NPU execution
provider available for either model tested).

### Kokoro-82M (ONNX Runtime, fp32) — good quality, not viable speed

- Quality: natural, non-robotic — confirmed by listening test.
- Speed: **not viable**. ~5-6 second fixed cost per synthesis call
  regardless of input text length, plus ~1.2s of additional compute per
  word. Confirmed compute-bound (CPU utilization measured at 386% across
  4 cores during generation, i.e. near-saturated), not a threading/config
  issue — tested and ruled out: explicit thread-count tuning was not
  attempted further once saturation was confirmed, since more threads
  cannot help an already-saturated CPU.
- Text-clause chunking (splitting a response into shorter segments,
  pipelining generation with playback) was tested as a mitigation.
  Result: **made total generation time worse** (the fixed per-call cost
  is paid once per chunk, so more chunks means more total fixed cost),
  and did not meaningfully reduce time-to-first-audio either, since the
  fixed cost dominates even for very short inputs (a single word still
  incurred the full ~5-6s floor).

### Kokoro-82M, INT8-quantized — slower than fp32 on this CPU

- Standard expectation going in: INT8 quantization reduces inference
  time relative to fp32.
- Measured result: **1.5-2x slower** than fp32 across every input tested
  (single words through full sentences), not faster.
- Likely explanation: INT8-accelerated inference depends on ARM's
  dot-product SIMD instructions, introduced in the ARMv8.2-A instruction
  set. The Cortex-A53 in this board's QRB2210 is an **ARMv8.0-A core**,
  predating those instructions. Without hardware support for fast
  low-precision math, quantized inference pays dequantization/requantization
  overhead at each operation without the compute savings that make
  quantization worthwhile on newer cores.

### Piper (VITS-based) — viable speed, variable quality by voice

- Speed: **dramatically better than Kokoro** — roughly 0.4-2s per
  utterance for realistic short-to-medium response lengths, measured
  warm (model loaded once, reused across calls) — a ~10-20x improvement.
- Quality varies significantly **by specific voice, not by nominal
  quality tier alone**. Piper ships voices at declared tiers (`x_low`,
  `low`, `medium`, `high`), but tier is not a reliable speed predictor:
  two "high" tier voices tested (`en_US-lessac-high`, `es_AR-daniela-high`)
  took 13-16 seconds per utterance — back in Kokoro's non-viable range —
  while a third "high" tier voice (`es_MX-claude-high`) took ~2.7
  seconds, comparable to `medium`-tier voices. This means different
  "high" tier voices are genuinely different underlying model
  sizes/architectures, not a uniform scaling of the same model.
- English quality at `medium` tier (`en_US-lessac-medium`) was assessed
  by direct listening as noticeably more robotic than Kokoro — described
  as "about 70% of the way to acceptable," usable but not polished.
- Spanish voices tested (`es_ES-davefx-medium`, `es_MX-claude-high`)
  were subjectively judged more natural-sounding than the English voices
  tested, at comparable or better speed. Not yet isolated whether this is
  primarily a property of the specific voice models tested, or a more
  general effect of Spanish's more regular grapheme-to-phoneme
  (spelling-to-sound) mapping compared to English — both plausible,
  contributing factors, not yet separated experimentally.

## Relevance to ARM platform / product design decisions

- **INT8 quantization is not a reliable speedup lever on Cortex-A53
  (ARMv8.0-A) class cores.** Projects targeting this SoC generation for
  real-time on-device AI audio (or likely other neural inference)
  workloads should not assume quantization improves CPU inference speed
  — verify on real hardware before depending on it, and budget model
  *size* (parameter count / FLOPs) as the more reliable lever instead.
- **Bluetooth HFP/SCO microphone input should not be assumed to work**
  on this board's current Bluetooth firmware/driver stack. A2DP output
  is unaffected and works reliably. Products needing voice *input*
  should plan for a wired microphone (USB or I2S) rather than relying on
  Bluetooth headsets/earbuds for capture.
- **TTS model "quality tier" labels are not reliable speed predictors**
  across different voice exports within the same framework — measure
  each candidate voice directly on target hardware rather than assuming
  tier-to-speed consistency.

## Status / open items

- **English default: `en_US-ryan-medium`** (2.16s generation, quality
  judged better than the initial `lessac-medium` candidate). Broader
  survey of `medium`-tier voices confirmed `medium` tier is a reliably
  fast choice across every speaker tested (`lessac`, `davefx`, `ryan`,
  `amy` all land 0.4-3s); `high` tier is a gamble that mostly loses
  (`lessac-high` 16.5s, `daniela-high` 13.3s, `ryan-high` 14.7s,
  `cori-high` 18.1s all non-viable — `claude-high` at 2.7s is the one
  exception found so far, not the norm). Speed and quality are
  independent axes: `amy-medium` matched `ryan-medium`'s speed but was
  judged clearly worse ("robot") — quality still requires a listening
  test per voice, speed data alone doesn't predict it.
- **Spanish default: `es_MX-claude-high`** (fast, subjectively best
  quality heard so far, notably an exception to the high-tier-is-slow
  pattern above).
- Not yet tested: whether ONNX Runtime has any usable execution path to
  this SoC's Adreno GPU (would sidestep the CPU-bound constraints above
  entirely if viable) — flagged as a real unknown, not yet investigated.
- Not yet built: the actual integrated STT → LLM → TTS pipeline. Every
  component has been benchmarked in isolation; nothing has been wired
  together end-to-end yet. This is the actual next step toward a working
  v0 loop.
