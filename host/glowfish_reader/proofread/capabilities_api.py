from fastapi import APIRouter

import capabilities

router = APIRouter()


@router.get("/api/capabilities")
def api_capabilities():
    caps = capabilities.capabilities()
    return {"ok": all(item["ok"] for item in caps.values()), "capabilities": caps}
