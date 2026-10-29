import logging
import httpx
from typing import Optional
from openai import AsyncOpenAI

from app.core.config import settings
from app.models.schemas import CoopiaLLMResponse
from app.services.prompt_templates import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

class LLMUnavailableError(Exception):
    """Exception levée en cas d'erreur réseau, timeout ou erreur fournisseur (DeepSeek)."""
    pass

client = AsyncOpenAI(
    api_key=settings.DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
    timeout=httpx.Timeout(25.0)
)

async def generate_coopia_response(
    history_messages: list,
    user_text: str,
    user_context: Optional[dict] = None
) -> CoopiaLLMResponse:
    """
    Construit le contexte, injecte le profil du planteur connecté, appelle le modèle DeepSeek, et parse le JSON retourné.
    """
    system_content = SYSTEM_PROMPT
    if user_context:
        name = user_context.get("name") or "Cher parent producteur"
        village = user_context.get("village") or "Côte d'Ivoire"
        culture = (user_context.get("culture") or "cacao").strip()
        system_content += f"""

PROFIL DU PLANTEUR ACTUELLEMENT CONNECTÉ :
- Nom : {name}
- Localité / Village : {village}
- Spéculation / Culture principale : {culture.upper()}
CONSIGNE CONTEXTUELLE OBLIGATOIRE :
Considère cette culture ({culture}) comme sa spéculation principale par défaut pour toute demande de prix, de valorisation, de fertilisation ou de récolte, sauf si le planteur cite explicitement une autre culture dans son message.
"""

    messages = [{"role": "system", "content": system_content}]
    
    for msg in history_messages:
        # Gère indifféremment un dictionnaire ou un objet de type asyncpg.Record
        text = msg.get("text", "").strip() if isinstance(msg, dict) else msg["text"].strip()
        if not text:
            continue
        is_user = msg.get("is_user") if isinstance(msg, dict) else msg["is_user"]
        role = "user" if is_user else "assistant"
        messages.append({"role": role, "content": text})
        
    messages.append({"role": "user", "content": user_text})
    
    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.3,
            max_tokens=2048,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content or ""
        return CoopiaLLMResponse.model_validate_json(content)
        
    except Exception as e:
        # En cas d'erreur de validation Pydantic (ValidationError) ou JSON
        if hasattr(e, "errors") or isinstance(e, ValueError):
            logger.error(f"Erreur de validation ou JSON invalide depuis l'IA : {e}")
            return CoopiaLLMResponse(
                reponse_texte="Je suis désolé, j'ai rencontré une difficulté pour formuler ma réponse. Pouvez-vous reformuler votre question ?",
                recommendations=[]
            )
        
        # En cas d'erreur de réseau ou d'API fournisseur
        logger.error(f"Erreur de communication avec DeepSeek : {e}")
        raise LLMUnavailableError(f"Le service IA est momentanément indisponible: {e}") from e
