from fastapi import APIRouter

router = APIRouter(tags=["changeset"])

@router.get("/api/changeset/health")
async def changeset_health():
    return {"status": "ok"}
