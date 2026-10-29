import asyncpg
from fastapi import Request
from app.core.config import settings

# Pool de connexions global
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Retourne le pool de connexions, en le créant si nécessaire."""
    global _pool
    if _pool is None:
        database_url = settings.DATABASE_URL
        if not database_url:
            raise ValueError("DATABASE_URL non définie dans l'environnement.")
            
        _pool = await asyncpg.create_pool(
            dsn=database_url,
            min_size=2,
            max_size=10,
            command_timeout=15.0,
            max_inactive_connection_lifetime=60.0,
            # Neon requiert un SSL activé
            ssl="require" if "sslmode=require" in database_url else None
        )
    return _pool


async def close_pool():
    """Ferme proprement le pool à l'arrêt de l'application."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def get_db_connection(request: Request):
    """Dépendance FastAPI pour obtenir une connexion à la BD depuis le pool."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn
