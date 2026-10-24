#!/bin/zsh
# One-time setup for J.A.R.V.I.S on an Apple Silicon Mac. Safe to re-run: it skips what is already there.
set -e
cd "$(dirname "$0")"

LLM_MODEL="qwen3:4b-instruct-2507-q4_K_M"
VISION_MODEL="qwen2.5vl:7b"
KOKORO_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

if [[ "$(uname -m)" != "arm64" ]]; then
  echo "J.A.R.V.I.S needs an Apple Silicon Mac (M1 or newer)." >&2
  exit 1
fi

if ! command -v uv >/dev/null; then
  echo "==> Installing uv (Python package manager)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v ollama >/dev/null; then
  echo "Ollama is not installed. Download it from https://ollama.com/download, open it once, then re-run ./setup.sh" >&2
  exit 1
fi

echo "==> Python environment (.venv, Python 3.12)"
[[ -d .venv ]] || uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt

echo "==> Ollama models (about 8.5 GB the first time)"
curl -s http://localhost:11434/api/version >/dev/null || { open -a Ollama 2>/dev/null || (ollama serve >/dev/null 2>&1 &); sleep 3; }
ollama pull "$LLM_MODEL"
ollama pull "$VISION_MODEL"

echo "==> Kokoro voice model (about 350 MB)"
mkdir -p models
[[ -f models/kokoro-v1.0.onnx ]] || curl -L --fail -o models/kokoro-v1.0.onnx "$KOKORO_URL/kokoro-v1.0.onnx"
[[ -f models/voices-v1.0.bin ]] || curl -L --fail -o models/voices-v1.0.bin "$KOKORO_URL/voices-v1.0.bin"

echo "==> Speech-to-text and wake-word models"
.venv/bin/python -c "
from huggingface_hub import snapshot_download
snapshot_download('mlx-community/parakeet-tdt-0.6b-v2')
from jarvis.voice.detectors import WakeWord
WakeWord(0.5)
"

chmod +x run.sh
echo
echo "Setup complete. Start J.A.R.V.I.S from Terminal.app with:  ./run.sh"
