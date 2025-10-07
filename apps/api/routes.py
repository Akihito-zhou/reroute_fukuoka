from fastapi import APIRouter

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def read_health() -> dict[str, str]:
    return {"status": "ok"}
