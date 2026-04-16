"""Desktop launcher: starts Flask in a background thread, opens a native window."""

import os
import sys
import threading
import time
from pathlib import Path

import webview
from dotenv import load_dotenv

from server.app import create_app

# Load .env from next to the .exe when frozen, or from the repo root
# when running from source. Matches server.app.config._project_root().
if getattr(sys, "frozen", False):
    _env_path = Path(sys.executable).resolve().parent / ".env"
else:
    _env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

HOST = "127.0.0.1"
PORT = 5000


def start_flask() -> None:
    app = create_app()
    app.run(host=HOST, port=PORT, use_reloader=False, debug=False)


def main() -> None:
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    # Give Flask a moment to bind the port before opening the window
    time.sleep(1.0)

    window_title = os.getenv("APP_TITLE", "Library Checkout")
    webview.create_window(
        title=window_title,
        url=f"http://{HOST}:{PORT}",
        width=1280,
        height=820,
        min_size=(1024, 700),
        resizable=True,
        text_select=True,
    )
    try:
        webview.start()
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
