import asyncio
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from app.core.database import get_pool, close_pool

async def main():
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT id, phone_number, first_name, last_name FROM users WHERE phone_number = '+225556255495'")
        print("USER:", dict(user) if user else None)
        if user:
            uid = user["id"]
            sessions = await conn.fetch("SELECT id, title, created_at FROM chat_sessions WHERE user_id = $1", uid)
            print(f"SESSIONS ({len(sessions)}):")
            for s in sessions:
                print("  ", dict(s))
            acts = await conn.fetch("SELECT id, type, title, subtitle, created_at FROM activities WHERE user_id = $1 ORDER BY created_at DESC", uid)
            print(f"ACTIVITIES ({len(acts)}):")
            for a in acts:
                print("  ", dict(a))
            recoltes = await conn.fetch("SELECT id, weight_kg, number_of_bags, bordereau_ref, status FROM recoltes WHERE user_id = $1", uid)
            print(f"RECOLTES ({len(recoltes)}):")
            for r in recoltes:
                print("  ", dict(r))
    await close_pool()

if __name__ == "__main__":
    asyncio.run(main())
