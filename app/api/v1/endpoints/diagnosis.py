from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from typing import Optional
from pydantic import BaseModel
import asyncio
import logging
from uuid import uuid4, UUID
from datetime import datetime, timezone
import json
import asyncpg

from app.core.database import get_pool
from app.core.security import get_current_user
from app.models.schemas import UserOut
from app.core.config import settings
from app.services.vision_service import (
    upload_to_cloudinary,
    analyze_image_with_gemini,
    VisionNotConfiguredError,
    VisionUnavailableError
)

logger = logging.getLogger(__name__)

router = APIRouter()

class DiagnosisUserMessage(BaseModel):
    text: str
    is_user: bool = True

class DiagnosisAgentMessage(BaseModel):
    text: str
    recommendations: list[dict]
    is_user: bool = False

class DiagnosisResponse(BaseModel):
    user_message: DiagnosisUserMessage
    agent_message: DiagnosisAgentMessage
    image_url: Optional[str] = None
    session_id: Optional[str] = None

@router.post("/visual", response_model=DiagnosisResponse)
async def visual_diagnosis(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    current_user: UserOut = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool)
):
    # 1. Configuration check
    if not settings.GEMINI_API_KEY or not settings.CLOUDINARY_CLOUD_NAME or not settings.GEMINI_MODEL:
        raise HTTPException(status_code=503, detail="Le service de diagnostic visuel n'est pas configuré.")

    # 2. Validation: Content-Type
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=415, detail=f"Format non supporté: {file.content_type}")

    # Read and check size
    max_mb = settings.DIAGNOSIS_MAX_IMAGE_MB or 10
    max_bytes = max_mb * 1024 * 1024
    file_bytes = await file.read(max_bytes + 1)
    
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Le fichier est vide.")
        
    if len(file_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"L'image dépasse la taille maximale de {max_mb} MB.")

    # Validate real content (magic bytes for jpeg/png/webp basic check, avoiding heavy deps)
    detected_mime = None
    if file_bytes.startswith(b'\xff\xd8'):
        detected_mime = "image/jpeg"
    elif file_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
        detected_mime = "image/png"
    elif file_bytes.startswith(b'RIFF') and file_bytes[8:12] == b'WEBP':
        detected_mime = "image/webp"
    elif file_bytes[4:12] in [b'ftypheic', b'ftypheix', b'ftypmif1', b'ftypmsf1']:
        detected_mime = "image/heic"
        
    if not detected_mime:
        raise HTTPException(status_code=415, detail="Le contenu du fichier n'est pas une image valide.")

    # Normalize empty string session_id to None
    if session_id == "":
        session_id = None
        
    if session_id is not None:
        if session_id in ("null", "undefined"):
            raise HTTPException(status_code=422, detail="Les valeurs littérales 'null' et 'undefined' sont interdites.")
        try:
            session_uuid = UUID(session_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="session_id doit être un UUID valide.")
    else:
        session_uuid = None

    # 3. Processing
    cloudinary_task = upload_to_cloudinary(file_bytes, str(current_user.id))
    gemini_task = analyze_image_with_gemini(file_bytes, mime_type=detected_mime)
    
    results = await asyncio.gather(cloudinary_task, gemini_task, return_exceptions=True)
    
    for r in results:
        if isinstance(r, asyncio.CancelledError):
            raise r
            
    cloudinary_result = results[0]
    gemini_result = results[1]
    
    if isinstance(gemini_result, Exception):
        logger.error(f"Gemini error for user {current_user.id}: {str(gemini_result)}")
        raise HTTPException(status_code=503, detail="Le service d'analyse IA est momentanément indisponible.")
        
    image_url = None
    if isinstance(cloudinary_result, Exception):
        logger.warning(f"Cloudinary error for user {current_user.id}: {str(cloudinary_result)}")
        # Continue with image_url = None
    else:
        image_url = cloudinary_result

    user_display_text = f"[IMAGE]{image_url}" if image_url else "[📸 Photo envoyée pour diagnostic]"
    
    recs_dict = [{"titre": r.titre, "description": r.description} for r in gemini_result.recommendations]

    nom_maladie = getattr(gemini_result, "nom_maladie", None)
    confidence = float(getattr(gemini_result, "certitude", 0.95) or 0.95)
    confidence = max(0.0, min(1.0, round(confidence, 2)))
    pct = int(round(confidence * 100))

    is_disease = (
        nom_maladie
        and nom_maladie.strip().lower() not in (
            "plante saine", "saine", "aucun", "none", "culture saine", "non analysable", "inconnu", ""
        )
    )

    # Insertion du badge de certitude IA en tête des recommandations
    if is_disease and nom_maladie:
        recs_dict.insert(0, {
            "is_diagnosis_badge": True,
            "titre": f"🎯 Diagnostic IA certifié ({pct}% de confiance)",
            "description": f"Pathologie détectée : {nom_maladie}",
            "nom_maladie": nom_maladie,
            "certitude": confidence,
            "pct": pct
        })
    elif nom_maladie and "saine" in nom_maladie.lower():
        recs_dict.insert(0, {
            "is_diagnosis_badge": True,
            "titre": f"🌿 Culture saine ({pct}% de certitude)",
            "description": "Aucune anomalie ni maladie détectée sur cette photo.",
            "nom_maladie": nom_maladie,
            "certitude": confidence,
            "pct": pct
        })

    # 4. Persistence Métier (diagnostics + activities) & Chat (chat_messages)
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Récupère la parcelle de l'agriculteur
            parcelle = await conn.fetchrow(
                "SELECT id, name, village FROM parcelles WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
                current_user.id
            )
            parcelle_id = parcelle["id"] if parcelle else None

            if is_disease:
                diag_id = uuid4()
                confidence = float(getattr(gemini_result, "certitude", 0.95) or 0.95)
                confidence = max(0.0, min(1.0, round(confidence, 2)))
                diag_image_url = image_url or "https://res.cloudinary.com/coopia/placeholder_diagnosis.jpg"

                await conn.execute(
                    """
                    INSERT INTO diagnostics (id, user_id, parcelle_id, disease_name, confidence_score, image_url, recommended_action, status, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::diagnostic_status, $9)
                    """,
                    diag_id,
                    current_user.id,
                    parcelle_id,
                    nom_maladie,
                    confidence,
                    diag_image_url,
                    gemini_result.reponse_texte,
                    "DETECTED",
                    now
                )

                # Insertion dans activities
                act_id = uuid4()
                parcelle_title = parcelle["name"] if parcelle else "Parcelle Principale"
                parcelle_village = parcelle["village"] if parcelle and parcelle["village"] else "Exploitation"
                await conn.execute(
                    """
                    INSERT INTO activities (id, user_id, type, reference_id, title, subtitle, ui_color_tag, created_at)
                    VALUES ($1, $2, $3::activity_type, $4, $5, $6, $7, $8)
                    """,
                    act_id,
                    current_user.id,
                    "DISEASE_WARNING",
                    diag_id,
                    f"Maladie détectée : {nom_maladie}",
                    f"{parcelle_title} • {parcelle_village}",
                    "warning",
                    now
                )

            # Persistence session chat (toujours créer ou rattacher la session pour l'historique)
            if not session_uuid:
                session_uuid = uuid4()
                if is_disease and nom_maladie:
                    session_title = f"Diagnostic : {nom_maladie}"
                else:
                    session_title = "Diagnostic photo"
                await conn.execute(
                    """
                    INSERT INTO chat_sessions (id, user_id, title, status, created_at, updated_at)
                    VALUES ($1, $2, $3, 'ACTIVE', $4, $4)
                    """,
                    session_uuid, current_user.id, session_title, now
                )

            user_msg_id = uuid4()
            agent_msg_id = uuid4()
            recommendations_json = json.dumps(recs_dict)

            await conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, text, is_user, created_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                user_msg_id, session_uuid, user_display_text, True, now
            )
            await conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, text, is_user, created_at, recommendations)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                agent_msg_id, session_uuid, gemini_result.reponse_texte, False, now, recommendations_json
            )
            await conn.execute(
                "UPDATE chat_sessions SET updated_at = $1 WHERE id = $2",
                now, session_uuid
            )

    # 5. Response
    return DiagnosisResponse(
        user_message=DiagnosisUserMessage(text=user_display_text, is_user=True),
        agent_message=DiagnosisAgentMessage(
            text=gemini_result.reponse_texte,
            recommendations=recs_dict,
            is_user=False
        ),
        image_url=image_url,
        session_id=str(session_uuid) if session_uuid else None
    )
