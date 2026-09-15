"""Un plancher a 1,0 eteignait la modulation tout en l'affichant active.

``quality = _clamp(produit, floor, 1.0)`` : le plancher sert de borne basse,
mais quand il vaut 1,0 il devient aussi la borne haute. Les cinq facteurs sont
alors calcules, journalises... et jetes.

Constate en production. Le reglage est passe a 1,0 le 12/09/2026 et chaque
ordre du 14/09 porte la trace de l'incoherence dans son journal d'audit :

    qualite 1.00 x budget 1.00 = 1.00 -> risque 10.000%
    (plus penalisant : rendement_risque 0.50)

Le facteur le plus penalisant vaut 0,50 et le risque reste a 10 %. Les quatre
positions parties au stop ce jour-la (-48, -40, -43,18 et -36,08 dollars sur un
compte de 540) auraient ete dimensionnees a 5,0 %, 3,75 %, 3,5 % et 3,5 % avec
le plancher documente de 0,35 : environ 67 dollars perdus au lieu de 167.

``dynamic_risk_enabled`` existe deja pour eteindre la modulation. Un second
chemin, silencieux celui-la, qui laisse l'interrupteur sur « active » et le
detail d'audit se contredire, n'a aucune raison d'exister.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.enums import ParserSource
from app.schemas.requests import RiskSettingsRequest
from app.services.risk.quality import MAX_QUALITY_FLOOR, quality_multiplier


def calculer(**kwargs: object) -> object:
    """Le signal 190 du 14/09 : XAUUSD, rendement/risque 0,25, stop a 12 $."""
    base: dict[str, object] = {
        "risk_percent": 10.0,
        "risk_reward": 0.25,
        "spread_cost": 0.24,
        "stop_distance": 12.0,
        "age_seconds": 2.0,
        "max_signal_age_seconds": 300,
        "consecutive_losses": 0,
        "warnings": [],
        "source": ParserSource.DETERMINISTIC,
        "day_risked_percent": 0.0,
        "max_daily_risk_percent": 0.0,
    }
    base.update(kwargs)
    return quality_multiplier(**base)  # type: ignore[arg-type]


class TestLePlancherNePeutPlusToutEteindre:
    def test_un_plancher_a_un_ne_neutralise_plus_la_modulation(self) -> None:
        resultat = calculer(floor=1.0)
        assert resultat.sized_risk_percent < 10.0

    def test_le_plancher_est_ramene_a_sa_borne(self) -> None:
        resultat = calculer(floor=1.0)
        assert resultat.quality <= MAX_QUALITY_FLOOR

    def test_la_borne_laisse_une_marge_de_reduction_reelle(self) -> None:
        assert MAX_QUALITY_FLOOR < 1.0

    def test_le_facteur_le_plus_penalisant_se_voit_dans_le_resultat(self) -> None:
        """Le detail d'audit ne doit plus se contredire lui-meme."""
        resultat = calculer(floor=1.0)
        assert resultat.factors["rendement_risque"] == pytest.approx(0.50)
        assert resultat.applied is True

    def test_un_plancher_negatif_ne_casse_rien(self) -> None:
        resultat = calculer(floor=-3.0)
        assert 0.0 <= resultat.quality <= 1.0


class TestLePlancherNormalEstIntact:
    def test_le_plancher_documente_donne_le_dimensionnement_attendu(self) -> None:
        """Le signal 190 aurait pris 5 % au lieu de 10 % : -24 $ au lieu de -48 $."""
        resultat = calculer(floor=0.35)
        assert resultat.sized_risk_percent == pytest.approx(5.0)

    def test_un_plancher_bas_borne_toujours_la_reduction(self) -> None:
        resultat = calculer(
            floor=0.35, risk_reward=None, spread_cost=500.0, consecutive_losses=2
        )
        assert resultat.quality == pytest.approx(0.35)


class TestSchemaApi:
    def test_le_plancher_neutralisant_est_refuse(self) -> None:
        """Pour eteindre la modulation il y a ``dynamicRiskEnabled``."""
        with pytest.raises(ValidationError):
            RiskSettingsRequest.model_validate({"dynamicRiskFloor": 1.0})

    def test_la_borne_reste_atteignable(self) -> None:
        requete = RiskSettingsRequest.model_validate({"dynamicRiskFloor": MAX_QUALITY_FLOOR})
        assert requete.dynamic_risk_floor == MAX_QUALITY_FLOOR

    def test_le_plancher_documente_passe_toujours(self) -> None:
        requete = RiskSettingsRequest.model_validate({"dynamicRiskFloor": 0.35})
        assert requete.dynamic_risk_floor == 0.35
