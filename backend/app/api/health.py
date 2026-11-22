"""Liveness and readiness. Public, and never reveals configuration values."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import error_body, ok
from app.integrations import llm as llm_module
from app.integrations import speech as speech_module

router = APIRouter()


@router.get("/health")
def health(request: Request):
    return ok(request, {"status": "ok"})


@router.get("/health/ready")
def ready(request: Request, db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content=error_body(request, "DATABASE_UNAVAILABLE", "The database is not reachable."))
    llm = llm_module.get_llm()
    speech = speech_module.get_speech()
    return ok(
        request,
        {
            "status": "ok",
            "database": "ok",
            "llm": {"provider": llm.name, "status": llm.status()},
            "speech": {"provider": speech.name, "available": speech.available},
        },
    )
