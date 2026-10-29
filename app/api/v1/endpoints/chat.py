from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
import asyncpg
from uuid import uuid4, UUID
from datetime import datetime, timezone
import json

from app.core.database import get_db_connection, get_pool
from app.core.security import get_current_user
from app.models.schemas import (
    UserOut,
    ChatMessageInput,
    ChatSessionResponse,
    ChatMessageResponse,
    ChatSendResponse,
)
from app.services.deepseek_service import generate_coopia_response, LLMUnavailableError
from app.services.transcription_service import transcribe_audio_with_gemini, TranscriptionUnavailableError
from app.core.pricing import get_crop_pricing

router = APIRouter()

@router.post("/message", response_model=ChatSendResponse)
async def send_message(
    data: ChatMessageInput,
    current_user: UserOut = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_pool),
):
    text = data.text.strip()
    session_id = data.session_id
    now = datetime.now(timezone.utc)
    user_msg_id = uuid4()
    history = []

    # Phase A: Vérification session, chargement contexte et insertion message utilisateur
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Création de session si nouvelle
            if not session_id:
                session_id = uuid4()
                title = text[:30] + "..." if len(text) > 30 else text
                await conn.execute(
                    """
                    INSERT INTO chat_sessions (id, user_id, title, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    session_id, current_user.id, title, now, now
                )
            else:
                # Vérification de la session
                session = await conn.fetchrow(
                    "SELECT id FROM chat_sessions WHERE id = $1 AND user_id = $2",
                    session_id, current_user.id
                )
                if not session:
                    raise HTTPException(status_code=404, detail="Session non trouvée ou non autorisée")

            # Chargement de l'historique AVANT l'insertion du message actuel
            rows = await conn.fetch(
                """
                SELECT text, is_user
                FROM chat_messages
                WHERE session_id = $1 
                  AND text != 'Ceci est une réponse simulée de l''assistant CoopIA.'
                  AND text NOT LIKE 'Ceci est une réponse simulée à : %'
                ORDER BY created_at DESC
                LIMIT 10
                """,
                session_id
            )
            history = list(reversed(rows))

            # Sauvegarde du message utilisateur
            await conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, text, is_user, created_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                user_msg_id, session_id, text, True, now
            )

    user_name = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or "Parent producteur"
    user_context = {
        "name": user_name,
        "village": current_user.village or "Côte d'Ivoire",
        "culture": current_user.culture or "cacao",
    }

    # Appel au LLM en dehors de la transaction et de la connexion poolée
    try:
        llm_response = await generate_coopia_response(history, text, user_context=user_context)
    except LLMUnavailableError as e:
        raise HTTPException(status_code=503, detail="Le service IA est momentanément indisponible.")

    agent_msg_id = uuid4()
    agent_now = datetime.now(timezone.utc)
    recommendations_json = json.dumps(llm_response.recommendations)

    # Phase B: Insertion de la réponse de l'agent & Enregistrement automatique de la récolte
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, text, is_user, created_at, recommendations)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                agent_msg_id, session_id, llm_response.reponse_texte, False, agent_now, recommendations_json
            )
            await conn.execute(
                "UPDATE chat_sessions SET updated_at = $1 WHERE id = $2",
                agent_now, session_id
            )

            # Détection et enregistrement de récolte (Commerce conversationnel)
            action_recolte = getattr(llm_response, "action_recolte", None)
            if action_recolte and getattr(action_recolte, "est_declaration", False):
                parcelle = await conn.fetchrow(
                    "SELECT id, name, village, crop_type FROM parcelles WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
                    current_user.id
                )
                parcelle_id = parcelle["id"] if parcelle else None
                parcelle_crop = (parcelle["crop_type"] if parcelle and parcelle["crop_type"] else current_user.culture or "cacao").lower()

                sacs = action_recolte.nombre_sacs or 0
                poids = action_recolte.poids_kg
                if not poids and sacs:
                    poids = float(sacs * 50)
                elif not sacs and poids:
                    sacs = max(1, int(round(poids / 50)))
                poids = float(poids or 0.0)

                # Récupération de la tarification officielle via le module centralisé
                crop_info = get_crop_pricing(parcelle_crop)
                crop_type = crop_info["key"]
                unit_price_fcfa = crop_info["price_kg"]
                label_tarif = crop_info["label"]

                if action_recolte.montant_estime_fcfa:
                    revenu_garanti_fcfa = int(action_recolte.montant_estime_fcfa)
                elif unit_price_fcfa > 0:
                    revenu_garanti_fcfa = int(round(poids * unit_price_fcfa))
                else:
                    revenu_garanti_fcfa = 0

                recolte_id = uuid4()
                bordereau_ref = f"BDR-2026-{uuid4().hex[:6].upper()}"

                await conn.execute(
                    """
                    INSERT INTO recoltes (
                        id, parcelle_id, user_id, weight_kg, number_of_bags, 
                        bordereau_ref, status, harvest_date, created_at,
                        crop_type, unit_price_fcfa, valeur_totale_fcfa
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7::validation_status, $8, $9, $10, $11, $12)
                    """,
                    recolte_id,
                    parcelle_id,
                    current_user.id,
                    poids,
                    sacs,
                    bordereau_ref,
                    "PENDING",
                    agent_now,
                    agent_now,
                    crop_type,
                    unit_price_fcfa,
                    revenu_garanti_fcfa,
                )

                # Insertion dans activities avec montant adapté
                act_id = uuid4()
                titre_act = f"Récolte déclarée : {sacs} sacs" if sacs > 0 else f"Récolte déclarée : {poids:g} kg"
                if revenu_garanti_fcfa:
                    revenu_formatte = f"{revenu_garanti_fcfa:,}".replace(",", " ")
                    sous_titre_act = f"{poids:g} kg • {revenu_formatte} FCFA ({label_tarif}) • BDR #{bordereau_ref}"
                else:
                    sous_titre_act = f"{poids:g} kg • {label_tarif} • BDR #{bordereau_ref}"

                await conn.execute(
                    """
                    INSERT INTO activities (id, user_id, type, reference_id, title, subtitle, ui_color_tag, created_at)
                    VALUES ($1, $2, $3::activity_type, $4, $5, $6, $7, $8)
                    """,
                    act_id,
                    current_user.id,
                    "HARVEST_LOG",
                    recolte_id,
                    titre_act,
                    sous_titre_act,
                    "success",
                    agent_now
                )

    return ChatSendResponse(
        session_id=session_id,
        user_message=ChatMessageResponse(
            id=user_msg_id,
            session_id=session_id,
            text=text,
            is_user=True,
            created_at=now,
            recommendations=None
        ),
        agent_message=ChatMessageResponse(
            id=agent_msg_id,
            session_id=session_id,
            text=llm_response.reponse_texte,
            is_user=False,
            created_at=agent_now,
            recommendations=llm_response.recommendations
        )
    )

@router.get("/sessions", response_model=list[ChatSessionResponse])
async def get_sessions(
    current_user: UserOut = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db_connection),
):
    """
    Récupère la liste des sessions de chat de l'utilisateur connecté,
    enrichie des métadonnées pour l'affichage de l'historique mobile.
    """
    rows = await conn.fetch(
        """
        SELECT 
            cs.id,
            cs.user_id,
            cs.title,
            cs.status::text AS db_status,
            cs.created_at,
            cs.updated_at,
            COUNT(cm.id) AS message_count,
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
        """,
        current_user.id
    )

    sessions: list[ChatSessionResponse] = []
    for r in rows:
        last_text = r["last_message_text"]
        subtitle = None
        if last_text:
            if last_text.startswith("[IMAGE]"):
                subtitle = "📸 Diagnostic photo analysé"
            else:
                clean_text = " ".join(last_text.strip().split())
                subtitle = (clean_text[:110] + "...") if len(clean_text) > 110 else clean_text

        # Détermination du statut UI contextuel
        is_harvest = bool(r["is_harvest_session"])
        is_disease = bool(r["is_disease_session"])
        db_status = r["db_status"]

        if is_harvest:
            ui_status = "Validé"
        elif is_disease:
            ui_status = "Action requise"
        elif db_status == "ARCHIVED":
            ui_status = "Terminé"
        else:
            ui_status = "Actif"

        title = r["title"]
        if not title:
            if subtitle:
                title = (subtitle[:30] + "...") if len(subtitle) > 30 else subtitle
            else:
                title = "Session CoopIA"

        sessions.append(
            ChatSessionResponse(
                id=r["id"],
                user_id=r["user_id"],
                title=title,
                subtitle=subtitle,
                sous_titre=subtitle,
                status=ui_status,
                statut=ui_status,
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                message_count=r["message_count"] or 0,
            )
        )

    return sessions


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
async def get_messages(
    session_id: UUID,
    current_user: UserOut = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db_connection),
):
    """
    Récupère la liste ordonnée des messages d'une session,
    avec contrôle d'accès strict (Anti-IDOR) et désérialisation JSONB.
    """
    # 1. Sécurité Anti-IDOR : Vérification stricte de l'appartenance de la session
    session = await conn.fetchrow(
        "SELECT id FROM chat_sessions WHERE id = $1 AND user_id = $2",
        session_id, current_user.id
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session non trouvée ou non autorisée")

    # 2. Récupération des messages ordonnés chronologiquement
    rows = await conn.fetch(
        """
        SELECT id, session_id, text, is_user, created_at, recommendations, media_url
        FROM chat_messages
        WHERE session_id = $1
        ORDER BY created_at ASC
        """,
        session_id
    )
    
    result: list[dict] = []
    for r in rows:
        d = dict(r)
        recs = d.get("recommendations")
        if recs and isinstance(recs, str):
            try:
                d["recommendations"] = json.loads(recs)
            except (json.JSONDecodeError, TypeError):
                d["recommendations"] = []
        elif not recs:
            d["recommendations"] = None
        result.append(d)
        
    return result


@router.delete("/sessions")
async def clear_chat_sessions(
    current_user: UserOut = Depends(get_current_user),
    conn: asyncpg.Connection = Depends(get_db_connection),
):
    """
    Suppression transactionnelle des messages et sessions du planteur connecté UNIQUEMENT.
    Isolation multi-tenant et Anti-IDOR garanties : les sessions des autres planteurs ne sont jamais impactées.
    """
    async with conn.transaction():
        # 1. Suppression des messages liés aux sessions de l'utilisateur
        await conn.execute(
            """
            DELETE FROM chat_messages 
            WHERE session_id IN (SELECT id FROM chat_sessions WHERE user_id = $1)
            """,
            current_user.id,
        )
        # 2. Suppression des sessions de l'utilisateur
        await conn.execute(
            "DELETE FROM chat_sessions WHERE user_id = $1",
            current_user.id,
        )

    return {
        "success": True,
        "message": "Historique des conversations supprimé avec succès.",
    }



@router.post("/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    current_user: UserOut = Depends(get_current_user),
):
    """
    Transcrit un message vocal envoyé par le planteur connecté.
    Accepte multipart/form-data avec le champ 'file'.
    Retourne { "text": "...", "success": True }.
    """
    if not file:
        raise HTTPException(status_code=400, detail="Aucun fichier audio fourni.")

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier audio trop volumineux (max 15 Mo).")

    mime_type = file.content_type or "audio/mp4"
    try:
        text = await transcribe_audio_with_gemini(content, mime_type=mime_type)
        return {
            "text": text,
            "success": True,
        }
    except TranscriptionUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de transcription audio: {str(e)}")
