import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent


def create_app(data_dir=None):
    data = Path(data_dir or ROOT / "data")
    app = FastAPI(title="CareFlow · Synthetic Operations Analytics", version="2.0.0")

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")

    @app.get("/api/report")
    def report():
        path = data / "report.json"
        if not path.exists():
            raise HTTPException(503, "Run python pipeline.py first.")
        return json.loads(path.read_text())

    @app.get("/api/appointments")
    def appointments(
        provider: str | None = None,
        appointment_type: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        path = data / "appointments.sqlite"
        if not path.exists():
            raise HTTPException(503, "Run python pipeline.py first.")
        conditions = []
        params = []
        for field, value in [
            ("provider", provider),
            ("appointment_type", appointment_type),
        ]:
            if value:
                conditions.append(field + "=?")
                params.append(value)
        clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            summary = dict(
                conn.execute(
                    "SELECT COUNT(*) AS appointments,AVG(no_show) AS no_show_rate,AVG(wait_minutes) AS mean_wait_minutes FROM appointments"
                    + clause,
                    params,
                ).fetchone()
            )
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM appointments"
                    + clause
                    + " ORDER BY appointment_date DESC,appointment_id LIMIT ?",
                    params + [limit],
                )
            ]
        return {"summary": summary, "rows": rows, "limit": limit}

    @app.get("/api/health")
    def health():
        return {"status": "ok", "synthetic": True}

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    return app


app = create_app()
