import logging
from typing import Optional
from fastapi import APIRouter, Depends, Query
from asyncpg import Connection
import httpx

from app.core.database import get_db_connection
from app.core.security import get_current_user
from app.models.schemas import UserOut, WeatherOut

logger = logging.getLogger("weather")

router = APIRouter()

# Dictionnaire des coordonnées géographiques des grands bassins agricoles ivoiriens
IVORIAN_COORDINATES = {
    "bodokro": {"lat": 7.45, "lon": -5.07, "name": "Bodokro"},
    "pindikro": {"lat": 6.85, "lon": -5.00, "name": "Pindikro"},
    "soubre": {"lat": 5.78, "lon": -6.60, "name": "Soubré"},
    "soubré": {"lat": 5.78, "lon": -6.60, "name": "Soubré"},
    "man": {"lat": 7.41, "lon": -7.55, "name": "Man"},
    "divo": {"lat": 5.83, "lon": -5.36, "name": "Divo"},
    "yamoussoukro": {"lat": 6.82, "lon": -5.28, "name": "Yamoussoukro"},
    "abidjan": {"lat": 5.36, "lon": -4.01, "name": "Abidjan"},
    "gagnoa": {"lat": 6.13, "lon": -5.95, "name": "Gagnoa"},
    "daloa": {"lat": 6.88, "lon": -6.45, "name": "Daloa"},
    "san pedro": {"lat": 4.75, "lon": -6.64, "name": "San Pédro"},
    "san pédro": {"lat": 4.75, "lon": -6.64, "name": "San Pédro"},
    "bouake": {"lat": 7.69, "lon": -5.03, "name": "Bouaké"},
    "bouaké": {"lat": 7.69, "lon": -5.03, "name": "Bouaké"},
    "abengourou": {"lat": 6.73, "lon": -3.50, "name": "Abengourou"},
    "tiassale": {"lat": 5.90, "lon": -4.83, "name": "Tiassalé"},
    "tiassalé": {"lat": 5.90, "lon": -4.83, "name": "Tiassalé"},
    "meagui": {"lat": 5.40, "lon": -6.95, "name": "Méagui"},
    "méagui": {"lat": 5.40, "lon": -6.95, "name": "Méagui"},
}

def map_wmo_code(code: int) -> tuple[str, str]:
    """Mappe le code météorologique WMO en libellé français et icône Ionicons."""
    if code == 0:
        return "Ensoleillé", "sunny-outline"
    elif code in (1, 2):
        return "Partiellement voilé", "partly-sunny-outline"
    elif code == 3:
        return "Ensoleillé voilé", "partly-sunny-outline"
    elif code in (45, 48):
        return "Brume matinale", "cloud-outline"
    elif code in (51, 53, 55):
        return "Bruine légère", "rainy-outline"
    elif code in (61, 63, 65):
        return "Pluie continue", "rainy-outline"
    elif code in (80, 81, 82):
        return "Averses orageuses", "rainy-outline"
    elif code in (95, 96, 99):
        return "Orages violents", "thunderstorm-outline"
    return "Ensoleillé voilé", "partly-sunny-outline"

def generate_agronomic_advice(
    code: int,
    temp: float,
    hum: int,
    precip: float,
    wind: float,
    current_time_str: Optional[str],
    hourly_precip_prob: list[int],
    hourly_precip: list[float]
) -> tuple[str, str]:
    """
    Génère un conseil agronomique contextuel rigoureux pour le planteur de cacao/café
    fondé sur les conditions météo réelles et prévisions immédiates (Recommandations ANADER / CNRA).
    """
    # 1. Extraction de l'heure courante locale (ex: "2026-10-20T09:45" -> 9)
    current_hour = 10
    if current_time_str and "T" in current_time_str:
        try:
            current_hour = int(current_time_str.split("T")[1].split(":")[0])
        except (ValueError, IndexError):
            current_hour = 10

    # 2. Orages ou pluies soutenues en cours
    if code in (95, 96, 99):
        return "Orages en cours •", "Suspendre les travaux et se mettre à l'abri"
    if code in (61, 63, 65, 80, 81, 82) or precip >= 1.0:
        return "Pluie en cours •", "Suspendre les travaux et abriter les récoltes"

    # 3. Bruine légère ou crachin tropical en cours
    if code in (51, 53, 55) or (0.2 <= precip < 1.0):
        return "Bruine légère •", "Reporter les traitements foliaires et pulvérisations"

    # 4. Vent fort (dérive des pulvérisations)
    if wind >= 20.0:
        return f"Vent soutenu ({round(wind)} km/h) •", "Reporter les pulvérisations (risque de dérive)"

    # 5. Averses probables dans les 1 à 2 prochaines heures uniquement (probabilité élevée >= 60% et pluie >= 0.8mm)
    upcoming_rain_hour = None
    for hour_idx in range(current_hour + 1, min(current_hour + 3, len(hourly_precip_prob))):
        prob = hourly_precip_prob[hour_idx] if hour_idx < len(hourly_precip_prob) else 0
        p_val = hourly_precip[hour_idx] if hour_idx < len(hourly_precip) else 0.0
        if prob >= 60 and p_val >= 0.8:
            upcoming_rain_hour = hour_idx
            break

    if upcoming_rain_hour is not None:
        return f"Averse probable vers {upcoming_rain_hour}h •", "Éviter tout épandage (risque de lessivage)"

    # 6. Temps chaud et ensoleillé / dégagé (Cacao / Café)
    if code in (0, 1, 2, 3):
        if temp >= 28.0:
            return f"Ensoleillé et chaud ({round(temp)}°C) •", "Idéal pour le séchage des fèves sur claies"
        else:
            return "Temps sec et dégagé •", "Conditions favorables pour les récoltes et l'entretien"

    # 7. Risque fongique lié à une forte humidité matinale / nocturne sans pluie
    if hum >= 85 and temp < 27.0:
        return f"Humidité élevée ({hum}%) •", "Surveiller les risques de pourriture brune"

    # 8. Temps stable standard
    return "Temps sec et stable •", "Conditions favorables pour l'épandage et l'entretien"


@router.get("/current", response_model=WeatherOut)
async def get_current_weather(
    lat: Optional[float] = Query(None, description="Latitude GPS optionnelle"),
    lon: Optional[float] = Query(None, description="Longitude GPS optionnelle"),
    current_user: UserOut = Depends(get_current_user),
    conn: Connection = Depends(get_db_connection),
):
    """
    Retourne la météo agricole en temps réel pour la localité ou la parcelle du planteur connecté.
    Utilise l'API Open-Meteo et applique un moteur de conseils agronomiques ivoiriens.
    """
    target_lat = lat
    target_lon = lon
    locality_name = "Bodokro"
    culture_name = "Cacao"

    # Si pas de coordonnées GPS directes, chercher la parcelle du planteur
    if target_lat is None or target_lon is None:
        parcel_row = await conn.fetchrow(
            """
            SELECT village, crop_type, gps_coordinates
            FROM parcelles
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            current_user.id
        )
        if parcel_row:
            village = (parcel_row["village"] or "").strip().lower()
            culture_name = parcel_row["crop_type"] or "Cacao"
            gps = parcel_row.get("gps_coordinates")
            if isinstance(gps, dict) and ("lat" in gps or "latitude" in gps):
                target_lat = float(gps.get("lat") or gps.get("latitude"))
                target_lon = float(gps.get("lon") or gps.get("longitude"))
                locality_name = parcel_row["village"] or "Parcelle"
            else:
                coord_match = None
                for key, val in IVORIAN_COORDINATES.items():
                    if key in village:
                        coord_match = val
                        break
                
                if coord_match:
                    target_lat = coord_match["lat"]
                    target_lon = coord_match["lon"]
                    locality_name = coord_match["name"]
                elif village:
                    locality_name = parcel_row["village"]
                    target_lat = 7.45
                    target_lon = -5.07
                else:
                    target_lat = 7.45
                    target_lon = -5.07
                    locality_name = "Bodokro"
        else:
            # Fallback sur Bodokro
            target_lat = 7.45
            target_lon = -5.07
            locality_name = "Bodokro"

    # Appel Open-Meteo
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": target_lat,
        "longitude": target_lon,
        "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
        "hourly": "precipitation_probability,precipitation",
        "timezone": "Africa/Abidjan",
        "forecast_days": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        current = data.get("current", {})
        temp = float(current.get("temperature_2m", 28.5))
        hum = int(current.get("relative_humidity_2m", 80))
        precip = float(current.get("precipitation", 0.0))
        code = int(current.get("weather_code", 3))
        wind = float(current.get("wind_speed_10m", 8.0))

        hourly = data.get("hourly", {})
        h_probs = hourly.get("precipitation_probability", [])
        h_precips = hourly.get("precipitation", [])

        time_str = current.get("time")
        condition, icon = map_wmo_code(code)
        alert_text, advice_text = generate_agronomic_advice(
            code, temp, hum, precip, wind, time_str, h_probs, h_precips
        )

        return WeatherOut(
            temperature=f"{round(temp)}°C",
            temperature_value=temp,
            condition=condition,
            icon=icon,
            alert=alert_text,
            advice=advice_text,
            humidity=hum,
            wind_speed=wind,
            locality=locality_name,
            culture=culture_name,
        )

    except Exception as exc:
        logger.warning(f"Open-Meteo non joignable ({exc}), utilisation du fallback météo saisonnier.")
        # Fallback élégant en climat tropical ivoirien
        return WeatherOut(
            temperature="29°C",
            temperature_value=29.0,
            condition="Ensoleillé voilé",
            icon="partly-sunny-outline",
            alert="Temps sec et stable •",
            advice="Conditions favorables pour les récoltes et soins",
            humidity=82,
            wind_speed=8.5,
            locality=locality_name,
            culture=culture_name,
        )
