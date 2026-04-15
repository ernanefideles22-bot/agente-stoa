from fastapi import APIRouter

router = APIRouter(tags=["preview"])

@router.get("/api/preview/health")
async def preview_health():
    return {"status": "ok"}
