from fastapi import APIRouter, Depends
from typing import Optional
from asyncpg import Connection

from app.core.database import get_db_connection
from app.core.security import get_current_user
from app.models.schemas import UserOut, ActivityOut

router = APIRouter()

@router.get("/latest", response_model=Optional[ActivityOut])
async def get_latest_activity(
    current_user: UserOut = Depends(get_current_user),
    conn: Connection = Depends(get_db_connection),
):
    """
    Renvoie la dernière activité pour l'utilisateur connecté
    pour alimenter la carte d'accueil de l'application mobile de manière 100% dynamique,
    en unifiant les activités métier (récoltes, diagnostics) et les interactions conversationnelles récentes.
    """
    # 1. Priorité absolue : la dernière session de chat active de l'utilisateur
    session_row = await conn.fetchrow(
        """
        SELECT 
            cs.id,
            cs.user_id,
            cs.title,
            cs.status::text AS db_status,
            cs.created_at,
            cs.updated_at,
            (
                SELECT text 
                FROM chat_messages 
                WHERE session_id = cs.id 
                ORDER BY created_at DESC 
                LIMIT 1
            ) AS last_message_text,
            BOOL_OR(
                cm.text ILIKE '%récolte%' 
                OR cm.text ILIKE '%déclaration%' 
                OR cm.text ILIKE '%bordereau%' 
                OR cm.text ILIKE '%sac%'
                OR cs.title ILIKE '%récolte%'
                OR cs.title ILIKE '%sac%'
            ) AS is_harvest_session,
            BOOL_OR(
                cm.text ILIKE '[IMAGE]%' 
                OR cm.text ILIKE '%[📸 Photo%' 
                OR cm.media_url IS NOT NULL 
                OR cm.text ILIKE '%pourriture%' 
                OR cm.text ILIKE '%swollen%' 
                OR cm.text ILIKE '%miride%' 
                OR cm.text ILIKE '%maladie%' 
                OR cm.text ILIKE '%rouille%'
                OR cs.title ILIKE '%diagnostic%'
                OR cs.title ILIKE '%maladie%'
            ) AS is_disease_session
        FROM chat_sessions cs
        LEFT JOIN chat_messages cm ON cm.session_id = cs.id
        WHERE cs.user_id = $1
        GROUP BY cs.id, cs.user_id, cs.title, cs.status, cs.created_at, cs.updated_at
        ORDER BY COALESCE(cs.updated_at, cs.created_at) DESC
        LIMIT 1
        """,
        current_user.id
    )

    if session_row:
        session_time = session_row["updated_at"] or session_row["created_at"]
        last_text = session_row["last_message_text"]
        subtitle = None
        if last_text:
            if last_text.startswith("[IMAGE]"):
                subtitle = "📸 Diagnostic photo analysé"
            else:
                clean_text = " ".join(last_text.strip().split())
                subtitle = (clean_text[:75] + "...") if len(clean_text) > 75 else clean_text
        else:
            subtitle = "Conversation enregistrée"

        title_lower = (session_row["title"] or "").lower()
        is_harvest_title = any(k in title_lower for k in ["récolte", "recolte", "sac", "kg", "pesée", "pesee", "bordereau", "bdr"])
        is_disease_title = any(k in title_lower for k in ["maladie", "diagnostic", "cabosse", "pourriture", "swollen", "chenille", "rouille"])

        if is_harvest_title or (session_row["is_harvest_session"] and "déclar" in title_lower):
            act_type = "HARVEST_LOG"
            ui_color = "success"
        elif is_disease_title or session_row["is_disease_session"]:
            act_type = "DISEASE_WARNING"
            ui_color = "warning"
        else:
            act_type = "CHAT_CONVERSATION"
            ui_color = "success"

        return ActivityOut(
            id=session_row["id"],
            user_id=session_row["user_id"],
            session_id=session_row["id"],
            type=act_type,
            reference_id=None,
            title=session_row["title"] or "Conseiller CoopIA",
            subtitle=subtitle,
            ui_color_tag=ui_color,
            created_at=session_time,
        )

    # 2. Si aucune session de chat, chercher dans la table activities
    act_row = await conn.fetchrow(
        """
        SELECT id, user_id, type, reference_id, title, subtitle, ui_color_tag, created_at
        FROM activities
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        current_user.id
    )
    if act_row:
        return ActivityOut(
            id=act_row["id"],
            user_id=act_row["user_id"],
            session_id=None,
            type=str(act_row["type"]),
            reference_id=act_row["reference_id"],
            title=act_row["title"],
            subtitle=act_row["subtitle"],
            ui_color_tag=act_row["ui_color_tag"],
            created_at=act_row["created_at"],
        )

    # Aucune activite pour ce producteur : renvoyer None pour afficher la carte d'accueil de bienvenue propre
    return None
@router.get("/", response_model=list[ActivityOut])
async def get_activities(
    current_user: UserOut = Depends(get_current_user),
    conn: Connection = Depends(get_db_connection),
):
    """
    Renvoie les 20 dernières activités de l'utilisateur connecté.
    """
    rows = await conn.fetch(
        """
        SELECT id, user_id, type, reference_id, title, subtitle, ui_color_tag, created_at
        FROM activities
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT 20
        """,
        current_user.id
    )
    return [dict(r) for r in rows]
