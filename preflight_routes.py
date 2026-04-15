from fastapi import APIRouter

router = APIRouter(tags=["preflight"])

@router.get("/api/preflight/health")
async def preflight_health():
    return {"status": "ok"}
