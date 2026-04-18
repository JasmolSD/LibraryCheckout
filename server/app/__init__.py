"""Flask application factory."""

from __future__ import annotations

from pathlib import Path

from flask import Flask
from flask_cors import CORS

from .config import get_config
from .database import db
from .utils.logger import setup_logging

#: Application version — compared against the latest GitHub release tag
#: by :mod:`server.app.services.update_check`.  Bump this whenever you
#: publish a new release so the "Update available" banner triggers for
#: older installs.  Tags on GitHub are expected to look like ``v0.1.0``.
VERSION = "0.1.0"


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure a Flask application instance.

    Reads configuration from the named environment class (development /
    production / testing), initialises SQLAlchemy and Flask-CORS, registers
    all route blueprints, registers a Jinja2 context processor that detects
    optional background / icon images, and creates database tables if they
    do not yet exist.

    Args:
        config_name: One of ``"development"``, ``"production"``, or
            ``"testing"``.  When ``None`` the value of the ``FLASK_ENV``
            environment variable is used, defaulting to ``"development"``.

    Returns:
        A fully-configured :class:`flask.Flask` application instance.
    """
    project_root = Path(__file__).resolve().parents[2]
    app = Flask(
        __name__,
        template_folder=str(project_root / "client" / "templates"),
        static_folder=str(project_root / "client" / "static"),
        static_url_path="/static",
    )

    # Load config
    app.config.from_object(get_config(config_name))

    # Guard against deploying with the default insecure secret key
    if app.config.get("ENV") == "production" and app.config["SECRET_KEY"] == "dev-secret-change-me":
        raise RuntimeError(
            "SECRET_KEY must be set to a strong random value in production. "
            "Set the SECRET_KEY environment variable."
        )

    # Make sure data + log directories exist
    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["LOG_DIR"]).mkdir(parents=True, exist_ok=True)

    # Init extensions
    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    setup_logging(app)

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # Context processor: detect background / icon images in client/static/images/
    images_dir = project_root / "client" / "static" / "images"

    @app.context_processor
    def inject_template_globals() -> dict:
        """Jinja2 context processor: expose library config and image paths.

        Injects the following into every template:

        * ``app_title`` — short title for header and browser tab
        * ``library_name`` — full organisation name
        * ``library_branch`` — branch name
        * ``library_phone`` — contact phone (empty string if unset)
        * ``library_email`` — contact email (empty string if unset)
        * ``library_address`` — street address (empty string if unset)
        * ``library_hours`` — opening hours (empty string if unset)
        * ``bg_image`` — relative path to background image, or ``None``
        * ``icon_image`` — relative path to icon image, or ``None``
        """
        bg_image: str | None = None
        icon_image: str | None = None
        if images_dir.exists():
            for ext in ("jpg", "jpeg", "png", "webp", "gif"):
                if (images_dir / f"background.{ext}").exists():
                    bg_image = f"images/background.{ext}"
                    break
            for ext in ("png", "svg", "ico", "jpg", "jpeg", "webp"):
                if (images_dir / f"icon.{ext}").exists():
                    icon_image = f"images/icon.{ext}"
                    break
        return {
            "app_version": VERSION,
            "app_title": app.config["APP_TITLE"],
            "library_name": app.config["LIBRARY_NAME"],
            "library_branch": app.config["LIBRARY_BRANCH"],
            "library_phone": app.config["LIBRARY_PHONE"],
            "library_email": app.config["LIBRARY_EMAIL"],
            "library_address": app.config["LIBRARY_ADDRESS"],
            "library_hours": app.config["LIBRARY_HOURS"],
            "bg_image": bg_image,
            "icon_image": icon_image,
        }

    # Register blueprints (added in batch 3)
    try:
        from .routes import books, checkouts, patrons, receipts

        app.register_blueprint(patrons.bp)
        app.register_blueprint(checkouts.bp)
        app.register_blueprint(receipts.bp)
        app.register_blueprint(books.bp)
    except ImportError as _bp_err:
        app.logger.warning("Route blueprints not yet available; skipping. Error: %s", _bp_err)

    # Default landing route — replaced by template in batch 4
    @app.route("/")
    def index():  # pragma: no cover
        try:
            from flask import render_template

            return render_template("index.html")
        except Exception:
            return "<h1>Library Checkout</h1><p>Frontend not yet installed.</p>"

    @app.route("/history")
    def history_page():
        """Render the patron transaction-history viewer."""
        from flask import render_template

        return render_template("history.html")

    @app.route("/help")
    def help_page():
        """Render the help & user-guide page."""
        from flask import render_template

        return render_template("help.html")

    @app.route("/register")
    def register_page():
        """Render the new-patron registration page."""
        from flask import render_template

        return render_template("register.html")

    @app.route("/catalog")
    def catalog_page():
        """Render the catalog search and management page."""
        from flask import render_template

        return render_template("catalog.html")

    @app.route("/stats")
    def stats_page():
        """Render the library statistics dashboard."""
        from flask import render_template

        return render_template("stats.html")

    @app.route("/api/stats")
    def stats_api():
        """Return aggregate library statistics as JSON.

        Pass ``?refresh=1`` to bypass the server-side cache.
        """
        from flask import jsonify, request

        from .services import checkout_service

        force = request.args.get("refresh") == "1"
        return jsonify(checkout_service.library_stats(force=force))

    @app.route("/api/health")
    def health():
        """Health-check endpoint used by monitoring and CI smoke tests.

        Returns:
            JSON ``{"status": "ok", "branch": "<library branch name>"}``.
        """
        return {"status": "ok", "branch": app.config["LIBRARY_BRANCH"]}

    @app.route("/api/update-check")
    def update_check_api():
        """Return the current version + whether a newer GitHub release exists.

        Pass ``?refresh=1`` to bypass the in-memory cache.
        """
        from flask import jsonify, request

        from .services.update_check import check_for_update

        force = request.args.get("refresh") == "1"
        return jsonify(check_for_update(force=force))

    # ── Startup connectivity guard ──────────────────────────────────
    # If DATABASE_URL points at a remote host (Supabase, etc.), verify
    # the connection is reachable NOW so the librarian sees a clear
    # message instead of a cryptic Python traceback.
    with app.app_context():
        from sqlalchemy import text as sa_text

        try:
            db.session.execute(sa_text("SELECT 1"))
        except Exception as exc:
            db_url = app.config["SQLALCHEMY_DATABASE_URI"]
            is_remote = "postgresql" in (db_url or "")
            if is_remote:
                app.logger.error(
                    "Cannot connect to the database. "
                    "Check your Wi-Fi connection and DATABASE_URL in .env.  "
                    "Error: %s",
                    exc,
                )
                raise SystemExit(
                    "\n"
                    "═══════════════════════════════════════════════════════\n"
                    "  CANNOT CONNECT TO THE DATABASE\n"
                    "\n"
                    "  This app requires a Wi-Fi / internet connection\n"
                    "  to reach the Supabase database.\n"
                    "\n"
                    "  Please check:\n"
                    "    1. Wi-Fi is connected and has internet access\n"
                    "    2. DATABASE_URL in your .env file is correct\n"
                    "\n"
                    f"  Technical details: {exc}\n"
                    "═══════════════════════════════════════════════════════\n"
                ) from exc
            raise  # Local SQLite — let the original error propagate

    # Create tables on first run, then apply any additive column migrations
    # so end users upgrading an older library.db don't hit "no such column".
    with app.app_context():
        db.create_all()
        from .utils.schema import ensure_schema

        added = ensure_schema(db.engine, db.metadata)
        if added:
            app.logger.info("Schema migration: added columns %s", ", ".join(added))
        app.logger.info("Application initialized (env=%s)", app.config["ENV"])

    # ── Request-time connectivity guard ──────────────────────────────
    # If the Wi-Fi drops while the app is running, catch DB errors on
    # each request and show a friendly message instead of a 500 trace.
    # Only catches OperationalError — all other exceptions (404s, etc.)
    # flow through Flask's normal handling untouched.
    from sqlalchemy.exc import OperationalError

    @app.errorhandler(OperationalError)
    def _handle_db_error(exc):
        db_url = app.config.get("SQLALCHEMY_DATABASE_URI") or ""
        if "postgresql" in db_url:
            app.logger.error("Database connection lost: %s", exc)
            try:
                from flask import render_template

                return (
                    render_template("offline.html"),
                    503,
                )
            except Exception:
                return (
                    "<h1>No Database Connection</h1>"
                    "<p>This app requires Wi-Fi to reach the library database.</p>"
                    "<p>Please check your internet connection and refresh this page.</p>",
                    503,
                )
        # Local SQLite — let Flask's default 500 handler deal with it
        raise exc

    return app
