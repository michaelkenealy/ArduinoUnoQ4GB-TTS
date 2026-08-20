# Arduino UNO Q 4GB — Local TTS and Bluetooth Findings

A record of experiments running speech synthesis and Bluetooth audio on an Arduino UNO Q 4GB.

Tested on the UNO Q's Debian Linux host in August 2026. The board has a Qualcomm QRB2210 application processor with four Cortex-A53 CPU cores and 4 GB RAM.

## Current conclusion

The practical audio architecture is:

```text
wired USB/I2S microphone → speech recognition → application logic
                                      ↓
                              Piper TTS → Bluetooth speaker
```

Bluetooth speaker output works. Bluetooth microphone input through the UNO Q's onboard radio does not currently work reliably and should not be used as the primary input path.

## Bluetooth

### Working

- Pairing and reconnecting Bluetooth audio devices.
- A2DP speaker output.
- Audible playback through both a JBL Focus 500 and a Bose portable speaker.
- Headless PipeWire/WirePlumber operation after configuring a persistent user session and the embedded WirePlumber profile.

### Not working

Bluetooth HFP/HSP microphone input was tested with two different devices. The software stack reported a successful headset profile and created a capture node, but an HCI-level `btmon` capture showed that the controller negotiated the eSCO link without transmitting any SCO audio data.

This points to a controller/firmware-level problem on the onboard Bluetooth path rather than a normal PipeWire or application configuration error. The current design therefore uses a wired microphone for input and Bluetooth only for optional TTS output.

## TTS experiments

### Kokoro-82M

Kokoro produced the most natural speech in listening tests, but it was too slow for conversation on this CPU-only board.

Observed results included:

- About 22–23 seconds to generate a roughly 20-word response in an early test.
- Around 90 seconds for a 29-word full-text test with the INT8 model.
- CPU utilisation near 386% across the four cores.
- Clause chunking made total generation slower because each call paid a large fixed cost.
- Pre-phonemising did not materially help.
- The INT8 model was slower than FP32 on this Cortex-A53 system.

Kokoro was therefore rejected for the on-device conversational path, although it remains useful for higher-quality speech generated on a laptop or desktop.

### Piper

Piper was adopted for the UNO Q because it is dramatically faster when the model remains loaded in memory.

Warm on-device tests showed approximately 0.4–3 seconds for realistic short responses, depending heavily on the individual voice. Voice quality and speed do not reliably follow Piper's nominal `medium` or `high` labels, so candidate voices need to be measured on the target board.

Current voice choices:

- English: `en_US-ryan-medium`
- Spanish: `es_MX-claude-high`

The Spanish voice was judged the most natural of the tested fast options. Piper is still more synthetic than Kokoro, but the speed difference makes it the better fit for an interactive device.

## What remains

The components have been tested separately, but the complete voice loop has not yet been assembled.

Remaining work:

1. Keep Piper resident in a small local service.
2. Test typed text → Piper → Bluetooth speaker.
3. Test recorded WAV → speech recognition → fixed response → Piper → speaker.
4. Acquire a USB microphone and test live press-to-talk interaction.
5. Measure complete end-to-end latency.
6. Finalise the speech-recognition model choice.

The most useful next milestone is a small reproducible end-to-end test, not further Bluetooth microphone debugging.

## Reproducibility notes

The Bluetooth investigation was performed from the UNO Q host shell, not inside an App Lab application container. System audio services and Bluetooth profiles need to be configured at the host level.

Piper voice models have individual licensing terms. Check each model's `MODEL_CARD` before redistributing model files.

## References

- [Piper](https://github.com/OHF-Voice/piper1-gpl)
- [Piper voice samples](https://piper.wide.video/samples)
- [Arduino UNO Q](https://docs.arduino.cc/hardware/uno-q/)
