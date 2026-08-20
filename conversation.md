# Agento — Conversation Log

Running log of decisions, research, and direction changes for this project.
Newest entries at the top. This is a project journal, not a spec — see
[SPEC.md](SPEC.md) for the current technical state and [PLAN.md](PLAN.md)
for the roadmap; this file explains *how* we got there and *why*.

---

## 2026-08-02 — Bluetooth mic: closed for good (not just pending a hardware test)

Follow-up to the root-cause entry directly below. The HCI trace conclusion
(eSCO link negotiates successfully, zero `SCO Data` packets ever appear —
firmware/controller not delivering audio over HCI) was independently
re-confirmed twice more via separate analysis passes over the same trace,
including one that correctly flagged bad advice in an earlier pass (a
non-portable `wpctl set-profile` index, and blind WirePlumber config edits
that can't fix a packet-level absence regardless of syntax). All three
passes converged on the same read.

One option was left open at that point: try an external USB Bluetooth
adapter, since it would use a different chipset/driver than the onboard
Qualcomm radio and could plausibly sidestep a vendor-specific firmware bug
(supporting evidence: the failing trace is dominated by Qualcomm-specific
vendor diagnostic packets). Cheap and worth a try in isolation — **but
closed as a real path during the broader product-strategy reset that
followed** (see next entry): even if a different adapter fixed *this*
board, HFP mic reliability across consumer Bluetooth headsets is a known-
flaky category industry-wide. Building the core product loop's reliability
on top of that would just relocate the fragility, not remove it. Final
architecture: **wired mic (integrated, known-good) is the core input path;
Bluetooth is strictly output-only and optional.** Not a consolation prize
— matches the original COMPETITION_ENTRY.md design ("a built-in mic and
speaker, and Bluetooth for pairing earbuds"), which always had Bluetooth
as an accessory transport, not the primary input method. The mid-session
exploration of BT-as-primary-mic was the detour, not the wired-mic
conclusion.

## 2026-08-07 — Separate project spun off: Versito (local audio content production tool), and Orpheus TTS testing underway

**Versito** (`c:\Users\mkene\Code\Versito`) — a new, explicitly separate local
Gradio-based tool for producing narrated audio content on the laptop's GPU,
distinct from Agento's on-device pipeline. Rationale: tonight's TTS findings
made clear that high-quality narration needs GPU-class hardware the board
doesn't have, so pre-generating content on the laptop and pushing it to a
delivery target (Tonie, the board, etc.) is a real, separate need, not a
detour. v1 built: paste text, pick a Kokoro voice (defaults to `ef_dora`,
Spanish), speed slider, generate, editable title (with an Ollama
`qwen2.5:7b-instruct`-powered suggest button), output filename derived from
title. Runs via a `run.bat` launcher, opens as a local webapp
(127.0.0.1:7860) rather than a native GUI, per explicit preference.

**Motivating problem for the next round of work**: the user's wife does not
approve of the Spanish voice quality — a concrete bar for "human enough."
Researched techniques used by Google NotebookLM (SoundStorm/AudioLM,
proprietary) and confirmed a real, current pattern: embedded inline
speech-direction tags (ElevenLabs v3 "Audio Tags", Gemini 3.1 Flash TTS
inline tags) — bracketed cues like `[whispering]`, `[pause=1.0]` directing
emotion/pacing/emphasis at the phrase level, replacing older SSML. Evaluated
and ruled out MagpieTTS (Nemotron Speech family) for now — 357M params is
fine, but the only confirmed CUDA-compatible deployment path (NVIDIA NeMo/
Riva) benchmarks at 10.87GB+ VRAM, over the 8GB budget; a community
quantized version exists (Soniqo) but is Apple Silicon-only (MLX/CoreML),
incompatible with this Windows/NVIDIA laptop. Also declined to pursue a
custom quantized MagpieTTS build — technically plausible (quantization is
much lighter than training, NeMo ModelOpt exists for exactly this) but real
risk (TTS vocoder/codec components are more quantization-sensitive than
typical LLMs) for no clear payoff given a working alternative exists.

**Landed on Orpheus TTS** (Canopy AI, 3B params, native emotion-tag
support, benchmarked as rivaling ElevenLabs) as the candidate to actually
test. Avoided the standard `pip install orpheus-speech` path — it depends
on vLLM, which has an active unresolved GitHub issue for Python 3.14
support (same category of gap hit with PyTorch's CUDA wheels earlier
tonight). Using the LM Studio-based path instead (`isaiahbjork/orpheus-tts-local`
wrapper), since the user already had LM Studio installed and GPU-configured.
Two GGUF checkpoints in use — Orpheus's multilingual support is fragmented
per-language, not one universal model: `isaiahbjork/orpheus-3b-0.1-ft-Q4_K_M-GGUF`
(English, voices tara/leah/jess/leo/dan/mia/zac/zoe) and
`lex-au/Orpheus-3b-Italian_Spanish-FT-Q8_0.gguf` (Spanish/Italian, Spanish
voices Javi/Sergio/Maria). Same emotion tag set on both (`<laugh>`,
`<sigh>`, `<cough>`, `<sniffle>`, `<groan>`, `<yawn>`, `<gasp>`, `<chuckle>`).
Status: downloading models and setting up the Python wrapper (LM Studio's
`lms` CLI confirmed available for scripted model load/server control, no
GUI interaction needed) — test batch in progress, not yet evaluated.

## 2026-08-07 — Word-level sync (future "lyrics" display idea): forced alignment via whisper.cpp is the recommended approach

Not being built now — noted for later. Raised idea: a future screen could
highlight words as they're spoken (karaoke/lyrics-style), which needs
word-level audio timing. Three options considered: (1) check whether
Piper/Kokoro expose internal phoneme-duration data directly (cleanest if
available, unconfirmed either way); (2) **forced alignment using
whisper.cpp's word-level timestamps** — since TTS output is generated
from known text, run the generated audio back through whisper.cpp and
match its timestamps against the source text; reuses infrastructure
already built and tested tonight, best accuracy-to-effort ratio; (3) crude
proportional estimation (duration ÷ word count, no real audio analysis) —
normally too inaccurate for real speech, but might work passably on our
specific TTS output given its prosody is already fairly flat/uniform.
**Recommended path when this gets built: option 2.**

## 2026-08-07 — TTS resolved: Kokoro out, Piper in. Voice defaults set.

Overnight/morning session, direct continuation of the Kokoro speed
investigation. Full technical detail now lives in [FINDINGS.md](FINDINGS.md)
(written for external/ARM-platform-feedback framing); this entry is the
decision summary.

**Kokoro-82M: comprehensively ruled out.** Every lever tested — clause
chunking, INT8 quantization, phonemization isolation, warm-process
repeated calls, the `speed` parameter — either did nothing or made things
worse. INT8 was actually *slower* than fp32 (1.5-2x), traced to the
Cortex-A53 predating the ARMv8.2 dot-product instructions INT8 inference
depends on for a real speedup. Not a config problem; a genuine hardware/
model mismatch.

**Piper: adopted.** ~10-20x faster than Kokoro for realistic short
responses (0.4-3s vs. 6-90s), tested warm (model resident, matching real
deployment). Quality is a step down from Kokoro but judged acceptable
given the speed gap is decisive. Voice **tier is not a reliable speed
predictor** — most `high`-tier voices tested were as slow as Kokoro,
`medium` tier was consistently fast across every speaker tried.

**Voice defaults set**: English → `en_US-ryan-medium`, Spanish →
`es_MX-claude-high` (a rare fast exception among high-tier voices, also
independently rated highly in Piper's own sample catalogue).

**Also observed, not yet confirmed**: Spanish voices tested sounded
subjectively more natural than English ones — plausible contributing
factor is Spanish's more regular spelling-to-sound mapping easing the
grapheme-to-phoneme step all these TTS systems depend on, but this is
entangled with a real voice-quality difference between the specific
models compared, not yet isolated.

**Next real milestone, not yet started**: every component (whisper.cpp,
Piper) has only been tested standalone. The actual integrated STT → LLM →
TTS pipeline doesn't exist yet — that's the next piece toward a working
v0 loop, and doesn't require the still-pending USB mic to start (can
trigger with typed/pre-recorded input in the meantime).

## 2026-08-02 — Kokoro installed and tested: quality is good, speed is a serious problem

Installed `kokoro-onnx` (the ONNX Runtime path, per SPEC.md — not the
default PyTorch-based `kokoro` package) in a host venv at
`~/kokoro-env`, model files at `~/kokoro/` (`kokoro-v1.0.onnx`,
`voices-v1.0.bin`). One real hiccup: first download of the `.onnx` file
was silently truncated (9.8MB of an expected 325,532,387 bytes) over the
same flaky connection that bit the earlier `git clone` — re-downloaded
with `curl --retry` and verified exact byte count before proceeding.
API also didn't match the README initially (`.generate()` doesn't exist
in installed version 0.5.0; introspected the actual class and found
`.create()` / `.create_stream()` instead — worth always verifying
against the installed version's real API rather than trusting docs that
may be for a different release).

**Quality: good.** Audio played through the Bose sounded natural, not
robotic — confirms Kokoro was the right model choice on quality grounds.

**Speed: a serious, unresolved problem.** `create()` took **22.62–22.85s**
to generate a single ~20-word sentence (4.80s of resulting audio) — an
RTF of ~4.76, far worse than even whisper's worst-case result (base.en
5-beam was 1.5x). Diagnosed, not guessed: CPU was confirmed maxed at
386.4% across all 4 cores during generation (checked via `top` in a
second shell tab while the script ran in the first — same two-tab
pattern used for the `btmon` trace), ruling out a threading fix. Tried
`create_stream()` (the library's built-in streaming API) hoping to
reframe the metric from "total generation time" to "time to first audio
chunk" — but it returned only 1 chunk for this input, with time-to-
first-chunk equal to total time, so no benefit for realistic short
responses.

**Not yet tested: manual clause-level chunking with pipelined playback**
(split response text into short clauses ourselves, generate+play them
sequentially so clause 2 generates while clause 1 plays) — prepared a
ready-to-run script (`test_tts_chunked.py`) for this, since it's the most
promising untested lever. If a short clause still takes many seconds to
generate, that's a much more serious finding pointing toward needing
quantization, a lighter model (Piper deserves a second look now that we
have real comparative speed data, despite being rejected earlier on
quality grounds), or offloading TTS to a cloud API (moves away from
local-first, a real tradeoff to weigh only if local options are
exhausted).

**Separately, corrected a second-opinion pass that re-litigated the
already-closed BT mic question** — it proposed re-checking
`bluetoothctl`/`wpctl`/`pactl` output for the Bose, which we already know
looks completely normal at that layer (that's exactly what made this bug
so hard to find — it's invisible above the kernel/HCI level, which is
why only `btmon` caught it). Not worth re-testing. Also flagged as a
genuinely open but lower-priority question: whether App Lab's Python
container has its own separate path to the audio hardware, distinct from
the host's PipeWire setup — relevant to the deferred host-vs-App-Lab
packaging decision, not to the mic question.

## 2026-08-02 — v0 gate sharpened: kid mode off the table, Kokoro is the untested risk

Follow-up to the strategy reset below, same day. Two refinements:

1. **Kid mode drops out of active planning entirely** — not "later phase,"
   not something to sequence against the memory pipeline, just off the
   table until the core loop is proven. The mode-selection/voice-
   recognition question raised (whether voice recognition should ever
   become a real mode-switching mechanism, vs. staying a soft post-wake-
   phrase check per SPEC.md §8) is explicitly deferred, not answered —
   premature to resolve before v0 is validated at all.
2. **v0's gate is sharper than "a loop that runs"**: it must feel human
   and respond fast enough on this board's 4GB RAM, or nothing else in
   the project matters. Identified the biggest untested assumption:
   **Kokoro (TTS) has never been installed or run on this board** — all
   effort so far went into whisper.cpp and Bluetooth. The "non-robotic"
   requirement lives almost entirely in TTS quality (that's the whole
   reason Kokoro was chosen over Piper), and it's untested. Unlike the
   mic (blocked on USB hardware), Kokoro can be tested immediately — next
   concrete action, and a real go/no-go signal for the project.

## 2026-08-02 — Product strategy reset: one reliable loop first, v0 north star defined

Prompted by the length/frustration of the Bluetooth debugging arc: stepped
back from hardware debugging to re-anchor on the actual product goal
before continuing.

**Decision: v0 is one reliable loop — press button → speak → transcribe →
safe response → spoken reply.** Everything else (kid mode, memory/ECL
pipeline, morning digest, custom enclosure, wake-word-always-on) is a
layer on top of a loop that has to work first, not something to build in
parallel. Explicit risk named: trying to ship a parent assistant, a kid
tutor, and custom Bluetooth hardware simultaneously is how projects stall.

Supporting architecture principles adopted for the prototype:
- Agent + audio orchestration runs on the Linux side; the STM32 MCU stays
  scoped to button/LEDs/power-state only (already SPEC.md's plan, now
  explicitly reaffirmed under time pressure not to scope-creep).
- **Audio abstraction layer**: STT/TTS/agent logic should not care whether
  audio comes from USB, Bluetooth (output), or an eventual custom mic
  module — swap the transport without touching the pipeline.
- Battery: prototype on an external USB-C power bank; battery electronics
  are explicitly not part of the first software milestone (PLAN.md Phase 6
  stays deferred, not pulled forward).
- Kid mode, when built, is a **policy boundary enforced in code** (allow-
  listed tools/topics, session limits), not just a different system
  prompt — consistent with SPEC.md §7's existing architectural-not-
  biometric framing, reaffirmed rather than changed.

**Answered the "who's the first user" question** (a real product-fit
question, not just process): parent mode's differentiator isn't voice
assistance generally (Alexa/Google already own that) — it's agentic
capability with memory that compounds across sessions, for a hands-full
moment (cooking, holding a kid) where existing stateless smart speakers
fall short. Kid mode's differentiator isn't tutoring content quality
(Duolingo etc. already do that better) — it's the no-screen, no-feed,
parent-bounded structure, addressing screen-time anxiety directly rather
than competing on pedagogy. v0's test: does a parent reach for this
instead of their phone specifically because their hands are full and they
trust it remembers context — testable with just the one loop, no kid mode
required.

**New interaction model decisions:**
- Profile/config management: a **local web page hosted by the board
  itself**, reachable from any phone browser on the same WiFi — not a
  native app. Keeps the device screen-free while config still happens on
  a screen the user already owns.
- Wake behavior: press-to-talk first (already PLAN.md's plan), wake-word
  later. Refined model: press → awake → listen → respond → **30s
  inactivity timer resets after each turn** → sleep after 30s of silence.
  Allows natural back-and-forth without re-pressing per utterance.

PLAN.md restructured around this v0 framing — see that file for the
updated phase breakdown.

## 2026-08-02 — Bluetooth mic: closed for good (not just pending a hardware test)

Conclusive resolution to the exact-zero-audio investigation (previous
entry). Captured an HCI trace with `btmon` in a second App Lab shell
session while running `pw-record` in the first (a second opinion from
Gemini correctly identified this as the decisive test). Result: the eSCO
connection for the Bose speaker negotiates and completes successfully
(`Synchronous Connect Complete`, `Status: Success`, real handle assigned,
valid eSCO parameters) — but across the entire ~5s recording window, **zero
`SCO Data RX` packets appear on that handle**. The link exists; no audio
payload ever crosses it. Everything else in the trace during that window
is either the RFCOMM/AT-command control channel or Qualcomm vendor
diagnostic telemetry — never the actual audio.

**Conclusion: this board's Bluetooth controller acknowledges SCO/eSCO
connection setup but never actually emits audio data over HCI.** This is a
firmware/controller-level limitation, not something fixable via PipeWire,
WirePlumber, BlueALSA, or any config change — no amount of further
userspace tinkering would have found this; it required an HCI-level trace
to see.

This retroactively explains every symptom cleanly:
- A2DP output worked flawlessly throughout (JBL, Bose) because A2DP runs
  over L2CAP, an entirely different data path uninvolved with SCO.
- HFP mic input failed identically, as pure digital silence, on two
  unrelated devices (JBL Focus 500, Bose "Undercover") because both
  depend on this board's SCO delivery specifically.
- The JBL's mic worked fine in an iPhone voice memo, because Apple's own
  BT silicon handles SCO correctly — confirming the JBL hardware was never
  the problem.

**Architecture decision:** Bluetooth stays as the output path (TTS via
Kokoro → earbuds/speaker — SPEC.md/PLAN.md's existing plan, unaffected).
For microphone input, revert to the *original* BOM plan from before this
detour: a wired mic (USB for near-term testing, I2S MEMS mic in the final
enclosure) rather than attempting BT mic capture on this board. SPEC.md
and PLAN.md updated accordingly. Live on-device mic testing is now
blocked on acquiring a USB mic (or wiring an I2S one) — no further time
should go into chasing BT mic capture on this hardware.

## 2026-08-02 — BT mic capture: confirmed device-independent (software bug, not hardware)

Extended debugging of the "`[BLANK_AUDIO]`" / exact-zero-amplitude mic
capture problem (see setup.md §8 follow-ups for full command-level detail).
Ruled out, in order: three separate volume/gain layers (PipeWire node
volume x2, BlueZ device-level route volume, all non-zero/unmuted); target-
by-name vs. target-by-numeric-ID for `pw-record`; SCO transport actually
opening/closing correctly at the BlueZ level (confirmed via WirePlumber
debug trace — a real file descriptor is allocated and released). Objective
proof via `sox -n stat`: `Maximum amplitude: 0.000000` — true digital
silence, not just quiet, ruling out mic sensitivity/placement as the cause
(a real but faint signal would show *some* non-zero amplitude).

Cross-checked against a second, physically different device (Bose
"Undercover" portable speaker, paired via `bluetoothctl` after resolving a
naming mix-up — "Undercover" was the user's own speaker name, not a
neighbor's device as initially assumed from context). **Same exact-zero
result.** This rules out JBL-specific hardware/firmware as the cause
(independently reinforced by a successful iPhone voice-memo test on the
JBL, which captured real, if faint, audio — proving that unit's mic
hardware works). Two different devices failing identically on the same
software stack means the bug is in our PipeWire/WirePlumber/BlueZ stack on
this board, not the peripherals.

Bose pairing did confirm **Bluetooth test 2 (A2DP output): PASS** — first
device we've gotten clean, audibly-confirmed playback from (JFK sample
played correctly through it), closing out that checklist item.

Current working hypothesis, not yet confirmed: the mic path runs through a
software loopback bridge (`libpipewire-module-loopback`) between the raw
capture node (`bluez_capture_internal.<mac>`) and the virtual source
everything has been targeting (`bluez_input.<mac>`). Testing whether the
raw internal node has real signal (bypassing the bridge) is the next
differential step — narrows the bug to either the loopback module
specifically, or further upstream in SCO/codec decode if that's also zero.

Practical unblock in parallel: STT accuracy validation doesn't strictly
require live on-device mic capture — a phrase recorded on the laptop and
transferred to the board can validate whisper.cpp's real-speech accuracy
independently of this investigation, decoupling forward progress on model
choice from resolving the live-capture bug.

## 2026-08-02 — Cloud LLM provider for testing: OpenRouter free tier

Compared options for the Phase 2 agent-harness cloud LLM calls: OpenRouter
free tier, Cerebras free tier (4 req/min), a laptop-hosted Ollama instance
reachable over LAN, and whether an existing Claude/ChatGPT/Gemini consumer
subscription could be reused.

**Decision: OpenRouter free tier**, for development/testing once Phase 2
starts. Rationale: consumer subscriptions (Claude Pro/Max, ChatGPT Plus,
Gemini Advanced) are billed separately from their developer APIs and can't
be repurposed by custom code — the one exception (Claude Code/Codex CLI
drawing on subscription usage) is specific to those tools, not a general
API our agent loop could call. Cerebras's 4 req/min free-tier limit is
impractical for iterative dev despite its real latency advantage (which
matters for later production round-trip tuning, revisit then). A
laptop-hosted Ollama over LAN is a valid zero-cost way to test tool-calling
*logic* decoupled from latency, but doesn't help validate real numbers.
OpenRouter's free-tier rate limits are workable for active development and
it's a unified API, easy to swap models later.

**Not needed yet** — nothing in Phase 1 (whisper.cpp, Bluetooth) calls an
LLM; this only becomes relevant once Phase 2's agent/tool-calling work
starts. Account/key creation is a manual step for the user (OpenRouter
signup), not something automatable here.

## 2026-08-02 — Bluetooth audio routing fully resolved (three stacked infrastructure issues)

Follow-up to the previous entry. What looked like one blocker turned out
to be three, stacked, each hiding the next until fixed. Full command-level
detail in setup.md §8; summary here:

1. **No session for `arduino` at all** — App Lab's "Connect to Shell"
   doesn't create a real logind session (confirmed via `loginctl
   list-sessions` showing zero sessions for `arduino`, only `lightdm`'s).
   Fixed with `loginctl enable-linger arduino` + manually exporting
   `XDG_RUNTIME_DIR`/`DBUS_SESSION_BUS_ADDRESS` for the current shell.
2. **Seat-gating** — WirePlumber's bluez5 monitor loads fine but
   deliberately refuses to touch Bluetooth hardware when the session's
   logind seat-state is `lingering` rather than `active` (a desktop-
   oriented protection against background users grabbing audio devices,
   which actively fights a headless appliance where no session is ever
   "active" at a seat). Fixed by switching to WirePlumber's built-in
   `main-embedded` profile, made permanent via a systemd user service
   override (`~/.config/systemd/user/wireplumber.service.d/override.conf`)
   rather than editing the vendor unit.
3. **A second PipeWire instance already owned Bluetooth** — `lightdm`
   (pulled in only by the default `graphical.target`, otherwise unused —
   confirmed no autologin configured and no display physically connected
   before touching it) was running its own PipeWire/WirePlumber under its
   greeter session, and had already registered the A2DP/HFP profiles and
   bound the SCO socket with BlueZ, locking `arduino`'s instance out
   (`RegisterProfile() failed: NotPermitted`, `sco_listen: Address already
   in use`). Stopped and disabled `lightdm` — confirmed as the real fix
   when doing so visibly dropped the already-paired JBL (lightdm's
   PipeWire really had been holding the connection).

**Result: Bluetooth audio fully working** — `wpctl status` shows the JBL
Focus 500 as both the default sink (A2DP output) and default source (HFP
mic input, via `bluez_input.<mac>`). Bluetooth test 1 (pairing/reconnect)
and the underlying audio-routing prerequisite for tests 2–4 are both done.

**Broader takeaway for future setup (any second board, or a factory
image):** App Lab's "Connect to Shell" alone is not sufficient to get
Bluetooth audio working out of the box — it needs linger enabled, the
`main-embedded` WirePlumber profile, and `lightdm` disabled. Worth
considering whether this should become a first-boot provisioning step
(§ setup.md) rather than something rediscovered per board.

## 2026-08-02 — Bluetooth pairing succeeded; audio routing blocked on a missing PipeWire session for `arduino`

JBL Focus 500 paired cleanly via `bluetoothctl` — `Paired`/`Bonded`/
`Trusted`/`Connected` all `yes`, advertises A2DP (Audio Sink), HFP
(Handsfree), and HSP (Headset) profiles. **Bluetooth test 1
(pairing/reconnect): PASS.** Full command log in setup.md §7.

Trying to confirm PipeWire picked up the device as an audio sink surfaced
a real infrastructure gap, not just a missing package: `pactl` isn't
installed, and `wpctl status` fails with "Could not connect to PipeWire" /
no D-Bus session bus. This connects back to something `needrestart` showed
during the `apt install` step (setup.md §3) — the running
`pipewire`/`pipewire-pulse`/`wireplumber` instance belongs to **`lightdm`'s**
session, not `arduino`'s. App Lab's "Connect to Shell" doesn't appear to
give `arduino` its own D-Bus session bus or PipeWire instance — both are
normally tied to an active per-user login session, and a shell-only
connection likely doesn't create one.

**Implication:** before Bluetooth audio (tests 2–7) can proceed, `arduino`
needs its own working PipeWire session — not just BlueZ pairing, which is
already confirmed working independently of this. Likely fix (untested):
`loginctl enable-linger arduino` to allow user services without an active
graphical login, then manually start `pipewire pipewire-pulse wireplumber`
as `arduino` user services. Currently mid-diagnosis (`echo
$XDG_RUNTIME_DIR`, `systemctl --user status`, `loginctl list-sessions`),
not yet resolved — see setup.md §8 for live status.

## 2026-08-02 — Test device swap: JBL Focus 500 instead of AirPods Pro 2

AirPods Pro 2 proved awkward to get into standard Bluetooth pairing mode —
opening the case lid only triggers Apple's proprietary quick-pair animation
(visible only to Apple devices), and the case's setup-button hold (needed
to force generic discoverable mode) wasn't reliably engaging; scans mostly
picked up "MICHAEL"-named entries that were actually the user's own
phone/laptop rotating BLE addresses (normal Apple privacy behavior, not a
bug), never a clearly-AirPods-named device.

A JBL Focus 500 showed up in the same scan and resolved to a proper name
immediately — standard Bluetooth device, no proprietary pairing dance.
**Decision: use the JBL for Phase 1 Bluetooth bring-up/testing** instead of
continuing to fight the AirPods. This is a test-hardware substitution, not
an architecture change — PLAN.md/SPEC.md's "Bluetooth earbuds" decision
was never brand-specific, AirPods were just what was on hand. Pairing with
AirPods (or any earbuds) can be revisited later if needed; nothing in the
plan depends on the specific device.

## 2026-08-01 — whisper.cpp built and benchmarked on real hardware; pausing STT tuning to test Bluetooth first

First hands-on bring-up session on the actual board (host shell via App
Lab's "Connect to Shell", see setup.md for the full command-by-command
log). Headline results:

- whisper.cpp compiled natively without issue (confirms the host-shell-not-
  App-Lab-container approach from the previous entry was correct).
- **base.en, default 5-beam decode**: 16.25s total for an 11.0s clip
  (RTF ≈ 1.5 — slower than real-time). Correct transcription.
- **base.en, greedy decode (`-bs 1 -bo 1`)**: 12.69s total (RTF ≈ 1.15).
  Confirmed encode time (~11.1s) is a fixed cost independent of decode
  strategy — beam search wasn't the main problem.
- **tiny.en, greedy decode**: 5.59s total (RTF ≈ 0.51 — the first config
  faster than real-time). Encode time dropped 2.35x vs. base.en. Minor
  accuracy cost (dropped one comma, segment split at a pause) but content
  fully intact — likely fine for voice-command routing, a real trade-off
  to remember if verbatim dictation capture matters later.
- Log consistently shows `whisper_backend_init_gpu: no GPU found` — the
  QRB2210's Adreno GPU isn't being reached by this build. Not yet
  investigated whether whisper.cpp has Vulkan/OpenCL backend support that
  would change this.
- Not yet tested: quantization (q4/q5/q8), keeping the model resident
  across invocations instead of `whisper-cli`'s one-shot reload, or
  benchmarking against a short (~3s) realistic command instead of the
  11s JFK sample.

**Second opinion relayed** (alternative STT models/architectures worth
testing later): Moonshine (`moonshine-tiny`/`moonshine-small`, purpose-
built for edge — handles variable-length input natively instead of
Whisper's fixed 30s-window zero-padding, which is a real, specific
inefficiency for short commands our benchmark doesn't fully capture since
the test clip was 11s); Distil-Whisper (`distil-small.en`/`distil-
medium.en`, layer-pruned distillation — more relevant at "small" size and
up than at `tiny`, where we already are); English-only vs. multilingual
weights (**already satisfied** — we're already testing `.en` variants);
quantized weights (`q5_0`/`q5_1`/`q8_0` — cheap lever, not yet tried);
Whisper Large-v3-Turbo (almost certainly not a fit for real-time on this
CPU, deprioritized). Of these, **Moonshine looks like the most promising
one to prioritize** when STT tuning resumes, given the fixed-window-padding
argument specifically addresses short commands, which is our actual use
case.

**Decision: pause further STT optimization and move to Bluetooth pairing**
(PLAN.md Phase 1 test items 1–3 — pairing/reconnect, A2DP output, HFP mic
sample rate) before spending more time on model/quantization choices.
Rationale: we already have a config (tiny.en, greedy) fast enough to be
promising; further tuning without real mic audio to validate against is
low-value right now, and Bluetooth pairing is a hard dependency for test 4
(whisper accuracy on real BT mic audio) regardless of which STT config
wins. STT model finalization (tiny.en vs. Moonshine vs. quantized variants)
deferred until after Bluetooth results are in.

## 2026-08-01 — No llama.cpp needed; added setup.md as the hands-on runbook

Question raised: does the plan need llama.cpp (in addition to whisper.cpp)?
**No.** llama.cpp is a general local-LLM hosting engine (same `ggml-org`
family as whisper.cpp, different job) — the architecture deliberately
doesn't host any LLM on-device (SPEC.md §3/§9: board can't run a large
model, reasoning goes to a cloud API). Surfaced a real ambiguity in
COMPETITION_ENTRY.md's Agent Harness section, which said "local models
handle fast/simple intents" without saying what that meant — tightened it
to state plainly that no LLM runs on-device: wake-word/VAD is non-LLM
signal processing, fixed skills are plain scripts, everything needing
reasoning goes to the cloud LLM. If offline/no-network operation becomes a
real requirement later, a tiny llama.cpp-hosted model for basic intent
routing is the way to add it — deliberately out of scope for now, not
something the current plan depends on.

Also added [setup.md](setup.md): a reproducible runbook of commands
actually run on the physical board (separate from this file, which is
decisions/rationale, and PLAN.md, which is forward-looking). First entries:
WiFi + device password via App Lab provisioning, confirming "Connect to
Shell" is host-level, `apt update` + `apt install build-essential cmake`.

## 2026-08-01 — Confirmed: App Lab's "Connect to Shell" is host-level, not the Python container

Ran the diagnostic from the previous entry on real hardware via App Lab's
"Connect to Shell" button. Results:
- `/.dockerenv` absent → this shell is on the host Debian filesystem, not
  inside the `uv`/Docker container that App Lab *Python apps* run in (those
  remain a separate, still-unverified execution context — this only
  confirms the shell tool itself).
- `gcc` not installed yet (expected — next step installs it).
- `df -h`: root (`/`, `mmcblk0p68`) is 9.8G total, **5.3G free** (44% used)
  — meaningfully roomier than the "tiny root partition" framing in the
  earlier research; `/home/arduino` (`mmcblk0p69`) is 18G with 17G free.
  **Correction to SPEC.md §1**: root partition has real headroom for
  `build-essential`/`cmake`, not just barely enough — SPEC.md storage note
  updated accordingly.

**Conclusion:** Phase 1 host-level bring-up (apt installs, whisper.cpp
build, PipeWire/BT config) can proceed directly via "Connect to Shell" —
no need for the SSH-from-laptop or `uv` cross-toolchain workaround
originally considered. Next action: `sudo apt update && sudo apt install
-y build-essential cmake`.

## 2026-08-01 — App Lab's Python container breaks native builds (whisper.cpp, C-extension packages)

Researched Arduino App Lab's actual execution model before starting Phase 1
bring-up. Finding: App Lab Python apps run inside Docker containers managed
by `uv`, separate from the host Debian Linux filesystem/apt packages. Per
community reports (Arduino forum), the container lacks `gcc`/build headers,
so `requirements.txt` packages needing C compilation fail to build inside
it, and packages installed via host `apt` are invisible to the container.
Community workaround: install a cross toolchain (`gcc-aarch64-linux-gnu`,
`python3-dev`, `binutils`) on the host and use `uv add <pkg>` / `uv run`
directly, outside the App Lab container.

**Implication for Agento:** whisper.cpp (native C++ build) and the
PipeWire/BlueZ/WirePlumber Bluetooth audio stack (host system services) are
not things the App Lab container model is built for. Plan: do Phase 1
bring-up (whisper.cpp compile, BT pairing/config, initial Kokoro test) over
direct SSH on the Debian host, outside any App Lab "app" project. Decide
later whether the finished pipeline gets wrapped into an App Lab app
(Python side shelling out to the natively-built whisper.cpp binary, plus
Bridge calls to the STM32 side) or runs as host-level systemd services with
App Lab used only for the STM32/sketch side — genuinely unconfirmed which
App Lab permits; first thing to check on-device, not assume.

Sources: [Arduino forum — installing Python packages on UNO Q](https://forum.arduino.cc/t/how-to-install-python-packages-on-the-arduino-q/1434480),
[Arduino UNO Q user manual](https://docs.arduino.cc/tutorials/uno-q/user-manual/)
(app.yaml/Python-folder/Sketch-folder structure, files live at
`/home/arduino/arduino_apps/`, SSH access confirmed).

## 2026-08-01 — Bluetooth stack fixes: hold off on building, test first

User relayed a second opinion (from Gemini) proposing four open-source
tools to fix Linux BT audio stack issues for bi-directional AI voice loops:
a PipeWire profile-lock/keep-alive daemon, a Whisper narrowband bandwidth-
extension preprocessor, a native C++/Rust zero-copy PipeWire pipeline, and
an LE Audio/LC3 auto-configurator.

**Assessment:** don't build any of these before running the Bluetooth test
checklist (PLAN.md Phase 1) — building fixes for unconfirmed problems is
premature. Notes for if/when revisited:
- Check LE Audio/LC3 support (BlueZ ≥5.66 ISO channels, board + earbuds
  hardware support) first — if available it removes the A2DP/HFP
  dual-profile problem by design rather than working around it.
- The profile-lock idea is likely a WirePlumber Lua policy script, not a
  new daemon against libpipewire — much less code than proposed.
- Bandwidth extension (inventing frequencies from 8kHz audio) is
  speculative and could hurt Whisper's WER rather than help; test real
  narrowband WER (test 4 in the checklist) before building this.
- Native zero-copy rewrite is premature optimization until profiling shows
  Python-level buffering is actually the bottleneck.
- If anything here gets open-sourced, the profile-lock + keep-alive helper
  (scoped down, not a full daemon) is the realistic candidate.

## 2026-08-01 — Audio I/O for first bring-up: Bluetooth earbuds

Clarified: the bare UNO Q board has no analog mic/speaker at all — only the
BT radio is on-board. Mic/speaker were already BOM items to add, but this
raised the question of which I/O path to bring up *first* for testing
whisper.cpp/Kokoro, before any enclosure/wiring exists.

Three options considered: USB mic+speaker (simplest, but throwaway test
rig, doesn't match final design), Bluetooth earbuds (matches actual product
design, but BT audio profile complexity gets tangled with STT/TTS latency
testing), wired I2S mic+speaker (closest to final BOM, most setup work
before any signal).

**Decision: Bluetooth earbuds**, since it matches the target design and
avoids building a throwaway rig. Accepted risk: BT headset mic input only
supports the HFP/HSP profile (narrowband, ~8kHz), noticeably lower quality
than the A2DP profile used for output — and profile switching between
listening/speaking can add latency and glitches. First bring-up steps
(logged in PLAN.md Phase 1) treat "does whisper transcribe narrowband BT
mic audio accurately enough" as the key risk test; fallback if not is a
dedicated wired/USB mic for input only, keeping BT for output.

Formalized this into an explicit 6-test pass/fail checklist in PLAN.md
Phase 1 (pairing/reconnect, A2DP output quality, HFP mic sample rate,
whisper accuracy on BT mic, profile-switch latency, full round trip) so
"test the Bluetooth path" has concrete criteria rather than just narrative
risk notes. Tests 1–3 don't need whisper/Kokoro built yet and can run in
parallel with the rest of Phase 1's bring-up work; tests 4–6 depend on it.

## 2026-08-01 — Hermes vs. smolagents: test both, or trust the reasoning?

Question raised: is it worth hands-on testing Hermes Agent on the board
before ruling it out, rather than deciding from research/reasoning alone?
Also: does the agent-harness decision block starting whisper.cpp/Kokoro
testing?

**Decision:** No symmetric bake-off. The architectural mismatch (Hermes'
persistent DB/messaging/async stack vs. the UNO Q's small eMMC user
partition and thin-orchestrator role) is strong enough not to warrant equal
investment in both. Plan instead:
- Cheap smoke test of smolagents (~30 min: pip install, run the `@tool`
  example) to confirm it behaves on-device.
- Cheap *falsifiability* pass on Hermes: attempt install only, see how far
  it gets before hitting predicted partition/dependency friction. No skill
  building on top of it — that would be disproportionate effort for what's
  already a fairly one-sided call.

**Also confirmed:** agent-harness choice does not gate whisper.cpp/Kokoro
testing — they're independent pipelines and should be benchmarked first
regardless (matches PLAN.md Phase 1 preceding Phase 2). Infra needed either
way, independent of which agent wins:
- whisper.cpp: cmake/gcc build toolchain (native ARM compile), `base.en` q4
  GGML model file, working mic capture (ALSA/`arecord`).
- Kokoro: Python env, `espeak-ng`, `onnxruntime` (**needs checking** — ARM64
  Linux wheel availability is unconfirmed and is the most likely early
  snag), model weights (~300MB), `libsndfile`, working speaker output.
- Common to both, and to whichever agent framework is picked: a Python/pip
  environment scoped correctly under `/home/Arduino` per the eMMC partition
  constraint.

**Next action:** start whisper.cpp + Kokoro bring-up now; agent harness
decision can wait until Phase 2.

## 2026-08-01 — Initial project docs created

Set up PLAN.md, SPEC.md, and COMPETITION_ENTRY.md in the (previously empty)
Agento folder, based on:
- A prior research conversation comparing Hermes Agent deployment on an
  Arduino UNO Q vs. a laptop, then narrowing down a full voice + agent +
  memory stack for the board (see decisions log in SPEC.md §10).
- An existing draft Autodesk University 2027 Product hardware-contest
  application ("Household Voice Agent" / dual parent+child voice assistant)
  that predated this project folder.

Key decisions carried in from that research (detailed rationale in SPEC.md):
- TTS: Kokoro-82M (ONNX) over Piper (too robotic), Fish Speech/XTTS v2
  (need GPU/VRAM not available on-board).
- STT: whisper.cpp (native, not Python-wrapped).
- Both STT/TTS models kept resident in RAM at boot rather than lazy-loaded
  — cold-load latency (2–3.5s) breaks conversational feel, and the board
  has RAM to spare (~2.4GB free even with both loaded).
- Agent harness: lean toward a minimal smolagents-style tool-calling loop
  over running full Hermes Agent on-device, given Hermes' heavy dependency
  footprint vs. the UNO Q's constrained eMMC partition.
- Memory: three-tier (episodic/semantic/procedural) daily ECL pipeline
  instead of a naive per-message vector dump, so contradicted facts get
  resolved (ADD/UPDATE/DELETE/NOOP) instead of accumulating as duplicates.

Open items flagged at this point: memory backend not chosen (Mem0 vs.
Cognee/Graphiti vs. hand-rolled SQLite), battery/runtime target not sized,
live Hackster contest form fields unconfirmed.

---

## How to keep this file current

Append a new dated entry (newest at top) after any session that produces a
decision, a direction change, a research finding, or a completed milestone
— not for routine file edits. Keep entries short: what was asked/decided,
what was rejected and why, what's next. See `CLAUDE.md` for the standing
instruction that keeps this happening across sessions.
