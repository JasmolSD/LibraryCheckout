# Library Checkout System

Desktop application for logging library item checkouts and printing receipts.
Ported from a legacy Excel/VBA workflow to a modern Flask + pywebview stack.

## Features

- **Library card scanning** — look up patrons instantly; new-patron registration via inline modal (no `prompt()`)
- **Auto-generated card numbers** — registration page assigns the next sequential 14-digit library card automatically; no manual entry required
- **Catalog management** — Books page with ISBN auto-fill via Google Books; Manage Existing Book panel for looking up items by barcode to return, archive, or reactivate them
- **Statistics dashboard** — at-a-glance counts (patrons, catalog size, active checkouts, overdue items); click the overdue tile to expand a full list showing patron name, card number, book, barcode, and days overdue
- **Loan period selector** — choose 1, 2, or 3 weeks per checkout or renewal; defaults to 2 weeks
- **Checkout / Return / Renew** — colour-coded action tabs with loading states and toast notifications; per-item Return buttons on the checkout screen and history page for manual override returns
- **PDF receipt generation** — ReportLab-based receipt printed directly from the browser
- **Patron history viewer** — full transaction log with filter tabs (All / Checkouts / Returns / Renewals)
- **Help & User Guide** — built-in `/help` page with step-by-step instructions and FAQ
- **Customisable UI** — drop `background.*` or `icon.*` into `client/static/images/` to brand the app without code changes
- **Archive / Reactivate** — soft-delete patrons and books (preserves all history); reactivate at any time; archived items cannot be checked out
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
| `/register` | New patron registration (card number auto-generated) |
| `/books` | Add items to catalog + manage existing books (return, archive, reactivate) |
| `/stats` | Library statistics dashboard with overdue detail |
| `/help` | User guide & FAQ |
| `/api/health` | Health-check JSON |

## API Reference

### Patrons

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/patrons/next-card` | Next auto-generated 14-digit card number |
| `GET` | `/api/patrons/search?q=` | Search patrons by name |
| `GET` | `/api/patrons/<card>` | Patron summary + active items + history |
| `POST` | `/api/patrons/` | Register a new patron |
| `POST` | `/api/patrons/<card>/archive` | Archive (soft-delete) a patron |
| `POST` | `/api/patrons/<card>/reactivate` | Reactivate an archived patron |

### Books

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/books/lookup?isbn=` | Fetch title/author/category from Google Books |
| `GET` | `/api/books/<barcode>` | Book details including loan status |
| `POST` | `/api/books/` | Add an item to the catalog |
| `POST` | `/api/books/<barcode>/archive` | Archive (soft-delete) a book |
| `POST` | `/api/books/<barcode>/reactivate` | Reactivate an archived book |

### Checkouts

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/checkouts/overdue` | All overdue checkouts with patron & book details |
| `POST` | `/api/checkouts/` | Check out an item |
| `POST` | `/api/checkouts/return` | Return an item |
| `POST` | `/api/checkouts/renew` | Renew an item |

### Receipts

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/receipts/<card>` | PDF receipt of active checkouts |

### Stats

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/stats` | Aggregate library statistics (patrons, catalog, activity, top books) |

## Customising the UI

Drop files into **`client/static/images/`** and restart the server — no code changes needed:

| Filename | Effect |
|---|---|
| `background.jpg` (or `.png`, `.webp`, `.gif`) | Full-page background image shown at ~20% opacity behind a white overlay |
| `icon.png` (or `.svg`, `.ico`, `.jpg`) | Replaces the default book SVG in the header and browser tab favicon |

## Loan Period

A **Loan period** dropdown appears under the barcode field when the Checkout or Renew tab is active.
Select 1, 2, or 3 weeks before submitting. The default is **2 weeks**.
The selection persists between scans so it only needs to be changed when the period changes.

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
| **Release** (`.github/workflows/release.yml`) | Published GitHub Release | Build `LibraryCheckout.exe` and attach to the release |

No secrets need to be configured — all workflows use the built-in `GITHUB_TOKEN`.

## Project Layout

```
library-checkout/
├── pyproject.toml              # uv project config + tool settings
├── run.py                      # desktop launcher (Flask + pywebview)
├── Start.bat                   # double-click launcher for Windows (requires uv)
├── .env                        # local environment overrides (not committed)
├── .github/
│   └── workflows/
│       ├── ci.yml              # lint + test pipeline
│       ├── cd.yml              # Docker build & push pipeline
│       └── release.yml         # Windows .exe build attached to GitHub Releases
├── server/
│   ├── app/
│   │   ├── __init__.py         # app factory + context processor
│   │   ├── config.py           # Dev / Prod / Test config classes
│   │   ├── database.py         # SQLAlchemy instance
│   │   ├── models.py           # Patron, Book, Loan, Transaction ORM models
│   │   ├── routes/
│   │   │   ├── patrons.py      # GET /api/patrons, POST /api/patrons/, GET /api/patrons/next-card
│   │   │   ├── checkouts.py    # POST /api/checkouts/{,return,renew}, GET /api/checkouts/overdue
│   │   │   ├── books.py        # GET /api/books/lookup, GET/POST /api/books/, archive, reactivate
│   │   │   └── receipts.py     # GET /api/receipts/<card>
│   │   ├── services/
│   │   │   ├── checkout_service.py  # Core business logic
│   │   │   ├── receipt_service.py   # PDF generation
│   │   │   └── validators.py        # Input validation
│   │   └── utils/
│   │       └── logger.py       # Rotating-file logger setup
│   └── tests/
│       ├── conftest.py
│       ├── test_archive.py
│       ├── test_books.py
│       ├── test_checkout.py
│       ├── test_patrons.py
│       ├── test_receipts.py
│       ├── test_stats.py
│       └── test_validators.py
├── client/
│   ├── templates/
│   │   ├── base.html           # Layout shell (header, nav, footer, background)
│   │   ├── index.html          # Checkout screen
│   │   ├── history.html        # Patron history viewer
│   │   ├── register.html       # New-patron registration (auto-generated card)
│   │   ├── books.html          # Books catalog and management page
│   │   ├── stats.html          # Library statistics dashboard
│   │   └── help.html           # User guide & FAQ
│   └── static/
│       ├── css/styles.css      # Design system (fonts, animations, components)
│       ├── js/
│       │   ├── app.js          # Checkout screen Alpine.js component
│       │   ├── register.js     # Registration page Alpine.js component
│       │   └── patron.js       # History page Alpine.js component
│       └── images/             # Drop background.* / icon.* here to customise
├── data/                       # SQLite database — gitignored
├── logs/                       # Rotating app logs — gitignored
└── docker/
    └── Dockerfile              # Headless API image
```

## Distributing to End Users

### Option A — Download the pre-built installer (recommended)

Every [GitHub Release](../../releases) automatically includes a `LibraryCheckout.exe`
built by the `release.yml` workflow.  End users:

1. Download `LibraryCheckout.exe` from the latest release.
2. Double-click it — no Python, no uv, no installation required.
3. A `data/` folder is created next to the `.exe` on first run to store the database.

> **Note:** Windows may show a SmartScreen warning the first time because the binary
> is not code-signed.  Click **More info → Run anyway**.

### Option B — Double-click launcher (for developers)

If you have the dev environment set up, double-click **`Start.bat`** in the project root.
It syncs dependencies and launches the app without opening a terminal.

### Option C — Build the executable yourself

```bash
uv sync --group desktop --group dev   # ensure pyinstaller is available

uv run pyinstaller \
    --windowed --onefile --name LibraryCheckout \
    --collect-all pywebview \
    --add-data "client;client" \
    --add-data "server;server" \
    run.py
```

The resulting `dist/LibraryCheckout.exe` is fully self-contained.

> **Docker** is for headless server deployment only — it does not produce a desktop app.

## Starting a Similar Project with AI

The prompt below will reproduce the architecture and quality level of this project for any domain. Paste it at the start of a new conversation and fill in the bracketed sections.

<details>
<summary>Expand chatbot prompt</summary>

```
I want to build a [desktop / web / CLI] application called "[App Name]".

## What it does
[2–4 sentences describing the core workflow. Be specific: what does the user
do, what does the app do with that, and what is the output?]

## Who uses it
[Describe the end user. Are they technical? Non-technical? How will they
run the app — double-click on Windows, open a browser, use a terminal?]

## Key features
- [Feature 1]
- [Feature 2]
- [Feature 3]

## Tech stack preferences
- Language: [Python / TypeScript / Go / etc.]
- Backend: [Flask / FastAPI / Express / etc., or "you choose"]
- Frontend: [React / Jinja2 + Alpine.js / etc., or "you choose"]
- Database: [SQLite / PostgreSQL / etc., or "you choose"]
- Package manager: [uv / pip / npm / etc.]

## Constraints
- [e.g. "Must run on Windows without requiring users to install anything"]
- [e.g. "No paid APIs or services"]
- [e.g. "Data must stay local — no cloud storage"]

---

Please scaffold the full project with the following quality standards applied
from the start:

1. **Project layout** — clean separation of concerns (routes, services,
   models, config, tests, static assets).

2. **Configuration via .env** — all environment-specific values (app name,
   contact info, secrets, URLs) must be in a .env file with a .env.example
   template. No hardcoded strings anywhere in the codebase.

3. **Security basics** — validate all user input at API boundaries; raise
   meaningful errors (400/404/500) instead of unhandled exceptions; add
   standard HTTP security headers; fail loudly at startup if a required
   secret is missing in production.

4. **Database** — index every column used in WHERE/filter clauses; use an
   ORM with explicit relationships.

5. **Tests** — pytest (or equivalent) covering the happy path, known edge
   cases, and all HTTP status codes each endpoint can return. Aim for
   meaningful coverage, not 100%.

6. **Linting and formatting** — ruff + black (Python) or eslint + prettier
   (JS/TS), configured in the project file, runnable with a single command.

7. **CI/CD (GitHub Actions)** — lint + test on every push/PR; Docker image
   build on merge to main; attach a standalone executable to GitHub Releases
   if the app targets non-technical end users.

8. **Docker** — non-root user, explicit HEALTHCHECK, BuildKit cache mounts,
   lock file copied for reproducible installs.

9. **Standalone executable** — if the target users are non-technical, include
   a PyInstaller / pkg / nexe build step so they get a single double-clickable
   file with no installation required.

10. **Documentation** — docstrings on every public function (Args/Returns/
    Raises); a README with quick-start, pages/API reference, and a
    "Distributing to end users" section.

Start by confirming you understand the requirements, then generate the full
project structure and all files.
```

</details>

## License

MIT — see [LICENSE](LICENSE).
