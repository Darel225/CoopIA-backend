import json
import logging
from datetime import datetime

import asyncpg
from fastapi import APIRouter, Depends
from typing import Optional

from app.core.database import get_pool, get_db_connection
from app.core.security import get_current_user
from app.models.schemas import ClearHistoryInput, HistoryInput, SessionInput, UserOut

router = APIRouter()
logger = logging.getLogger(__name__)


def _serialize(obj):
    """Convertit les types non-JSON-sérialisables (datetime, etc.)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


# ── Connexion robuste : retry automatique sur connexion périmée ─────────────
_STALE_CONN_ERRORS = (
    asyncpg.ConnectionDoesNotExistError,
    asyncpg.ConnectionFailureError,
    OSError,          # WinError 10054 / ConnectionResetError
)


async def _fetch_with_retry(pool: asyncpg.Pool, query: str, *args):
    """
    Exécute un SELECT avec 1 tentative de retry sur connexion périmée.
    Retourne une liste vide plutôt que de propager l'erreur.
    """
    for attempt in range(2):
        try:
            async with pool.acquire() as conn:
                return await conn.fetch(query, *args)
        except _STALE_CONN_ERRORS as exc:
            logger.warning(
                "[DB] Connexion périmée (tentative %d/2) : %s", attempt + 1, exc
            )
            if attempt == 1:
                logger.error("[DB] Échec définitif après retry — fallback liste vide.")
                return []
    return []


async def _execute_with_retry(pool: asyncpg.Pool, *statements):
    """
    Exécute plusieurs (query, *args) dans une transaction avec 1 retry.
    Utilisé pour les opérations d'écriture (clear-history).
    Lève l'exception après 2 échecs (comportement identique à l'original).
    """
    for attempt in range(2):
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for query, *args in statements:
                        await conn.execute(query, *args)
            return
        except _STALE_CONN_ERRORS as exc:
            logger.warning(
                "[DB] Connexion périmée (écriture, tentative %d/2) : %s", attempt + 1, exc
            )
            if attempt == 1:
                raise


# ============================================================
# POST /get-recent-contacts
# Reproduit le nœud n8n "Execute a SQL query" + "Respond to Webhook1"
# ============================================================
@router.post("/get-recent-contacts")
async def get_recent_contacts(data: HistoryInput):
    """
    Retourne les 2 derniers prestataires distincts contactés par l'utilisateur.
    Format de réponse : { "success": true, "contacts": [...] }
    Reproduit exactement la réponse du nœud n8n Webhook1.
    """
    pool = await get_pool()
    records = await _fetch_with_retry(
        pool,
        """
        WITH unique_contacts AS (
            SELECT DISTINCT ON (telephone)
                nom,
                metier,
                note,
                nombre_interventions,
                telephone,
                whatsapp,
                created_at
            FROM contacts_recents
            WHERE user_email = $1
            ORDER BY telephone, created_at DESC
        )
        SELECT 
            nom,
            metier,
            note,
            nombre_interventions,
            REGEXP_REPLACE(telephone, '[^0-9+]', '', 'g') AS telephone,
            REGEXP_REPLACE(
                COALESCE(NULLIF(whatsapp, ''), NULLIF(telephone, '')),
                '[^0-9+]', '', 'g'
            ) AS whatsapp,
            created_at
        FROM unique_contacts
        ORDER BY created_at DESC
        LIMIT 2
        """,
        data.email,
    )

    contacts = []
    for r in records:
        d = dict(r)
        if isinstance(d.get("created_at"), datetime):
            d["created_at"] = d["created_at"].isoformat()
        contacts.append(d)

    # Format identique au nœud n8n "Respond to Webhook1"
    return {"success": True, "contacts": contacts}


# ============================================================
# POST /get-history
# Reproduit le nœud n8n "Execute a SQL query2" + "Respond to Webhook2"
# ============================================================
@router.post("/get-history")
async def get_history(data: HistoryInput):
    """
    Retourne l'historique des sessions de l'utilisateur.
    Format de réponse : { "success": true, "conversations": [...] }
    IMPORTANT : la clé retournée est "conversations" (et non "history")
    pour correspondre à ce que lit le frontend history.jsx.
    """
    pool = await get_pool()
    records = await _fetch_with_retry(
        pool,
        """
        SELECT DISTINCT ON (session_id)
            session_id,
            titre,
            sous_titre,
            statut,
            created_at
        FROM demandes_historique
        WHERE user_email = $1
        ORDER BY session_id, created_at DESC
        LIMIT 20
        """,
        data.email,
    )

    conversations = []
    for r in records:
        d = dict(r)
        if isinstance(d.get("created_at"), datetime):
            d["created_at"] = d["created_at"].isoformat()
        conversations.append(d)

    # Tri côté Python : du plus récent au plus ancien
    conversations.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    # Format identique au nœud n8n "Respond to Webhook2"
    return {"success": True, "conversations": conversations}


# ============================================================
# POST /get-conversation
# Reproduit le nœud n8n "Execute a SQL query3" + "Respond to Webhook3"
# ============================================================
@router.post("/get-conversation")
async def get_conversation(data: SessionInput):
    """
    Retourne tous les messages d'une session spécifique dans l'ordre chronologique.
    Format de réponse : { "success": true, "messages": [...] }
    """
    pool = await get_pool()
    records = await _fetch_with_retry(
        pool,
        """
        SELECT message_user, reponse_agent, prestataires_proposes, timestamp
        FROM conversations
        WHERE session_id = $1
        ORDER BY timestamp ASC
        """,
        data.session_id,
    )

    messages = []
    for idx, r in enumerate(records):
        ts = r["timestamp"].isoformat() if isinstance(r["timestamp"], datetime) else str(r["timestamp"])

        # Parsing des prestataires enregistrés en base
        prestataires_proposes = []
        if hasattr(r, "prestataires_proposes") or "prestataires_proposes" in r.keys():
            raw_pp = r.get("prestataires_proposes") or "[]"
            try:
                import json as _json
                prestataires_proposes = _json.loads(raw_pp) if isinstance(raw_pp, str) else raw_pp
            except Exception:
                prestataires_proposes = []

        # Le frontend (ai-chat.jsx) attend un objet par paire message/réponse
        # avec les champs exacts : message_user, reponse_agent, timestamp
        messages.append({
            "id": idx,                                  # id unique pour le keyExtractor
            "message_user": r["message_user"],          # lu par : if (row.message_user)
            "reponse_agent": r["reponse_agent"],        # lu par : if (row.reponse_agent)
            "prestataires_proposes": prestataires_proposes,
            "timestamp": ts,
            "created_at": ts,                           # alias pour compatibilité
        })

    # Format identique au nœud n8n "Respond to Webhook3"
    return {"success": True, "messages": messages}


# ============================================================
# POST /clear-history & DELETE /clear-history
# Route alias (compatibilité) pour le vidage sécurisé de l'historique
# ============================================================
@router.delete("/clear-history")
@router.post("/clear-history")
async def clear_history(
    current_user: UserOut = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db_connection),
):
    """
    Suppression transactionnelle des messages et sessions du planteur connecté UNIQUEMENT.
    Garantit le cloisonnement strict multi-tenant et la protection Anti-IDOR.
    """
    async with conn.transaction():
        await conn.execute(
            """
            DELETE FROM chat_messages 
            WHERE session_id IN (SELECT id FROM chat_sessions WHERE user_id = $1)
            """,
            current_user.id,
        )
        await conn.execute(
            "DELETE FROM chat_sessions WHERE user_id = $1",
            current_user.id,
        )

    return {
        "success": True,
        "message": "Historique des conversations supprimé avec succès.",
    }

