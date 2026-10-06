"""Admin-only runtime LLM settings and unsaved-form connection tests."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.db import get_db
from app.schemas.ai_settings import AiSettingsIn, AiSettingsOut, AiTestIn, AiTestOut
from app.services import llm_config, secret_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ai/settings", tags=["ai-settings"])


@router.get("", response_model=AiSettingsOut)
def get_settings(admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Expose non-secret effective configuration only to administrators."""
    return llm_config.view(db)


@router.put("", response_model=AiSettingsOut)
def put_settings(body: AiSettingsIn, admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Validate and save a partial update; audit field names without their values."""
    values = body.model_dump(exclude_unset=True, exclude={"api_key", "clear_api_key"})
    try:
        llm_config.save(db, values, api_key=body.api_key, clear_api_key=body.clear_api_key)
    except llm_config.ConfigError as exc:
        raise HTTPException(422, str(exc)) from None
    except secret_store.SecretStoreError:
        logger.error("LLM key store write failed")
        raise HTTPException(500, "failed to store key") from None
    logger.info("llm settings updated by user:%s fields=%s", admin.id, sorted(body.model_fields_set))
    return llm_config.view(db)


@router.post("/test", response_model=AiTestOut)
def test_settings(body: AiTestIn, admin=Depends(require_admin), db: Session = Depends(get_db)):
    """Probe unsaved values without changing DB, secret store, or worker configuration."""
    return llm_config.test_connection(db, body.model_dump(exclude_unset=True, exclude={"api_key", "clear_api_key"}),
                                      body.api_key, clear_api_key=body.clear_api_key)
