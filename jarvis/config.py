from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


class Config(dict):
    """Nested dict with attribute access: cfg.llm.model."""

    def __getattr__(self, name):
        try:
            value = self[name]
        except KeyError as e:
            raise AttributeError(name) from e
        return Config(value) if isinstance(value, dict) else value


def load_config(path: Path = ROOT / "config.yaml") -> Config:
    with open(path) as f:
        return Config(yaml.safe_load(f))


def resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p
