"""Health and integration diagnostics endpoints."""

from fastapi import APIRouter
from typing import Any, Dict

from app.config import get_settings
from app.services.telecmi_service import TeleCMIService
from app.services.welfog_service import WelfogService
from app.services.qdrant_service import QdrantService
from app.services.gemini_service import GeminiService

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health_check() -> Dict[str, str]:
    """Primary liveness check."""
    return {"status": "ok"}


@router.get("/health/integrations")
async def integrations_diagnostic() -> Dict[str, Any]:
    """
    Non-destructive integration connectivity check.
    Does NOT leak any secrets or sensitive keys.
    """
    settings = get_settings()
    results: Dict[str, Any] = {
        "status": "ok",
        "integrations": {}
    }

    # 1. TeleCMI Connectivity
    telecmi = TeleCMIService()
    try:
        token = await telecmi.get_app_token()
        results["integrations"]["telecmi"] = {
            "status": "connected" if token else "failed",
            "app_id": settings.telecmi_app_id,
            "sbc": settings.telecmi_sbc
        }
    except Exception as e:
        results["integrations"]["telecmi"] = {"status": "error", "message": str(e)}
    finally:
        await telecmi.close()

    # 2. Welfog API Connectivity
    welfog = WelfogService()
    try:
        welfog_res = await welfog.get_order_history(user_id=1, limit=1)
        results["integrations"]["welfog_api"] = {
            "status": "connected" if welfog_res.get("success") else "unreachable",
            "base_url": settings.welfog_api_base
        }
    except Exception as e:
        results["integrations"]["welfog_api"] = {"status": "error", "message": str(e)}
    finally:
        await welfog.close()

    # 3. Welfog Knowledge Base (aidata.welfog.com / Qdrant)
    qdrant = QdrantService()
    try:
        if settings.welfog_knowledge_api_key or settings.qdrant_url:
            q_res = await qdrant.search_knowledge("test")
            results["integrations"]["knowledge_base"] = {
                "status": "connected" if q_res.get("success") else "error",
                "provider": q_res.get("provider", "unknown"),
                "collection": settings.qdrant_collection
            }
        else:
            results["integrations"]["knowledge_base"] = {
                "status": "unconfigured",
                "message": "Awaiting WELFOG_KNOWLEDGE_API_KEY or QDRANT_URL. Production RAG will activate when key is provided.",
                "existing_admin_ui": "https://aidata.welfog.com/admin"
            }
    except Exception as e:
        results["integrations"]["knowledge_base"] = {"status": "error", "message": str(e)}
    finally:
        await qdrant.close()

    # 4. Gemini Configuration
    gemini = GeminiService()
    results["integrations"]["gemini"] = {
        "status": "configured" if gemini.is_configured() else "unconfigured",
        "live_model": settings.gemini_live_model,
        "voice": settings.gemini_voice_name
    }

    return results
