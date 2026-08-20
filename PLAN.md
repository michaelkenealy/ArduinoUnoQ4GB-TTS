# Agento — Project Plan

Working names in circulation: **Agento**, "Household Voice Agent",
"Two Voices", "Casa Agent". This plan uses **Agento**.

Screen-free, battery-powered voice appliance on an Arduino UNO Q, with two
switchable identities: an agentic productivity assistant (parent mode) and a
locked-down Spanish-language learning companion (child mode). Built for daily
household use and as the hardware entry for the **Autodesk University 2027
Product** contest.

See [SPEC.md](SPEC.md) for the technical spec and [COMPETITION_ENTRY.md](COMPETITION_ENTRY.md)
for the contest application draft.

## Status

Breadboard-stage. Board is in hand and under test. Voice stack and agent
harness choices are made (see SPEC.md decisions log). whisper.cpp is built
and benchmarked on-device (tiny.en greedy decode is the current best
config, RTF ≈ 0.51 — see conversation.md and setup.md 2026-08-01).

**Bluetooth audio architecture resolved (2026-08-02): output only, not
mic input.** After extensive investigation (missing logind session,
WirePlumber seat-gating, a conflicting `lightdm` PipeWire instance — all
fixed) Bluetooth **output** (A2DP) works cleanly and is confirmed with
real audible playback on two devices. Bluetooth **mic input** (HFP/SCO)
was root-caused via an HCI trace to a firmware/controller limitation on
this board, independently reconfirmed twice more — the eSCO link
negotiates successfully but the controller never emits audio data over
HCI, on two unrelated Bluetooth devices. Not fixable in software; closed
for good, not just pending a hardware test — see SPEC.md §1/§12 and
conversation.md 2026-08-02. **Mic input is wired** (USB for near-term
testing, I2S MEMS mic in the final enclosure — the original BOM plan, not
a new direction). Live on-device mic testing is blocked on acquiring a USB
mic; STT model validation proceeds meanwhile via a laptop-recorded test
file transferred to the board.

## v0 north star

**Product strategy reset, 2026-08-02** (see conversation.md for full
reasoning), **sharpened same day**: the single thing that has to work
before anything else is attempted is not just "a loop that runs" — it's a
loop that **feels human and responds fast enough**, on this board's 4GB
RAM:

> Press button → speak → transcribe → safe response → spoken reply —
> **non-robotic, low-latency.** If this doesn't hold up, nothing else
> (memory, skills, kid mode, morning digest) matters, because the core
> interaction itself hasn't been validated as viable.

Kid mode is explicitly **not in active planning right now** — not later-
phase, not being sequenced against memory/digest, just off the table
until the core loop is proven. Don't revisit phase-ordering questions
about it until v0 is solid. Everything post-v0 (Phases 2–6) stays
deferred as before.

**Resolved (2026-08-07): TTS is Piper, not Kokoro.** Kokoro-82M was
installed, benchmarked, and comprehensively ruled out — good quality, but
every speed lever tested (chunking, INT8 quantization, phonemization
isolation, warm repeated calls, the `speed` parameter) failed to make it
viable; INT8 was even *slower* than fp32, traced to this board's
Cortex-A53 predating the ARM instructions INT8 inference needs for a
speedup. Piper is ~10-20x faster (0.4-3s vs. 6-90s per realistic
response) with acceptable, if not Kokoro-level, quality. Voice defaults:
English `en_US-ryan-medium`, Spanish `es_MX-claude-high`. Full technical
writeup in [FINDINGS.md](FINDINGS.md); decision summary in
conversation.md 2026-08-07.

Supporting principles adopted alongside this:
- Agent + audio orchestration runs on the Linux side; the STM32 MCU stays
  scoped to button/LEDs/power-state only (reaffirms SPEC.md's existing
  plan under time pressure not to scope-creep).
- **Audio abstraction layer**: the STT/TTS/agent pipeline shouldn't care
  whether audio comes from USB, Bluetooth (output only), or an eventual
  custom mic module — swapping the transport shouldn't touch the pipeline.
- Battery: prototype on an external USB-C power bank. Battery electronics
  are explicitly not a v0 concern (Phase 6 stays deferred).
- Interaction model: press-to-talk state machine (SPEC.md §7), not
  wake-word, for v0.
- v0's success test: does a parent reach for this instead of their phone
  specifically because their hands are full and it remembers context —
  testable with just the one loop, no kid mode required.

## Phases

### Phase 0 — Feasibility & architecture decisions (done)
- Confirmed UNO Q (4GB RAM, QRB2210 quad Cortex-A53 + STM32 co-MCU) can host
  STT + TTS + agent orchestration resident in RAM simultaneously (~1.3–1.6GB
  footprint, ~2.4GB headroom).
- Selected local STT/TTS: whisper.cpp + Piper (ONNX), rejecting Kokoro-82M
  (comprehensively benchmarked 2026-08-07 — good quality, but not viable
  speed on this CPU; see FINDINGS.md) and Fish Speech / XTTS v2 (need
  4–12GB VRAM, not viable on-board).
- Selected agent harness: smolagents-style minimal tool-calling loop,
  rejecting Hermes Agent (heavy Python/DB/messaging stack, disk-partition
  friction on the UNO Q's constrained eMMC user partition).
- Rejected on-device heavy LLM hosting; cloud API (Claude/DeepSeek) handles
  reasoning, board handles wake word, STT, TTS, and fast/simple skills.

### Phase 1 — Core voice loop (= all of v0, see above)
- whisper.cpp STT resident in RAM at boot. **Model choice under test as of
  2026-08-01** — original plan (`base.en`, q4) is looking too slow on real
  hardware (RTF ≈ 1.15 even at greedy decode; encode time is a fixed cost
  independent of quantization/decode strategy); `tiny.en` (unquantized,
  greedy) is the current front-runner at RTF ≈ 0.51. Final choice deferred
  until quantized variants and Moonshine are benchmarked too — see STT
  backlog below and conversation.md 2026-08-01.
- Piper (ONNX runtime) TTS resident in RAM at boot — not lazy-loaded (model
  load takes ~8-13s, unacceptable to pay per-utterance; fine as a one-time
  boot cost). Voice: `en_US-ryan-medium` (English), `es_MX-claude-high`
  (Spanish) — see FINDINGS.md for how these were chosen.
- Interaction model: press-to-talk state machine (SPEC.md §7) —
  `SLEEP → LISTENING → PROCESSING → SPEAKING → SLEEP`, 30s inactivity
  timeout from last detected speech, not from button press. Wake-word is
  explicitly a post-v0 addition, not part of this phase.
- Exit criteria: sub-1s round trip from end-of-speech to first audio token
  for a canned response.

**Audio I/O, final: wired mic (USB now, I2S in the final enclosure) +
Bluetooth for TTS output only.** BT-for-mic was explored and conclusively
ruled out (firmware limitation, see Status above and SPEC.md §12) — this
isn't a fallback pending further testing, it's the settled architecture.
Next hardware action: acquire a USB mic.

**Bring-up steps so far (host shell, not App Lab):**

**Do this over direct SSH on the Debian host, not inside an App Lab "app"
project.** App Lab's Python apps run in `uv`-managed Docker containers that
(per community reports) lack `gcc`/build headers and can't see host
`apt`-installed packages — that breaks whisper.cpp's native build and any
Python package needing C compilation, and Bluetooth/PipeWire configuration
is a host system-service concern App Lab isn't meant for anyway. Wrapping
the proven pipeline into an App Lab app (for STM32/Bridge access) is a
later, separate decision — see conversation.md 2026-08-01.

0. ✅ Done — used App Lab's "Connect to Shell" (confirmed host-level, not
   the Docker container App Lab Python apps run in).
1. ✅ Done — `apt update`, installed `build-essential`/`cmake`. Root
   partition turned out roomier than expected (5.3G free of 9.8G); see
   SPEC.md §1.
2. ✅ Done — paired JBL Focus 500 via `bluetoothctl` (test device swap from
   AirPods Pro 2, see conversation.md 2026-08-02). Getting audio actually
   routed required three additional fixes not originally anticipated:
   `loginctl enable-linger arduino` (no logind session existed for
   `arduino` at all), switching WirePlumber to its `main-embedded` profile
   (default profile gates Bluetooth on active-seat state, which a headless
   session never has), and disabling `lightdm` (was running a competing
   PipeWire instance that had already claimed BlueZ's audio profiles). Full
   root-cause chain in setup.md §8, decision summary in conversation.md
   2026-08-02.
3. ✅ Confirmed — `wpctl status` shows JBL Focus 500 as both default sink
   (A2DP) and default source (HFP mic, via `bluez_input.<mac>`). Audio
   routing is live; **next** is actually playing/recording through it
   (test wav playback, mic sample) rather than just confirming presence.
4. ❌ **Ruled out** — BT mic input (HFP/SCO) is non-viable on this board:
   an HCI trace (`btmon`) showed the eSCO link negotiates successfully but
   the controller never emits `SCO Data` packets — audio never flows
   despite a "successful" connection, confirmed on two unrelated devices
   (JBL Focus 500, Bose "Undercover"). Firmware/controller limitation, not
   fixable via PipeWire/WirePlumber/BlueALSA config. Full investigation in
   setup.md §8, conclusion in conversation.md 2026-08-02.
5. **Superseded** — mic input goes wired instead (USB now, I2S in the
   final enclosure; the original BOM plan). Next action: acquire a USB
   mic. Until then, STT model/accuracy validation proceeds via a phrase
   recorded on the laptop and transferred to the board — decouples model
   choice validation from live capture hardware.
6. ✅ Done — stood up TTS (Kokoro tested and rejected, Piper adopted; see
   FINDINGS.md), played back over BT (output path unaffected by the mic
   finding — confirmed working).
7. Time a full mic→transcribe→respond→speak round trip once a wired mic
   is in hand — the mic leg is now wired (fast, no BT profile-switch
   delay to worry about), only TTS output remains over BT. Still
   pending: the actual integrated pipeline doesn't exist yet — every
   component so far has only been tested standalone.

**STT model/quantization backlog (deferred until after Bluetooth test
items 1–3, see conversation.md 2026-08-01):**
- Quantized whisper weights (`q5_0`/`q5_1`/`q8_0`) — cheap lever, not yet
  tried; expect meaningful speedup on ARM NEON with little accuracy loss.
- **Moonshine** (`moonshine-tiny`/`moonshine-small`) — purpose-built for
  edge STT, handles variable-length input natively instead of Whisper's
  fixed 30s-window zero-padding. Worth prioritizing over further Whisper
  tuning: that padding overhead specifically penalizes short commands,
  which is our actual use case, not long clips like the JFK test sample.
- Distil-Whisper (`distil-small.en`) — less clearly relevant since we're
  already at `tiny`, where distillation gains are smaller than at `small`+.
- English-only vs. multilingual weights — already satisfied, we're testing
  `.en` variants.
- Whisper Large-v3-Turbo — deprioritized, unlikely to fit real-time
  constraints on this CPU.
- Also untested: keeping the model resident across requests instead of
  `whisper-cli`'s per-invocation reload (~200ms saved per utterance in
  the real deployment), and benchmarking a realistic ~3s command instead
  of extrapolating from the 11s JFK sample.

**Bluetooth audio test plan — final status, closed:**

| # | Test | Result |
|---|---|---|
| 1 | Pairing & reconnect | ✅ **PASS** |
| 2 | A2DP output quality | ✅ **PASS** — confirmed via real audible playback (JFK sample through the Bose) |
| 3 | HFP/HSP mic sample rate | ❌ **Moot** — superseded by test 4's finding |
| 4 | Whisper accuracy on BT mic | ❌ **N/A — BT mic ruled out entirely.** Root cause found at the HCI level (`btmon`): eSCO link negotiates successfully but the controller never emits `SCO Data` packets, on two unrelated devices (JBL, Bose). Firmware/controller limitation, independently reconfirmed twice, not a config issue. |
| 5 | Profile switch latency | ❌ **N/A** — moot, no BT mic leg to switch to/from |
| 6 | Full round trip | ➡️ **Superseded** — round trip will be re-tested once a wired mic is in hand; only the TTS-output leg stays over BT |

**Next up:**
- **Assemble the actual integrated STT → LLM → TTS pipeline** — the real
  next milestone. Every component (whisper.cpp, Piper) has only been
  benchmarked standalone; nothing is wired together yet. Doesn't require
  the USB mic to start — can trigger with typed/pre-recorded input.
- Acquire a USB mic (the actual unblocking action for live on-device testing).
- Meanwhile: record a test phrase on the laptop, transfer it to the board,
  validate whisper.cpp accuracy on real speech independent of live capture.
- Resolve STT model choice (quantization, Moonshine vs. tiny.en — backlog
  above) once a wired mic allows testing against real captured speech
  rather than only the bundled JFK sample.

### Phase 2 — Agent harness & skills (post-v0)
- Minimal Python tool-calling loop (smolagents `CodeAgent` or hand-rolled
  equivalent) wired to a cloud LLM (Claude Haiku / DeepSeek) for intent
  parsing and structured tool calls.
- First skills: morning stats/hardware check, RSS/news summary, weather,
  read-aloud utility (hands-free recipe/step reading).
- Skills live as plain `@tool`-decorated functions in a `skills/` directory,
  loaded dynamically — no framework-specific skill format.
- Exit criteria: three working skills, invoked correctly from open-ended
  voice phrasing, not just exact commands.

### Phase 3 — Morning digest job (post-v0)
- systemd timer (07:00) runs a fixed pipeline: gather RSS + weather +
  calendar + board/hardware status → synthesize via cloud LLM into a ~45s
  spoken brief → Piper TTS → play on wake or on next interaction.
- Exit criteria: unattended overnight run produces a correct, current brief
  without manual trigger.

### Phase 4 — Memory & persistence pipeline (post-v0)
- Daily ECL (Extract → Cognify → Load) job over captured conversation logs:
  extract episodic/semantic/procedural facts, resolve against existing
  store (ADD / UPDATE / DELETE / NOOP), promote recurring patterns to
  candidate skills.
- Local-first storage (SQLite + lightweight vector store) on the 32GB eMMC.
- Injection of top-N relevant facts into the system prompt at runtime.
- Exit criteria: a fact stated on day 1, contradicted on day 3, is correctly
  updated (not duplicated) and reflected in a day-4 conversation.

### Phase 5 — Dual-mode wake word & child mode (post-v0)
- Second wake phrase switches to child mode: Spanish-only, fixed
  parent-curated content list, no open-ended generation, no web access, no
  reachability into parent-mode skills or data.
- Soft speaker-similarity check against an enrolled child voice profile —
  documented explicitly as a usability gate, not a security boundary.
- Parent-mode UI (voice or simple local web form) for curating the child
  content list.
- Exit criteria: child mode cannot, through any phrasing, trigger a
  parent-mode skill or return unscripted content.

### Phase 6 — Hardware & enclosure (post-v0)
- Fusion 360 parametric enclosure: handheld dimensions, on/off button
  cutout, mic + speaker ports, USB-C charge cutout, battery bay, BLE-safe
  (non-shielding) material.
- Battery + charge/protection circuit sizing against target runtime.
- PCBWay fabrication of a first physical shell.
- Exit criteria: working breadboard electronics fit inside a fabricated
  shell with functioning button, ports, and charging.

### Phase 7 — Contest submission
- Finalize COMPETITION_ENTRY.md content against the live Hackster
  application form (field labels unconfirmed as of this writing — see note
  in that file).
- Link Fusion project (even if not final form factor).
- Submit before contest deadline (TBD — confirm from contest page once
  reachable).

## Open decisions to track

- Local-first vs. cloud-synced backup for the memory store — currently
  leaning local-first, especially for child-mode data.
- Mem0 vs. Cognee/Graphiti vs. hand-rolled SQLite for the memory pipeline
  (Phase 4) — not yet chosen, see SPEC.md.
- Battery capacity / target runtime not yet sized.
- Contest deadline and exact form fields unconfirmed.
