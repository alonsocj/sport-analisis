"""Pestana Modelo de la app Streamlit (R11, Feature 9 + Feature 5 + Feature 19).

Muestra los metadatos de los parametros Dixon-Coles, un aviso visible si
convergencia.success es False, la dispersion attack vs defense para las
48 selecciones, la seccion Backtest (Feature 5) y el panel Forma reciente
vs v1 (Feature 19).
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from ..data import AppData
from ..figures import fig_fuerzas

# Ruta default del reporte de backtest (R11 de la feature 5)
DEFAULT_BACKTEST_SUMMARY = Path("data/reports/backtest/summary.json")

# Ruta default del artefacto de comparativa forma vs v1 (Feature 19, R1)
DEFAULT_FORMA_VS_V1 = Path("data/reports/forma_vs_v1.json")


def render_modelo(app_data: AppData) -> None:
    """Renderiza la pestana Modelo (R11).

    Args:
        app_data: Estado cargado de la app.
    """
    params = app_data.params

    st.subheader("Metadatos del modelo")

    # Metadatos del JSON de params (R11)
    col1, col2 = st.columns(2)
    with col1:
        st.metric("as_of_date", params.as_of_date)
        st.metric("from_date", params.from_date)
        st.metric("n_matches", params.n_matches)
    with col2:
        st.metric("n_teams", params.n_teams)
        st.metric("xi (decaimiento)", f"{params.xi:.3f}")

        conv = params.convergencia
        n_iter = conv.get("n_iter", "—") if isinstance(conv, dict) else "—"
        st.metric("n_iter", n_iter)

    # Aviso visible si convergencia.success es False (R11)
    conv_dict = params.convergencia if isinstance(params.convergencia, dict) else {}
    conv_success = conv_dict.get("success", True)
    if not conv_success:
        conv_msg = conv_dict.get("message", "sin mensaje")
        st.warning(
            f"El modelo **no convergió** en el entrenamiento. "
            f"Las probabilidades pueden ser poco fiables. "
            f"Mensaje del optimizador: `{conv_msg}`. "
            "Considera reentrenar con `python -m src.models.dixon_coles --as-of-date YYYY-MM-DD`."
        )

    st.divider()
    st.subheader("Dispersión de fuerzas (48 selecciones)")

    # Dispersion attack vs defense (R11)
    params_dict = {
        "attack": params.attack,
        "defense": params.defense,
    }
    st.plotly_chart(
        fig_fuerzas(params_dict),
        width="stretch",
    )

    st.divider()
    _render_backtest_section(DEFAULT_BACKTEST_SUMMARY)

    st.divider()
    _render_forma_vs_v1(DEFAULT_FORMA_VS_V1)


def _render_backtest_section(summary_path: Path) -> None:
    """Renderiza la seccion Backtest de la pestana Modelo (Feature 5, R11).

    Si existe ``summary.json`` en la ruta default, muestra las metricas clave
    (modelo vs baselines, as_of y n partidos). Si no existe, muestra el comando
    para generarlo. Lectura tolerante a JSON invalido (sin crash, R11).

    Args:
        summary_path: Path to the backtest summary.json file.
    """
    st.subheader("Backtest")

    if not summary_path.is_file():
        st.caption(
            "No hay reporte de backtest todavia. Generalo con:\n\n"
            "`python -m src.cli backtest`"
        )
        return

    try:
        raw = summary_path.read_text(encoding="utf-8")
        summary = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        st.warning(
            f"El archivo summary.json existe pero no se pudo leer ({exc}). "
            "Regeneralo con `python -m src.cli backtest`."
        )
        return

    if not isinstance(summary, dict):
        st.warning(
            "El archivo summary.json tiene un formato inesperado. "
            "Regeneralo con `python -m src.cli backtest`."
        )
        return

    metrics = summary.get("metrics", {})
    as_of = summary.get("as_of", "?")
    n_matches = metrics.get("model", {}).get("n_matches", "?")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.caption("as_of")
        st.write(as_of)
        st.caption(f"n_partidos: {n_matches}")

    with col2:
        model_m = metrics.get("model", {})
        uniform_m = metrics.get("uniform", {})
        ll_model = model_m.get("log_loss")
        ll_uniform = uniform_m.get("log_loss")
        delta_ll = None
        if ll_model is not None and ll_uniform is not None:
            delta_ll = round(ll_model - ll_uniform, 4)
        st.metric(
            "log-loss (modelo)",
            value=f"{ll_model:.4f}" if ll_model is not None else "n/d",
            delta=f"{delta_ll:+.4f} vs uniforme" if delta_ll is not None else None,
            delta_color="inverse",
        )
        marginal_m = metrics.get("marginal", {})
        ll_marginal = marginal_m.get("log_loss")
        st.metric(
            "log-loss uniforme",
            value=f"{ll_uniform:.4f}" if ll_uniform is not None else "n/d",
        )
        st.metric(
            "log-loss marginal",
            value=f"{ll_marginal:.4f}" if ll_marginal is not None else "n/d",
        )

    with col3:
        brier_model = model_m.get("brier")
        brier_uniform = uniform_m.get("brier")
        acc_model = model_m.get("accuracy")
        delta_brier = None
        if brier_model is not None and brier_uniform is not None:
            delta_brier = round(brier_model - brier_uniform, 4)
        st.metric(
            "Brier (modelo)",
            value=f"{brier_model:.4f}" if brier_model is not None else "n/d",
            delta=f"{delta_brier:+.4f} vs uniforme" if delta_brier is not None else None,
            delta_color="inverse",
        )
        st.metric(
            "Exactitud (modelo)",
            value=f"{100 * acc_model:.1f}%" if acc_model is not None else "n/d",
        )


def _render_forma_vs_v1(path: Path) -> None:
    """Renderiza el panel 'Forma reciente vs v1' en la pestana Modelo (Feature 19, R1-R4).

    Lee el artefacto forma_vs_v1.json y muestra la tabla gamma x {log-loss, Brier,
    exactitud} con el delta vs la fila baseline (v1, gamma=0) y el veredicto medido.
    Degradacion elegante si el archivo no existe, esta malformado o le faltan campos.

    Args:
        path: Path to the forma_vs_v1.json artifact.
    """
    st.subheader("Forma reciente vs v1")

    # --- Carga del artefacto (R1) ---
    if not path.is_file():
        st.info(
            "No hay reporte de forma vs v1 todavia. Generalo con:\n\n"
            "`python -m src.cli backtest --from-date YYYY-MM-DD --to-date YYYY-MM-DD"
            " --form-weight 0`\n\n"
            "(repite con `--form-weight 0.2` y `--form-weight 0.3`) y consolida el JSON."
        )
        return

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        st.info(
            f"El archivo forma_vs_v1.json existe pero no se pudo leer ({exc}). "
            "Regeneralo con `python -m src.cli backtest --form-weight <gamma>`."
        )
        return

    # --- Validacion del schema (R1) ---
    if not isinstance(data, dict):
        st.info(
            "El archivo forma_vs_v1.json tiene un formato inesperado. "
            "Regeneralo con `python -m src.cli backtest --form-weight <gamma>`."
        )
        return

    rows: list[dict] = data.get("rows") or []
    if not rows:
        st.info(
            "El archivo forma_vs_v1.json no contiene filas ('rows' vacio o ausente). "
            "Regeneralo con `python -m src.cli backtest --form-weight <gamma>`."
        )
        return

    baseline_row = next((r for r in rows if r.get("is_baseline")), None)
    if baseline_row is None:
        st.info(
            "No se encontro fila baseline (is_baseline=true) en forma_vs_v1.json. "
            "Regeneralo con `python -m src.cli backtest --form-weight 0`."
        )
        return

    bl_ll = baseline_row.get("log_loss")
    bl_brier = baseline_row.get("brier")
    bl_acc = baseline_row.get("accuracy")

    # --- Construir tabla con delta vs v1 (R2) ---
    table_rows = []
    for row in rows:
        gamma = row.get("gamma")
        ll = row.get("log_loss")
        brier = row.get("brier")
        acc = row.get("accuracy")
        is_bl = bool(row.get("is_baseline", False))

        gamma_label = f"γ={gamma} (v1)" if is_bl else f"γ={gamma}"

        delta_ll = round(ll - bl_ll, 4) if ll is not None and bl_ll is not None else None
        delta_brier = round(brier - bl_brier, 4) if brier is not None and bl_brier is not None else None
        delta_acc = round(acc - bl_acc, 4) if acc is not None and bl_acc is not None else None

        table_rows.append({
            "γ": gamma_label,
            "log-loss": f"{ll:.4f}" if ll is not None else "n/d",
            "Δ log-loss": f"{delta_ll:+.4f}" if delta_ll is not None else "—",
            "Brier": f"{brier:.4f}" if brier is not None else "n/d",
            "Δ Brier": f"{delta_brier:+.4f}" if delta_brier is not None else "—",
            "exactitud": f"{acc:.4f}" if acc is not None else "n/d",
            "Δ exactitud": f"{delta_acc:+.4f}" if delta_acc is not None else "—",
        })

    st.dataframe(table_rows, use_container_width=True, hide_index=True)
    st.caption("Δ negativo mejora log-loss/Brier; Δ positivo mejora exactitud.")

    # --- Veredicto y contexto (R2) ---
    verdict = data.get("verdict", "")
    if verdict:
        st.success(verdict)

    from_date = data.get("from_date", "?")
    to_date = data.get("to_date", "?")
    n_eval = data.get("n_eval", "?")
    caveat = data.get("caveat", "")
    st.caption(f"Ventana: {from_date} – {to_date} | n_eval: {n_eval} | {caveat}")
