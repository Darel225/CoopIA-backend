import asyncio
import cloudinary
import cloudinary.uploader
from google import genai
from google.genai import types
from typing import Optional
from pydantic import BaseModel, Field
import logging

from app.core.config import settings
from app.services.vision_prompts import VISION_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

class VisionNotConfiguredError(Exception):
    pass

class VisionUnavailableError(Exception):
    pass

# Typed schema strictly for Gemini JSON schema constraint
class VisionRecommendationItem(BaseModel):
    titre: str
    description: str

class VisionDiagnosisResponse(BaseModel):
    reponse_texte: str
    recommendations: list[VisionRecommendationItem]
    nom_maladie: Optional[str] = Field(None, description="Nom précis de la maladie ou ravageur (ex: 'Pourriture brune des cabosses', 'Swollen Shoot', 'Chenilles défoliatrices', ou 'Plante saine')")
    certitude: Optional[float] = Field(0.95, description="Indice de confiance entre 0.0 et 1.0 (ex: 0.94)")

# Lazy configuration variables
_cloudinary_configured = False

def _ensure_configured():
    if not settings.GEMINI_API_KEY or not settings.CLOUDINARY_CLOUD_NAME or not settings.CLOUDINARY_API_KEY or not settings.CLOUDINARY_API_SECRET:
        raise VisionNotConfiguredError("Les clés d'API Cloudinary ou Gemini sont manquantes.")
    
    global _cloudinary_configured
    if not _cloudinary_configured:
        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True
        )
        _cloudinary_configured = True

def _get_gemini_client() -> genai.Client:
    _ensure_configured()
    return genai.Client(api_key=settings.GEMINI_API_KEY)

async def upload_to_cloudinary(file_bytes: bytes, user_id: str) -> str:
    _ensure_configured()
    try:
        # Offload synchronous cloudinary.uploader to thread
        result = await asyncio.to_thread(
            cloudinary.uploader.upload,
            file_bytes,
            folder=f"coopia/diagnostics/{user_id}",
            resource_type="image",
            timeout=15, # Explicite timeout
            # Option to discard EXIF is implied by Cloudinary's default image processing, 
            # or could use image_metadata=False, but default upload usually strips if auto qualities are used.
        )
        return result.get("secure_url")
    except Exception as e:
        logger.error(f"Cloudinary upload failed: {str(e)}")
        raise VisionUnavailableError(f"Échec de l'upload de l'image: {str(e)}") from e

async def upload_avatar_to_cloudinary(file_bytes: bytes, user_id: str) -> str:
    """Téléverse l'avatar vers Cloudinary dans coopia/avatars/{user_id} avec overwrite=True."""
    _ensure_configured()
    try:
        result = await asyncio.to_thread(
            cloudinary.uploader.upload,
            file_bytes,
            folder=f"coopia/avatars/{user_id}",
            public_id=f"avatar_{user_id}",
            overwrite=True,
            invalidate=True,
            resource_type="image",
            timeout=15,
        )
        return result.get("secure_url")
    except Exception as e:
        logger.error(f"Cloudinary avatar upload failed: {str(e)}")
        raise VisionUnavailableError(f"Échec de l'upload de l'avatar: {str(e)}") from e


from google.genai import errors

def _get_fallback_response() -> VisionDiagnosisResponse:
    return VisionDiagnosisResponse(
        reponse_texte="Je n'ai pas pu analyser cette photo. Veuillez vous assurer qu'il s'agit d'une image claire d'une plante, d'une culture ou d'un sol, et réessayez.",
        recommendations=[],
        nom_maladie=None,
        certitude=0.0
    )

async def analyze_image_with_gemini(file_bytes: bytes, mime_type: str = "image/jpeg") -> VisionDiagnosisResponse:
    if not settings.GEMINI_MODEL:
        raise VisionNotConfiguredError("Le modèle Gemini n'est pas défini dans GEMINI_MODEL.")

    client = _get_gemini_client()
    model_name = settings.GEMINI_MODEL
    
    try:
        image_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
        
        max_retries = 3
        base_delay = 1.0
        response = None
        for attempt in range(1, max_retries + 1):
            try:
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=[image_part, VISION_SYSTEM_PROMPT],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=VisionDiagnosisResponse,
                        temperature=0.4,
                    )
                )
                break
            except errors.APIError as e:
                if (e.code == 429 or e.code >= 500) and attempt < max_retries:
                    logger.warning(
                        f"Gemini API {e.code} (tentative {attempt}/{max_retries}), nouvel essai dans {base_delay * attempt}s... Détail: {str(e)}"
                    )
                    await asyncio.sleep(base_delay * attempt)
                    continue
                raise
        
        # Handle prompt blocking
        if getattr(response, "prompt_feedback", None) and getattr(response.prompt_feedback, "block_reason", None):
            logger.warning(f"Gemini prompt blocked: {response.prompt_feedback.block_reason}")
            return _get_fallback_response()
            
        # Handle candidate finish reasons (like SAFETY, MAX_TOKENS, etc.)
        if getattr(response, "candidates", None) and len(response.candidates) > 0:
            reason = getattr(response.candidates[0], "finish_reason", None)
            reason_str = str(reason).replace("FinishReason.", "")
            if reason and reason_str not in ("STOP", "FINISH_REASON_UNSPECIFIED", "None"):
                logger.warning(f"Gemini finish_reason: {reason}")
                return _get_fallback_response()
        
        if not getattr(response, "text", None):
            logger.warning("Réponse vide de Gemini.")
            return _get_fallback_response()
            
        # Parse output as JSON/Pydantic
        try:
            return VisionDiagnosisResponse.model_validate_json(response.text)
        except Exception as e:
            logger.warning(f"Gemini invalid JSON format: {str(e)}")
            return _get_fallback_response()
        
    except errors.APIError as e:
        if e.code in (401, 403):
            logger.error(f"Gemini authentication failed, check GEMINI_API_KEY and key restrictions (HTTP {e.code})")
            raise VisionUnavailableError(f"Erreur d'authentification Gemini (HTTP {e.code}).") from e
            
        if e.code == 400:
            err_msg = str(getattr(e, 'message', '')).lower()
            if 'api key' in err_msg or 'key not valid' in err_msg or 'invalid key' in err_msg:
                logger.error("Gemini authentication failed, check GEMINI_API_KEY and key restrictions (HTTP 400 with invalid key details)")
                raise VisionUnavailableError("Erreur d'authentification Gemini (HTTP 400).") from e
            else:
                logger.warning(f"Gemini Bad Request (HTTP 400): {str(e)}")
                return _get_fallback_response()
                
        if e.code == 404:
            logger.error("Gemini model not found, update GEMINI_MODEL")
            raise VisionUnavailableError(f"Le modèle {model_name} est introuvable ou désactivé.") from e
            
        if e.code == 429 or e.code >= 500:
            logger.error(f"Gemini service unavailable (HTTP {e.code}): {str(e)}")
            raise VisionUnavailableError(f"Service Gemini indisponible (HTTP {e.code}).") from e
            
        logger.error(f"Gemini API Error {e.code}: {str(e)}")
        return _get_fallback_response()
        
    except asyncio.TimeoutError as e:
        logger.error("Gemini timeout")
        raise VisionUnavailableError("Le service Gemini a expiré.") from e
    except Exception as e:
        logger.error(f"Gemini analysis failed: {type(e).__name__}")
        return _get_fallback_response()
