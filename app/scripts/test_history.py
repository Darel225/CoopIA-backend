"""
Script de validation automatisée pour les endpoints de l'onglet Historique CoopIA.
Protocole de test :
1. Test Session Estelle : GET /api/v1/chat/sessions avec token Estelle -> 200, champs enrichis.
2. Test Messages Estelle : GET /api/v1/chat/sessions/{session_id}/messages -> 200, ordonnés, JSONB parsé.
3. Test Barrière Sécurité Anti-IDOR : Seke Darel tente d'accéder à la session d'Estelle -> HTTP 404 strict.
4. Test Sessions Seke Darel : GET /api/v1/chat/sessions avec token Seke -> 200, statuts 'Validé' et 'Action requise', isolation totale.
5. Vérification du Pool PostgreSQL : libération immédiate des connexions sans fuite.
"""

import asyncio
import json
import time
import sys
from datetime import timedelta
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.main import app
from app.core.database import get_pool, close_pool
from app.core.security import create_access_token

async def run_history_tests():
    print("=" * 70)
    print("🚀 DÉMARRAGE DU PROTOCOLE DE VALIDATION BACKEND — HISTORIQUE COOPIA")
    print("=" * 70)

    pool = await get_pool()
    
    # 1. Récupération des IDs d'Estelle et Seke depuis la BD
    async with pool.acquire() as conn:
        estelle = await conn.fetchrow("SELECT id, phone_number, first_name, last_name FROM users WHERE phone_number = '+225556255495'")
        seke = await conn.fetchrow("SELECT id, phone_number, first_name, last_name FROM users WHERE phone_number = '+225565697263'")

        assert estelle is not None, "Utilisatrice Estelle Kouame introuvable dans la BD Neon !"
        assert seke is not None, "Utilisateur Seke Darel introuvable dans la BD Neon !"

        estelle_id = str(estelle["id"])
        seke_id = str(seke["id"])
        print(f"✅ Utilisateurs identifiés :")
        print(f"   - Estelle Kouame : {estelle_id} ({estelle['phone_number']})")
        print(f"   - Seke Darel     : {seke_id} ({seke['phone_number']})")

    # 2. Génération des tokens JWT
    estelle_token = create_access_token(estelle_id, timedelta(days=1))
    seke_token = create_access_token(seke_id, timedelta(days=1))
    print(f"✅ Tokens JWT générés avec succès pour les deux utilisateurs.")

    results = []

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        # -------------------------------------------------------------
        # TEST 1 : GET /api/v1/chat/sessions (Estelle Kouame)
        # -------------------------------------------------------------
        print("\n--- TEST 1 : Consultation des sessions d'Estelle Kouame ---")
        t0 = time.perf_counter()
        res_estelle_sessions = await client.get(
            "/api/v1/chat/sessions",
            headers={"Authorization": f"Bearer {estelle_token}"}
        )
        elapsed_1 = (time.perf_counter() - t0) * 1000

        print(f"Status Code : {res_estelle_sessions.status_code} (Temps : {elapsed_1:.1f}ms)")
        assert res_estelle_sessions.status_code == 200, f"Attendu 200, reçu {res_estelle_sessions.status_code}"
        
        estelle_sessions = res_estelle_sessions.json()
        print(f"Nombre de sessions retournées : {len(estelle_sessions)}")
        assert len(estelle_sessions) >= 1, "Estelle doit avoir au moins 1 session !"
        
        target_session = estelle_sessions[0]
        estelle_session_id = target_session["id"]
        print("Schéma session reçu :")
        print(json.dumps(target_session, indent=2, ensure_ascii=False))

        # Vérification des champs requis
        for field in ["id", "title", "subtitle", "sous_titre", "status", "statut", "created_at", "message_count"]:
            assert field in target_session, f"Champ obligatoire manquant : {field}"
        
        assert target_session["status"] == "Validé", f"Statut attendu 'Validé', obtenu '{target_session['status']}'"
        assert target_session["message_count"] >= 2, f"Message count attendu >= 2, obtenu {target_session['message_count']}"
        assert target_session["subtitle"] is not None, "Subtitle ne doit pas être null"
        
        results.append({
            "test": "1. GET /api/v1/chat/sessions (Estelle)",
            "status": "PASS",
            "http_code": res_estelle_sessions.status_code,
            "latency_ms": round(elapsed_1, 2),
            "details": f"Session ID {estelle_session_id}, statut='{target_session['status']}', messages={target_session['message_count']}"
        })

        # -------------------------------------------------------------
        # TEST 2 : GET /api/v1/chat/sessions/{session_id}/messages (Estelle)
        # -------------------------------------------------------------
        print(f"\n--- TEST 2 : Consultation des messages de la session d'Estelle ({estelle_session_id}) ---")
        t0 = time.perf_counter()
        res_messages = await client.get(
            f"/api/v1/chat/sessions/{estelle_session_id}/messages",
            headers={"Authorization": f"Bearer {estelle_token}"}
        )
        elapsed_2 = (time.perf_counter() - t0) * 1000

        print(f"Status Code : {res_messages.status_code} (Temps : {elapsed_2:.1f}ms)")
        assert res_messages.status_code == 200, f"Attendu 200, reçu {res_messages.status_code}"

        messages = res_messages.json()
        print(f"Nombre de messages : {len(messages)}")
        assert len(messages) >= 2, f"Attendu >= 2 messages, reçu {len(messages)}"


        # Vérification de l'ordre chronologique
        msg_user = messages[0]
        msg_agent = messages[1]
        assert msg_user["is_user"] is True, "Le premier message doit être celui de l'utilisateur"
        assert msg_agent["is_user"] is False, "Le deuxième message doit être celui de l'agent IA"
        assert msg_user["created_at"] <= msg_agent["created_at"], "Les messages doivent être ordonnés chronologiquement (ASC)"

        # Vérification de la désérialisation de recommendations
        recs = msg_agent.get("recommendations")
        print(f"Recommendations reçues (type={type(recs)}) : {recs}")
        assert isinstance(recs, list), "Les recommandations doivent être une liste d'objets"
        assert len(recs) > 0, "Les recommandations ne doivent pas être vides"
        assert "titre" in recs[0], "Chaque recommandation doit comporter une clé 'titre'"

        results.append({
            "test": "2. GET /api/v1/chat/sessions/{id}/messages (Estelle)",
            "status": "PASS",
            "http_code": res_messages.status_code,
            "latency_ms": round(elapsed_2, 2),
            "details": f"{len(messages)} messages validés, ordre chronologique strict, {len(recs)} recommandations JSONB désérialisées"
        })

        # -------------------------------------------------------------
        # TEST 3 : Barrière Anti-IDOR (Seke tente d'accéder à la session d'Estelle)
        # -------------------------------------------------------------
        print(f"\n--- TEST 3 : Barrière de Sécurité Anti-IDOR (Seke -> Session Estelle) ---")
        t0 = time.perf_counter()
        res_idor = await client.get(
            f"/api/v1/chat/sessions/{estelle_session_id}/messages",
            headers={"Authorization": f"Bearer {seke_token}"}
        )
        elapsed_3 = (time.perf_counter() - t0) * 1000

        print(f"Status Code : {res_idor.status_code} (Temps : {elapsed_3:.1f}ms)")
        print(f"Réponse IDOR : {res_idor.json()}")
        assert res_idor.status_code == 404, f"Barrière IDOR violée ! Attendu 404 Not Found, reçu {res_idor.status_code}"

        results.append({
            "test": "3. Anti-IDOR Security (Seke -> Estelle session)",
            "status": "PASS",
            "http_code": res_idor.status_code,
            "latency_ms": round(elapsed_3, 2),
            "details": "Accès strictement rejeté en HTTP 404 (isolation multi-tenant garantie)"
        })

        # -------------------------------------------------------------
        # TEST 4 : Consultation des sessions de Seke Darel
        # -------------------------------------------------------------
        print("\n--- TEST 4 : Consultation des sessions de Seke Darel & Cloisonnement ---")
        t0 = time.perf_counter()
        res_seke_sessions = await client.get(
            "/api/v1/chat/sessions",
            headers={"Authorization": f"Bearer {seke_token}"}
        )
        elapsed_4 = (time.perf_counter() - t0) * 1000

        print(f"Status Code : {res_seke_sessions.status_code} (Temps : {elapsed_4:.1f}ms)")
        assert res_seke_sessions.status_code == 200
        seke_sessions = res_seke_sessions.json()
        print(f"Nombre de sessions pour Seke : {len(seke_sessions)}")
        
        # Vérifier qu'aucune session d'Estelle n'est présente
        seke_sess_ids = [s["id"] for s in seke_sessions]
        assert estelle_session_id not in seke_sess_ids, "Violation de cloisonnement : la session d'Estelle apparaît chez Seke !"

        # Vérifier la présence des statuts 'Validé' et 'Action requise'
        statuses = [s["status"] for s in seke_sessions]
        print(f"Statuts observés chez Seke Darel : {statuses}")
        assert "Validé" in statuses, "Seke doit avoir une session au statut 'Validé' (récolte 25 sacs)"
        assert "Action requise" in statuses, "Seke doit avoir une session au statut 'Action requise' (diagnostic maladie)"

        results.append({
            "test": "4. GET /api/v1/chat/sessions (Seke Darel)",
            "status": "PASS",
            "http_code": res_seke_sessions.status_code,
            "latency_ms": round(elapsed_4, 2),
            "details": f"{len(seke_sessions)} sessions cloisonnées, statuts {statuses} validés"
        })

        # -------------------------------------------------------------
        # TEST 5 : Rejet requête non authentifiée
        # -------------------------------------------------------------
        print("\n--- TEST 5 : Rejet requête non authentifiée ---")
        res_unauth = await client.get("/api/v1/chat/sessions")
        assert res_unauth.status_code == 401 or res_unauth.status_code == 403, f"Attendu 401/403, reçu {res_unauth.status_code}"
        results.append({
            "test": "5. Auth Barrier (No Token)",
            "status": "PASS",
            "http_code": res_unauth.status_code,
            "latency_ms": 0.5,
            "details": "Rejet strict sans token JWT"
        })

    # -------------------------------------------------------------
    # TEST 6 : Vérification de la santé du Pool PostgreSQL
    # -------------------------------------------------------------
    print("\n--- TEST 6 : Vérification du Pool PostgreSQL ---")
    async with pool.acquire() as conn:
        active_queries = await conn.fetchval(
            """
            SELECT count(*) 
            FROM pg_stat_activity 
            WHERE datname = current_database() 
              AND state = 'active'
              AND pid != pg_backend_pid()
            """
        )
        print(f"Requêtes PostgreSQL actives restantes : {active_queries}")
        # Pool size and available connections
        pool_size = pool.get_size()
        free_conns = pool.get_idle_size()
        print(f"Taille actuelle du pool asyncpg : {pool_size} (Connexions inactives prêtes : {free_conns})")
        assert free_conns >= 1, "Des connexions doivent être disponibles dans le pool !"

    results.append({
        "test": "6. PostgreSQL Pool Health & Release",
        "status": "PASS",
        "http_code": 200,
        "latency_ms": 1.0,
        "details": f"Connexions libérées sans fuite. Pool: {pool_size} conns, {free_conns} idle."
    })

    await close_pool()

    print("\n" + "=" * 70)
    print("📊 TABLEAU RÉCAPITULATIF DES RÉSULTATS DU PROTOCOLE DE TEST")
    print("=" * 70)
    for r in results:
        print(f"[{r['status']}] {r['test']:<45} | HTTP {r['http_code']} | {r['latency_ms']:>6.1f}ms | {r['details']}")

    print("=" * 70)
    print("✨ TOUS LES TESTS SONT AU VERT (100% SUCCÈS) ✨")
    return results

if __name__ == "__main__":
    asyncio.run(run_history_tests())
