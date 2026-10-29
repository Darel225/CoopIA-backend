"""
=============================================================================
Projet : CoopIA - Backend FastAPI & Socle Analytique CAPED
Fichier : app/core/pricing.py
Description : Référentiel centralisé des cours officiels de campagne et barèmes
              agronomiques par filière en Côte d'Ivoire (CCC, CCA, APROMAC).
=============================================================================
"""

import unicodedata
from typing import Optional, TypedDict


class CropPricingInfo(TypedDict):
    key: str
    price_kg: int
    board: str
    label: str
    optimal_yield_kg_ha: float
    satisfactory_yield_kg_ha: float


# Table de référence officielle Côte d'Ivoire — Campagne 2026
OFFICIAL_CROP_PRICES: dict[str, CropPricingInfo] = {
    "cacao": {
        "key": "cacao",
        "price_kg": 1850,
        "board": "CCC",
        "label": "Cacao CCC",
        "optimal_yield_kg_ha": 800.0,
        "satisfactory_yield_kg_ha": 400.0,
    },
    "cafe": {
        "key": "cafe",
        "price_kg": 1000,
        "board": "CCC",
        "label": "Café Robusta CCC",
        "optimal_yield_kg_ha": 700.0,
        "satisfactory_yield_kg_ha": 350.0,
    },
    "anacarde": {
        "key": "anacarde",
        "price_kg": 350,
        "board": "CCA",
        "label": "Anacarde CCA",
        "optimal_yield_kg_ha": 550.0,
        "satisfactory_yield_kg_ha": 300.0,
    },
    "hevea": {
        "key": "hevea",
        "price_kg": 350,
        "board": "APROMAC",
        "label": "Hévéa / Caoutchouc APROMAC",
        "optimal_yield_kg_ha": 1200.0,
        "satisfactory_yield_kg_ha": 700.0,
    },
    "vivrier": {
        "key": "vivrier",
        "price_kg": 0,
        "board": "Marché libre",
        "label": "Vivrier divers",
        "optimal_yield_kg_ha": 5000.0,
        "satisfactory_yield_kg_ha": 2000.0,
    },
}


def normalize_crop_name(crop_name: Optional[str]) -> str:
    """Normalise une chaîne de culture en retirant les accents et espaces superflus."""
    if not crop_name:
        return "cacao"
    nfkd_form = unicodedata.normalize("NFKD", str(crop_name))
    ascii_str = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    return ascii_str.lower().strip()


def get_crop_pricing(crop_name: Optional[str]) -> CropPricingInfo:
    """
    Retourne la configuration tarifaire et agronomique officielle pour une culture donnée.
    Tolérant aux variantes orthographiques, synonymes et accents :
      - 'café', 'cafeier', 'coffee' -> cafe (1 000 FCFA)
      - 'cajou', 'anacardier', 'cashew' -> anacarde (350 FCFA)
      - 'caoutchouc', 'rubber' -> hevea (350 FCFA)
      - 'manioc', 'igname', 'banane', 'riz', 'mais' -> vivrier
      - Défaut -> cacao (1 850 FCFA)
    """
    clean = normalize_crop_name(crop_name)

    if any(k in clean for k in ("caf", "coffee")):
        return OFFICIAL_CROP_PRICES["cafe"]
    elif any(k in clean for k in ("anacard", "cajou", "cashew")):
        return OFFICIAL_CROP_PRICES["anacarde"]
    elif any(k in clean for k in ("hevea", "caoutchouc", "rubber")):
        return OFFICIAL_CROP_PRICES["hevea"]
    elif any(k in clean for k in ("vivrier", "manioc", "igname", "banane", "riz", "mais", "maraich")):
        return OFFICIAL_CROP_PRICES["vivrier"]
    else:
        # Cacao par défaut
        return OFFICIAL_CROP_PRICES["cacao"]


def evaluate_yield_status(crop_name: Optional[str], yield_kg_ha: float) -> str:
    """
    Évalue le statut agronomique ('OPTIMAL', 'SATISFAISANT', 'SOUS-PERFORMANCE')
    en appliquant les seuils agronomiques spécifiques à la filière.
    """
    pricing = get_crop_pricing(crop_name)
    opt = pricing["optimal_yield_kg_ha"]
    sat = pricing["satisfactory_yield_kg_ha"]

    if yield_kg_ha >= opt:
        return "OPTIMAL"
    elif yield_kg_ha >= sat:
        return "SATISFAISANT"
    else:
        return "SOUS-PERFORMANCE"
