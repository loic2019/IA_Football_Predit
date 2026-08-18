"""Page Fichiers & outils : acces rapide aux scripts et donnees du projet."""

from pathlib import Path

import streamlit as st

from common import get_project_files, run_auto_cycle, run_python_file


RUNNABLE_TOOLS = [
    ("Scraper CongoBet + 1xBet", "scraper_multi.py", []),
    ("Scraper CongoBet", "scraper_api.py", []),
    ("Scraper 1xBet", "scraper_1xbet_api.py", []),
    ("Scraper BeSoccer", "scraper_besoccer.py", ["--all"]),
    ("Analyser avec predictor", "predictor.py", ["--analyze"]),
    ("Generer coupon 8 matchs", "predictor.py", ["--coupon", "8"]),
    ("Stats du modele", "predictor.py", ["--stats"]),
    ("Entrainer le modele", "predictor.py", ["--train"]),
]


def _file_kind(path):
    if path.suffix == ".py":
        return "Scripts Python"
    if path.suffix in {".json", ".jsonl", ".csv", ".db"}:
        return "Donnees"
    if path.suffix == ".log":
        return "Logs"
    return "Documentation"


def _preview_file(path):
    if path.suffix == ".db":
        st.info("Fichier SQLite. Utilise la page Parametres pour voir les tables.")
        return

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        st.error(f"Impossible de lire le fichier : {exc}")
        return

    st.code(text[:12000], language="python" if path.suffix == ".py" else None)
    if len(text) > 12000:
        st.caption("Apercu limite aux 12 000 premiers caracteres.")


def render():
    st.title("Fichiers & outils")
    st.caption("Boutons rapides pour consulter les fichiers, lancer les scrapers et appeler predictor.py")

    st.markdown("### Actions rapides")
    if st.button(":material/autoplay: Cycle complet maintenant", width="stretch"):
        with st.spinner("Scraping, entrainement et predictions..."):
            st.session_state.tool_output = run_auto_cycle(force=True, include_besoccer=True)

    cols = st.columns(4)
    for idx, (label, script, args) in enumerate(RUNNABLE_TOOLS):
        with cols[idx % 4]:
            if st.button(label, key=f"run_{script}_{idx}", width="stretch"):
                with st.spinner(f"Execution de {script}..."):
                    st.session_state.tool_output = run_python_file(script, *args)

    if st.session_state.get("tool_output"):
        result = st.session_state.tool_output
        if "summary" in result or "state" in result:
            status = result.get("state", {}).get("last_cycle_status", "cycle")
            st.markdown(f"**Dernier cycle ({status})**")
            st.json(result.get("summary") or result, expanded=False)
        else:
            status = "succes" if result.get("success") else "echec"
            st.markdown(f"**Derniere commande ({status}) :** `{result.get('command', '')}`")
            if result.get("output"):
                st.text_area("Sortie", result["output"], height=220)
            if result.get("stderr") or result.get("error"):
                st.text_area("Erreurs", result.get("stderr") or result.get("error"), height=160)

    st.markdown("---")
    st.markdown("### Fichiers du projet")

    files = get_project_files()
    categories = ["Tous", "Scripts Python", "Donnees", "Logs", "Documentation"]
    category = st.segmented_control("Categorie", categories, default="Tous")

    visible_files = [p for p in files if category == "Tous" or _file_kind(p) == category]
    if not visible_files:
        st.info("Aucun fichier trouve dans cette categorie.")
        return

    labels = [str(path) for path in visible_files]
    selected_label = st.selectbox("Choisir un fichier", labels)
    selected_path = Path(selected_label)

    with st.container(horizontal=True):
        if st.button(":material/visibility: Apercu", width="stretch"):
            st.session_state.selected_project_file = str(selected_path)

        try:
            data = selected_path.read_bytes()
            st.download_button(
                ":material/download: Telecharger",
                data=data,
                file_name=selected_path.name,
                width="stretch",
            )
        except Exception as exc:
            st.error(f"Telechargement impossible : {exc}")

    if st.session_state.get("selected_project_file"):
        preview_path = Path(st.session_state.selected_project_file)
        st.markdown(f"### Apercu : `{preview_path}`")
        _preview_file(preview_path)
