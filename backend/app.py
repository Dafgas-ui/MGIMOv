"""One origin, explicit static assets, no personal-data endpoints."""
import sqlite3
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from .config import ROOT, Settings
from .db import connection
from .migrations.manager import MigrationError, status

ASSETS = {
    "/": ("index.html", "text/html"),
    "/css/tokens.css": ("css/tokens.css", "text/css"),
    "/css/base.css": ("css/base.css", "text/css"),
    "/js/app.js": ("js/app.js", "text/javascript"),
    "/js/api.js": ("js/api.js", "text/javascript"),
    "/js/utils/dates.js": ("js/utils/dates.js", "text/javascript"),
}
HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"}

def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_environment()
    application = FastAPI(title="Цифровой деканат — конкурсный концепт", docs_url=None, redoc_url=None, openapi_url=None)
    application.state.settings = settings

    @application.get("/api/health")
    def health():
        try:
            state = status(settings.database)
            if state["pending"] or state["state"] != "managed":
                raise MigrationError("Schema not ready")
            with connection(settings) as database:
                row = database.execute("SELECT value FROM app_metadata WHERE key='application'").fetchone()
                if row is None or row["value"] != "mgimov":
                    raise MigrationError("Unexpected application database")
        except (OSError, sqlite3.Error, MigrationError):
            return JSONResponse({"status": "unavailable"}, status_code=503, headers={"Cache-Control": "no-store"})
        return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})

    def asset(filename, media_type):
        def send():
            return FileResponse(ROOT / "frontend" / filename, media_type=media_type,
                                headers={**HEADERS, "Cache-Control": "no-cache"})
        return send
    for url, (filename, media_type) in ASSETS.items():
        application.add_api_route(url, asset(filename, media_type), methods=["GET"], include_in_schema=False)
    return application

app = create_app()
