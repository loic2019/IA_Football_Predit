"""
Couche service pour les pronostics / le coupon.

La génération réelle des prédictions (modèles ML, ensemble, seuils de
confiance/cote) reste 100% dans common.py et predictor.py —
inchangée. Ici on expose juste ces capacités proprement pour l'API.
"""
import common


def get_predictions(limit: int = 200, min_confidence: float = 0.0, min_cote: float = 1.30) -> dict:
    """
    Reprend exactement les paramètres déjà utilisés côté Streamlit
    (voir pronostics.py::load_predictions et le coupon de 8 filtré >= 1.30).
    """
    return common.run_prediction_pipeline(
        limit=limit,
        min_confidence=min_confidence,
        min_cote=min_cote,
    )


def get_combo_analysis() -> dict:
    """Analyse des tickets combinés CongoBet (voir pronostics.py::_load_combo_analysis)."""
    from pronostics import _load_combo_analysis

    return _load_combo_analysis()
