"""
Script de validation pour la calibration multi-cultures (Cacao, Café, Hévéa, Vivrier) et le calcul automatique du revenu en FCFA.
1. Planteur Cacao (Seke Darel, Bodokro) :
   - "🤝 Demander un prix" -> Tarif CCC Cacao 1 850 FCFA/kg (92 500 FCFA/sac).
   - "J'ai récolté 10 sacs prêts" -> 500 kg x 1 850 = 925 000 FCFA (CCC Cacao).
2. Planteur Café (Yao N'Guessan, Man) :
   - "🤝 Demander un prix" -> Détection profil Café -> Tarif CCC Café 1 000 FCFA/kg (50 000 FCFA/sac).
   - "J'ai récolté 10 sacs de café" -> 500 kg x 1 000 = 500 000 FCFA (CCC Café).
3. Nettoyage des données de test.
"""

import asyncio
import sys
import time
from datetime import timedelta
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.main import app
from app.core.database import get_pool, close_pool
from app.core.security import create_access_token

async def run_ccc_tests():
    print("=" * 70)
    print("🇨🇮 PROTOCOLE DE VALIDATION — CALIBRATION MULTI-FILIÈRES & REVENU EN FCFA")
    print("=" * 70)

    pool = await get_pool()
    created_sessions = []
    created_recoltes = []

    try:
        async with pool.acquire() as conn:
            seke = await conn.fetchrow("SELECT id, phone_number, first_name, last_name FROM users WHERE phone_number = '+225565697263'")
            yao = await conn.fetchrow("SELECT id, phone_number, first_name, last_name FROM users WHERE phone_number = '+2250700000003'")
            
            assert seke is not None, "Utilisateur Seke Darel introuvable !"
            assert yao is not None, "Utilisateur Yao N'Guessan introuvable !"
            
            seke_id = str(seke["id"])
            yao_id = str(yao["id"])
            print(f"✅ Planteur Cacao : Seke Darel ({seke_id})")
            print(f"✅ Planteur Café  : Yao N'Guessan ({yao_id})")

        seke_token = create_access_token(seke_id, timedelta(days=1))
        yao_token = create_access_token(yao_id, timedelta(days=1))

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

            # -------------------------------------------------------------
            # TEST 1 : Planteur Cacao (Seke Darel) - Prix officiel CCC Cacao
            # -------------------------------------------------------------
            print("\n--- TEST 1 : Planteur Cacao (Seke Darel) — Demande de prix ---")
            t0 = time.perf_counter()
            resp1 = await client.post(
                "/api/v1/chat/message",
                json={"text": "🤝 Demander un prix", "session_id": None},
                headers={"Authorization": f"Bearer {seke_token}"},
                timeout=30.0
            )
            lat1 = (time.perf_counter() - t0) * 1000
            assert resp1.status_code == 200, f"Erreur chat/message: {resp1.status_code} {resp1.text}"
            data1 = resp1.json()
            created_sessions.append(data1["session_id"])

            agent_text1 = data1["agent_message"]["text"]
            print(f"Status Code : 200 (Latence : {lat1:.1f}ms)")
            print(f"Réponse CoopIA (Cacao) :\n{agent_text1[:250]}...")

            has_1850 = "1 850" in agent_text1 or "1850" in agent_text1
            print(f"-> Mention du tarif Cacao (1 850 FCFA/kg) : {'✅ PASS' if has_1850 else '❌ FAIL'}")
            assert has_1850, "Le tarif de 1 850 FCFA/kg n'a pas été mentionné pour le cacao !"

            # -------------------------------------------------------------
            # TEST 2 : Planteur Café (Yao N'Guessan) - Prix officiel CCC Café
            # -------------------------------------------------------------
            print("\n--- TEST 2 : Planteur Café (Yao N'Guessan) — Demande de prix contextualisée ---")
            t0 = time.perf_counter()
            resp2 = await client.post(
                "/api/v1/chat/message",
                json={"text": "🤝 Demander un prix", "session_id": None},
                headers={"Authorization": f"Bearer {yao_token}"},
                timeout=30.0
            )
            lat2 = (time.perf_counter() - t0) * 1000
            assert resp2.status_code == 200, f"Erreur chat/message: {resp2.status_code} {resp2.text}"
            data2 = resp2.json()
            created_sessions.append(data2["session_id"])

            agent_text2 = data2["agent_message"]["text"]
            print(f"Status Code : 200 (Latence : {lat2:.1f}ms)")
            print(f"Réponse CoopIA (Café) :\n{agent_text2[:250]}...")

            has_1000 = "1 000" in agent_text2 or "1000" in agent_text2
            has_cafe = "café" in agent_text2.lower() or "cafe" in agent_text2.lower()
            print(f"-> Détection culture Café & Mention tarif (1 000 FCFA/kg) : {'✅ PASS' if has_1000 and has_cafe else '❌ FAIL'}")
            assert has_1000, "Le tarif de 1 000 FCFA/kg n'a pas été mentionné pour le café !"

            # -------------------------------------------------------------
            # TEST 3 : Déclaration Récolte Cacao (10 sacs = 500 kg x 1850 = 925 000 FCFA)
            # -------------------------------------------------------------
            print("\n--- TEST 3 : Déclaration Récolte Cacao (10 sacs) ---")
            resp3 = await client.post(
                "/api/v1/chat/message",
                json={"text": "J'ai récolté 10 sacs de cacao prêts pour la pesée", "session_id": None},
                headers={"Authorization": f"Bearer {seke_token}"},
                timeout=30.0
            )
            assert resp3.status_code == 200
            data3 = resp3.json()
            created_sessions.append(data3["session_id"])
            print(f"Réponse CoopIA récolte Cacao :\n{data3['agent_message']['text'][:200]}...")

            async with pool.acquire() as conn:
                act_cacao = await conn.fetchrow(
                    "SELECT subtitle, reference_id FROM activities WHERE user_id = $1 AND type = 'HARVEST_LOG' ORDER BY created_at DESC LIMIT 1",
                    seke["id"]
                )
                assert act_cacao is not None
                created_recoltes.append(act_cacao["reference_id"])
                print(f"Sous-titre Cacao : {act_cacao['subtitle']}")
                assert "925 000" in act_cacao["subtitle"]
                assert "CCC Cacao" in act_cacao["subtitle"]
                print("-> Sous-titre Cacao validé : ✅ PASS")

            # -------------------------------------------------------------
            # TEST 4 : Déclaration Récolte Café (10 sacs = 500 kg x 1000 = 500 000 FCFA)
            # -------------------------------------------------------------
            print("\n--- TEST 4 : Déclaration Récolte Café (10 sacs) ---")
            resp4 = await client.post(
                "/api/v1/chat/message",
                json={"text": "J'ai récolté 10 sacs de café prêts pour la pesée", "session_id": None},
                headers={"Authorization": f"Bearer {yao_token}"},
                timeout=30.0
            )
            assert resp4.status_code == 200
            data4 = resp4.json()
            created_sessions.append(data4["session_id"])
            print(f"Réponse CoopIA récolte Café :\n{data4['agent_message']['text'][:200]}...")

            async with pool.acquire() as conn:
                act_cafe = await conn.fetchrow(
                    "SELECT subtitle, reference_id FROM activities WHERE user_id = $1 AND type = 'HARVEST_LOG' ORDER BY created_at DESC LIMIT 1",
                    yao["id"]
                )
                assert act_cafe is not None
                created_recoltes.append(act_cafe["reference_id"])
                print(f"Sous-titre Café : {act_cafe['subtitle']}")
                assert "500 000" in act_cafe["subtitle"]
                assert "CCC Café" in act_cafe["subtitle"]
                print("-> Sous-titre Café validé : ✅ PASS")

        print("\n" + "=" * 70)
        print("🎉 TOUS LES TESTS MULTI-FILIÈRES ONT RÉUSSI AVEC SUCCÈS (100% SUCCÈS) !")
        print("=" * 70)

    finally:
        print("\n🧹 Nettoyage des données de test...")
        async with pool.acquire() as conn:
            for s_id in created_sessions:
                await conn.execute("DELETE FROM chat_messages WHERE session_id = $1", s_id)
                await conn.execute("DELETE FROM chat_sessions WHERE id = $1", s_id)
            for r_id in created_recoltes:
                await conn.execute("DELETE FROM activities WHERE reference_id = $1", r_id)
                await conn.execute("DELETE FROM recoltes WHERE id = $1", r_id)
        print("✅ Nettoyage terminé.")
        await close_pool()

if __name__ == "__main__":
    asyncio.run(run_ccc_tests())
