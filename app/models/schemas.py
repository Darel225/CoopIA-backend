from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from uuid import UUID
from datetime import datetime

# ============================================================
# AUTHENTIFICATION
# ============================================================

# Format E.164 : +[code pays][numéro] sans espaces
PHONE_REGEX = r"^\+[1-9]\d{7,14}$"

class RequestOTPInput(BaseModel):
    phone_number: str = Field(..., pattern=PHONE_REGEX, description="Numéro de téléphone au format E.164")

class VerifyOTPInput(BaseModel):
    phone_number: str = Field(..., pattern=PHONE_REGEX)
    code: str = Field(..., min_length=6, max_length=6)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    requires_profile_setup: bool = False
    user: Optional[dict] = None

# ============================================================
# UTILISATEURS (OUTPUTS)
# ============================================================

class UserOut(BaseModel):
    id: UUID
    phone_number: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    cooperative_id: Optional[UUID] = None
    cooperative_name: Optional[str] = None
    role: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: Optional[datetime] = None
    village: Optional[str] = None
    culture: Optional[str] = None

# ============================================================
# PROFIL (Schémas CoopIA)
# ============================================================

class AvatarUploadResponse(BaseModel):
    success: bool = True
    avatar_url: str
    message: str = "Photo de profil mise à jour avec succès."

class ProfileSetupInput(BaseModel):
    nom_complet: str
    village: str
    culture_principale: str
    superficie: Optional[float] = Field(None, ge=0.0, description="Superficie exploitée en hectares (ex: 3.50)")

class UpdateProfileInput(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    nom: Optional[str] = None
    prenom: Optional[str] = None
    email: Optional[str] = None
    photo_url: Optional[str] = ""

# ============================================================
# CHAT / AGENT IA (Anciens schémas)
# ============================================================

class ConvCommerceInput(BaseModel):
    session_id: str
    email: str
    message: str = Field(..., max_length=1000)
    user_location: Optional[str] = "Abidjan"

# ============================================================
# HISTORIQUE (Anciens schémas)
# ============================================================

class HistoryInput(BaseModel):
    email: str

class SessionInput(BaseModel):
    session_id: str
    email: str

class ClearHistoryInput(BaseModel):
    email: str

# ============================================================
# COOPIA CHAT (Nouveaux schémas Phase 1)
# ============================================================

class ChatMessageInput(BaseModel):
    session_id: Optional[UUID] = None
    text: str = Field(..., min_length=1, max_length=1000)

class ChatSessionResponse(BaseModel):
    id: UUID
    user_id: Optional[UUID] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    sous_titre: Optional[str] = None
    status: Optional[str] = "Actif"
    statut: Optional[str] = "Actif"
    created_at: datetime
    updated_at: Optional[datetime] = None
    message_count: int = 0

class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    text: str
    is_user: bool
    created_at: datetime
    recommendations: Optional[list] = None
    media_url: Optional[str] = None

class ChatSendResponse(BaseModel):
    session_id: UUID
    user_message: ChatMessageResponse
    agent_message: ChatMessageResponse

class ActionRecolte(BaseModel):
    est_declaration: bool = False
    nombre_sacs: Optional[int] = None
    poids_kg: Optional[float] = None
    montant_estime_fcfa: Optional[int] = None

class CoopiaLLMResponse(BaseModel):
    reponse_texte: str = Field(..., min_length=1)
    recommendations: Optional[list[dict]] = Field(default_factory=list)
    action_recolte: Optional[ActionRecolte] = None

# ============================================================
# ACTIVITÉS / DASHBOARD
# ============================================================

class ActivityOut(BaseModel):
    id: UUID
    user_id: Optional[UUID] = None
    type: str
    reference_id: Optional[UUID] = None
    session_id: Optional[UUID] = None
    title: str
    subtitle: Optional[str] = None
    ui_color_tag: Optional[str] = None
    created_at: datetime
    planter_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

# ============================================================
# MÉTÉO AGRICOLE
# ============================================================

class WeatherOut(BaseModel):
    temperature: str
    temperature_value: float
    condition: str
    icon: str
    alert: str
    advice: str
    humidity: int
    wind_speed: float
    locality: str
    culture: Optional[str] = None


# ============================================================
# GESTION COOPÉRATIVE (TABLEAU DE BORD WEB)
# ============================================================

class SectionStat(BaseModel):
    section: str
    crop: str
    parcelles_count: int
    superficie_ha: float
    planters_count: int
    tonnage_total_kg: Optional[float] = 0.0
    tonnage_total_tonnes: Optional[float] = 0.0

class AlertSummary(BaseModel):
    disease_name: str
    status: str
    count: int

class DailyDeliveryItem(BaseModel):
    jour: str
    date_iso: str
    volume: float
    sacs: int
    valeur_fcfa: int
    is_real: bool = True

class FiliereStatItem(BaseModel):
    filiere: str
    libelle: str
    prix_unitaire_ref: int
    tonnage_kg: float
    tonnage_tonnes: float
    part_production_pct: float
    valeur_fcfa: int

class CoopKPIsResponse(BaseModel):
    cooperative_id: UUID
    cooperative_name: str
    total_tonnage_tonnes: float
    total_weight_kg: float
    approved_tonnage_tonnes: float
    approved_weight_kg: float
    pending_tonnage_tonnes: float
    pending_weight_kg: float
    valeur_totale_fcfa: Optional[int] = None
    valeur_validee_fcfa: Optional[int] = None
    total_bags: int
    approved_bags: int
    pending_bags: int
    total_planters: int
    total_parcelles: int
    parcelles_by_section: list[SectionStat]
    ventilation_villages: Optional[list['AnalyticsVillageStat']] = None
    filieres: list[FiliereStatItem] = []
    daily_deliveries: Optional[list[DailyDeliveryItem]] = None
    moyenne_journaliere: Optional[float] = 0.8
    peak_date: Optional[str] = "14/10/2026"
    peak_volume: Optional[float] = 2.8
    active_alerts_count: int
    total_alerts_count: Optional[int] = 12
    alerts_by_crop: Optional[dict[str, int]] = None
    alerts_summary: list[AlertSummary]
    recent_activities: list[ActivityOut]

class CoopRecolteItem(BaseModel):
    id: UUID
    bordereau_ref: Optional[str] = None
    status: str
    statut_ui: str
    weight_kg: float
    number_of_bags: int
    unit_price_fcfa: Optional[int] = None
    valeur_totale_fcfa: Optional[int] = None
    valeur_estimee_fcfa: Optional[int] = None
    harvest_date: datetime
    created_at: Optional[datetime] = None
    planter_id: UUID
    planter_name: str
    planter_phone: str
    parcelle_id: Optional[UUID] = None
    parcelle_name: Optional[str] = None
    village: Optional[str] = None
    crop_type: Optional[str] = None

    planter_phone: str
    parcelle_id: Optional[UUID] = None
    parcelle_name: Optional[str] = None
    village: Optional[str] = None
    crop_type: Optional[str] = None

class UpdateRecolteStatusInput(BaseModel):
    status: str = Field(..., description="Nouveau statut : APPROVED ou REJECTED")
    motif: Optional[str] = None

class CoopPlanterItem(BaseModel):
    id: UUID
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    nom_complet: str
    phone_number: str
    avatar_url: Optional[str] = None
    village: Optional[str] = None
    culture: Optional[str] = None
    parcelles_count: int
    total_superficie_ha: float
    total_harvests_count: int
    total_tonnage_kg: float
    created_at: Optional[datetime] = None

class CoopParcelleItem(BaseModel):
    id: UUID
    name: str
    crop_type: str
    superficie: Optional[float] = None
    superficie_ha: Optional[float] = None
    village: Optional[str] = None
    gps_coordinates: Optional[dict] = None
    planter_id: UUID
    planter_name: str
    planter_phone: str
    created_at: Optional[datetime] = None

class CoopDiagnosticItem(BaseModel):
    id: UUID
    disease_name: str
    confidence_score: Optional[float] = None
    status: str
    image_url: str
    recommended_action: Optional[str] = None
    created_at: Optional[datetime] = None
    planter_id: Optional[UUID] = None
    planter_name: Optional[str] = None
    parcelle_id: Optional[UUID] = None
    parcelle_name: Optional[str] = None
    village: Optional[str] = None


# ============================================================
# 8. SOCLE ANALYTIQUE & TOUR DE CONTRÔLE (Brief 2 - C2)
# ============================================================

class AnalyticsVillageStat(BaseModel):
    village: str
    parcelles_count: int
    superficie_ha: float
    tonnage_total_kg: float
    tonnage_valide_kg: float
    taux_approbation: float
    planters_count: int
    culture: Optional[str] = "cacao"

class AnalyticsOverview(BaseModel):
    total_tonnage_kg: float
    total_tonnage_tonnes: float
    approved_tonnage_kg: float
    approved_tonnage_tonnes: float
    pending_tonnage_kg: float
    pending_tonnage_tonnes: float
    valeur_totale_fcfa: int
    valeur_validee_fcfa: int
    taux_approbation: float
    total_planters: int
    total_parcelles: int
    total_superficie_ha: float
    ventilation_villages: list[AnalyticsVillageStat]
    filieres: list[FiliereStatItem] = []

class AnalyticsProductivityPlanter(BaseModel):
    planter_id: UUID
    nom_complet: str
    telephone: str
    village: Optional[str] = None
    culture: Optional[str] = None
    superficie_ha: float
    tonnage_livre_kg: float
    tonnage_valide_kg: float
    rendement_moyen_kg_ha: float
    statut_productivite: str

class AnalyticsSanitaryWeatherItem(BaseModel):
    mois: str
    mois_num: int
    annee: int
    pluviometrie_moyenne_mm: float
    temperature_c: float
    diagnostics_count: int
    maladies_principales: list[str]
    niveau_alerte: str

class AnalyticsChurnPlanter(BaseModel):
    planter_id: UUID
    nom_complet: str
    telephone: str
    village: Optional[str] = None
    culture: Optional[str] = None
    superficie_ha: float
    tonnage_livre_kg: float
    risk_score: int
    risk_level: str
    facteurs_influence: list[str]

class AnalyticsFoyerVillage(BaseModel):
    village: str
    niveau: str  # "ÉLEVÉ", "MODÉRÉ", "FAIBLE"
    cas_actifs: int
    maladie_dominante: str
    actions: str
    badge_bg: str = "bg-emerald-100 text-emerald-800"
    filiere: Optional[str] = "Cacao (CCC)"

class CoopAnalyticsResponse(BaseModel):
    cooperative_id: UUID
    cooperative_name: str
    generated_at: datetime
    overview: AnalyticsOverview
    filieres: list[FiliereStatItem] = []
    productivity: list[AnalyticsProductivityPlanter]
    sanitary_weather: list[AnalyticsSanitaryWeatherItem]
    churn_matrix: list[AnalyticsChurnPlanter]
    foyers_villages: list[AnalyticsFoyerVillage] = []

# --- Schémas IA / Machine Learning (Bloc 2 & 5) ---
class ModelMetrics(BaseModel):
    accuracy: float
    precision: float
    recall: float
    f1_score: float

class ConfusionMatrixData(BaseModel):
    vn: int
    fp: int
    fn: int
    vp: int

class FeatureImportanceItem(BaseModel):
    name: str
    importance: float
    bar_width: str

class PlanterPredictionItem(BaseModel):
    planter_id: UUID
    nom_complet: str
    telephone: Optional[str] = None
    village: Optional[str] = "N/A"
    culture: Optional[str] = "cacao"
    superficie_ha: float
    tonnage_livre_kg: float
    risk_score: int
    risk_level: str
    factors: list[str] = []

class ChurnPredictionResponse(BaseModel):
    cooperative_id: UUID
    cooperative_name: str
    generated_at: datetime
    metrics: ModelMetrics
    confusion_matrix: ConfusionMatrixData
    feature_importances: list[FeatureImportanceItem]
    planters: list[PlanterPredictionItem]
    total_members: int
    critical_count: int
    summary_text: str

class SimulateChurnRequest(BaseModel):
    apports_recents_t: float = 1.4
    pluviometrie_mm: float = 85.0
    superficie_ha: float = 4.2
    culture: Optional[str] = "cacao"

class SimulateChurnResponse(BaseModel):
    score: int
    level: str
    probability: float
    factors: list[str] = []

# --- Schémas Prévision Tonnage & Benchmark (Onglet 2) ---
class MonthlyTrajectoryPoint(BaseModel):
    mois: str
    tonnage_mensuel_t: float
    tonnage_cumule_t: float
    type: str  # 'reel', 'actuel', 'prevision'

class TonnageBenchmarkItem(BaseModel):
    name: str
    score: str
    rmse: float
    width: str
    color: str
    badge: Optional[str] = None
    desc: str

class ScatterPointItem(BaseModel):
    x_reel: float
    y_predit: float

class TonnageMetrics(BaseModel):
    rmse: float
    mae: float
    r2: float

class TonnagePredictionResponse(BaseModel):
    cooperative_id: UUID
    cooperative_name: str
    generated_at: datetime
    recolte_a_date_t: float
    sacs_count: int
    prevision_finale_t: float
    intervalle_95_t: float
    ci_low_t: float
    ci_high_t: float
    monthly_trajectory: list[MonthlyTrajectoryPoint]
    metrics: TonnageMetrics
    benchmarks: list[TonnageBenchmarkItem]
    scatter_points: list[ScatterPointItem]
    summary_text: str

class SimulateTonnageRequest(BaseModel):
    apports_kg_sem: float = 380.0
    pluviometrie_mm: float = 115.0
    superficie_ha: float = 3.5
    culture: Optional[str] = "cacao"

class SimulateTonnageResponse(BaseModel):
    yield_ton_ha: str
    ci_low: str
    ci_high: str
    rendement_brut: float
    factors: list[str] = []

CoopKPIsResponse.model_rebuild()
ChurnPredictionResponse.model_rebuild()
TonnagePredictionResponse.model_rebuild()


