#!/usr/bin/env python3
"""
=============================================================================
Projet : CoopIA - Backend FastAPI & Socle Décisionnel CAPED
Fichier : export_powerbi_data.py
Description : Script d'extraction automatisée et génération des tables Power BI
              (Modélisation en Étoile - Tables Dimensionnelles, Faits et Références).
Auteur : Équipe CoopIA (Brief 2 - Data Analyst & Power BI C2)
Encodage : utf-8-sig (compatibilité native Power BI Desktop & Excel)
=============================================================================
RÈGLE CRUCIALE D'ÉVOLUTIVITÉ :
ZÉRO HARDCODING DES VILLAGES.
La liste des localités actives est extraite dynamiquement de la base Neon :
`SELECT DISTINCT village FROM parcelles WHERE village IS NOT NULL;`
=============================================================================
"""

import asyncio
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# Ajout du chemin racine du projet pour importer l'application
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Fix encodage console Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.core.database import get_pool, close_pool

# Répertoire de sortie des exports Power BI
OUTPUT_DIR = ROOT_DIR / "powerbi_data"


def format_dt(dt):
    """Formate une date/heure en chaîne ISO standard pour Power BI."""
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def write_csv_utf8_sig(filepath: Path, fieldnames: list[str], rows: list[dict]):
    """Écrit un fichier CSV encodé en UTF-8-SIG avec délimiteur virgule."""
    with open(filepath, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  -> {filepath.name} généré ({len(rows)} enregistrements, {filepath.stat().st_size} octets)")


async def export_powerbi_data():
    """Fonction principale d'exportation."""
    print("==================================================================")
    print("🚀 DÉMARRAGE DE L'EXPORTATION ANALYTIQUE POWER BI (CoopIA / CAPED)")
    print("==================================================================")
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"📁 Dossier de destination : {OUTPUT_DIR}")

    pool = await get_pool()

    async with pool.acquire() as conn:
        # =====================================================================
        # 1. EXTRACTION DYNAMIQUE DES VILLAGES (ZÉRO HARDCODING)
        # =====================================================================
        print("\n🔍 1. Extraction dynamique des villages actifs...")
        village_rows = await conn.fetch(
            "SELECT DISTINCT village FROM parcelles WHERE village IS NOT NULL ORDER BY village;"
        )
        active_villages = [r["village"] for r in village_rows if r["village"]]
        print(f"  ✓ {len(active_villages)} villages dynamiquement détectés : {active_villages}")

        # Superficies par village pour calibrage dynamique des cibles de production
        village_sup_rows = await conn.fetch(
            """
            SELECT village, COALESCE(SUM(superficie), 0) AS total_sup, COUNT(id) AS parcelles_count
            FROM parcelles
            WHERE village IS NOT NULL
            GROUP BY village;
            """
        )
        village_sup_map = {r["village"]: float(r["total_sup"]) for r in village_sup_rows}

        # =====================================================================
        # 2. DIMENSION : COOPÉRATIVES (dim_cooperatives.csv)
        # =====================================================================
        print("\n🏛️ 2. Export de dim_cooperatives.csv...")
        coop_rows = await conn.fetch(
            "SELECT id, name, code, region, created_at FROM cooperatives ORDER BY created_at;"
        )
        coop_data = []
        for r in coop_rows:
            coop_data.append({
                "id": str(r["id"]),
                "name": r["name"],
                "code": r["code"],
                "region": r["region"] or "Côte d'Ivoire",
                "created_at": format_dt(r["created_at"]),
            })
        write_csv_utf8_sig(
            OUTPUT_DIR / "dim_cooperatives.csv",
            ["id", "name", "code", "region", "created_at"],
            coop_data
        )

        # =====================================================================
        # 3. DIMENSION : PLANTEURS (dim_planteurs.csv)
        # =====================================================================
        print("\n👨‍🌾 3. Export de dim_planteurs.csv (role = 'PLANTER')...")
        planter_rows = await conn.fetch(
            """
            SELECT id, first_name, last_name, phone_number, cooperative_id, role, avatar_url, created_at
            FROM users
            WHERE role = 'PLANTER'
            ORDER BY created_at ASC;
            """
        )
        planter_data = []
        for r in planter_rows:
            fn = r["first_name"] or ""
            ln = r["last_name"] or ""
            nom_complet = f"{fn} {ln}".strip() or "Planteur Inconnu"
            planter_data.append({
                "id": str(r["id"]),
                "nom_complet": nom_complet,
                "first_name": fn,
                "last_name": ln,
                "telephone": r["phone_number"],
                "cooperative_id": str(r["cooperative_id"]) if r["cooperative_id"] else "",
                "role": r["role"],
                "avatar_url": r["avatar_url"] or "",
                "date_adhesion": format_dt(r["created_at"]),
            })
        write_csv_utf8_sig(
            OUTPUT_DIR / "dim_planteurs.csv",
            ["id", "nom_complet", "first_name", "last_name", "telephone", "cooperative_id", "role", "avatar_url", "date_adhesion"],
            planter_data
        )

        # =====================================================================
        # 4. DIMENSION : PARCELLES (dim_parcelles.csv)
        # =====================================================================
        print("\n🗺️ 4. Export de dim_parcelles.csv (avec extraction GPS)...")
        parcelle_rows = await conn.fetch(
            """
            SELECT id, user_id, name, crop_type, superficie, village, gps_coordinates, created_at
            FROM parcelles
            ORDER BY village, name;
            """
        )
        parcelle_data = []
        for r in parcelle_rows:
            coords = r["gps_coordinates"]
            if isinstance(coords, str):
                try:
                    coords = json.loads(coords)
                except Exception:
                    coords = {}
            elif not isinstance(coords, dict):
                coords = {}

            lat = coords.get("lat") or coords.get("latitude")
            lng = coords.get("lng") or coords.get("longitude")
            sup = float(r["superficie"]) if r["superficie"] is not None else 0.0

            parcelle_data.append({
                "id": str(r["id"]),
                "user_id": str(r["user_id"]) if r["user_id"] else "",
                "name": r["name"],
                "crop_type": r["crop_type"],
                "superficie_ha": round(sup, 2),
                "village": r["village"] or "Non spécifié",
                "latitude": round(float(lat), 6) if lat is not None else "",
                "longitude": round(float(lng), 6) if lng is not None else "",
                "created_at": format_dt(r["created_at"]),
            })
        write_csv_utf8_sig(
            OUTPUT_DIR / "dim_parcelles.csv",
            ["id", "user_id", "name", "crop_type", "superficie_ha", "village", "latitude", "longitude", "created_at"],
            parcelle_data
        )

        # =====================================================================
        # 5. FAIT : RÉCOLTES (fact_recoltes.csv)
        # =====================================================================
        print("\n⚖️ 5. Export de fact_recoltes.csv (Multi-filières : barèmes officiels CCC / CCA)...")
        recolte_rows = await conn.fetch(
            """
            SELECT id, parcelle_id, user_id, crop_type, weight_kg, number_of_bags, bordereau_ref, unit_price_fcfa, valeur_totale_fcfa, status, harvest_date, created_at
            FROM recoltes
            ORDER BY harvest_date DESC;
            """
        )
        recolte_data = []
        for r in recolte_rows:
            weight = float(r["weight_kg"])
            unit_price = r["unit_price_fcfa"] or 1850
            montant_garanti = r["valeur_totale_fcfa"] if r["valeur_totale_fcfa"] is not None else int(round(weight * unit_price))

            recolte_data.append({
                "recolte_id": str(r["id"]),
                "user_id": str(r["user_id"]) if r["user_id"] else "",
                "parcelle_id": str(r["parcelle_id"]) if r["parcelle_id"] else "",
                "crop_type": r["crop_type"] or "cacao",
                "poids_kg": round(weight, 2),
                "nombre_sacs": r["number_of_bags"],
                "bordereau_ref": r["bordereau_ref"] or "",
                "prix_unitaire_fcfa": unit_price,
                "montant_garanti_fcfa": montant_garanti,
                "statut": r["status"],
                "date_recolte": format_dt(r["harvest_date"]),
                "created_at": format_dt(r["created_at"]),
            })
        write_csv_utf8_sig(
            OUTPUT_DIR / "fact_recoltes.csv",
            ["recolte_id", "user_id", "parcelle_id", "crop_type", "poids_kg", "nombre_sacs", "bordereau_ref", "prix_unitaire_fcfa", "montant_garanti_fcfa", "statut", "date_recolte", "created_at"],
            recolte_data
        )

        # =====================================================================
        # 6. FAIT : DIAGNOSTICS (fact_diagnostics.csv)
        # =====================================================================
        print("\n🔬 6. Export de fact_diagnostics.csv (alertes sanitaires & IA)...")
        diagnostic_rows = await conn.fetch(
            """
            SELECT id, parcelle_id, user_id, disease_name, confidence_score, image_url, recommended_action, status, created_at
            FROM diagnostics
            ORDER BY created_at DESC;
            """
        )
        diagnostic_data = []
        for r in diagnostic_rows:
            score = float(r["confidence_score"]) if r["confidence_score"] is not None else None
            diagnostic_data.append({
                "id": str(r["id"]),
                "parcelle_id": str(r["parcelle_id"]) if r["parcelle_id"] else "",
                "user_id": str(r["user_id"]) if r["user_id"] else "",
                "disease_name": r["disease_name"],
                "confidence_score": round(score, 4) if score is not None else "",
                "image_url": r["image_url"] or "",
                "recommended_action": (r["recommended_action"] or "").replace("\n", " ").strip(),
                "status": r["status"],
                "created_at": format_dt(r["created_at"]),
            })
        write_csv_utf8_sig(
            OUTPUT_DIR / "fact_diagnostics.csv",
            ["id", "parcelle_id", "user_id", "disease_name", "confidence_score", "image_url", "recommended_action", "status", "created_at"],
            diagnostic_data
        )

        # =====================================================================
        # 7. RÉFÉRENCE EXTERNE : PLUVIOMÉTRIE & MÉTÉO (ref_meteo_pluviometrie.csv)
        # Généré STRICTEMENT pour les villages extraits de la table parcelles.
        # Pics pluvieux > 100mm en JUIN et SEPTEMBRE (corrélation sanitaire).
        # =====================================================================
        print("\n🌧️ 7. Export de ref_meteo_pluviometrie.csv (Mai à Octobre 2026, 100% dynamique)...")

        # Profil saisonnier de base de la zone forestière café-cacao en Côte d'Ivoire
        # Juin (Grande saison des pluies) & Septembre (Petite saison des pluies) > 100 mm
        base_monthly_climate = [
            {"mois_num": 5, "mois_nom": "Mai", "annee": 2026, "date_debut": "2026-05-01", "date_fin": "2026-05-31", "base_rain": 78.0, "base_temp": 28.5, "base_hum": 80},
            {"mois_num": 6, "mois_nom": "Juin", "annee": 2026, "date_debut": "2026-06-01", "date_fin": "2026-06-30", "base_rain": 165.0, "base_temp": 26.0, "base_hum": 88},
            {"mois_num": 7, "mois_nom": "Juillet", "annee": 2026, "date_debut": "2026-07-01", "date_fin": "2026-07-31", "base_rain": 55.0, "base_temp": 25.5, "base_hum": 78},
            {"mois_num": 8, "mois_nom": "Août", "annee": 2026, "date_debut": "2026-08-01", "date_fin": "2026-08-31", "base_rain": 46.0, "base_temp": 25.0, "base_hum": 76},
            {"mois_num": 9, "mois_nom": "Septembre", "annee": 2026, "date_debut": "2026-09-01", "date_fin": "2026-09-30", "base_rain": 138.0, "base_temp": 26.5, "base_hum": 86},
            {"mois_num": 10, "mois_nom": "Octobre", "annee": 2026, "date_debut": "2026-10-01", "date_fin": "2026-10-31", "base_rain": 82.0, "base_temp": 27.5, "base_hum": 82},
        ]

        meteo_data = []
        for village in active_villages:
            # Variation microclimatique déterministe basée sur le nom du village (-6mm à +8mm)
            village_hash = sum(ord(c) for c in village)
            rain_jitter = (village_hash % 15) - 6
            temp_jitter = round(((village_hash % 9) - 4) * 0.1, 1)

            for m in base_monthly_climate:
                rain_val = round(max(30.0, m["base_rain"] + rain_jitter), 1)
                temp_val = round(m["base_temp"] + temp_jitter, 1)
                hum_val = int(min(95, max(65, m["base_hum"] + int(rain_jitter * 0.4))))

                # Garantie absolue de la consigne : > 100mm en juin et septembre
                if m["mois_num"] in (6, 9) and rain_val <= 100.0:
                    rain_val = 125.0

                is_pic = "OUI" if rain_val > 100.0 else "NON"
                
                # Évaluation du risque phytosanitaire (pourriture brune favorisée par humidité + pluie)
                if rain_val > 100.0:
                    risk = "ÉLEVÉ"
                elif rain_val > 65.0:
                    risk = "MODÉRÉ"
                else:
                    risk = "FAIBLE"

                meteo_data.append({
                    "id": f"METEO-{village.upper()[:4]}-{m['annee']}{m['mois_num']:02d}",
                    "village": village,
                    "annee": m["annee"],
                    "mois": m["mois_num"],
                    "mois_nom": m["mois_nom"],
                    "date_debut": m["date_debut"],
                    "date_fin": m["date_fin"],
                    "pluviometrie_mm": rain_val,
                    "temperature_c": temp_val,
                    "humidite_pct": hum_val,
                    "pic_pluvieux": is_pic,
                    "risque_phytosanitaire": risk,
                })

        write_csv_utf8_sig(
            OUTPUT_DIR / "ref_meteo_pluviometrie.csv",
            ["id", "village", "annee", "mois", "mois_nom", "date_debut", "date_fin", "pluviometrie_mm", "temperature_c", "humidite_pct", "pic_pluvieux", "risque_phytosanitaire"],
            meteo_data
        )

        # =====================================================================
        # 8. RÉFÉRENCE EXTERNE : CIBLES DE PRODUCTION (ref_cibles_production.csv)
        # Généré STRICTEMENT pour les villages existants dans la table parcelles.
        # =====================================================================
        print("\n🎯 8. Export de ref_cibles_production.csv (Objectifs mensuels de campagne)...")

        # Facteurs mensuels de saisonnalité agricole (calendrier cacao/café ivoirien)
        # Mai-Août : Campagne intermédiaire (flux modéré)
        # Septembre-Octobre : Début de la Grande Campagne principale (montée en puissance)
        campaign_months = [
            {"mois_num": 5, "mois_nom": "Mai", "annee": 2026, "campagne": "Campagne Intermédiaire 2026", "kg_per_ha": 120},
            {"mois_num": 6, "mois_nom": "Juin", "annee": 2026, "campagne": "Campagne Intermédiaire 2026", "kg_per_ha": 150},
            {"mois_num": 7, "mois_nom": "Juillet", "annee": 2026, "campagne": "Campagne Intermédiaire 2026", "kg_per_ha": 90},
            {"mois_num": 8, "mois_nom": "Août", "annee": 2026, "campagne": "Campagne Intermédiaire 2026", "kg_per_ha": 80},
            {"mois_num": 9, "mois_nom": "Septembre", "annee": 2026, "campagne": "Grande Campagne Principale 2026/2027", "kg_per_ha": 260},
            {"mois_num": 10, "mois_nom": "Octobre", "annee": 2026, "campagne": "Grande Campagne Principale 2026/2027", "kg_per_ha": 420},
        ]

        cibles_data = []
        for village in active_villages:
            village_ha = village_sup_map.get(village, 2.5)  # Superficie observée ou 2.5 ha par défaut
            
            for cm in campaign_months:
                # Cible proportionnelle à la superficie du village
                raw_target_kg = village_ha * cm["kg_per_ha"]
                # Arrondi propre à la tranche de 50 kg avec un plancher minimal de 250 kg
                target_kg = max(250.0, round(raw_target_kg / 50.0) * 50.0)
                target_tonnes = round(target_kg / 1000.0, 3)
                target_sacs = int(round(target_kg / 65.0))  # Sac standard CCC = 65 kg

                cibles_data.append({
                    "id": f"CIBLE-{village.upper()[:4]}-{cm['annee']}{cm['mois_num']:02d}",
                    "village": village,
                    "annee": cm["annee"],
                    "mois": cm["mois_num"],
                    "mois_nom": cm["mois_nom"],
                    "campagne": cm["campagne"],
                    "cible_tonnage_kg": round(target_kg, 1),
                    "cible_tonnes": target_tonnes,
                    "cible_sacs_65kg": target_sacs,
                })

        write_csv_utf8_sig(
            OUTPUT_DIR / "ref_cibles_production.csv",
            ["id", "village", "annee", "mois", "mois_nom", "campagne", "cible_tonnage_kg", "cible_tonnes", "cible_sacs_65kg"],
            cibles_data
        )

    await close_pool()

    print("\n==================================================================")
    print("✅ EXPORTATION POWER BI TERMINÉE AVEC SUCCÈS !")
    print(f"📦 7 fichiers CSV générés dans {OUTPUT_DIR.resolve()} :")
    for f in OUTPUT_DIR.glob("*.csv"):
        print(f"   • {f.name} ({f.stat().st_size} octets)")
    print("==================================================================")


if __name__ == "__main__":
    asyncio.run(export_powerbi_data())
