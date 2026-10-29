import asyncio
import asyncpg
import joblib
import os
import pandas as pd
import numpy as np

async def test():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    model_path = os.path.abspath(os.path.join(current_dir, "..", "models", "modele_churn_xgboost.pkl"))
    artefact = joblib.load(model_path)
    model = artefact['model']
    features = artefact['feature_names']
    print('Model features:', features)

    db_url = os.environ.get('DATABASE_URL', 'postgresql://neondb_owner:npg_EUky3sg1raoY@ep-tiny-shadow-b20di0sq-pooler.c-6.eu-central-1.aws.neon.tech/neondb?sslmode=require')
    conn = await asyncpg.connect(db_url)
    rows = await conn.fetch('''
        SELECT 
            u.id, u.first_name, u.last_name,
            p_agg.village, COALESCE(p_agg.crop_type, 'cacao') as culture,
            COALESCE(p_agg.total_superficie, 3.0) as superficie_ha,
            COALESCE(r_agg.total_weight, 0) as tonnage_livre_kg,
            COALESCE(r_agg.approved_weight, 0) as approved_weight,
            COALESCE(d_agg.nb_maladies, 0) as nb_maladies,
            COALESCE(EXTRACT(DAY FROM NOW() - u.created_at), 5)::int as jours_inactivite
        FROM users u
        LEFT JOIN (
            SELECT user_id, SUM(superficie) as total_superficie, 
                   (ARRAY_AGG(village ORDER BY created_at DESC))[1] as village,
                   (ARRAY_AGG(crop_type ORDER BY created_at DESC))[1] as crop_type
            FROM parcelles GROUP BY user_id
        ) p_agg ON p_agg.user_id = u.id
        LEFT JOIN (
            SELECT user_id, SUM(weight_kg) as total_weight,
                   SUM(weight_kg) FILTER (WHERE status = 'APPROVED') as approved_weight
            FROM recoltes GROUP BY user_id
        ) r_agg ON r_agg.user_id = u.id
        LEFT JOIN (
            SELECT user_id, COUNT(id) as nb_maladies FROM diagnostics GROUP BY user_id
        ) d_agg ON d_agg.user_id = u.id
        WHERE u.role = 'PLANTER'
    ''')
    await conn.close()
    
    print(f'Found {len(rows)} planters:')
    for r in rows:
        sup = float(r['superficie_ha']) if r['superficie_ha'] and float(r['superficie_ha']) > 0 else 3.0
        livre = float(r['tonnage_livre_kg'])
        appr = float(r['approved_weight'])
        rendement = livre / sup if sup > 0 else 0
        objectif = sup * 750 # 750 kg/ha
        ecart_pct = ((livre - objectif) / objectif) * 100
        taux_appr = (appr / livre) if livre > 0 else 0.85
        nb_mal = int(r['nb_maladies'])
        jours_inact = int(r['jours_inactivite']) if r['jours_inactivite'] else 7
        culture = (r['culture'] or 'cacao').lower()

        feat_dict = {
            'superficie_ha': sup,
            'rendement_kg_ha': round(rendement, 1),
            'tonnage_livre_kg': round(livre, 1),
            'ecart_objectif_pct': round(ecart_pct, 1),
            'taux_approbation': round(taux_appr, 2),
            'retard_moyen_jours': 3.0 if livre == 0 else 1.0,
            'nb_maladies': nb_mal,
            'jours_inactivite': jours_inact,
            'culture_anacarde': 1 if 'anacard' in culture else 0,
            'culture_cacao': 1 if 'cacao' in culture else 0,
            'culture_cafe': 1 if 'caf' in culture else 0,
        }
        df_row = pd.DataFrame([feat_dict])[features]
        proba = model.predict_proba(df_row)[0][1]
        score_pct = int(round(proba * 100))
        level = 'Critique' if score_pct >= 60 else ('Moyen' if score_pct >= 25 else 'Faible')
        name = f"{r['first_name']} {r['last_name']}"
        print(f"- {name:<22} ({r['village'] or 'N/A':<10}, {culture:<8}): Score Churn = {score_pct:>2}%, Niveau = {level}")

if __name__ == '__main__':
    asyncio.run(test())
