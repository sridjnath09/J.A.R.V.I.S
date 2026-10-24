#!/bin/zsh
# Start J.A.R.V.I.S. Run from Terminal.app the first time so macOS asks for Microphone access.
cd "$(dirname "$0")"
if ! curl -s http://localhost:11434/api/version >/dev/null; then
  echo "Starting Ollama..."
  open -a Ollama 2>/dev/null || (ollama serve >/dev/null 2>&1 &)
  sleep 3
fi
export HF_HUB_OFFLINE=1   # models are already downloaded; skip network checks on wake
exec .venv/bin/python -m jarvis "$@"
