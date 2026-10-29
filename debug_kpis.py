import asyncio
import asyncpg
import traceback
from app.api.v1.endpoints.cooperative import get_cooperative_kpis
from app.models.schemas import UserOut
from uuid import UUID

DATABASE_URL = "postgresql://neondb_owner:npg_EUky3sg1raoY@ep-tiny-shadow-b20di0sq-pooler.c-6.eu-central-1.aws.neon.tech/neondb?sslmode=require"

async def test():
    conn = await asyncpg.connect(DATABASE_URL)
    admin = UserOut(
        id=UUID('1a1580be-8ed0-4e77-b359-91f0763d24d1'),
        phone_number='+2250000000000',
        role='COOP_ADMIN',
        cooperative_id=UUID('6b0901f9-d797-4143-a9b7-d3641970eeba'),
        cooperative_name='Coopérative CAPED - Soubré',
    )
    try:
        res = await get_cooperative_kpis(admin=admin, conn=conn)
        print("SUCCESS! Total tonnage:", res.total_tonnage_tonnes)
        print("Ventilation villages:", len(res.ventilation_villages or []))
    except Exception as e:
        traceback.print_exc()
    finally:
        await conn.close()

asyncio.run(test())
