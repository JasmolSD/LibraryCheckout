# Library Checkout System

Desktop application for logging library item checkouts and printing receipts.
Ported from a legacy Excel/VBA workflow to a modern Flask + pywebview stack.

## Features

- **Library card scanning** — look up patrons instantly; new-patron registration via inline modal (no `prompt()`)
- **Barcode scanning with week prefixes** — `1W`, `2W`, `3W` before the barcode overrides the default 3-week loan period
- **Checkout / Return / Renew** — colour-coded action tabs with loading states and toast notifications
- **PDF receipt generation** — ReportLab-based receipt printed directly from the browser
- **Patron history viewer** — full transaction log with filter tabs (All / Checkouts / Returns / Renewals)
- **Help & User Guide** — built-in `/help` page with step-by-step instructions and FAQ
- **Customisable UI** — drop `background.*` or `icon.*` into `client/static/images/` to brand the app without code changes
- **Late item flagging** — overdue items highlighted in red on the checkout screen and history page
- **Category support** — book, DVD, audiobook, magazine, eBook, other

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Flask 3, SQLAlchemy 2, SQLite |
| Frontend | Jinja2 templates, Tailwind CSS (CDN), Alpine.js 3 |
| Typography | Inter (Google Fonts) |
| Desktop wrapper | pywebview 5 (native window, no browser required) |
| Package manager | [uv](https://docs.astral.sh/uv/) |
| PDF receipts | ReportLab 4 |
| Tests | pytest 8, pytest-flask, pytest-cov |
| Linting | ruff, black |
| CI/CD | GitHub Actions (`.github/workflows/`) |

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
uv python install 3.12          # downloads Python 3.12 if needed
uv sync --group desktop         # creates .venv and installs all deps including pywebview
```

### 3. Run the desktop app

```bash
uv run python run.py
```

A native window opens with the checkout UI. No browser required.

### 4. Run as a web server (headless / Docker)

```bash
# Local Flask dev server
uv run flask --app "server.app:create_app()" run

# Docker
docker build -f docker/Dockerfile -t library-checkout .
docker run -p 5000:5000 library-checkout
```

## Pages

| URL | Description |
|---|---|
| `/` | Main checkout screen |
| `/history` | Patron transaction history |
| `/help` | User guide & FAQ |
| `/api/health` | Health-check JSON |

## API Reference

### Patrons

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/patrons/<card>` | Patron summary + active items + history |
| `POST` | `/api/patrons/` | Register a new patron |

### Checkouts

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/checkouts/` | Check out an item |
| `POST` | `/api/checkouts/return` | Return an item |
| `POST` | `/api/checkouts/renew` | Renew an item |

### Receipts

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/receipts/<card>` | PDF receipt of active checkouts |

## Customising the UI

Drop files into **`client/static/images/`** and restart the server — no code changes needed:

| Filename | Effect |
|---|---|
| `background.jpg` (or `.png`, `.webp`, `.gif`) | Full-page background image shown at ~20% opacity behind a white overlay |
| `icon.png` (or `.svg`, `.ico`, `.jpg`) | Replaces the default book SVG in the header and browser tab favicon |

## Barcode Week Prefixes

Scan or type a prefix immediately before the barcode digits to override the default 3-week loan:

| Prefix | Period | Example |
|---|---|---|
| `1W` | 1 week | `1W1234567890` |
| `2W` | 2 weeks | `2W1234567890` |
| `3W` or none | 3 weeks (default) | `3W1234567890` or `1234567890` |

## Development

First install dev dependencies (pywebview not needed for tests):

```bash
uv sync --group dev
```

### Tests

```bash
uv run pytest                        # all tests
uv run pytest --cov=server           # with coverage report
uv run pytest --cov=server --cov-report=html  # HTML coverage
```

### Lint & format

```bash
uv run ruff check .          # lint
uv run ruff check --fix .    # auto-fix
uv run black .               # format
uv run black --check .       # check formatting without changing files
```

## CI/CD (GitHub Actions)

| Workflow | Trigger | Jobs |
|---|---|---|
| **CI** (`.github/workflows/ci.yml`) | Push / PR to `main` | Ruff lint, Black format check, pytest on Python 3.11 & 3.12 |
| **CD** (`.github/workflows/cd.yml`) | Push to `main` or published Release | Build & push Docker image to `ghcr.io` |

No secrets need to be configured — the Docker push uses the built-in `GITHUB_TOKEN`.

## Project Layout

```
library-checkout/
├── pyproject.toml              # uv project config + tool settings
├── run.py                      # desktop launcher (Flask + pywebview)
├── .env                        # local environment overrides (not committed)
├── .github/
│   └── workflows/
│       ├── ci.yml              # lint + test pipeline
│       └── cd.yml              # Docker build & push pipeline
├── server/
│   ├── app/
│   │   ├── __init__.py         # app factory + context processor
│   │   ├── config.py           # Dev / Prod / Test config classes
│   │   ├── database.py         # SQLAlchemy instance
│   │   ├── models.py           # Patron, Book, Checkout ORM models
│   │   ├── routes/
│   │   │   ├── patrons.py      # GET /api/patrons, POST /api/patrons/
│   │   │   ├── checkouts.py    # POST /api/checkouts/{,return,renew}
│   │   │   └── receipts.py     # GET /api/receipts/<card>
│   │   ├── services/
│   │   │   ├── checkout_service.py  # Core business logic
│   │   │   ├── receipt_service.py   # PDF generation
│   │   │   └── validators.py        # Input validation
│   │   └── utils/
│   │       └── logger.py       # Rotating-file logger setup
│   └── tests/
│       ├── conftest.py
│       ├── test_checkout.py
│       ├── test_patrons.py
│       └── test_validators.py
├── client/
│   ├── templates/
│   │   ├── base.html           # Layout shell (header, nav, footer, background)
│   │   ├── index.html          # Checkout screen
│   │   ├── history.html        # Patron history viewer
│   │   └── help.html           # User guide & FAQ
│   └── static/
│       ├── css/styles.css      # Design system (fonts, animations, components)
│       ├── js/
│       │   ├── app.js          # Checkout screen Alpine.js component
│       │   └── patron.js       # History page Alpine.js component
│       └── images/             # Drop background.* / icon.* here to customise
├── data/                       # SQLite database — gitignored
├── logs/                       # Rotating app logs — gitignored
└── docker/
    └── Dockerfile              # Headless API image
```

## Building a Standalone Executable

```bash
uv run pyinstaller --windowed --onefile --name LibraryCheckout run.py
```

The resulting binary in `dist/` is fully self-contained — users do not need
Python or any dependencies installed.

## License

MIT — see [LICENSE](LICENSE).
