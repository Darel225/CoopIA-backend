from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from asyncpg import Connection

from app.core.database import get_db_connection
from app.core.security import get_current_user
from app.models.schemas import (
    UpdateProfileInput,
    ProfileSetupInput,
    UserOut,
    AvatarUploadResponse,
)
from app.services.vision_service import upload_avatar_to_cloudinary

router = APIRouter()


# ============================================================
# POST /avatar — Téléversement de la photo de profil (Avatar)
# ============================================================
@router.post("/avatar", response_model=AvatarUploadResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: UserOut = Depends(get_current_user),
    conn: Connection = Depends(get_db_connection),
):
    """
    Téléverse et persiste la photo de profil de l'utilisateur connecté sur Cloudinary.
    - Valide les types MIME (JPEG, PNG, WebP) et la taille max (5 Mo).
    - Valide les magic bytes du fichier.
    - Téléverse vers Cloudinary dans coopia/avatars/{user_id} avec écrasement automatique.
    - Persiste l'avatar_url dans la base PostgreSQL Neon.
    """
    # 1. Validation Content-Type déclaré
    allowed_types = ["image/jpeg", "image/png", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Format d'image non supporté ({file.content_type}). Formats acceptés : JPEG, PNG, WebP.",
        )

    # 2. Validation de taille (max 5 Mo)
    max_mb = 5
    max_bytes = max_mb * 1024 * 1024
    file_bytes = await file.read(max_bytes + 1)

    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le fichier image est vide.")

    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"L'image dépasse la taille maximale autorisée de {max_mb} Mo.",
        )

    # 3. Validation de contenu réel par Magic Bytes
    detected_mime = None
    if file_bytes.startswith(b"\xff\xd8"):
        detected_mime = "image/jpeg"
    elif file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        detected_mime = "image/png"
    elif file_bytes.startswith(b"RIFF") and len(file_bytes) >= 12 and file_bytes[8:12] == b"WEBP":
        detected_mime = "image/webp"

    if not detected_mime:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Le contenu du fichier n'est pas une image valide (signature binaire invalide).",
        )

    # 4. Téléversement Cloudinary sécurisé
    try:
        secure_url = await upload_avatar_to_cloudinary(file_bytes, str(current_user.id))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erreur lors de l'enregistrement de l'avatar sur Cloudinary : {str(exc)}",
        )

    # 5. Persistance dans PostgreSQL Neon
    updated_url = await conn.fetchval(
        """
        UPDATE users
        SET avatar_url = $1
        WHERE id = $2
        RETURNING avatar_url
        """,
        secure_url,
        current_user.id,
    )

    return AvatarUploadResponse(
        success=True,
        avatar_url=updated_url or secure_url,
        message="Photo de profil mise à jour avec succès.",
    )


# ============================================================
# POST /setup — Onboarding : profil + première parcelle
# ============================================================
@router.post("/setup")
async def setup_profile(
    data: ProfileSetupInput,
    current_user: UserOut = Depends(get_current_user),
    conn: Connection = Depends(get_db_connection),
):
    """
    Complète le profil de l'agriculteur (prénom / nom) et crée
    automatiquement sa première parcelle ("Parcelle Principale").
    """
    nom_complet = data.nom_complet.strip()
    village = data.village.strip()
    culture = data.culture_principale.strip()

    if not nom_complet:
        raise HTTPException(status_code=422, detail="Le nom complet est requis.")

    parts = nom_complet.split(" ", 1)
    first_name = parts[0]
    last_name = parts[1].strip() if len(parts) > 1 else ""

    async with conn.transaction():
        user_record = await conn.fetchrow(
            """
            WITH updated AS (
                UPDATE users 
                SET first_name = $1, last_name = $2,
                    cooperative_id = COALESCE(cooperative_id, (SELECT id FROM cooperatives WHERE code = 'CAPED'))
                WHERE id = $3
                RETURNING id, phone_number, first_name, last_name, cooperative_id, role, avatar_url, created_at
            )
            SELECT updated.*, c.name AS cooperative_name
            FROM updated
            LEFT JOIN cooperatives c ON updated.cooperative_id = c.id
            """,
            first_name,
            last_name,
            current_user.id,
        )
        if user_record is None:
            raise HTTPException(status_code=404, detail="Utilisateur introuvable.")

        await conn.execute(
            """
            INSERT INTO parcelles (user_id, name, crop_type, village, superficie)
            VALUES ($1, $2, $3, $4, $5)
            """,
            current_user.id,
            "Parcelle Principale",
            culture,
            village,
            data.superficie,
        )

    return {
        "success": True,
        "message": "Profil configuré avec succès.",
        "user": {
            "id": str(user_record["id"]),
            "phone_number": user_record["phone_number"],
            "first_name": user_record["first_name"],
            "last_name": user_record["last_name"],
            "cooperative_id": str(user_record["cooperative_id"]) if user_record["cooperative_id"] else None,
            "cooperative_name": user_record["cooperative_name"],
            "role": user_record["role"],
            "avatar_url": user_record["avatar_url"],
        },
    }


# ============================================================
# GET /me
# ============================================================
@router.get("/me")
async def get_my_profile(current_user: UserOut = Depends(get_current_user)):
    """Récupère le profil complet de l'utilisateur connecté."""
    requires_profile_setup = True if not current_user.first_name or not str(current_user.first_name).strip() else False
    return {
        "user": current_user,
        "requires_profile_setup": requires_profile_setup,
    }


# ============================================================
# POST /update-profile
# ============================================================
@router.post("/update-profile")
async def update_profile(
    data: UpdateProfileInput,
    current_user: UserOut = Depends(get_current_user),
    conn: Connection = Depends(get_db_connection),
):
    """
    Met à jour le profil de l'utilisateur connecté (first_name, last_name).
    """
    first_name = data.first_name or data.prenom
    last_name = data.last_name or data.nom

    user = await conn.fetchrow(
        """
        WITH updated AS (
            UPDATE users
            SET
                first_name = COALESCE(NULLIF($1, ''), first_name),
                last_name  = COALESCE(NULLIF($2, ''), last_name)
            WHERE id = $3
            RETURNING id, phone_number, first_name, last_name, cooperative_id, role, avatar_url, created_at
        )
        SELECT updated.*, c.name AS cooperative_name
        FROM updated
        LEFT JOIN cooperatives c ON updated.cooperative_id = c.id
        """,
        first_name,
        last_name,
        current_user.id,
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Utilisateur non trouvé.",
        )

    return {
        "success": True,
        "message": "Profil mis à jour avec succès.",
        "user": {
            "id": str(user["id"]),
            "phone_number": user["phone_number"],
            "first_name": user["first_name"],
            "last_name": user["last_name"],
            "cooperative_id": str(user["cooperative_id"]) if user["cooperative_id"] else None,
            "cooperative_name": user["cooperative_name"],
            "role": user["role"],
            "avatar_url": user["avatar_url"],
        },
    }
