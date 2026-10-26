"""Demo-mode router: serve a sample fintech profile with prefilled answers (Req 7).

Sources fixed sample data from ``demo.json`` via the content loader. A missing
or invalid demo file surfaces as :class:`ContentError`, which the centralized
handler renders as HTTP 500 without partial data (Req 7.5).
"""

from __future__ import annotations

from fastapi import APIRouter

from app import schemas
from app.services.content_loader import load_demo

router = APIRouter(prefix="/api", tags=["demo"])


@router.get("/demo", response_model=schemas.DemoResponse)
def get_demo() -> schemas.DemoResponse:
    """Return the sample company profile and prefilled answers (Req 7.1, 7.4)."""
    demo = load_demo()
    return schemas.DemoResponse(
        company={k: str(v) for k, v in demo.company.items()},
        answers=demo.answers,
    )
