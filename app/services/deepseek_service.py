import logging
import re
import json
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

def _parse_llm_json_or_text(content: str) -> CoopiaLLMResponse:
    """
    Parse la réponse de l'IA de manière ultra-résiliente :
    1. Validation Pydantic directe
    2. Extraction bloc ```json ... ```
    3. Extraction du premier objet { ... }
    4. Fallback intelligent en encapsulant le texte brut sans jamais bloquer l'utilisateur.
    """
    content_clean = content.strip()
    if not content_clean:
        raise ValueError("Contenu vide ou uniquement composé d'espaces.")

    # 1. Validation Pydantic directe
    try:
        return CoopiaLLMResponse.model_validate_json(content_clean)
    except Exception:
        pass

    # 2. Extraction bloc ```json ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content_clean, re.DOTALL)
    if match:
        try:
            return CoopiaLLMResponse.model_validate_json(match.group(1))
        except Exception:
            pass

    # 3. Extraction objet { ... }
    match = re.search(r"(\{.*\})", content_clean, re.DOTALL)
    if match:
        try:
            return CoopiaLLMResponse.model_validate_json(match.group(1))
        except Exception:
            pass

    # 4. Fallback texte brut propre
    clean_text = re.sub(r"^```\w*\n?|\n?```$", "", content_clean).strip()
    return CoopiaLLMResponse(
        reponse_texte=clean_text or "Je suis à votre écoute pour vous conseiller sur votre exploitation.",
        recommendations=[]
    )

async def generate_coopia_response(
    history_messages: list,
    user_text: str,
    user_context: Optional[dict] = None
) -> CoopiaLLMResponse:
    """
    Construit le contexte, injecte le profil du planteur connecté,
    applique une fenêtre glissante optimisée (anti-saturation DeepSeek),
    appelle DeepSeek et retourne un CoopiaLLMResponse garanti.
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

    # Fenêtre glissante : max 4 derniers messages pour éviter la saturation de grammaire JSON
    recent_history = history_messages[-4:] if len(history_messages) > 4 else history_messages

    messages = [{"role": "system", "content": system_content}]
    
    for msg in recent_history:
        text = msg.get("text", "").strip() if isinstance(msg, dict) else msg["text"].strip()
        if not text:
            continue

        # Remplacement des URLs d'images brutes par un token propre
        if text.startswith("[IMAGE]"):
            text = "[Photo de la parcelle envoyée pour diagnostic agricole]"

        # Troncature des très longues réponses précédentes (ex: longs diagnostics) à 500 car.
        if len(text) > 500:
            text = text[:500] + "... [suite du conseil]"

        is_user = msg.get("is_user") if isinstance(msg, dict) else msg["is_user"]
        role = "user" if is_user else "assistant"
        messages.append({"role": role, "content": text})
        
    messages.append({"role": "user", "content": user_text})
    
    # ── Tentative 1 : Mode JSON structuré ───────────────────────────────────
    try:
        response = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.3,
            max_tokens=2048,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content or ""
        if content.strip():
            return _parse_llm_json_or_text(content)
        logger.warning("DeepSeek a renvoyé des espaces vides en mode JSON, bascule vers mode texte...")
    except Exception as e:
        logger.warning(f"Échec parsing JSON DeepSeek ({e}), bascule vers mode texte...")

    # ── Tentative 2 : Fallback automatique en mode standard (infaillible) ───
    try:
        response_fallback = await client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.3,
            max_tokens=2048
        )
        content_fallback = response_fallback.choices[0].message.content or ""
        return _parse_llm_json_or_text(content_fallback)
    except Exception as e:
        logger.error(f"Erreur de communication avec DeepSeek : {e}")
        raise LLMUnavailableError(f"Le service IA est momentanément indisponible: {e}") from e
