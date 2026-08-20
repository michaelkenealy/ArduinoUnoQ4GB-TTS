# Agento — Board Setup Log

Reproducible log of steps actually run on the physical Arduino UNO Q —
commands, in the order they were run, with what they did and what came
back. This is the "what we did and it worked" runbook; contrast with
[PLAN.md](PLAN.md) (what we intend to do next) and [conversation.md](conversation.md)
(why we decided things). If a second unit or a fresh image ever needs
setting up again, start here.

## Board info

- Model: Arduino UNO Q, 4GB RAM variant (hostname `ArduinoUnoQ4GB`)
- OS: Debian trixie (`trixie`, `trixie-backports`, `trixie-updates`,
  `trixie-security` repos, plus Arduino's own `apt-repo.arduino.cc`)
- User account: `arduino`

## 1. Initial provisioning (via App Lab)

- Connected the board to WiFi through App Lab's setup flow.
- Set the board's OS/device password during App Lab's initial pairing —
  this is the password `sudo` prompts for on the shell, not an Arduino
  Cloud login. Worth remembering which one this is; it's easy to conflate
  the two later.

## 2. Connect to Shell (App Lab)

Used App Lab's built-in "Connect to Shell" button rather than manual SSH
from a laptop.

Verified this is a host-level shell, not the Docker container that App
Lab's Python *apps* run in (see conversation.md 2026-08-01):

```
cat /.dockerenv 2>/dev/null && echo "IN A CONTAINER" || echo "NOT containerized"
```
Result: `NOT containerized` — confirmed host access.

Checked storage layout:

```
df -h
```
Result: root (`/`, `mmcblk0p68`) 9.8G total / 5.3G free (44% used);
`/home/arduino` (`mmcblk0p69`) 18G total / 17G free — roomier than the
"tiny root partition" the early research implied (SPEC.md §1 updated).

## 3. System packages

```
sudo apt update
sudo apt install -y build-essential cmake
```

- `apt update` — refreshed the package index across all configured repos.
- `apt install -y build-essential cmake` — installed the compiler
  toolchain (gcc/g++/make) and cmake, required to natively build
  whisper.cpp on-device. This is exactly what App Lab's Python app
  container reportedly lacks, which is why this setup is happening over
  the host shell rather than inside an App Lab app project.
- Note: `apt update` reported 205 upgradable packages; deliberately
  skipped a full `apt upgrade` — not needed for this work, costs time/
  bandwidth for no benefit right now.
- Gotcha hit along the way: pasting multiple commands at once into this
  shell can eat the newline between them, causing the next command to be
  interpreted as arguments to the previous one (e.g. `ls` swallowing
  `sudo apt update` as bogus filenames). Send one command at a time.
- The install triggered a `needrestart` prompt (normal Debian post-install
  step after a library update): accepted the suggested system-service
  restarts (defaults left as-is; notably `bluetooth.service` and
  `NetworkManager.service` were *not* flagged, so nothing networking-
  related was touched). It also reported stale user-session binaries under
  `lightdm`'s session (`pipewire.service`, `pipewire-pulse.service`,
  `wireplumber.service`, `dbus.service`, `gvfs-daemon.service`, etc.) —
  informational only, no action taken; a reboot would clear it but wasn't
  needed to proceed.
- **Useful finding: PipeWire + WirePlumber are already installed on this
  image** — confirmed via the needrestart output above. Phase 1's
  Bluetooth audio work (PLAN.md) won't need to install that stack, only
  configure it.

## 4. whisper.cpp — clone and build

`git` was already present (2.47.3), no install needed.

First clone attempt failed mid-transfer over a slow/unstable WiFi link
(`RPC failed`, `unexpected disconnect while reading sideband packet`,
`fatal: early EOF` — network issue, not a command error). Retried with a
shallow clone, which succeeded:

```
git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git
cd whisper.cpp
cmake -B build
cmake --build build -j --config Release
```

Build succeeded — `whisper-cli` and `whisper-server` both compiled
(`Built target whisper-cli`, `Built target whisper-server`). Confirms the
host shell (not the App Lab Python container) can compile C/C++ natively,
as expected.

- Gotcha: pasting multiple commands while a prior one (`git clone`) is
  still running in the foreground just queues them in the terminal's input
  buffer — they execute in order once the foreground command returns, no
  need to retype. Different from the earlier `ls`-swallows-`sudo` issue,
  where the problem was a missing newline between two lines pasted while
  the shell *was* idle and ready for input.

## 5. whisper.cpp — first transcription benchmark (base.en, defaults)

```
sh ./models/download-ggml-model.sh base.en
./build/bin/whisper-cli -m models/ggml-base.en.bin -f samples/jfk.wav
```

Downloaded fine (141MB, full-precision `ggml-base.en.bin`, not yet
quantized). Transcription was **accurate** — correctly transcribed the
11.0s JFK sample.

**Performance — this is the first real latency data point, and it's a
problem as-run:**

| Metric | Value |
|---|---|
| Audio length | 11.0s |
| `load time` | 257.56 ms |
| `mel time` | 58.88 ms |
| `encode time` | **11051.57 ms** (68% of total) |
| `sample time` | 460.05 ms |
| `batchd time` | 4148.32 ms |
| `decode time` | 223.11 ms |
| **`total time`** | **16252.97 ms** |

Real-time factor ≈ 1.5 (slower than real-time) — far over the sub-1s
round-trip target in PLAN.md Phase 1. Two likely levers, not yet tested:
- Decode used whisper.cpp's default **5 beams + best of 5** (expensive;
  encode time is unaffected by this, but sample/batchd/decode — ~4.8s
  combined — should shrink a lot with greedy decoding, `-bs 1 -bo 1`).
- Log shows `whisper_backend_init_gpu: no GPU found` — GPU acceleration
  was requested but fell back to CPU-only. The QRB2210's Adreno GPU isn't
  being reached by this build; unclear yet if whisper.cpp has
  Vulkan/OpenCL backend support that would change this. Worth checking
  before concluding CPU-only performance is the ceiling — encode time is
  the dominant cost and exactly what GPU offload would target.

## 6. whisper.cpp — greedy decoding benchmark (base.en, `-bs 1 -bo 1`)

```
./build/bin/whisper-cli -m models/ggml-base.en.bin -f samples/jfk.wav -bs 1 -bo 1
```

Transcription still accurate. Timings:

| Metric | 5-beam (§5) | Greedy | Change |
|---|---|---|---|
| encode time | 11051.57 ms | 11180.64 ms | ~unchanged |
| sample time | 460.05 ms | 105.50 ms | ↓ |
| batchd time | 4148.32 ms | 0.00 ms | ↓ (eliminated) |
| decode time | 223.11 ms | 941.80 ms | ↑ (absorbs batchd's work) |
| **total time** | 16252.97 ms | **12690.10 ms** | ↓ ~22% |

**Confirms the hypothesis from §5**: encode time is a fixed cost,
independent of decode strategy — still ~88% of total runtime. RTF ≈ 1.15
even at the cheapest decode settings, i.e. still slower than real-time.
Greedy decoding is worth keeping (free ~22% win, no accuracy cost seen)
but doesn't come close to solving the latency problem on its own.

**Important reframe**: encode time scales roughly 1:1 with audio duration
on this hardware, so this isn't an artifact of the 11s test clip being
unusually long — a realistic ~3s voice command would still take roughly 3s
just to encode. The bottleneck is the encoder forward pass itself on this
CPU, not decode strategy or clip length. Next lever to test: a smaller
model (`tiny.en`), since it's the more promising path to cut the fixed
encode cost; quantization is the other lever, not yet tested.

## 7. Bluetooth pairing — test 1 (pairing & reconnect)

Test device: **JBL Focus 500** (standard Bluetooth headset), not the
AirPods Pro 2 originally on hand — AirPods' proprietary quick-pair mode
proved awkward to get into standard discoverable mode from Linux; see
conversation.md 2026-08-02. Test-hardware swap only, not an architecture
change.

```
bluetoothctl
power on
agent on
default-agent
scan on
scan off              # once JBL Focus 500 appeared in the scan
pair 00:11:67:33:16:25
trust 00:11:67:33:16:25
connect 00:11:67:33:16:25
info
```

Result: `Paired: yes`, `Bonded: yes`, `Trusted: yes`, `Connected: yes`.
Advertises `Audio Sink` (A2DP), `Handsfree` (HFP), `Headset` (HSP) UUIDs —
covers both the output and mic-input profiles the test plan needs. Battery
reported at 40%.

**Test 1: PASS.**

## 8. Bluetooth audio routing — blocked: no PipeWire session for `arduino`

Tried to confirm PipeWire saw the paired JBL as a sink:

```
pactl list short sinks
```
→ `bash: pactl: command not found` (not installed — comes from the
separate `pulseaudio-utils` package).

```
wpctl status
```
→ `Failed to connect to session bus: Unable to autolaunch a dbus-daemon
without a $DISPLAY for X11` / `Could not connect to PipeWire`.

**Finding:** this isn't a missing-package problem, it's a missing-session
problem. The `pipewire`/`pipewire-pulse`/`wireplumber` instance flagged
earlier by `needrestart` (§3) was running under **`lightdm`'s** session
(likely its greeter/login session), not under `arduino`. App Lab's
"Connect to Shell" apparently doesn't provide `arduino` with its own
D-Bus session bus or a running PipeWire instance — both are normally
per-user, tied to an active login session. Diagnosing before fixing:

```
echo $XDG_RUNTIME_DIR
systemctl --user status
loginctl list-sessions
```

**Resolved — three-layer problem, fixed in three steps:**

**Layer 1: no session at all.** `loginctl list-sessions` showed zero
sessions for `arduino` — App Lab's "Connect to Shell" doesn't create a real
logind session (no PAM registration), so there was no `XDG_RUNTIME_DIR`,
no D-Bus bus, nothing for `arduino` to run user services on.
```
sudo loginctl enable-linger arduino
export XDG_RUNTIME_DIR=/run/user/1000
export DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus
```
`systemctl --user status` then connected and showed `pipewire`,
`pipewire-pulse`, `wireplumber` all auto-started under the new session.

**Layer 2: seat-gating.** Even with a session, `wpctl status` showed no
Bluetooth device at all (not even disconnected). Debug trace
(`WIREPLUMBER_DEBUG=3 timeout 5 wireplumber > /tmp/wp-debug.log 2>&1`)
showed `bluez.lua` loads fine but gates itself on logind seat state, and
our `enable-linger` session reports as `lingering`, not `active` — the
monitor treats that as "don't touch audio hardware" (a desktop-oriented
protection against background users grabbing devices, actively wrong for
a headless appliance with no one ever "at a seat"). Fix: WirePlumber ships
a `main-embedded` profile ("embedded use cases, systemwide without
maintaining state") that skips this gating. Confirmed via
`wireplumber --profile main-embedded` in the same debug-trace harness —
the bluez5 backend then actually enumerated devices, including the JBL.

**Layer 3: a second, competing PipeWire owner.** Even on `main-embedded`,
bluez5 logged `RegisterProfile() failed: org.bluez.Error.NotPermitted` and
`sco_listen: listen(): Address already in use`. Root cause: `lightdm` (the
graphical login manager, pulled in only by the default `graphical.target`)
was already running its *own* PipeWire/WirePlumber instance under its
greeter session, and had already claimed BlueZ's A2DP/HFP profile
registration and the SCO audio socket — only one process can own these at
a time. Investigated before touching it: no `autologin-user` configured,
no display physically connected (`cat /sys/class/drm/*/status` →
`disconnected`), nothing else depends on it besides `graphical.target`
itself. Confirmed dead weight on this headless board — disabled it:
```
sudo systemctl stop lightdm
sudo systemctl disable lightdm
```
(Stopping it visibly dropped the already-paired JBL, confirming lightdm's
PipeWire really did hold the connection — expected, not a new problem.)

**Made `main-embedded` the permanent profile** for the real service via a
systemd user override (not editing the vendor unit):
```
mkdir -p ~/.config/systemd/user/wireplumber.service.d
cat > ~/.config/systemd/user/wireplumber.service.d/override.conf << 'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/wireplumber --profile main-embedded
EOF
systemctl --user daemon-reload
systemctl --user restart wireplumber
```

Reconnected the JBL (needed a power-cycle first — the abrupt disconnect
from killing lightdm left it unresponsive, `br-connection-page-timeout` on
the first retry, unrelated to all of the above):
```
bluetoothctl connect 00:11:67:33:16:25
```

**Result — `wpctl status` confirms both directions working:**
- Sink `54. JBL Focus 500` — default output (A2DP).
- Source `60. bluez_input.00:11:67:33:16:25` — default input (HFP mic).
  Shows under "Filters" rather than "Sources" — normal PipeWire quirk for
  HFP mic routing via an internal loopback node, not a problem.

**Bluetooth audio routing: RESOLVED.** (Later found to be output-only —
BT mic input separately ruled out via HCI trace, see conversation.md
2026-08-02. Test 2/3/4 status finalized in PLAN.md.)

## 9. Kokoro TTS — install and first benchmark

```
sudo apt install -y python3-pip python3-venv
python3 -m venv ~/kokoro-env
source ~/kokoro-env/bin/activate
pip install --upgrade pip
pip install kokoro-onnx soundfile
```
Installed cleanly, all prebuilt wheels (`onnxruntime-1.28.0` included) —
no compilation needed, unlike whisper.cpp.

Model files:
```
mkdir -p ~/kokoro && cd ~/kokoro
curl -L --retry 5 --retry-delay 3 -o kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L --retry 5 --retry-delay 3 -o voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```
**Gotcha**: first attempt (without `--retry`) silently truncated the
`.onnx` file at 9.8MB of an expected 325,532,387 bytes over a flaky
connection (same failure mode as the earlier `git clone`) — `pw-play`
error was a red herring pointing at a missing file, the real error was
`onnxruntime.InvalidProtobuf` on load, which is the actual symptom of a
truncated model file. Verified the correct size via a HEAD request
(`curl -sIL ... | grep -i content-length`) before re-downloading with
`--retry`, then confirmed the re-download's exact byte count matched.

**API mismatch with the README**: installed version (`kokoro-onnx==0.5.0`)
has no `.generate()` method — introspected the real API instead of
trusting the docs:
```
python3 -c "from kokoro_onnx import Kokoro; print([m for m in dir(Kokoro) if not m.startswith('_')])"
# -> ['create', 'create_stream', 'from_session', 'get_voice_style', 'get_voices']
python3 -c "from kokoro_onnx import Kokoro; import inspect; print(inspect.signature(Kokoro.create))"
```
Correct method is `.create(text, voice, speed=1.0, lang='en-us', ...)`,
returns `(samples, sample_rate)`. Voice `"af_bella"` confirmed valid via
`k.get_voices()` (52 voices available across several accents/languages).

**Result — quality good, speed is a serious problem:**
- Playback through the Bose (`wpctl set-volume @DEFAULT_AUDIO_SINK@ 0.15`
  then `pw-play output.wav`) sounded natural, not robotic.
- `.create()` on a ~20-word sentence: **22.62–22.85s generation time**
  for 4.80s of resulting audio (RTF ≈ 4.76 — far worse than real-time).
- CPU confirmed maxed at **386.4%** across all 4 cores during generation
  (checked via `top -d 1` in a second "Connect to Shell" tab while the
  script ran in the first) — rules out a threading fix.
- Tried `.create_stream()` hoping for incremental chunks to reduce
  perceived latency — returned only 1 chunk for this input, time-to-
  first-chunk equal to total time. No benefit as tested.

**Full benchmark script used:**
```python
import kokoro_onnx, soundfile as sf, time
kokoro = kokoro_onnx.Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
text = "Hello. This is the first time I am speaking on this device. How do I sound?"
start = time.time()
samples, sample_rate = kokoro.create(text, voice="af_bella")
elapsed = time.time() - start
sf.write("output.wav", samples, sample_rate)
print(f"Done. Sample rate: {sample_rate}, generation time: {elapsed:.2f}s")
```

## Next up

- **Priority**: manual clause-chunking + pipelined playback test
  (`test_tts_chunked.py`, prepared 2026-08-02) — splits text into short
  clauses, generates+plays sequentially, measures per-clause generation
  time and true time-to-first-audible-word. Most promising untested lever
  for Kokoro's speed problem.
- If chunking doesn't get generation into a tolerable range: check for a
  quantized Kokoro ONNX variant, and reconsider TTS model choice entirely
  (Piper deserves a second look now that we have real comparative speed
  data; cloud TTS API as a last-resort option, moves away from
  local-first).
- Mic input still blocked on acquiring a USB mic (BT mic ruled out, see
  conversation.md 2026-08-02 "closed for good" entry).
- STT model tuning (quantization, Moonshine, tiny.en resident-process
  benchmark) remains deferred — lower priority than the Kokoro speed
  problem right now.
