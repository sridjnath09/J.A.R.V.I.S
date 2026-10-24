"""Wake word ("hey jarvis") and voice activity detection. Both are tiny and always loaded."""

import numpy as np
from openwakeword.model import Model
from openwakeword.vad import VAD


def _ensure_models() -> None:
    """Fetch the wake-word, embedding and VAD models on first run (a few MB)."""
    import os

    import openwakeword
    from openwakeword.utils import download_models
    folder = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
    if not os.path.exists(os.path.join(folder, "hey_jarvis_v0.1.onnx")):
        download_models(model_names=["hey_jarvis"])


class WakeWord:
    def __init__(self, threshold: float):
        self.threshold = threshold
        _ensure_models()
        self.model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")

    def detect(self, frame: np.ndarray) -> bool:
        scores = self.model.predict(frame)
        if max(scores.values()) >= self.threshold:
            self.model.reset()
            return True
        return False


class VoiceActivity:
    def __init__(self, threshold: float):
        self.threshold = threshold
        self.vad = VAD()

    def is_speech(self, frame: np.ndarray, threshold: float | None = None) -> bool:
        return float(self.vad.predict(frame, frame_size=640)) >= (threshold or self.threshold)

    def reset(self) -> None:
        self.vad.reset_states()
