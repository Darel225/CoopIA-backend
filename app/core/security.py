import os
import jwt
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from asyncpg import Connection

from app.core.database import get_db_connection
from app.models.schemas import UserOut

security_bearer = HTTPBearer()

ALGORITHM = "HS256"

from app.core.config import settings

def get_secret_key() -> str:
    secret = settings.JWT_SECRET_KEY
    if not secret:
        raise ValueError("JWT_SECRET_KEY n'est pas configuré dans l'environnement.")
    return secret

def create_access_token(user_id: str, expires_delta: timedelta) -> str:
    """Crée un token JWT signé."""
    to_encode = {"sub": user_id}
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    
    encoded_jwt = jwt.encode(to_encode, get_secret_key(), algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_bearer),
    conn: Connection = Depends(get_db_connection)
) -> UserOut:
    """Décode le token JWT et récupère l'utilisateur depuis Neon."""
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = UUID(user_id_str)
    except (jwt.PyJWTError, ValueError):
        raise credentials_exception

    # Récupération de l'utilisateur complet en BD avec sa coopérative et parcelle principale
    user_record = await conn.fetchrow(
        """
        SELECT u.id, u.phone_number, u.first_name, u.last_name, u.cooperative_id, u.role, u.avatar_url, u.created_at,
               c.name AS cooperative_name,
               p.village, p.crop_type as culture
        FROM users u
        LEFT JOIN cooperatives c ON u.cooperative_id = c.id
        LEFT JOIN parcelles p ON p.user_id = u.id
        WHERE u.id = $1
        ORDER BY p.created_at DESC
        LIMIT 1
        """,
        user_id
    )

    if user_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur introuvable.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UserOut(**dict(user_record))


async def require_coop_admin(
    current_user: UserOut = Depends(get_current_user)
) -> UserOut:
    """
    Vérifie strictement que l'utilisateur connecté possède le rôle COOP_ADMIN
    et est associé à une coopérative existante.
    """
    if current_user.role != "COOP_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé. Cette section est réservée aux administrateurs de la coopérative.",
        )
    if not current_user.cooperative_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="L'utilisateur administrateur n'est rattaché à aucune coopérative.",
        )
    return current_user


async def require_planter(
    current_user: UserOut = Depends(get_current_user)
) -> UserOut:
    """Vérifie que l'utilisateur est un PLANTER."""
    if current_user.role != "PLANTER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux planteurs.",
        )
    return current_user

