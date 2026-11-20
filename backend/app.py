"""One origin, explicit assets and protected V3 identity routes."""
import sqlite3
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from .config import ROOT, Settings
from .auth.routes import install_identity
from .migrations.manager import MigrationError
from .health import Readiness
from .schedule.routes import install_schedule
from .academics.routes import install_academics
from .academics.attestation_routes import install_attestations
from .requests.routes import install_requests
from .deanery.routes import install_deanery
from .brs.routes import install_brs
from .coursework_routes import install_coursework
from .attendance_routes import install_attendance
from .room_routes import install_rooms

ASSETS = {
    "/js/rooms.js": ("js/rooms.js", "text/javascript"),
    "/js/rooms-state.js": ("js/rooms-state.js", "text/javascript"),
    "/js/forecast.js": ("js/forecast.js", "text/javascript"),
    "/js/forecast-state.js": ("js/forecast-state.js", "text/javascript"),
    "/js/progress.js": ("js/progress.js", "text/javascript"),
    "/js/deadlines.js": ("js/deadlines.js", "text/javascript"),
    "/js/deadlines-state.js": ("js/deadlines-state.js", "text/javascript"),
    "/js/attendance.js": ("js/attendance.js", "text/javascript"),
    "/js/coursework.js": ("js/coursework.js", "text/javascript"),
    "/js/coursework-client.js": ("js/coursework-client.js", "text/javascript"),
    "/css/coursework.css": ("css/coursework.css", "text/css"),
    "/js/attestations.js": ("js/attestations.js", "text/javascript"),
    "/js/language.js": ("js/language.js", "text/javascript"),
    "/css/design.css": ("css/design.css", "text/css"),
    "/js/ui-shell.js": ("js/ui-shell.js", "text/javascript"),
    "/js/ui-state.js": ("js/ui-state.js", "text/javascript"),
    "/css/mvp.css": ("css/mvp.css", "text/css"),
    "/js/mvp.js": ("js/mvp.js", "text/javascript"),
    "/js/mvp-state.js": ("js/mvp-state.js", "text/javascript"),
    "/js/request-operation.js": ("js/request-operation.js", "text/javascript"),
    "/": ("index.html", "text/html"),
    "/css/tokens.css": ("css/tokens.css", "text/css"),
    "/css/base.css": ("css/base.css", "text/css"),
    "/js/app.js": ("js/app.js", "text/javascript"),
    "/js/requests.js": ("js/requests.js", "text/javascript"),
    "/js/requests-state.js": ("js/requests-state.js", "text/javascript"),
    "/js/academics.js": ("js/academics.js", "text/javascript"),
    "/js/academics-state.js": ("js/academics-state.js", "text/javascript"),
    "/js/schedule.js": ("js/schedule.js", "text/javascript"),
    "/js/schedule-state.js": ("js/schedule-state.js", "text/javascript"),
    "/js/account.js": ("js/account.js", "text/javascript"),
    "/js/account-state.js": ("js/account-state.js", "text/javascript"),
    "/js/api.js": ("js/api.js", "text/javascript"),
    "/js/utils/dates.js": ("js/utils/dates.js", "text/javascript"),
}
HEADERS = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"}

def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_environment()
    application = FastAPI(title="Цифровой деканат — конкурсный концепт", docs_url=None, redoc_url=None, openapi_url=None)
    application.state.settings = settings
    install_identity(application,settings)
    install_schedule(application,settings)
    install_academics(application,settings)
    install_attestations(application,settings)
    install_requests(application,settings)
    install_deanery(application,settings)
    install_brs(application,settings)
    install_coursework(application,settings)
    install_attendance(application,settings)
    install_rooms(application,settings)
    readiness = Readiness(settings)

    @application.get("/api/health")
    def health():
        try:
            if not readiness.check():
                raise MigrationError('Schema not ready')
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
