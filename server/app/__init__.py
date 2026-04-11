"""Flask application factory."""

from __future__ import annotations

from pathlib import Path
from flask import Flask
from flask_cors import CORS

from .config import get_config
from .database import db
from .utils.logger import setup_logging


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure a Flask application instance."""
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

    # Register blueprints (added in batch 3)
    try:
        from .routes import patrons, checkouts, receipts  # noqa: WPS433

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
        from flask import render_template

        return render_template("history.html")

    @app.route("/api/health")
    def health():
        return {"status": "ok", "branch": app.config["LIBRARY_BRANCH"]}

    # Create tables on first run
    with app.app_context():
        db.create_all()
        app.logger.info("Application initialized (env=%s)", app.config["ENV"])

    return app
