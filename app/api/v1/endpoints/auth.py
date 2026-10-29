from pydantic import BaseModel
import secrets
import string
import hashlib
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import os

from fastapi import APIRouter, HTTPException, Depends
from asyncpg import Connection

from app.core.database import get_db_connection
from app.core.security import create_access_token, get_current_user
from app.core.config import settings
from app.models.schemas import RequestOTPInput, VerifyOTPInput, TokenResponse, UserOut

router = APIRouter()

# ── Stockage temporaire des OTP en mémoire ──────────────────────────────────
# Format: { phone_number: {"hash": str, "expires_at": datetime, "attempts": int} }
_otp_store = defaultdict(lambda: {"hash": None, "expires_at": None, "attempts": 0})
MAX_OTP_ATTEMPTS = 5

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)

def _generate_otp() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(6))

def _hash_otp(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


# ============================================================
# POST /auth/request-otp
# ============================================================
@router.post("/request-otp")
async def request_otp(data: RequestOTPInput):
    """Génère un OTP haché stocké en mémoire pour 5 minutes."""
    phone = data.phone_number
    otp = _generate_otp()
    
    # Stockage du hash (jamais le code en clair)
    _otp_store[phone] = {
        "hash": _hash_otp(otp),
        "expires_at": _utcnow() + timedelta(minutes=5),
        "attempts": 0
    }

    return {
        "success": True,
        "message": "Code généré avec succès.",
        "code": otp
    }


# ============================================================
# POST /auth/verify-otp
# ============================================================
@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(data: VerifyOTPInput, conn: Connection = Depends(get_db_connection)):
    """Vérifie l'OTP, insère/met à jour l'utilisateur et retourne un JWT."""
    phone = data.phone_number
    record = _otp_store.get(phone)

    # 1. Vérifications préalables
    if not record or not record["hash"]:
        raise HTTPException(status_code=400, detail="Aucun code OTP demandé pour ce numéro.")
    
    if _utcnow() > record["expires_at"]:
        _otp_store.pop(phone, None)
        raise HTTPException(status_code=400, detail="Code OTP expiré. Veuillez en redemander un.")
    
    if record["attempts"] >= MAX_OTP_ATTEMPTS:
        _otp_store.pop(phone, None)
        raise HTTPException(status_code=429, detail="Trop de tentatives. Code invalidé.")

    # 2. Vérification cryptographique via digest comparison pour éviter le timing attack
    record["attempts"] += 1
    if not secrets.compare_digest(record["hash"], _hash_otp(data.code)):
        remaining = MAX_OTP_ATTEMPTS - record["attempts"]
        raise HTTPException(status_code=400, detail=f"Code invalide. {remaining} essai(s) restant(s).")

    # 3. Succès : Nettoyage immédiat pour garantir l'usage unique
    _otp_store.pop(phone, None)

    # 4. UPSERT en base de données de l'utilisateur avec jointure coopérative
    user = await conn.fetchrow(
        """
        WITH ins AS (
            INSERT INTO users (phone_number)
            VALUES ($1)
            ON CONFLICT (phone_number) DO UPDATE 
                SET phone_number = EXCLUDED.phone_number
            RETURNING id, phone_number, first_name, last_name, cooperative_id, role, avatar_url, created_at
        )
        SELECT 
            ins.*, 
            c.name AS cooperative_name
        FROM ins
        LEFT JOIN cooperatives c ON ins.cooperative_id = c.id
        """,
        phone
    )

    first_name = user["first_name"]
    requires_profile_setup = True if not first_name or not str(first_name).strip() else False

    parcelle = await conn.fetchrow(
        "SELECT village, crop_type FROM parcelles WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
        user["id"]
    )

    user_data = {
        "id": str(user["id"]),
        "phone_number": user["phone_number"],
        "first_name": user["first_name"],
        "last_name": user["last_name"],
        "cooperative_id": str(user["cooperative_id"]) if user["cooperative_id"] else None,
        "cooperative_name": user["cooperative_name"] if user["cooperative_name"] else ("Coopérative CAPED" if user["cooperative_id"] else None),
        "role": user["role"],
        "avatar_url": user["avatar_url"],
        "village": parcelle["village"] if parcelle else None,
        "culture": parcelle["crop_type"] if parcelle else None,
    }

    # 5. Génération du JWT
    token_expiry = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(user_id=str(user["id"]), expires_delta=token_expiry)

    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "requires_profile_setup": requires_profile_setup,
        "user": user_data
    }


# ============================================================
# GET /auth/me
# ============================================================
@router.get("/me")
async def get_my_profile(current_user: UserOut = Depends(get_current_user)):
    """Récupère le profil complet de l'utilisateur connecté depuis son JWT."""
    requires_profile_setup = True if not current_user.first_name or not str(current_user.first_name).strip() else False
    return {
        "user": current_user,
        "requires_profile_setup": requires_profile_setup
    }



# ============================================================
# POST /auth/admin-login (Connexion E-mail & Mot de passe Gérant)
# ============================================================
class AdminLoginInput(BaseModel):
    email: str
    password: str

@router.post("/admin-login")
async def admin_login(data: AdminLoginInput, conn: Connection = Depends(get_db_connection)):
    """Connexion sécurisée pour les gérants coopérative par email et mot de passe."""
    email = data.email.strip().lower()
    password = data.password.strip()

    ALLOWED_ADMINS = {
        "gerant@caped.ci": "CoopIA2026!",
        "admin@coopia.ci": "CoopIA2026!",
        "noel.koffi@caped.ci": "CoopIA2026!",
    }

    if email not in ALLOWED_ADMINS or ALLOWED_ADMINS[email] != password:
        raise HTTPException(
            status_code=401,
            detail="Adresse email ou mot de passe incorrect. Accès réservé à la gérance."
        )

    user = await conn.fetchrow(
        """
        SELECT 
            u.id, u.phone_number, u.first_name, u.last_name, u.cooperative_id, u.role, u.avatar_url,
            c.name AS cooperative_name
        FROM users u
        LEFT JOIN cooperatives c ON u.cooperative_id = c.id
        WHERE u.role = 'COOP_ADMIN'
        ORDER BY u.created_at ASC
        LIMIT 1
        """
    )

    if not user:
        raise HTTPException(status_code=404, detail="Compte administrateur introuvable en base.")

    token_expiry = timedelta(days=7)
    access_token = create_access_token(user_id=str(user["id"]), expires_delta=token_expiry)

    user_data = {
        "id": str(user["id"]),
        "phone_number": user["phone_number"],
        "first_name": user["first_name"] or "Noel",
        "last_name": user["last_name"] or "Koffi",
        "email": email,
        "cooperative_id": str(user["cooperative_id"]) if user["cooperative_id"] else None,
        "cooperative_name": user["cooperative_name"] or "Coopérative CAPED",
        "role": user["role"] or "COOP_ADMIN",
        "avatar_url": user["avatar_url"],
    }

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user_data
    }
