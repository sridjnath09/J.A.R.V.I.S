# J.A.R.V.I.S v1.0.0

First public release of J.A.R.V.I.S: a free, fully local desktop tutor for macOS on Apple Silicon. It reads your
screen, listens for "Hey Jarvis", and answers in a JARVIS-style British voice, usually about 1.75 s after you
finish your question. No cloud services, no API keys, no cost.

## Highlights

- **Sees the screen you choose.** JARVIS reads the display its floating orb is on; drag the orb to another
  monitor to switch. Multi-pane windows (sidebar, editor, chat) are read pane by pane, so the text stays in order.
- **Knows what you point at.** Highlight text and ask "explain this", or point the mouse at a line and ask
  "what is this?".
- **Hands-free voice.** Wake word, follow-up questions without the wake word for 45 s, and a British voice with
  JARVIS-style effects.
- **Easy to interrupt.** Talk over it, say "Hey Jarvis" or "stop", press Esc, or click the orb.
- **Tutor modes.** Explain, Teach me, Debug and Quiz me, switched by voice or from the orb's menu.
- **Iron Man style HUD orb** that shows whether JARVIS is in standby, ready, listening, thinking, speaking or paused.

## Features

**Screen understanding**
- Background screen reading with Apple's on-device OCR; text is read again only after the screen changes and settles.
- Option to read every display instead of just the orb's (`screen.read: all`).
- Visual questions ("what does this chart show?") go to a local vision model, using the area around the pointer.

**Voice**
- Wake word "Hey Jarvis" (openWakeWord) and voice activity detection (Silero VAD).
- Speech-to-text with parakeet-mlx on the Apple GPU.
- Kokoro voice (`bm_george` by default) with effects presets: `off`, `subtle`, `classic`, `full-lab`.
- Speech starts after the first clause of the answer. Long answers are spoken in part, and the full text goes to
  the transcript.
- Voice commands: "stop", "stand by", "stay awake", "pause", "teach me mode", "quiz me", "debug mode",
  "explain mode".

**Desktop**
- A floating orb that stays above all windows and on every desktop Space. Click to talk, hold for push-to-talk,
  double-click for the transcript, right-click for the menu. ⌥J hides it; Esc stops JARVIS.
- Clicking the orb leaves your current app focused, so its selection is kept.
- Transcript panel showing answers, code blocks and per-question latency.

**Lifecycle**
- Starts in standby (about 300 MB). Models load when you wake JARVIS (3–5 s) and unload after 5 minutes without a
  question.

## Performance

Measured on an M1 Mac with 16 GB, with the screen already prepared:

| Stage | Time |
| --- | --- |
| End-of-speech detection | 0.75 s (setting) |
| Speech-to-text | 0.19 s |
| First LLM token | 0.39 s |
| First audio | 0.42 s |
| **Your last word to JARVIS's first word** | **≈ 1.75 s** |

Answers are much slower when macOS is swapping heavily. JARVIS needs about 6 GB of free memory while you talk to it.

## Privacy

- Everything runs on your Mac. The only network use is the one-time model download in `setup.sh`.
- Screen captures and OCR text stay in memory and are never saved.
- Apps on the blocklist (password managers, Keychain Access, trading apps, Wallet) are left out before reading, on
  any display.
- JARVIS's own windows are invisible to its screen reader.
- Conversation history and logs are stored locally in `data/`, which is excluded from git.

## Requirements

- Mac with Apple Silicon (M1 or newer); 16 GB of memory recommended
- macOS 14 or newer
- [Ollama](https://ollama.com/download)
- About 10 GB of free disk space for the models

## Install

```sh
git clone https://github.com/sridjnath09/J.A.R.V.I.S.git
cd J.A.R.V.I.S
./setup.sh
./run.sh
```

Run it from Terminal.app and grant **Microphone**, **Screen & System Audio Recording** and **Accessibility** to
Terminal. Accessibility is needed for highlighted text and the hotkeys. Restart JARVIS after granting them.
See the [README](README.md) for details.

## Models

| Part | Model |
| --- | --- |
| Answers | `qwen3:4b-instruct-2507-q4_K_M` (Ollama) |
| Visual questions | `qwen2.5vl:7b` (Ollama) |
| Speech-to-text | `mlx-community/parakeet-tdt-0.6b-v2` |
| Voice | Kokoro-82M (ONNX) |
| Wake word and voice detection | openWakeWord "hey jarvis", Silero VAD |
| Screen reading | Apple Vision OCR |

## Known limitations

- **Not yet tested on real hardware:** visual-question latency, barge-in with a headset, reading highlighted text
  (Accessibility and the ⌘C fallback), and the orb's click, hold and drag gestures.
- **Speakers:** talking over JARVIS only works with headphones. On speakers, set `listen.barge_in: false` and use
  "Hey Jarvis", "stop" or Esc instead.
- **Screen capture:** JARVIS uses `CGWindowListCreateImage`, which Apple has deprecated. If capture stops
  responding after a permission change, quit and reopen Terminal. Moving to ScreenCaptureKit is planned.
- **OCR:** very small or dense code can be misread; text in images is only read through the vision model.
- **English only.**
