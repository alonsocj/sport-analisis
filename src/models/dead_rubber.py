"""src/models/dead_rubber.py — Amortiguación de motivación para partidos de trámite (F34, R3).

El partido por el 3er puesto de un Mundial se juega "sin ánimos": ambos equipos vienen de
perder la semifinal y la recompensa es marginal. Empíricamente estos partidos son más
ABIERTOS y la ventaja del que "debería" ganar se DILUYE (menos presión → más aleatoriedad).

Base histórica (partidos por el 3er puesto de Copas del Mundo, muestra ilustrativa):
promedian ~3.4 goles/partido frente a ~2.6 de las finales — sistemáticamente más goles.

Esta amortiguación tiene dos palancas puras y deterministas:

- ``delta`` ∈ [0, 1]: **encoge** la desviación de ataque/defensa de cada equipo hacia la
  media del torneo (aplana la ventaja del favorito). ``delta=0`` → identidad; ``delta=1`` →
  ambos equipos colapsan a la media (partido 50/50).
- ``kappa`` ≥ 1: **bump de apertura** que multiplica ambas λ (más goles esperados).
  ``kappa=1`` → identidad.

Aditiva y aislada: con ``DeadRubber(0.0, 1.0)`` (== ``OFF``) el resultado es byte-idéntico al
baseline; sólo el bloque del 3er puesto la activa (ver ``simulation/match_sim.py`` y la app).
"""

from __future__ import annotations

from dataclasses import dataclass

# Defaults documentados (base histórica del 3er puesto: más abierto, ventaja diluida).
DEFAULT_DELTA: float = 0.45
DEFAULT_KAPPA: float = 1.12


@dataclass(frozen=True)
class DeadRubber:
    """Configuración de amortiguación de motivación (R3).

    Args:
        delta: Factor de encogimiento hacia la media, en [0, 1].
        kappa: Bump multiplicativo de apertura sobre las λ, ≥ 1.

    Raises:
        ValueError: Si ``delta`` cae fuera de [0, 1] o ``kappa`` < 1.
    """

    delta: float = DEFAULT_DELTA
    kappa: float = DEFAULT_KAPPA

    def __post_init__(self) -> None:
        if not (0.0 <= self.delta <= 1.0):
            raise ValueError(f"delta debe estar en [0, 1], se recibió {self.delta}.")
        if self.kappa < 1.0:
            raise ValueError(f"kappa debe ser >= 1, se recibió {self.kappa}.")


# Interruptor apagado (no-regresión): identidad exacta.
OFF: DeadRubber = DeadRubber(delta=0.0, kappa=1.0)


def shrink_toward(value: float, mean: float, delta: float) -> float:
    """Encoge ``value`` hacia ``mean`` por un factor ``delta`` (R3).

    ``delta=0`` → ``value`` (identidad); ``delta=1`` → ``mean``.
    """
    return mean + (1.0 - delta) * (value - mean)


def shrink_strengths(
    attack: float,
    defense: float,
    mean_attack: float,
    mean_defense: float,
    delta: float,
) -> tuple[float, float]:
    """Encoge los coeficientes de ataque y defensa de un equipo hacia la media (R3).

    Args:
        attack: Coeficiente de ataque del equipo.
        defense: Coeficiente de defensa del equipo.
        mean_attack: Media de ataque del torneo.
        mean_defense: Media de defensa del torneo.
        delta: Factor de encogimiento en [0, 1].

    Returns:
        Tupla ``(attack', defense')`` encogida hacia la media.
    """
    return (
        shrink_toward(attack, mean_attack, delta),
        shrink_toward(defense, mean_defense, delta),
    )


def apply_openness(lambda_home: float, lambda_away: float, kappa: float) -> tuple[float, float]:
    """Aplica el bump de apertura ``kappa`` a ambas λ (R3).

    ``kappa=1`` → identidad; ``kappa>1`` → ambas λ suben (partido más abierto).
    """
    return (lambda_home * kappa, lambda_away * kappa)
