# Library Checkout System

Desktop application for logging library book checkouts and printing receipts.
Ported from a legacy Excel/VBA workflow to a modern Flask + pywebview stack.

## Tech Stack

- **Backend**: Flask 3, SQLAlchemy, SQLite
- **Frontend**: Server-rendered HTML + Tailwind (CDN) + Alpine.js
- **Desktop wrapper**: pywebview (native window, no browser needed)
- **Package manager**: [uv](https://docs.astral.sh/uv/)
- **Receipts**: ReportLab (PDF generation)
- **Tests**: pytest

## Quick Start

### 1. Install uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. Bootstrap the project

```bash
git clone <your-repo> library-checkout
cd library-checkout
cp .env.example .env
uv python install 3.12   # downloads Python if needed
uv sync                  # creates .venv and installs all deps
```

### 3. Run the desktop app

```bash
uv run python run.py
```

A native window will open running the checkout UI. No browser required.

### 4. Run tests

```bash
uv run pytest
uv run pytest --cov=server  # with coverage
```

### 5. Lint & format

```bash
uv run ruff check .
uv run black .
```

## Project Layout

```
library-checkout/
├── pyproject.toml      # uv project config + dependencies
├── run.py              # desktop launcher (Flask + pywebview)
├── .env.example        # copy to .env for local config
├── server/             # Flask backend (app factory, models, routes, services)
├── client/             # Templates, CSS, JS
├── data/               # SQLite database (gitignored)
├── logs/               # rotating app logs (gitignored)
└── docker/             # Dockerfile for headless API mode
```

See each subdirectory's README for details.

## Building a Standalone Executable

```bash
uv run pyinstaller --windowed --onefile --name LibraryCheckout run.py
```

The resulting binary in `dist/` is a fully self-contained app — users do
not need Python or any dependencies installed.

## License

MIT — see LICENSE.