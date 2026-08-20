# Agento — Technical Spec

Status: **draft, in progress**. Covers the capabilities scoped in
[PLAN.md](PLAN.md); fills in as design decisions firm up. Source material:
research conversation on Hermes Agent vs. lighter alternatives for the
Arduino UNO Q (see decisions log at bottom), and the Autodesk University
2027 contest draft in [COMPETITION_ENTRY.md](COMPETITION_ENTRY.md).

## 1. Hardware platform

- **Compute:** Arduino UNO Q — Qualcomm Dragonwing QRB2210, quad-core
  Cortex-A53, Adreno GPU, 4GB LPDDR4 RAM, 32GB eMMC, running Debian Linux.
- **Real-time co-processor:** on-board STM32U585 MCU, bridged to the Linux
  side via Arduino's RPC/Bridge layer. Owns the physical on/off button,
  power management, and wake-state signaling — things that must not stall
  on a Linux/Python hiccup.
- **I/O:** wired MEMS microphone (USB for near-term testing, I2S in the
  final enclosure), mono speaker, physical on/off pushbutton, USB-C
  (charging), Li-Po battery + charge/protection circuit, WiFi 5, Bluetooth
  5.1 (**output only** — earbud/speaker pairing for TTS playback).
  Bluetooth mic (HFP/SCO) input was tested and confirmed non-viable on
  this board: an HCI trace (`btmon`) showed the eSCO connection negotiates
  successfully but the controller never emits `SCO Data` packets — a
  firmware/controller limitation, not a config issue. A2DP output is
  unaffected (different data path, L2CAP not SCO). See conversation.md
  2026-08-02 for the full investigation and decisions log below.
- **Storage constraint:** confirmed on-device (2026-08-01): root (`/`,
  `mmcblk0p68`) is 9.8GB with 5.3GB free — roomier than initially assumed,
  enough for `build-essential`/`cmake` and similar system packages.
  `/home/arduino` (`mmcblk0p69`) is 18GB with 17GB free. App Lab's own apps
  and app data still live under `/home/arduino/arduino_apps/`, and that
  remains the right place for application-level data (models, skills,
  memory store) — but the root partition is not as tight as earlier
  research suggested; it's not a reason to avoid normal `apt install` use.

## 2. Voice pipeline (STT/TTS)

Both models are loaded once at boot and **kept resident in RAM** for the
life of the process — not lazy-loaded per interaction. Cold load takes
0.8–1.5s for whisper and roughly 8–13s for Piper (confirmed on-device,
2026-08-07 — higher than originally estimated) — enough dead air either
way to break the sense of a live conversation, and the board has RAM to
spare, so there's no reason to trade latency for memory it isn't using.

| Layer | Choice | RAM (resident) | Notes |
|---|---|---|---|
| STT | whisper.cpp, model TBD (`base.en` too slow on real hardware, RTF≈1.15 even at greedy decode; `tiny.en` unquantized is the current front-runner, RTF≈0.51 — see PLAN.md Phase 1 STT backlog for quantization/Moonshine comparisons still pending) | ~150–390MB depending on model | Native C++ binary, not Python — avoids GC pauses. |
| Wake word / VAD | silero-vad or pvporcupine | small | Local, always listening. |
| TTS | Piper (VITS-based, ONNX) — `en_US-ryan-medium` (English), `es_MX-claude-high` (Spanish) | smaller than Kokoro's 500-900MB; exact figure TBD | Confirmed on-device 2026-08-07: ~10-20x faster than Kokoro-82M (0.4-3s vs. 6-90s per realistic response, warm). Quality is a step down from Kokoro but judged acceptable given the speed gap. Full benchmark data in FINDINGS.md. |
| OS + Python runtime | Debian + orchestrator | ~350–430MB | FastAPI/uvicorn serving TTS locally over HTTP. |
| **Total resident** | | **TBD, likely lower than original ~1.3–1.6GB estimate** | RAM headroom was never the constraint; not re-measured since switching to Piper. |

Rejected alternatives and why:
- **Kokoro-82M (ONNX Runtime)** — the original choice, evaluated and
  rejected on real hardware (2026-08-07): quality was good (natural,
  non-robotic) but speed was not viable — ~5-6s fixed cost per synthesis
  call regardless of text length, plus ~1.2s/word, confirmed compute-bound
  (CPU maxed at 386% across 4 cores). Every mitigation tested (clause
  chunking, INT8 quantization, phonemization isolation, the `speed`
  parameter) failed — INT8 was actually *slower* than fp32, traced to the
  Cortex-A53 lacking the ARMv8.2 dot-product instructions INT8 inference
  needs for a real speedup. Full writeup in FINDINGS.md. This reverses the
  original Piper-vs-Kokoro call below — Piper's speed advantage turned out
  to matter more than Kokoro's quality advantage, once real numbers existed.
- **Fish Speech / Fish Audio** — best-in-class expressiveness and zero-shot
  voice cloning, but needs 8–12GB+ VRAM and GPU acceleration; unusable on a
  Cortex-A53 CPU (minutes, not milliseconds, per utterance). Out of scope
  unless offloaded to a laptop/desktop GPU or cloud API over the network —
  not planned for v1.
- **XTTS v2 (Coqui)** — voice cloning capable but ~4.5GB RAM and wants GPU;
  same story as Fish Speech, out of scope for on-board execution.
- **MeloTTS** — viable lightweight fallback (<200MB, CPU-friendly) — not
  tested since Piper resolved the speed problem directly; kept as a
  documented fallback if Piper's quality ceiling ever becomes a blocker.

## 3. Agent / tool-calling harness

**Decision: do not run Hermes Agent on-device.** Hermes is a full
autonomous-agent framework (persistent SQLite/vector memory, multi-platform
messaging gateways, async task queues, heavy `uv`/Python dependency tree).
On the UNO Q it would still only be forwarding API payloads to a remote LLM
— i.e. running an entire agent OS on the edge board to do what a ~15-line
tool-calling loop can do, while fighting the small eMMC partition for
package storage the whole time.

Instead: a minimal Python tool-calling loop, in the style of Hugging Face's
`smolagents` (`CodeAgent`) — the LLM writes/calls small Python actions
against locally-defined tools rather than the app maintaining a bespoke JSON
schema layer. Reasoning/intent-parsing is delegated to a cloud LLM (Claude
Haiku, DeepSeek) reached over WiFi; the board itself never hosts a large
local model.

```python
from smolagents import CodeAgent, HfApiModel, tool

@tool
def get_board_temperature() -> str:
    """Returns internal board temperature from the MCU bridge."""
    return "34.2 C"

agent = CodeAgent(tools=[get_board_temperature], model=HfApiModel())
```

If even `smolagents`' footprint turns out to be unnecessary, fall back
further to raw provider tool-calling (Anthropic/OpenAI JSON tool schemas)
plus a hand-rolled dispatch loop — effectively zero framework overhead, at
the cost of writing the glue by hand. Decision point: revisit after Phase 2
if `smolagents` shows any friction on-device.

## 4. Skills system

- A skill is a plain Python function under `skills/`, decorated with
  `@tool`, documented via type hints + docstring (the harness reads these to
  describe the tool to the LLM — no separate schema file to maintain).
- Skills are loaded dynamically (`importlib`) at startup; adding a skill is
  "write a function, add it to the tools list."
- v1 skills: morning stats / hardware status (via MCU bridge), RSS/news
  summary, weather lookup, hands-free step-by-step read-aloud (e.g. recipes).
- Skills that don't need agentic tool selection (fixed daily jobs) should
  just be plain scripts invoked by systemd timers, not routed through the
  agent loop — the agent is for unpredictable voice-driven requests, not
  fixed cron work (see §5).

## 5. Morning digest job

Fixed pipeline, not agent-mediated, triggered by a systemd timer at 07:00:

1. Gather: RSS/news feed(s), weather API, calendar, MCU-reported hardware
   status (battery, sensors).
2. Synthesize: pipe gathered raw data to a fast cloud model with a fixed
   prompt ("condense into a ~45s spoken brief").
3. Speak: send the resulting text to the always-resident Piper instance via
   its local HTTP endpoint; play on speaker.

## 6. Memory & persistence pipeline

Goal: recurring conversations build on prior ones (compounding context);
one-off conversations don't pollute long-term memory. Structured as an
**ECL pipeline** (Extract → Cognify → Load), run as a daily batch job over
the day's captured transcripts, not per-turn.

### 6.1 Memory tiers

| Tier | Captures | Example |
|---|---|---|
| Episodic | What happened, when | "On [date], debugged the motor driver on the turret project." |
| Semantic | Facts / entity relationships | `[Piper] --voice--> [en_US-ryan-medium]`, `[User] --dislikes--> [Kokoro's speed on this board]` |
| Procedural | How-to / recurring workflows | "Morning brief = scrape feed → summarize via Haiku → Piper TTS." |

### 6.2 Daily extraction & consolidation loop

1. **Extract** (cheap LLM, e.g. Haiku/DeepSeek): pull structured
   `episodic_summary`, `extracted_facts`, `candidate_skills` out of the
   day's transcripts.
2. **Resolve**: for each extracted fact, classify against the existing
   store as `NOOP` (already known), `ADD` (new), or `UPDATE`/`DELETE`
   (contradicts an existing fact — e.g. a changed hardware/tooling choice)
   rather than blindly appending, which would let stale facts accumulate.
3. **Consolidate**: if a task/workflow recurs across multiple days'
   transcripts, flag it as a candidate skill and draft a standalone
   function into `skills/` for review.

### 6.3 Storage

- Local-first on the 32GB eMMC: SQLite for structured facts, a lightweight
  vector/graph store for semantic retrieval.
- Candidate frameworks (not yet chosen — see decisions log):
  - **Mem0** — fastest to stand up; built-in extract→update pipeline with
    contradiction handling; SQLite/vector backend (Qdrant/LanceDB).
  - **Cognee / Graphiti** — stronger for temporal, multi-hop knowledge
    graphs across sessions ("show all hardware bugs logged in the last 3
    weeks"); more moving parts.
  - Hand-rolled SQLite + prompt injection — lowest overhead, most manual
    work, full control.
- Child-mode content/state is kept **local-only**, no cloud sync, regardless
  of what's decided for the parent-mode memory store.

### 6.4 Runtime use

At query time: fetch top-N semantically relevant facts from the store →
inject into the LLM system prompt → run the agent tool loop. This is how
the assistant avoids re-asking things already answered and keeps context
across sessions without re-summarizing full history every time.

## 7. Interaction state machine (v0)

```
SLEEP
  ↓ button press
LISTENING
  ↓ speech ends / inactivity timeout
PROCESSING
  ↓
SPEAKING
  ↓ optional short follow-up window (reuses LISTENING)
SLEEP
```

- **v0 is press-to-talk, not wake-word.** Safer and more predictable for
  a first prototype — wake-word detection isn't built yet.
- **30s inactivity timeout is measured from the last detected speech**,
  not from the button press — a hard timer from press would cut off a
  user mid-conversation if they paused to think. Each turn (LISTENING →
  PROCESSING → SPEAKING) resets the clock; only silence after the last
  reply counts down to SLEEP.
- Wake-word is a later addition (PLAN.md), not a v0 requirement.

## 8. Dual-mode wake word & child safety model

- **Parent mode** (default): English, switchable to Spanish on request.
  Full skill/tool access, dictation, memory read/write.
- **Child mode**: separate, distinct wake phrase. Spanish-language only.
  Content restricted to a small, parent-curated list (vocabulary practice,
  short guided lessons) managed from parent mode. No open-ended chat, no
  web access, no reachability into parent-mode skills, data, or memory
  store.
- **Mode selection is always a deliberate action, never passive
  recognition** — this is a firm boundary, not a v0-only simplification.
  Two supported mechanisms, kept for different reasons:
  - The **wake phrase** is the primary kid-mode entry point, so a child
    can start their own session without an adult manually switching
    anything — a real independent-use requirement. It's deliberate speech,
    not recognition, so it carries no false-positive safety risk.
  - The **phone app / a long-press** is a parent-controlled override — for
    forcing kid-mode-only at certain times, disabling it entirely, or as a
    fallback while wake-word detection doesn't exist yet.
  - **Automatic speaker/voice recognition for mode-switching is explicitly
    out of scope, indefinitely** — not deferred as "build it later," ruled
    out as a mechanism for this specific decision. If voice-based
    personalization is ever built (e.g. recognizing which parent is
    speaking to personalize responses), it must never be allowed near the
    parent/kid safety boundary.
  - Different chime/LED pattern per active mode, so it's always
    observable which policy is currently active.
- **Speaker check within child mode**: lightweight voice-similarity match
  against an enrolled child profile once *already in* child mode. This is
  a **soft usability gate**, explicitly *not* a security or mode-selection
  boundary — it reduces accidental confusion once in kid mode, it doesn't
  decide whether to enter kid mode and doesn't authenticate.
- The hard safety boundary is architectural, not biometric: child mode's
  process/config has no code path to parent-mode skills, finance data,
  dictation storage, or the open-ended agent loop, regardless of who
  triggers it.
- **Profile schema** (managed via the phone-based control plane, §9):
  ```yaml
  profile:
    mode: parent | kid
    language: en | es | bilingual
    voice: ...
    allowed_tools: [...]
    content_topics: [...]
    max_session_seconds: ...
  ```

## 9. Phone as setup/control plane

- Phone pairs over BLE, configures WiFi, creates parent/kid profiles (§8
  schema), sets language/voice/allowed tools/content topics/schedules/
  limits, and pushes those settings to the device.
- **After initial setup, the device works without the phone present.**
  Phone solves configuration only — it is explicitly not an audio
  transport and does not relay mic/speaker data (that question is settled:
  wired mic, Bluetooth output-only, see §1/§10).
- Implementation leans toward a **local web page hosted by the device
  itself**, reachable from any phone browser on the same WiFi, over a
  native app — keeps the device screen-free while configuration still
  happens on a screen the user already owns, with far less build overhead
  than a native app.

## 10. Networking

- WiFi 5 for cloud LLM API calls and data lookups (news, weather, pricing).
- Bluetooth 5.1 for earbud/speaker pairing — **output only** (TTS
  playback). Confirmed non-viable for mic input: HCI trace shows the
  controller never emits `SCO Data` packets despite successful eSCO
  connection setup — a firmware limitation, not fixable in software. Mic
  input is wired instead (see §1).
- No requirement for the device to be reachable from outside the LAN in v1.

## 11. Open questions

- Mem0 vs. Cognee/Graphiti vs. hand-rolled store for §6.3 — needs a
  hands-on spike before Phase 4.
- Whether parent-mode memory ever syncs off-device (backup/multi-device) —
  leaning no for v1.
- Exact wake-word engine (silero-vad vs. pvporcupine) — needs on-device
  false-positive testing with the two wake phrases running concurrently.
- Battery capacity / runtime target, and whether the enclosure needs active
  thermal management for sustained STT+TTS+agent load.

## 12. Decisions log (source: research conversation, dated pre-2026-08-01)

| Decision | Rejected alternative(s) | Reason |
|---|---|---|
| Piper (ONNX) for TTS, superseding Kokoro-82M | Kokoro-82M (reversed 2026-08-07 after on-device benchmarking — see §2), Fish Speech, XTTS v2, MeloTTS (fallback only) | Kokoro's quality was better but speed was not viable on this CPU (see §2 rejected-alternatives entry for full detail); Piper is ~10-20x faster with acceptable quality. Fish/XTTS need GPU/VRAM the board doesn't have. |
| whisper.cpp (native) for STT | Python-wrapped Whisper | Avoids GC overhead, loads faster, smaller footprint. |
| Both models resident in RAM at boot | Lazy/on-demand loading | Cold-load latency (2–3.5s) breaks conversational feel; RAM headroom makes it a non-tradeoff. |
| smolagents-style minimal tool-calling loop | Hermes Agent, Langroid | Hermes' DB/messaging/dependency stack is redundant weight for an edge orchestrator that just forwards to a cloud LLM; smolagents is ~1,000 LOC and skill-authoring is a plain decorated function. |
| Cloud LLM for reasoning, board handles STT/TTS/routing only | On-device large LLM hosting | UNO Q is CPU-only for inference at this scale; not viable to host 32B–70B locally. |
| ECL (Extract/Cognify/Load) daily batch memory pipeline with tiered (episodic/semantic/procedural) memory | Naive per-message vector dump | Naive dumps duplicate facts and never resolve contradictions; tiered + resolution logic (ADD/UPDATE/DELETE/NOOP) is required for "recurring conversations build on each other." |
| Wired mic (USB now, I2S in final enclosure), Bluetooth for output only | Bluetooth for both input and output | Confirmed on real hardware (2026-08-02): eSCO/HFP connection negotiates successfully but the board's BT controller never emits `SCO Data` packets over HCI — audio never flows despite a "successful" link, on two unrelated Bluetooth devices. A2DP output is unaffected (different data path, L2CAP not SCO). This is the original BOM plan; the detour through BT-for-mic was explored and ruled out, not a change from first principles. |
| v0 = one reliable loop (press → speak → transcribe → respond → speak) before any other feature | Building kid mode, memory pipeline, and BT hardware exploration in parallel | Trying to ship a parent assistant, a kid tutor, and custom Bluetooth hardware simultaneously is how projects stall; every other feature is a layer on top of a loop that has to work first. |
| Mode selection (parent/kid) via wake phrase or phone app/long-press only, never automatic voice recognition | Auto-detecting speaker to switch modes | False positives on a safety boundary are dangerous — mistaking a child's voice for an adult's could expose unrestricted content. Deliberate action only; voice-similarity stays a soft usability check *within* kid mode, never the entry mechanism. |
