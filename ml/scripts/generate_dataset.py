"""
CoopIA - Script de Génération du Dataset Historique Planteurs (500 lignes)
Bloc 2 : Entraînement de Modèle - Étape 1

Ce script génère un jeu de données réaliste calibré sur le secteur agricole ivoirien
(Cacao CCC, Café, Anacarde CCA) pour l'apprentissage supervisé de la détection de décrochage.
"""

import os
import random
import numpy as np
import pandas as pd

# Fixer la graine pour garantir une reproductibilité à 100% (exigence Data Science)
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

NB_PLANTEURS = 500

NOMS_FAMILLE = [
    "Kouamé", "Traoré", "Konan", "N'Guessan", "Bakayoko", "Bamba", "Touré",
    "Yao", "Soro", "Diallo", "Ouattara", "Koffi", "Diomandé", "Koné", "Gbané",
    "Coulibaly", "Sanogo", "Brou", "Dje", "Amani", "Goli", "Seka", "Kouassi"
]

PRENOMS = [
    "Amadou", "Koffi", "Yao", "Sékou", "Moussa", "Jean", "Estelle", "Rosine",
    "Awa", "Fatou", "Adama", "Ibrahim", "Alassane", "Mariam", "Affoué", "Amenan",
    "Seydou", "Lacina", "Désiré", "Hervé", "Clarisse", "Salimata", "Brice"
]

VILLAGES = [
    "Divo", "Soubré", "Gagnoa", "San Pedro", "Meagui", "Duékoué",
    "Man", "Daloa", "Abengourou", "Aboisso", "Pindikro", "Bodokro", "Abobo"
]

CULTURES_CONFIG = {
    "cacao": {
        "poids": 0.65,           # 65% des planteurs
        "rendement_moyen": 950,  # kg/ha
        "rendement_std": 200,
    },
    "cafe": {
        "poids": 0.20,           # 20% des planteurs
        "rendement_moyen": 850,
        "rendement_std": 180,
    },
    "anacarde": {
        "poids": 0.15,           # 15% des planteurs
        "rendement_moyen": 680,
        "rendement_std": 140,
    },
}

data = []

cultures_list = ["cacao", "cafe", "anacarde"]
cultures_probs = [CULTURES_CONFIG[c]["poids"] for c in cultures_list]

for i in range(1, NB_PLANTEURS + 1):
    planteur_id = f"PLT-{i:04d}"
    nom_complet = f"{random.choice(PRENOMS)} {random.choice(NOMS_FAMILLE)}"
    village = random.choice(VILLAGES)
    
    # Choix de la culture
    culture = np.random.choice(cultures_list, p=cultures_probs)
    config = CULTURES_CONFIG[culture]
    
    # 1. Superficie de l'exploitation (1.2 ha à 7.5 ha, moyenne ~3.5 ha)
    superficie_ha = round(float(np.random.gamma(shape=4.0, scale=0.85) + 0.5), 2)
    superficie_ha = max(1.0, min(8.0, superficie_ha))
    
    # 2. Facteur de difficulté latent (0 = situation optimale, 1 = crise sévère)
    latente_difficulte = np.random.beta(a=2.0, b=4.0)
    
    # 3. Nombre d'alertes maladies (0 à 6)
    nb_maladies = int(np.random.poisson(lam=latente_difficulte * 3.8))
    nb_maladies = min(6, nb_maladies)
    
    # 4. Retard moyen de livraison en jours (0 à 35 jours)
    retard_jours = int(np.random.exponential(scale=latente_difficulte * 14.0))
    retard_jours = min(40, retard_jours)
    
    # 5. Jours sans activité mobile / contact coopérative (1 à 90 jours)
    jours_inactivite = int(np.random.exponential(scale=latente_difficulte * 28.0) + 2)
    jours_inactivite = min(90, max(1, jours_inactivite))
    
    # 6. Taux d'approbation qualité des récoltes (0.60 à 1.0)
    taux_approbation = round(float(1.0 - (latente_difficulte * 0.35 + np.random.uniform(0, 0.08))), 2)
    taux_approbation = max(0.55, min(1.0, taux_approbation))
    
    # 7. Rendement réel en kg/ha
    malus_maladie = (nb_maladies * 0.09)
    rendement_base = np.random.normal(config["rendement_moyen"], config["rendement_std"])
    rendement_kg_ha = float(rendement_base * (1.0 - (latente_difficulte * 0.40) - malus_maladie))
    rendement_kg_ha = max(70.0, round(rendement_kg_ha, 1))
    
    # 8. Tonnage total livré (en kg)
    tonnage_livre_kg = round(superficie_ha * rendement_kg_ha, 1)
    
    # 9. Écart par rapport à l'objectif de récolte de la coopérative (%)
    rendement_cible = config["rendement_moyen"]
    ecart_objectif_pct = round(((rendement_kg_ha - rendement_cible) / rendement_cible) * 100, 1)
    
    # 10. Formule calibrée de probabilité de décrochage (cible ~20% de churn représentatif)
    score_risque = (
        - 0.70                                     # Calibrage pour ~20% de taux positif
        + 0.048 * retard_jours                     # Retard de livraison
        + 0.040 * jours_inactivite                 # Inactivité sur l'application
        + 0.38  * nb_maladies                      # Pression phytosanitaire
        - 0.0025 * rendement_kg_ha                 # Un fort rendement fidélise le producteur
        - 2.2   * (taux_approbation - 0.8)         # Rejet de récoltes = mécontentement
        + np.random.normal(0, 0.35)                # Aléa réel
    )
    
    proba_decrochage = 1.0 / (1.0 + np.exp(-score_risque))
    a_decroche = 1 if proba_decrochage >= 0.50 else 0
    
    data.append({
        "id_planteur": planteur_id,
        "nom_complet": nom_complet,
        "village": village,
        "culture": culture,
        "superficie_ha": superficie_ha,
        "rendement_kg_ha": rendement_kg_ha,
        "tonnage_livre_kg": tonnage_livre_kg,
        "ecart_objectif_pct": ecart_objectif_pct,
        "taux_approbation": taux_approbation,
        "retard_moyen_jours": retard_jours,
        "nb_maladies": nb_maladies,
        "jours_inactivite": jours_inactivite,
        "a_decroche": a_decroche,
    })

df = pd.DataFrame(data)

# Sortie vers le dossier ml/data
target_csv = r"C:\Users\Simplon-CI\.gemini\antigravity-ide\scratch\chatgo-backend\ml\data\dataset_planteurs_500.csv"
os.makedirs(os.path.dirname(target_csv), exist_ok=True)
df.to_csv(target_csv, index=False, encoding="utf-8")

print(f"SUCCESS: {len(df)} planteurs generes dans : {target_csv}")
taux_churn = (df['a_decroche'].sum() / len(df)) * 100
print(f"Planteurs fideles (0) : {len(df) - df['a_decroche'].sum()} ({100 - taux_churn:.1f}%)")
print(f"Planteurs en decrochage (1) : {df['a_decroche'].sum()} ({taux_churn:.1f}%)")
print(f"Cultures : {dict(df['culture'].value_counts())}")
