import logging
import asyncio
from google import genai
from google.genai import types
from google.genai import errors
from app.core.config import settings

logger = logging.getLogger(__name__)

class TranscriptionUnavailableError(Exception):
    pass

def _get_gemini_client() -> genai.Client:
    if not settings.GEMINI_API_KEY:
        raise TranscriptionUnavailableError("Clé GEMINI_API_KEY manquante dans la configuration.")
    return genai.Client(api_key=settings.GEMINI_API_KEY)

def _extract_text_from_response(response) -> str:
    """Extrait fidèlement le texte de la réponse (gère audio_transcription et text)."""
    if not response:
        return ""
    if hasattr(response, "candidates") and response.candidates:
        for c in response.candidates:
            if hasattr(c, "content") and hasattr(c.content, "parts"):
                for p in c.content.parts:
                    if hasattr(p, "audio_transcription") and p.audio_transcription:
                        t = getattr(p.audio_transcription, "text", "")
                        if t:
                            return t.strip()
                    elif hasattr(p, "text") and p.text:
                        return p.text.strip()
    if getattr(response, "text", None):
        return response.text.strip()
    return ""

async def transcribe_audio_with_gemini(audio_bytes: bytes, mime_type: str = "audio/m4a") -> str:
    """
    Transcrit un fichier audio avec une fidélité absolue en utilisant
    le modèle spécialisé Google Gemini 3.5 Transcribe.
    """
    if not audio_bytes or len(audio_bytes) == 0:
        return ""

    client = _get_gemini_client()
    
    # Normalisation du mime_type pour l'API
    m_lower = mime_type.lower() if mime_type else ""
    if "m4a" in m_lower or "mp4" in m_lower or "aac" in m_lower:
        effective_mime = "audio/mp4"
    elif "wav" in m_lower:
        effective_mime = "audio/wav"
    elif "ogg" in m_lower:
        effective_mime = "audio/ogg"
    elif "mp3" in m_lower or "mpeg" in m_lower:
        effective_mime = "audio/mpeg"
    else:
        effective_mime = "audio/mp4"

    audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=effective_mime)

    prompt = (
        "Tu es le transcripteur vocal de l'application agricole CoopIA en Côte d'Ivoire. "
        "Transcris avec une fidélité absolue mot à mot ce qui est dit dans cet audio en français. "
        "RÈGLES CRITIQUES : "
        "1. Nombres et quantités : Retranscris fidèlement les nombres exacts prononcés (ex: '500 kg', '100 kg', '50 kg'). "
        "Sois extrêmement vigilant : ne confonds JAMAIS 'cinq cents' (500) avec 'cent' (100) ni 'cinq cent cinq' (505). "
        "2. Vocabulaire agricole et localités : Respecte scrupuleusement les termes agricoles et toponymes de Côte d'Ivoire (cacao, café, cabosses, fèves, Soubré, Daloa, San Pedro, Duékoué, Gagnoa, etc.). "
        "3. Renvoie UNIQUEMENT le texte exact prononcé, sans inventer, sans résumer et sans ajouter de guillemets."
    )

    # 1. Essai prioritaire avec le modèle spécialisé gemini-3.5-transcribe
    try:
        response = await client.aio.models.generate_content(
            model="gemini-3.5-transcribe",
            contents=[audio_part, prompt]
        )
        text = _extract_text_from_response(response)
        if text:
            # Nettoyage guillemets superflus
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1].strip()
            return text
    except Exception as e:
        logger.warning(f"Modèle gemini-3.5-transcribe non disponible ou en échec: {str(e)}, fallback sur gemini-3.5-flash...")

    # 2. Fallback avec gemini-3.5-flash et consignes numériques strictes
    try:
        strict_prompt = (
            "Tu es le transcripteur vocal de CoopIA. "
            "Transcris mot à mot ce qui est dit dans cet audio en français. "
            "RÈGLE CRITIQUE : Sois extrêmement rigoureux sur les nombres ('cinq cents' = 500, 'cent' = 100, 'cinq cent cinq' = 505). "
            "N'invente rien. Renvoie UNIQUEMENT le texte exact prononcé."
        )
        response = await client.aio.models.generate_content(
            model="gemini-3.5-flash",
            contents=[audio_part, strict_prompt],
            config=types.GenerateContentConfig(temperature=0.0)
        )
        text = _extract_text_from_response(response)
        if text:
            if text.startswith('"') and text.endswith('"'):
                text = text[1:-1].strip()
            return text
        return ""
    except Exception as e:
        logger.error(f"Erreur de transcription audio finale: {str(e)}")
        raise TranscriptionUnavailableError(f"Échec de la transcription vocale: {str(e)}") from e
