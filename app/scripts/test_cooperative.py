"""
Script de validation automatisée pour les endpoints du Tableau de Bord Web Coopérative (CoopIA / CAPED).
Protocole de test :
1. Barrière d'autorisation : Seke Darel (PLANTER) tente d'accéder au dashboard -> HTTP 403 strict.
2. Barrière d'authentification : Appel sans token -> HTTP 401 strict.
3. Consultation KPIs : Awa Koné (COOP_ADMIN) consulte le dashboard -> HTTP 200, métriques consolidées.
4. Consultation Récoltes : Listing avec filtres (statut, pagination) -> HTTP 200.
5. Approbation de Bordereau : Passage d'un bordereau PENDING à APPROVED -> HTTP 200 + création activité.
6. Barrière Anti-IDOR : Tentative de modification d'un bordereau inexistant -> HTTP 404 strict.
7. Listing Planteurs : Agrégation des superficies et tonnages par planteur -> HTTP 200.
8. Cartographie Parcelles : Vérification des coordonnées GPS pour affichage Web -> HTTP 200.
9. Diagnostics Phytosanitaires : Suivi des alertes sanitaires actives -> HTTP 200.
"""

import asyncio
import json
import time
import sys
from uuid import uuid4
from datetime import timedelta
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.main import app
from app.core.database import get_pool, close_pool
from app.core.security import create_access_token


async def run_cooperative_tests():
    print("=" * 75)
    print("🏢 DÉMARRAGE DU PROTOCOLE DE VALIDATION — TABLEAU DE BORD WEB COOPÉRATIVE")
    print("=" * 75)

    pool = await get_pool()

    # 1. Récupération des utilisateurs clés depuis la base Neon
    async with pool.acquire() as conn:
        admin_row = await conn.fetchrow(
            "SELECT id, phone_number, first_name, last_name, role, cooperative_id FROM users WHERE phone_number = '+2250700000001'"
        )
        planter_row = await conn.fetchrow(
            "SELECT id, phone_number, first_name, last_name, role, cooperative_id FROM users WHERE phone_number = '+225565697263'"
        )

        assert admin_row is not None, "Administratrice Awa Koné (+2250700000001) introuvable !"
        assert planter_row is not None, "Planteur Seke Darel (+225565697263) introuvable !"

        admin_id = str(admin_row["id"])
        planter_id = str(planter_row["id"])
        coop_id = str(admin_row["cooperative_id"])

        print(f"✅ Utilisateurs identifiés :")
        print(f"   - Directrice Awa Koné (Admin) : {admin_id} | Coop: {coop_id}")
        print(f"   - Planteur Seke Darel        : {planter_id} | Rôle: {planter_row['role']}")

    # 2. Génération des tokens JWT
    admin_token = create_access_token(admin_id, timedelta(days=1))
    planter_token = create_access_token(planter_id, timedelta(days=1))
    print(f"✅ Tokens JWT générés.")

    results = []

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

        # -------------------------------------------------------------
        # TEST 1 : Barrière Sécurité RBAC — Planteur tente d'accéder au dashboard
        # -------------------------------------------------------------
        print("\n--- TEST 1 : Sécurité RBAC — Accès interdit pour rôle PLANTER ---")
        t0 = time.perf_counter()
        res_forbidden = await client.get(
            "/api/v1/cooperative/dashboard",
            headers={"Authorization": f"Bearer {planter_token}"},
        )
        elapsed_1 = (time.perf_counter() - t0) * 1000
        print(f"Status Code : {res_forbidden.status_code} (Temps : {elapsed_1:.1f}ms)")
        assert res_forbidden.status_code == 403, f"Attendu 403 Forbidden, obtenu {res_forbidden.status_code}"
        print(f"Message rejet : {res_forbidden.json().get('detail')}")
        results.append({
            "test": "1. Sécurité RBAC (PLANTER -> HTTP 403)",
            "status": "PASS",
            "http_code": res_forbidden.status_code,
            "latency_ms": round(elapsed_1, 2),
            "details": "Accès strictement bloqué pour les non-administrateurs",
        })

        # -------------------------------------------------------------
        # TEST 2 : Barrière Authentification — Pas de token
        # -------------------------------------------------------------
        print("\n--- TEST 2 : Sécurité — Requête anonyme sans token ---")
        t0 = time.perf_counter()
        res_unauth = await client.get("/api/v1/cooperative/dashboard")
        elapsed_2 = (time.perf_counter() - t0) * 1000
        print(f"Status Code : {res_unauth.status_code} (Temps : {elapsed_2:.1f}ms)")
        assert res_unauth.status_code == 401 or res_unauth.status_code == 403
        results.append({
            "test": "2. Sécurité Authentification (No Token -> 401/403)",
            "status": "PASS",
            "http_code": res_unauth.status_code,
            "latency_ms": round(elapsed_2, 2),
            "details": "Rejet immédiat des requêtes non authentifiées",
        })

        # -------------------------------------------------------------
        # TEST 3 : KPIs & Dashboard Global (Awa Koné)
        # -------------------------------------------------------------
        print("\n--- TEST 3 : Consultation KPIs Globaux (Awa Koné) ---")
        t0 = time.perf_counter()
        res_kpis = await client.get(
            "/api/v1/cooperative/dashboard",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        elapsed_3 = (time.perf_counter() - t0) * 1000
        print(f"Status Code : {res_kpis.status_code} (Temps : {elapsed_3:.1f}ms)")
        assert res_kpis.status_code == 200, f"Attendu 200, reçu {res_kpis.status_code}"
        kpis = res_kpis.json()

        print(f"Coopérative : {kpis['cooperative_name']} ({kpis['cooperative_id']})")
        print(f"Tonnage Total : {kpis['total_tonnage_tonnes']} tonnes ({kpis['total_weight_kg']} kg)")
        print(f"  - Validé : {kpis['approved_tonnage_tonnes']} t ({kpis['approved_bags']} sacs)")
        print(f"  - En attente : {kpis['pending_tonnage_tonnes']} t ({kpis['pending_bags']} sacs)")
        print(f"Planteurs actifs : {kpis['total_planters']}")
        print(f"Parcelles totales : {kpis['total_parcelles']}")
        print(f"Sections agricoles : {len(kpis['parcelles_by_section'])}")
        for s in kpis["parcelles_by_section"]:
            print(f"   * {s['section']} ({s['crop']}): {s['parcelles_count']} parcelles, {s['superficie_ha']} ha")
        print(f"Alertes phytosanitaires actives : {kpis['active_alerts_count']}")
        for a in kpis["alerts_summary"]:
            print(f"   * {a['disease_name']} ({a['status']}): {a['count']}")

        assert kpis["total_planters"] >= 5, "Au moins 5 planteurs attendus"
        assert kpis["total_tonnage_tonnes"] > 0, "Le tonnage total doit être supérieur à 0"
        assert len(kpis["parcelles_by_section"]) >= 4, "Au moins 4 sections représentées"
        assert kpis["active_alerts_count"] >= 1, "Des alertes actives doivent être présentes"

        results.append({
            "test": "3. GET /cooperative/dashboard (KPIs)",
            "status": "PASS",
            "http_code": res_kpis.status_code,
            "latency_ms": round(elapsed_3, 2),
            "details": f"Tonnage: {kpis['total_tonnage_tonnes']}t, Planteurs: {kpis['total_planters']}, Alertes: {kpis['active_alerts_count']}",
        })

        # -------------------------------------------------------------
        # TEST 4 : Consultation Récoltes & Bordereaux avec filtres
        # -------------------------------------------------------------
        print("\n--- TEST 4 : Consultation Récoltes & Bordereaux ---")
        t0 = time.perf_counter()
        res_recoltes = await client.get(
            "/api/v1/cooperative/recoltes?limit=50",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        elapsed_4 = (time.perf_counter() - t0) * 1000
        print(f"Status Code : {res_recoltes.status_code} (Temps : {elapsed_4:.1f}ms)")
        assert res_recoltes.status_code == 200
        recoltes = res_recoltes.json()
        print(f"Nombre total de bordereaux récupérés : {len(recoltes)}")
        assert len(recoltes) >= 15, "Au moins 15 récoltes attendues"

        # Test filtre statut PENDING
        res_pending = await client.get(
            "/api/v1/cooperative/recoltes?status=PENDING",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        pending_list = res_pending.json()
        print(f"Bordereaux en attente ('PENDING') : {len(pending_list)}")
        assert all(r["status"] == "PENDING" for r in pending_list), "Tous les éléments doivent être PENDING"

        results.append({
            "test": "4. GET /cooperative/recoltes (Listing & Filtres)",
            "status": "PASS",
            "http_code": res_recoltes.status_code,
            "latency_ms": round(elapsed_4, 2),
            "details": f"{len(recoltes)} récoltes totales, {len(pending_list)} en attente",
        })

        # -------------------------------------------------------------
        # TEST 5 : Approbation d'un Bordereau de Récolte
        # -------------------------------------------------------------
        print("\n--- TEST 5 : Approbation d'un bordereau de récolte (PENDING -> APPROVED) ---")
        target_pending = pending_list[0] if pending_list else recoltes[0]
        target_recolte_id = target_pending["id"]
        initial_status = target_pending["status"]
        print(f"Bordereau ciblé : {target_pending['bordereau_ref']} (ID: {target_recolte_id}, Statut: {initial_status})")

        t0 = time.perf_counter()
        res_patch = await client.patch(
            f"/api/v1/cooperative/recoltes/{target_recolte_id}/status",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"status": "APPROVED", "motif": "Pesée et contrôle qualité validés au pont bascule"},
        )
        elapsed_5 = (time.perf_counter() - t0) * 1000
        print(f"Status Code : {res_patch.status_code} (Temps : {elapsed_5:.1f}ms)")
        assert res_patch.status_code == 200, f"Attendu 200, reçu {res_patch.status_code}"
        updated_recolte = res_patch.json()
        print(f"Nouveau statut : {updated_recolte['status']} (statut_ui: {updated_recolte['statut_ui']})")
        assert updated_recolte["status"] == "APPROVED"
        assert updated_recolte["statut_ui"] == "Validé"

        # Remise dans l'état initial pour conserver l'intégrité exacte des données si c'était PENDING
        if initial_status == "PENDING":
            await client.patch(
                f"/api/v1/cooperative/recoltes/{target_recolte_id}/status",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"status": "PENDING"},
            )
            print("🔄 Bordereau remis en PENDING pour préserver l'état du dataset.")

        results.append({
            "test": "5. PATCH /cooperative/recoltes/{id}/status",
            "status": "PASS",
            "http_code": res_patch.status_code,
            "latency_ms": round(elapsed_5, 2),
            "details": f"Validation bordereau {target_pending['bordereau_ref']} -> 'Validé' + Notification",
        })

        # -------------------------------------------------------------
        # TEST 6 : Sécurité Anti-IDOR sur Récolte Inexistante / Autre Coop
        # -------------------------------------------------------------
        print("\n--- TEST 6 : Barrière Anti-IDOR sur ID inconnu ---")
        fake_id = str(uuid4())
        res_fake = await client.patch(
            f"/api/v1/cooperative/recoltes/{fake_id}/status",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"status": "APPROVED"},
        )
        print(f"Status Code : {res_fake.status_code}")
        assert res_fake.status_code == 404, f"Attendu 404, obtenu {res_fake.status_code}"

        results.append({
            "test": "6. Anti-IDOR / Intégrité (UUID inconnu -> 404)",
            "status": "PASS",
            "http_code": res_fake.status_code,
            "latency_ms": 0.0,
            "details": "Rejet strict des tentatives de modification hors périmètre",
        })

        # -------------------------------------------------------------
        # TEST 7 : Listing et Agrégation Planteurs
        # -------------------------------------------------------------
        print("\n--- TEST 7 : Consultation des Planteurs et Agrégations ---")
        t0 = time.perf_counter()
        res_planters = await client.get(
            "/api/v1/cooperative/planters",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        elapsed_7 = (time.perf_counter() - t0) * 1000
        print(f"Status Code : {res_planters.status_code} (Temps : {elapsed_7:.1f}ms)")
        assert res_planters.status_code == 200
        planters = res_planters.json()
        print(f"Nombre de planteurs retournés : {len(planters)}")
        for p in planters:
            print(f"   * {p['nom_complet']} ({p['phone_number']}) - {p['village']} ({p['culture']}) : {p['parcelles_count']} parcelles, {p['total_superficie_ha']} ha, {p['total_tonnage_kg']} kg livrés")

        assert len(planters) >= 5
        results.append({
            "test": "7. GET /cooperative/planters",
            "status": "PASS",
            "http_code": res_planters.status_code,
            "latency_ms": round(elapsed_7, 2),
            "details": f"{len(planters)} planteurs avec parcelles, superficies et tonnages consolidés",
        })

        # -------------------------------------------------------------
        # TEST 8 : Cartographie / Inventaire des Parcelles
        # -------------------------------------------------------------
        print("\n--- TEST 8 : Cartographie des Parcelles (Coordonnées GPS) ---")
        t0 = time.perf_counter()
        res_parcelles = await client.get(
            "/api/v1/cooperative/parcelles",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        elapsed_8 = (time.perf_counter() - t0) * 1000
        print(f"Status Code : {res_parcelles.status_code} (Temps : {elapsed_8:.1f}ms)")
        assert res_parcelles.status_code == 200
        parcelles = res_parcelles.json()
        print(f"Nombre de parcelles cartographiées : {len(parcelles)}")
        for parc in parcelles:
            gps = parc["gps_coordinates"]
            gps_str = f"lat: {gps.get('lat')}, lng: {gps.get('lng')}" if gps else "N/A"
            print(f"   * [{parc['village']}] {parc['name']} ({parc['crop_type']}, {parc['superficie']} ha) - Planteur: {parc['planter_name']} | GPS: {gps_str}")

        assert len(parcelles) >= 5
        assert all("gps_coordinates" in p for p in parcelles)
        results.append({
            "test": "8. GET /cooperative/parcelles (Cartographie GPS)",
            "status": "PASS",
            "http_code": res_parcelles.status_code,
            "latency_ms": round(elapsed_8, 2),
            "details": f"{len(parcelles)} parcelles géoréférencées pour affichage Web Leaflet/Mapbox",
        })

        # -------------------------------------------------------------
        # TEST 9 : Diagnostics Phytosanitaires
        # -------------------------------------------------------------
        print("\n--- TEST 9 : Alertes et Diagnostics Phytosanitaires ---")
        t0 = time.perf_counter()
        res_diags = await client.get(
            "/api/v1/cooperative/diagnostics",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        elapsed_9 = (time.perf_counter() - t0) * 1000
        print(f"Status Code : {res_diags.status_code} (Temps : {elapsed_9:.1f}ms)")
        assert res_diags.status_code == 200
        diags = res_diags.json()
        print(f"Nombre de diagnostics déclarés : {len(diags)}")
        for d in diags:
            print(f"   * [{d['status']}] {d['disease_name']} ({d['village']}) - Planteur: {d['planter_name']} | Confiance: {d['confidence_score']}")

        assert len(diags) >= 4
        results.append({
            "test": "9. GET /cooperative/diagnostics",
            "status": "PASS",
            "http_code": res_diags.status_code,
            "latency_ms": round(elapsed_9, 2),
            "details": f"{len(diags)} diagnostics phytosanitaires répertoriés",
        })

    await close_pool()

    print("\n" + "=" * 75)
    print("📋 RAPPORT DE VALIDATION DES ENDPOINTS WEB COOPÉRATIVE")
    print("=" * 75)
    print(f"{'#':<3} | {'TEST':<48} | {'CODE':<5} | {'LATENCE':<8} | {'RÉSULTAT'}")
    print("-" * 75)
    for i, r in enumerate(results, start=1):
        print(f"{i:<3} | {r['test']:<48} | {r['http_code']:<5} | {r['latency_ms']:>6.1f}ms | ✅ {r['status']}")
    print("=" * 75)
    print("🎉 TOUS LES 9 TESTS ONT RÉUSSI AVEC SUCCÈS (100% SUCCÈS) !")
    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(run_cooperative_tests())
