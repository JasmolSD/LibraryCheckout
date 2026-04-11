"""Flask application factory."""

from __future__ import annotations

from pathlib import Path

from flask import Flask
from flask_cors import CORS

from .config import get_config
from .database import db
from .utils.logger import setup_logging


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

    # Make sure data + log directories exist
    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["LOG_DIR"]).mkdir(parents=True, exist_ok=True)

    # Init extensions
    db.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    setup_logging(app)

    # Context processor: detect background / icon images in client/static/images/
    images_dir = project_root / "client" / "static" / "images"

    @app.context_processor
    def inject_static_images() -> dict:
        """Jinja2 context processor: expose ``bg_image`` and ``icon_image``.

        Searches ``client/static/images/`` for files named ``background.*``
        and ``icon.*`` (common image extensions).  The resulting relative
        paths (e.g. ``"images/background.jpg"``) are made available in every
        template as ``bg_image`` and ``icon_image`` respectively.  Either
        value is ``None`` when no matching file is found.
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
        return {"bg_image": bg_image, "icon_image": icon_image}

    # Register blueprints (added in batch 3)
    try:
        from .routes import checkouts, patrons, receipts

        app.register_blueprint(patrons.bp)
        app.register_blueprint(checkouts.bp)
        app.register_blueprint(receipts.bp)
    except ImportError:
        app.logger.warning("Route blueprints not yet available; skipping.")

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

    @app.route("/api/health")
    def health():
        """Health-check endpoint used by monitoring and CI smoke tests.

        Returns:
            JSON ``{"status": "ok", "branch": "<library branch name>"}``.
        """
        return {"status": "ok", "branch": app.config["LIBRARY_BRANCH"]}

    # Create tables on first run
    with app.app_context():
        db.create_all()
        app.logger.info("Application initialized (env=%s)", app.config["ENV"])

    return app
