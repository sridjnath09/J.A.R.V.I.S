"""Run with:  .venv/bin/python -m jarvis"""

import asyncio
import logging
import sys

from .config import ROOT, load_config


def setup_logging() -> None:
    (ROOT / "data").mkdir(exist_ok=True)
    fmt = "%(asctime)s %(levelname)-5s %(name)s: %(message)s"
    # Console shows warnings only: a scrolling log in a visible terminal would itself look like a
    # changing screen to JARVIS. Full detail goes to data/jarvis.log.
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format=fmt, datefmt="%H:%M:%S",
                        handlers=[console, logging.FileHandler(ROOT / "data" / "jarvis.log")])
    for noisy in ("httpx", "httpcore", "httpx2", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("phonemizer").setLevel(logging.ERROR)


def main() -> None:
    setup_logging()
    import qasync
    from PySide6.QtWidgets import QApplication

    from .main import Jarvis
    from .ui import macos

    app = QApplication(sys.argv)
    app.setApplicationName("J.A.R.V.I.S")
    app.setQuitOnLastWindowClosed(False)
    macos.hide_dock_icon()

    async def run() -> None:
        closing = asyncio.Event()
        app.aboutToQuit.connect(closing.set)
        jarvis = Jarvis(load_config())
        await jarvis.start()
        print("J.A.R.V.I.S is running. Say 'Hey Jarvis' or click the orb. Log: data/jarvis.log", flush=True)
        await closing.wait()

    try:
        qasync.run(run())
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    main()
