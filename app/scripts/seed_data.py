"""
Script d'injection de données métier (Seed Data) pour CoopIA / Coopérative CAPED.
Idempotent et respectant strictement les schémas et ENUMs PostgreSQL.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from uuid import uuid4, UUID
from decimal import Decimal

import os
import sys
from pathlib import Path

# Ajouter la racine du projet au sys.path
BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.core.database import get_pool, close_pool

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_data")

async def get_or_create_cooperative(conn) -> UUID:
    """Récupère ou crée la Coopérative CAPED."""
    row = await conn.fetchrow("SELECT id FROM cooperatives WHERE code = 'CAPED'")
    if row:
        logger.info(f"Coopérative CAPED existante: {row['id']}")
        return row["id"]
    
    coop_id = uuid4()
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        INSERT INTO cooperatives (id, name, code, region, created_at)
        VALUES ($1, $2, $3, $4, $5)
        """,
        coop_id,
        "Coopérative CAPED",
        "CAPED",
        "Côte d'Ivoire",
        now
    )
    logger.info(f"Coopérative CAPED créée: {coop_id}")
    return coop_id

async def seed_users(conn, caped_id: UUID) -> dict[str, UUID]:
    """
    Crée ou met à jour les utilisateurs CAPED (1 Admin + 4 Planteurs dont Seke Darel).
    Préserve impérativement Seke Darel (+225565697263).
    """
    users_data = [
        # Planteur existant (référence Bodokro)
        {
            "phone_number": "+225565697263",
            "first_name": "Seke",
            "last_name": "Darel",
            "role": "PLANTER",
            "cooperative_id": caped_id,
        },
        # Directrice / Gérante
        {
            "phone_number": "+2250700000001",
            "first_name": "Awa",
            "last_name": "Koné",
            "role": "COOP_ADMIN",
            "cooperative_id": caped_id,
        },
        # Planteur 2 (Soubré)
        {
            "phone_number": "+2250700000002",
            "first_name": "Koffi",
            "last_name": "Kouamé",
            "role": "PLANTER",
            "cooperative_id": caped_id,
        },
        # Planteur 3 (Man)
        {
            "phone_number": "+2250700000003",
            "first_name": "Yao",
            "last_name": "N'Guessan",
            "role": "PLANTER",
            "cooperative_id": caped_id,
        },
        # Planteur 4 (Divo)
        {
            "phone_number": "+2250700000004",
            "first_name": "Amadou",
            "last_name": "Traoré",
            "role": "PLANTER",
            "cooperative_id": caped_id,
        },
        # Planteuse active de test (Pindikro)
        {
            "phone_number": "+225556255495",
            "first_name": "Estelle",
            "last_name": "Kouame",
            "role": "PLANTER",
            "cooperative_id": caped_id,
        },
    ]

    users_map: dict[str, UUID] = {}
    now = datetime.now(timezone.utc)

    for u in users_data:
        phone = u["phone_number"]
        existing = await conn.fetchrow("SELECT id, role, cooperative_id FROM users WHERE phone_number = $1", phone)
        if existing:
            user_id = existing["id"]
            # Mise à jour idempotente des champs sans écraser les données personnelles
            await conn.execute(
                """
                UPDATE users
                SET first_name = COALESCE(first_name, $1),
                    last_name = COALESCE(last_name, $2),
                    role = $3::user_role,
                    cooperative_id = $4
                WHERE id = $5
                """,
                u["first_name"],
                u["last_name"],
                u["role"],
                u["cooperative_id"],
                user_id
            )
            users_map[phone] = user_id
            logger.info(f"Utilisateur existant mis à jour: {u['first_name']} {u['last_name']} ({phone}) -> {user_id}")
        else:
            new_id = uuid4()
            await conn.execute(
                """
                INSERT INTO users (id, phone_number, first_name, last_name, role, cooperative_id, created_at)
                VALUES ($1, $2, $3, $4, $5::user_role, $6, $7)
                """,
                new_id,
                phone,
                u["first_name"],
                u["last_name"],
                u["role"],
                u["cooperative_id"],
                now
            )
            users_map[phone] = new_id
            logger.info(f"Nouvel utilisateur créé: {u['first_name']} {u['last_name']} ({phone}) -> {new_id}")

    return users_map

async def seed_parcelles(conn, users_map: dict[str, UUID]) -> dict[str, UUID]:
    """
    Crée ou met à jour les parcelles agricoles pour chaque planteur.
    Préserve la Parcelle Principale de Seke Darel.
    """
    parcelles_data = [
        # Seke Darel (Bodokro)
        {
            "phone": "+225565697263",
            "name": "Parcelle Principale",
            "crop_type": "cacao",
            "superficie": Decimal("3.8"),
            "village": "Bodokro",
            "gps_coordinates": {"lat": 7.45, "lng": -4.88},
        },
        # Koffi Kouamé (Soubré)
        {
            "phone": "+2250700000002",
            "name": "Parcelle Kôkô",
            "crop_type": "cacao",
            "superficie": Decimal("4.5"),
            "village": "Soubré",
            "gps_coordinates": {"lat": 5.78, "lng": -6.60},
        },
        # Yao N'Guessan (Man)
        {
            "phone": "+2250700000003",
            "name": "Champ Montagnard",
            "crop_type": "café",
            "superficie": Decimal("3.2"),
            "village": "Man",
            "gps_coordinates": {"lat": 7.41, "lng": -7.55},
        },
        # Amadou Traoré (Divo)
        {
            "phone": "+2250700000004",
            "name": "Parcelle Djiboua",
            "crop_type": "cacao",
            "superficie": Decimal("5.0"),
            "village": "Divo",
            "gps_coordinates": {"lat": 5.83, "lng": -5.35},
        },
        # Estelle Kouame (Pindikro)
        {
            "phone": "+225556255495",
            "name": "Parcelle Pindikro",
            "crop_type": "cacao",
            "superficie": Decimal("2.5"),
            "village": "Pindikro",
            "gps_coordinates": {"lat": 6.82, "lng": -5.02},
        },
    ]

    parcelles_map: dict[str, UUID] = {}
    now = datetime.now(timezone.utc)

    for p in parcelles_data:
        phone = p["phone"]
        user_id = users_map[phone]
        name = p["name"]

        existing = await conn.fetchrow(
            "SELECT id FROM parcelles WHERE user_id = $1 AND name = $2",
            user_id, name
        )
        if existing:
            parcelle_id = existing["id"]
            await conn.execute(
                """
                UPDATE parcelles
                SET crop_type = COALESCE(crop_type, $2),
                    superficie = COALESCE(superficie, $3),
                    village = COALESCE(village, $4),
                    gps_coordinates = COALESCE(gps_coordinates, $5::jsonb)
                WHERE id = $1
                """,
                parcelle_id,
                p["crop_type"],
                p["superficie"],
                p["village"],
                json.dumps(p["gps_coordinates"])
            )
            parcelles_map[f"{phone}:{name}"] = parcelle_id
            logger.info(f"Parcelle existante mise à jour: '{name}' ({p['village']}) -> {parcelle_id}")
        else:
            new_id = uuid4()
            await conn.execute(
                """
                INSERT INTO parcelles (id, user_id, name, crop_type, superficie, village, gps_coordinates, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                """,
                new_id,
                user_id,
                name,
                p["crop_type"],
                p["superficie"],
                p["village"],
                json.dumps(p["gps_coordinates"]),
                now
            )
            parcelles_map[f"{phone}:{name}"] = new_id
            logger.info(f"Nouvelle parcelle créée: '{name}' ({p['village']}) -> {new_id}")

    return parcelles_map

async def seed_recoltes(conn, users_map: dict[str, UUID], parcelles_map: dict[str, UUID]) -> dict[str, UUID]:
    """
    Génère 20 déclarations de récoltes échelonnées sur les 6 derniers mois (mai à octobre 2026).
    16 APPROVED + 4 PENDING (récentes prêtes pour ramassage).
    """
    recoltes_definitions = [
        # --- Seke Darel (Bodokro, Cacao) ---
        {
            "phone": "+225565697263", "parcelle_name": "Parcelle Principale",
            "bags": 16, "weight": Decimal("804.5"), "ref": "BDR-2026-BD01", "status": "APPROVED",
            "harvest_date": datetime(2026, 5, 14, 8, 30, tzinfo=timezone.utc),
        },
        {
            "phone": "+225565697263", "parcelle_name": "Parcelle Principale",
            "bags": 22, "weight": Decimal("1098.0"), "ref": "BDR-2026-BD02", "status": "APPROVED",
            "harvest_date": datetime(2026, 7, 2, 9, 15, tzinfo=timezone.utc),
        },
        {
            "phone": "+225565697263", "parcelle_name": "Parcelle Principale",
            "bags": 18, "weight": Decimal("905.5"), "ref": "BDR-2026-BD03", "status": "APPROVED",
            "harvest_date": datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc),
        },
        {
            "phone": "+225565697263", "parcelle_name": "Parcelle Principale",
            "bags": 25, "weight": Decimal("1248.0"), "ref": "BDR-2026-BD04", "status": "PENDING",
            "harvest_date": datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc),
        },

        # --- Koffi Kouamé (Soubré, Cacao) ---
        {
            "phone": "+2250700000002", "parcelle_name": "Parcelle Kôkô",
            "bags": 20, "weight": Decimal("1002.0"), "ref": "BDR-2026-SB01", "status": "APPROVED",
            "harvest_date": datetime(2026, 5, 22, 14, 0, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000002", "parcelle_name": "Parcelle Kôkô",
            "bags": 28, "weight": Decimal("1395.5"), "ref": "BDR-2026-SB02", "status": "APPROVED",
            "harvest_date": datetime(2026, 6, 30, 11, 30, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000002", "parcelle_name": "Parcelle Kôkô",
            "bags": 32, "weight": Decimal("1604.0"), "ref": "BDR-2026-SB03", "status": "APPROVED",
            "harvest_date": datetime(2026, 8, 5, 9, 45, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000002", "parcelle_name": "Parcelle Kôkô",
            "bags": 24, "weight": Decimal("1198.5"), "ref": "BDR-2026-SB04", "status": "APPROVED",
            "harvest_date": datetime(2026, 9, 18, 16, 20, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000002", "parcelle_name": "Parcelle Kôkô",
            "bags": 30, "weight": Decimal("1503.0"), "ref": "BDR-2026-SB05", "status": "PENDING",
            "harvest_date": datetime(2026, 10, 12, 10, 15, tzinfo=timezone.utc),
        },

        # --- Yao N'Guessan (Man, Café) ---
        {
            "phone": "+2250700000003", "parcelle_name": "Champ Montagnard",
            "bags": 12, "weight": Decimal("598.0"), "ref": "BDR-2026-MN01", "status": "APPROVED",
            "harvest_date": datetime(2026, 5, 18, 8, 45, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000003", "parcelle_name": "Champ Montagnard",
            "bags": 15, "weight": Decimal("752.5"), "ref": "BDR-2026-MN02", "status": "APPROVED",
            "harvest_date": datetime(2026, 6, 25, 15, 0, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000003", "parcelle_name": "Champ Montagnard",
            "bags": 18, "weight": Decimal("901.0"), "ref": "BDR-2026-MN03", "status": "APPROVED",
            "harvest_date": datetime(2026, 8, 10, 11, 10, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000003", "parcelle_name": "Champ Montagnard",
            "bags": 20, "weight": Decimal("998.0"), "ref": "BDR-2026-MN04", "status": "APPROVED",
            "harvest_date": datetime(2026, 9, 22, 14, 40, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000003", "parcelle_name": "Champ Montagnard",
            "bags": 14, "weight": Decimal("703.5"), "ref": "BDR-2026-MN05", "status": "PENDING",
            "harvest_date": datetime(2026, 10, 14, 9, 30, tzinfo=timezone.utc),
        },

        # --- Amadou Traoré (Divo, Cacao) ---
        {
            "phone": "+2250700000004", "parcelle_name": "Parcelle Djiboua",
            "bags": 22, "weight": Decimal("1105.0"), "ref": "BDR-2026-DV01", "status": "APPROVED",
            "harvest_date": datetime(2026, 5, 10, 7, 30, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000004", "parcelle_name": "Parcelle Djiboua",
            "bags": 26, "weight": Decimal("1298.0"), "ref": "BDR-2026-DV02", "status": "APPROVED",
            "harvest_date": datetime(2026, 6, 16, 10, 20, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000004", "parcelle_name": "Parcelle Djiboua",
            "bags": 34, "weight": Decimal("1696.5"), "ref": "BDR-2026-DV03", "status": "APPROVED",
            "harvest_date": datetime(2026, 7, 28, 16, 0, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000004", "parcelle_name": "Parcelle Djiboua",
            "bags": 30, "weight": Decimal("1502.0"), "ref": "BDR-2026-DV04", "status": "APPROVED",
            "harvest_date": datetime(2026, 8, 29, 13, 15, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000004", "parcelle_name": "Parcelle Djiboua",
            "bags": 25, "weight": Decimal("1251.5"), "ref": "BDR-2026-DV05", "status": "APPROVED",
            "harvest_date": datetime(2026, 9, 28, 9, 0, tzinfo=timezone.utc),
        },
        {
            "phone": "+2250700000004", "parcelle_name": "Parcelle Djiboua",
            "bags": 28, "weight": Decimal("1402.0"), "ref": "BDR-2026-DV06", "status": "PENDING",
            "harvest_date": datetime(2026, 10, 16, 11, 0, tzinfo=timezone.utc),
        },
    ]

    recoltes_map: dict[str, UUID] = {}

    for r in recoltes_definitions:
        ref = r["ref"]
        phone = r["phone"]
        user_id = users_map[phone]
        parcelle_key = f"{phone}:{r['parcelle_name']}"
        parcelle_id = parcelles_map[parcelle_key]

        existing = await conn.fetchrow("SELECT id FROM recoltes WHERE bordereau_ref = $1", ref)
        if existing:
            recolte_id = existing["id"]
            await conn.execute(
                """
                UPDATE recoltes
                SET weight_kg = $2,
                    number_of_bags = $3,
                    status = $4::validation_status,
                    harvest_date = $5
                WHERE id = $1
                """,
                recolte_id,
                r["weight"],
                r["bags"],
                r["status"],
                r["harvest_date"]
            )
            recoltes_map[ref] = recolte_id
            logger.info(f"Récolte existante mise à jour: {ref} ({r['bags']} sacs, {r['weight']} kg)")
        else:
            new_id = uuid4()
            await conn.execute(
                """
                INSERT INTO recoltes (id, parcelle_id, user_id, weight_kg, number_of_bags, bordereau_ref, status, harvest_date, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7::validation_status, $8, $9)
                """,
                new_id,
                parcelle_id,
                user_id,
                r["weight"],
                r["bags"],
                ref,
                r["status"],
                r["harvest_date"],
                r["harvest_date"]
            )
            recoltes_map[ref] = new_id
            logger.info(f"Nouvelle récolte enregistrée: {ref} ({r['bags']} sacs, {r['weight']} kg) -> {new_id}")

    return recoltes_map

async def seed_diagnostics(conn, users_map: dict[str, UUID], parcelles_map: dict[str, UUID]) -> dict[str, UUID]:
    """
    Insère 5 diagnostics sanitaires localisés avec statuts DETECTED, ESCALATED et TREATED.
    """
    diags_data = [
        # 1. Seke Darel (Bodokro) - Très récent, DETECTED
        {
            "key": "seke_pourriture_brune",
            "phone": "+225565697263",
            "parcelle_name": "Parcelle Principale",
            "disease_name": "Pourriture brune des cabosses",
            "confidence_score": Decimal("0.94"),
            "status": "DETECTED",
            "image_url": "https://res.cloudinary.com/diqqqcayf/image/upload/v1/diagnostics/cacao_pod_rot.jpg",
            "recommended_action": "Récolte sanitaire immédiate des cabosses atteintes et amélioration de l'aération.",
            "created_at": datetime(2026, 10, 17, 14, 30, tzinfo=timezone.utc),
        },
        # 2. Koffi Kouamé (Soubré) - ESCALATED
        {
            "key": "koffi_swollen_shoot",
            "phone": "+2250700000002",
            "parcelle_name": "Parcelle Kôkô",
            "disease_name": "Maladie du Swollen Shoot",
            "confidence_score": Decimal("0.91"),
            "status": "ESCALATED",
            "image_url": "https://res.cloudinary.com/diqqqcayf/image/upload/v1/diagnostics/swollen_shoot.jpg",
            "recommended_action": "Arrachage et destruction des arbres infectés, signalement au délégué régional ANADER.",
            "created_at": datetime(2026, 10, 14, 9, 15, tzinfo=timezone.utc),
        },
        # 3. Amadou Traoré (Divo) - TREATED
        {
            "key": "amadou_mirides",
            "phone": "+2250700000004",
            "parcelle_name": "Parcelle Djiboua",
            "disease_name": "Chenilles défoliatrices / Mirides",
            "confidence_score": Decimal("0.88"),
            "status": "TREATED",
            "image_url": "https://res.cloudinary.com/diqqqcayf/image/upload/v1/diagnostics/mirides.jpg",
            "recommended_action": "Traitement phytosanitaire ciblé avec produit homologué et désherbage sous canopée.",
            "created_at": datetime(2026, 10, 10, 16, 45, tzinfo=timezone.utc),
        },
        # 4. Yao N'Guessan (Man) - DETECTED
        {
            "key": "yao_rouille_cafe",
            "phone": "+2250700000003",
            "parcelle_name": "Champ Montagnard",
            "disease_name": "Rouille orangée du caféier",
            "confidence_score": Decimal("0.89"),
            "status": "DETECTED",
            "image_url": "https://res.cloudinary.com/diqqqcayf/image/upload/v1/diagnostics/rouille_cafe.jpg",
            "recommended_action": "Élagage des arbres d'ombrage excessif et pulvérisation de bouillie bordelaise.",
            "created_at": datetime(2026, 10, 12, 11, 20, tzinfo=timezone.utc),
        },
        # 5. Seke Darel (Bodokro) - Cas antérieur guéri / TREATED
        {
            "key": "seke_mirides_treated",
            "phone": "+225565697263",
            "parcelle_name": "Parcelle Principale",
            "disease_name": "Chenilles défoliatrices / Mirides",
            "confidence_score": Decimal("0.85"),
            "status": "TREATED",
            "image_url": "https://res.cloudinary.com/diqqqcayf/image/upload/v1/diagnostics/mirides_bodokro.jpg",
            "recommended_action": "Application localisée de bio-insecticide au pied des troncs.",
            "created_at": datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc),
        },
    ]

    diags_map: dict[str, UUID] = {}

    for d in diags_data:
        phone = d["phone"]
        user_id = users_map[phone]
        parcelle_key = f"{phone}:{d['parcelle_name']}"
        parcelle_id = parcelles_map[parcelle_key]
        key = d["key"]

        existing = await conn.fetchrow(
            """
            SELECT id FROM diagnostics
            WHERE user_id = $1 AND parcelle_id = $2 AND disease_name = $3 AND created_at = $4
            """,
            user_id, parcelle_id, d["disease_name"], d["created_at"]
        )
        if existing:
            diag_id = existing["id"]
            await conn.execute(
                """
                UPDATE diagnostics
                SET confidence_score = $2,
                    status = $3::diagnostic_status,
                    recommended_action = $4,
                    image_url = $5
                WHERE id = $1
                """,
                diag_id,
                d["confidence_score"],
                d["status"],
                d["recommended_action"],
                d["image_url"]
            )
            diags_map[key] = diag_id
            logger.info(f"Diagnostic existant mis à jour: {d['disease_name']} ({key})")
        else:
            new_id = uuid4()
            await conn.execute(
                """
                INSERT INTO diagnostics (id, parcelle_id, user_id, disease_name, confidence_score, image_url, recommended_action, status, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::diagnostic_status, $9)
                """,
                new_id,
                parcelle_id,
                user_id,
                d["disease_name"],
                d["confidence_score"],
                d["image_url"],
                d["recommended_action"],
                d["status"],
                d["created_at"]
            )
            diags_map[key] = new_id
            logger.info(f"Nouveau diagnostic inséré: {d['disease_name']} ({key}) -> {new_id}")

    return diags_map

async def seed_activities(
    conn,
    users_map: dict[str, UUID],
    recoltes_map: dict[str, UUID],
    diags_map: dict[str, UUID]
) -> list[UUID]:
    """
    Insère 7 activités reliées aux récoltes et diagnostics.
    Garantit que Seke Darel a la dernière activité active (DISEASE_WARNING sur la pourriture brune).
    """
    activities_data = [
        # 1. Seke Darel (Bodokro) - Activité la plus récente (pour affichage mobile direct)
        {
            "phone": "+225565697263",
            "type": "DISEASE_WARNING",
            "reference_id": diags_map.get("seke_pourriture_brune"),
            "title": "Alerte Maladie : Pourriture brune des cabosses",
            "subtitle": "Parcelle Principale • Bodokro",
            "ui_color_tag": "warning",
            "created_at": datetime(2026, 10, 17, 14, 35, tzinfo=timezone.utc),
        },
        # 2. Seke Darel - Déclaration récolte récente
        {
            "phone": "+225565697263",
            "type": "HARVEST_LOG",
            "reference_id": recoltes_map.get("BDR-2026-BD04"),
            "title": "Récolte déclarée : 25 sacs",
            "subtitle": "1248 kg • Bordereau #BDR-2026-BD04",
            "ui_color_tag": "success",
            "created_at": datetime(2026, 10, 15, 8, 30, tzinfo=timezone.utc),
        },
        # 3. Koffi Kouamé - Alerte Swollen Shoot critique
        {
            "phone": "+2250700000002",
            "type": "DISEASE_WARNING",
            "reference_id": diags_map.get("koffi_swollen_shoot"),
            "title": "Alerte Critique : Swollen Shoot détecté",
            "subtitle": "Parcelle Kôkô • Soubré",
            "ui_color_tag": "danger",
            "created_at": datetime(2026, 10, 14, 9, 20, tzinfo=timezone.utc),
        },
        # 4. Koffi Kouamé - Récolte enregistrée
        {
            "phone": "+2250700000002",
            "type": "HARVEST_LOG",
            "reference_id": recoltes_map.get("BDR-2026-SB05"),
            "title": "Récolte déclarée : 30 sacs",
            "subtitle": "1503 kg • Bordereau #BDR-2026-SB05",
            "ui_color_tag": "success",
            "created_at": datetime(2026, 10, 12, 10, 15, tzinfo=timezone.utc),
        },
        # 5. Amadou Traoré - Récolte récente
        {
            "phone": "+2250700000004",
            "type": "HARVEST_LOG",
            "reference_id": recoltes_map.get("BDR-2026-DV06"),
            "title": "Récolte déclarée : 28 sacs",
            "subtitle": "1402 kg • Bordereau #BDR-2026-DV06",
            "ui_color_tag": "success",
            "created_at": datetime(2026, 10, 16, 11, 0, tzinfo=timezone.utc),
        },
        # 6. Yao N'Guessan - Alerte Rouille Caféier
        {
            "phone": "+2250700000003",
            "type": "DISEASE_WARNING",
            "reference_id": diags_map.get("yao_rouille_cafe"),
            "title": "Alerte Sanitaire : Rouille orangée",
            "subtitle": "Champ Montagnard • Man",
            "ui_color_tag": "warning",
            "created_at": datetime(2026, 10, 12, 11, 25, tzinfo=timezone.utc),
        },
        # 7. Awa Koné (Gérante) - Annonce Système CAPED
        {
            "phone": "+2250700000001",
            "type": "SYSTEM_INFO",
            "reference_id": None,
            "title": "Campagne Principale Cacao 2026 Ouverte",
            "subtitle": "Coopérative CAPED • Prix bord champ garanti",
            "ui_color_tag": "success",
            "created_at": datetime(2026, 10, 16, 8, 0, tzinfo=timezone.utc),
        },
    ]

    act_ids = []
    for a in activities_data:
        phone = a["phone"]
        user_id = users_map[phone]

        existing = await conn.fetchrow(
            """
            SELECT id FROM activities
            WHERE user_id = $1 AND type = $2::activity_type AND title = $3
            """,
            user_id, a["type"], a["title"]
        )
        if existing:
            act_id = existing["id"]
            await conn.execute(
                """
                UPDATE activities
                SET subtitle = $2,
                    reference_id = $3,
                    ui_color_tag = $4,
                    created_at = $5
                WHERE id = $1
                """,
                act_id,
                a["subtitle"],
                a["reference_id"],
                a["ui_color_tag"],
                a["created_at"]
            )
            act_ids.append(act_id)
            logger.info(f"Activité existante mise à jour: {a['title']}")
        else:
            new_id = uuid4()
            await conn.execute(
                """
                INSERT INTO activities (id, user_id, type, reference_id, title, subtitle, ui_color_tag, created_at)
                VALUES ($1, $2, $3::activity_type, $4, $5, $6, $7, $8)
                """,
                new_id,
                user_id,
                a["type"],
                a["reference_id"],
                a["title"],
                a["subtitle"],
                a["ui_color_tag"],
                a["created_at"]
            )
            act_ids.append(new_id)
            logger.info(f"Nouvelle activité enregistrée: {a['title']} -> {new_id}")

    return act_ids
async def seed_chat_history(conn, users_map: dict[str, UUID]):
    """
    Injecte ou préserve les sessions d'historique de chat pour la démonstration.
    - Préserve la session existante d'Estelle Kouame (+225556255495) avec ses messages.
    - Injecte de manière idempotente les sessions de Seke Darel (+225565697263) :
      * Déclaration de récolte 25 sacs (BDR-2026-BD04) -> Statut UI 'Validé'
      * Diagnostic photo pourriture brune -> Statut UI 'Action requise'
    """
    logger.info("--- Début injection historique de chat (chat_sessions & chat_messages) ---")
    
    # 1. Estelle Kouame
    estelle_id = users_map.get("+225556255495")
    if estelle_id:
        estelle_session = await conn.fetchrow(
            "SELECT id FROM chat_sessions WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
            estelle_id
        )
        if not estelle_session:
            sess_id = uuid4()
            t1 = datetime(2026, 10, 18, 3, 31, 19, tzinfo=timezone.utc)
            t2 = datetime(2026, 10, 18, 3, 31, 26, tzinfo=timezone.utc)
            await conn.execute(
                """
                INSERT INTO chat_sessions (id, user_id, title, status, created_at, updated_at)
                VALUES ($1, $2, $3, $4::session_status, $5, $6)
                """,
                sess_id, estelle_id, "J'ai 15 sacs de 10kg de cacao...", "ACTIVE", t1, t2
            )
            recs = [
                {"titre": "Vérifiez la qualité du cacao", "description": "Assurez-vous que les fèves sont bien fermentées et sèches (humidité < 8%) pour éviter les moisissures."},
                {"titre": "Préparez le stockage", "description": "Stockez les sacs sur des palettes, dans un local aéré et à l'abri de l'humidité."},
                {"titre": "Contactez votre coopérative", "description": "Informez votre coopérative de la disponibilité pour planifier la pesée et la vente."}
            ]
            await conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, text, is_user, created_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                uuid4(), sess_id, "J'ai 15 sac de 10kg de cacao a pindikro", True, t1
            )
            await conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, text, is_user, created_at, recommendations)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                uuid4(), sess_id, "Félicitations pour votre récolte ! J'ai bien enregistré votre déclaration de 15 sacs de 10 kg, soit 150 kg de cacao à Pindikro. C'est un bon début. Assurez-vous que les sacs sont bien secs et stockés dans un endroit aéré avant la pesée officielle. Un conseiller pourra vous aider à organiser la livraison.", False, t2, json.dumps(recs)
            )
            logger.info(f"Session Estelle Kouame créée: {sess_id}")
        else:
            logger.info(f"Session Estelle Kouame préservée: {estelle_session['id']}")

    # 2. Seke Darel
    seke_id = users_map.get("+225565697263")
    if seke_id:
        # Session A : Déclaration de récolte 25 sacs (Validé)
        seke_harvest_sess_id = UUID("a1010001-0000-4000-8000-000000000001")
        existing_h = await conn.fetchrow("SELECT id FROM chat_sessions WHERE id = $1", seke_harvest_sess_id)
        if not existing_h:
            t1 = datetime(2026, 10, 15, 8, 0, 0, tzinfo=timezone.utc)
            t2 = datetime(2026, 10, 15, 8, 0, 15, tzinfo=timezone.utc)
            await conn.execute(
                """
                INSERT INTO chat_sessions (id, user_id, title, status, created_at, updated_at)
                VALUES ($1, $2, $3, $4::session_status, $5, $6)
                """,
                seke_harvest_sess_id, seke_id, "Déclaration récolte 25 sacs Bodokro", "ACTIVE", t1, t2
            )
            recs_harvest = [
                {"titre": "Stockage sur palettes", "description": "Conservez les 25 sacs dans un endroit sec et aéré à Bodokro pour éviter toute moisissure."},
                {"titre": "Pesée officielle", "description": "L'équipe de collecte CAPED passera valider le tonnage officiel."},
                {"titre": "Contrôle d'humidité", "description": "Maintenez le taux d'humidité sous 7.5% pour préserver le grade I d'exportation."}
            ]
            await conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, text, is_user, created_at)
                VALUES ($1, $2, $3, $4, $5)
                """,
                uuid4(), seke_harvest_sess_id, "Bonjour CoopIA, j'ai récolté 25 sacs de cacao sur ma parcelle de Bodokro. Poids total estimé à 1248 kg. Pouvez-vous enregistrer ma déclaration ?", True, t1
            )
            await conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, text, is_user, created_at, recommendations)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                uuid4(), seke_harvest_sess_id, "Félicitations pour cette belle récolte M. Seke ! Votre déclaration de 25 sacs (1248 kg) à Bodokro a bien été enregistrée sous le bordereau #BDR-2026-BD04. Vos sacs sont en attente de pesée officielle par la coopérative CAPED. Veillez à bien stocker les fèves sur palettes surélevées à l'abri de l'humidité.", False, t2, json.dumps(recs_harvest)
            )
            logger.info(f"Session récolte Seke Darel créée: {seke_harvest_sess_id}")
        else:
            logger.info(f"Session récolte Seke Darel existante: {seke_harvest_sess_id}")

        # Session B : Diagnostic photo Pourriture brune (Action requise)
        seke_diag_sess_id = UUID("a1010001-0000-4000-8000-000000000002")
        existing_d = await conn.fetchrow("SELECT id FROM chat_sessions WHERE id = $1", seke_diag_sess_id)
        if not existing_d:
            t1 = datetime(2026, 10, 17, 14, 30, 0, tzinfo=timezone.utc)
            t2 = datetime(2026, 10, 17, 14, 30, 20, tzinfo=timezone.utc)
            await conn.execute(
                """
                INSERT INTO chat_sessions (id, user_id, title, status, created_at, updated_at)
                VALUES ($1, $2, $3, $4::session_status, $5, $6)
                """,
                seke_diag_sess_id, seke_id, "Diagnostic cabosse suspecte Bodokro", "ACTIVE", t1, t2
            )
            recs_diag = [
                {"titre": "Récolte sanitaire d'urgence", "description": "Retirez et enfouissez immédiatement toutes les cabosses atteintes hors de la plantation."},
                {"titre": "Traitement fongicide cuprique", "description": "Appliquez un fongicide homologué à base d'oxyde de cuivre en respectant les doses recommandées."},
                {"titre": "Aération de l'ombrage", "description": "Éclaircissez les arbres d'ombrage pour favoriser la circulation de l'air et réduire l'humidité."}
            ]
            await conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, text, is_user, created_at, media_url)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                uuid4(), seke_diag_sess_id, "[IMAGE]https://res.cloudinary.com/coopia/diagnostics/cabosse_pourriture_brune.jpg", True, t1, "https://res.cloudinary.com/coopia/diagnostics/cabosse_pourriture_brune.jpg"
            )
            await conn.execute(
                """
                INSERT INTO chat_messages (id, session_id, text, is_user, created_at, recommendations)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                """,
                uuid4(), seke_diag_sess_id, "Diagnostic phytosanitaire : Pourriture brune des cabosses détectée (Phytophthora palmivora, indice de confiance 94%). Cette pathologie fongique nécessite une intervention rapide pour stopper la propagation sur votre parcelle de Bodokro.", False, t2, json.dumps(recs_diag)
            )
            logger.info(f"Session diagnostic Seke Darel créée: {seke_diag_sess_id}")
        else:
            logger.info(f"Session diagnostic Seke Darel existante: {seke_diag_sess_id}")
async def run_seed():
    """Point d'entrée principal asynchrone du script de seed."""
    logger.info("=== DÉBUT DE L'INJECTION DES DONNÉES MÉTIER (COOPÉRATIVE CAPED) ===")
    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1. Coopérative
            caped_id = await get_or_create_cooperative(conn)

            # 2. Utilisateurs
            users_map = await seed_users(conn, caped_id)

            # 3. Parcelles
            parcelles_map = await seed_parcelles(conn, users_map)

            # 4. Récoltes
            recoltes_map = await seed_recoltes(conn, users_map, parcelles_map)

            # 5. Diagnostics
            diags_map = await seed_diagnostics(conn, users_map, parcelles_map)

            # 6. Activités
            act_ids = await seed_activities(conn, users_map, recoltes_map, diags_map)

            # 7. Historique de Chat (Chat Sessions & Messages)
            await seed_chat_history(conn, users_map)

    # Récupération des statistiques consolidées pour le rapport
    async with pool.acquire() as conn:
        total_planters = await conn.fetchval(
            "SELECT count(*) FROM users WHERE role = 'PLANTER' AND cooperative_id = $1",
            caped_id
        )
        admins = await conn.fetch(
            "SELECT first_name, last_name, phone_number, role FROM users WHERE role = 'COOP_ADMIN' AND cooperative_id = $1",
            caped_id
        )
        recoltes_stats = await conn.fetchrow(
            """
            SELECT count(*) AS total_count, COALESCE(SUM(weight_kg), 0) AS total_weight
            FROM recoltes
            WHERE user_id IN (SELECT id FROM users WHERE cooperative_id = $1)
            """,
            caped_id
        )
        diags_stats = await conn.fetch(
            """
            SELECT disease_name, count(*) AS count
            FROM diagnostics
            WHERE user_id IN (SELECT id FROM users WHERE cooperative_id = $1)
            GROUP BY disease_name
            ORDER BY count DESC
            """,
            caped_id
        )
        total_activities = await conn.fetchval(
            """
            SELECT count(*) FROM activities
            WHERE user_id IN (SELECT id FROM users WHERE cooperative_id = $1)
            """,
            caped_id
        )

    await close_pool()

    summary = {
        "total_planters": total_planters,
        "admins": [dict(a) for a in admins],
        "total_recoltes": recoltes_stats["total_count"],
        "total_tonnage_tonnes": round(float(recoltes_stats["total_weight"]) / 1000.0, 3),
        "total_weight_kg": float(recoltes_stats["total_weight"]),
        "diagnostics_by_disease": {r["disease_name"]: r["count"] for r in diags_stats},
        "total_activities": total_activities,
    }

    logger.info("=== FIN DE L'INJECTION AVEC SUCCÈS ===")
    return summary

if __name__ == "__main__":
    result = asyncio.run(run_seed())
    print("\n" + "=" * 50)
    print("RAPPORT SYNTHÈSE D'INJECTION MÉTIER CAPED")
    print("=" * 50)
    print(json.dumps(result, indent=2, ensure_ascii=False))
