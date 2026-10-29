import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

async def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("❌ La variable d'environnement DATABASE_URL est manquante.")

    print("🔌 Test de connexion à la base de données Neon...")
    
    try:
        conn = await asyncpg.connect(database_url)
        # Simple test de connectivité
        result = await conn.fetchval("SELECT 1")
        if result == 1:
            print("✅ Connexion réussie ! Le schéma de la base est prêt.")
        else:
            print("⚠️ Connexion établie, mais la requête de test a échoué.")
    except Exception as e:
        print(f"❌ Erreur lors de la connexion à la base de données : {e}")
        raise
    finally:
        if 'conn' in locals() and not conn.is_closed():
            await conn.close()
            print("🔌 Connexion fermée.")

if __name__ == "__main__":
    asyncio.run(main())
