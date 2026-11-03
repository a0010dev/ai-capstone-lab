"""Streamlit UI for the existing, synchronous industrial reporting agent."""

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import streamlit as st
from dotenv import load_dotenv

from est_prog.capstone_reporting.agent import run_agent


def suggested_questions(result):
    """Build self-contained shortcuts from a single successful filter set."""
    filters = []
    for call in result.get("tool_calls", []):
        if "error" in call["result"]:
            continue
        arguments = json.loads(call["arguments"])
        selection = tuple(arguments.get(key) for key in ("section", "date_from", "date_to"))
        if selection not in filters:
            filters.append(selection)
    # Comparisons and unbounded selections need more context than these shortcuts.
    if len(filters) != 1 or not all(filters[0]):
        return []
    section, start, end = filters[0]
    context = f"de la secció {section} entre {start} i {end}, ambdós inclosos"
    return [
        ("Resum", f"Mostra el resum de defectes {context}."),
        ("Detall de retirades", f"Mostra el total i els registres que expliquen les plaques retirades {context}."),
        ("Pareto de retirades", f"Fes un Pareto de plaques retirades per codi de defecte {context}."),
    ]


def render_trace(calls):
    if not calls:
        st.caption("L’agent no ha cridat cap eina en aquesta resposta.")
    for call in calls:
        st.markdown(f"**{call['name']}**")
        st.json(json.loads(call["arguments"]), expanded=False)
        if "error" in call["result"]:
            st.error("L’eina ha retornat un error; consulta el resultat.")
        st.json(call["result"], expanded=False)


def render_metadata(result):
    source_ids = sorted({
        call["result"]["source"]["dataset_id"]
        for call in result["tool_calls"]
        if "dataset_id" in call["result"].get("source", {})
    })
    cols = st.columns(3)
    cols[0].caption(f"Model: {result['model']}")
    cols[1].caption(f"Data de referència: {result['reference_date']}")
    cols[2].caption("Origen: " + (", ".join(source_ids) or "Sense dades consultades"))


def queue_prompt(prompt):
    st.session_state.pending_prompt = prompt


def main():
    st.set_page_config(page_title="Reporting industrial", page_icon="📊", layout="wide")
    load_dotenv(Path(__file__).resolve().parent / ".env")
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("pending_prompt", None)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    has_key = bool(os.getenv("OPENAI_API_KEY"))

    with st.sidebar:
        st.title("Reporting industrial")
        st.caption("Prototip amb dades sintètiques · només lectura")
        st.caption(f"Model: {model}")
        if st.button("Esborra la conversa", key="clear_conversation", use_container_width=True):
            st.session_state.messages = []
            st.session_state.pending_prompt = None
            st.rerun()

    st.title("Assistent de reporting industrial")
    st.info("Dades sintètiques de demostració. Indica la secció i el període a cada pregunta.")
    st.caption(
        "Pots consultar resums, detall i Pareto. Cada consulta és independent; "
        "l’historial es conserva en aquesta sessió."
    )
    if not has_key:
        st.warning("Configura OPENAI_API_KEY al fitxer .env per poder consultar l’agent.")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant" and "result" in message:
                with st.status("Consulta completada", state="complete", expanded=True):
                    render_trace(message["result"]["tool_calls"])
                st.markdown(message["content"])
                render_metadata(message["result"])
            elif message.get("error"):
                st.error(message["content"])
            else:
                st.markdown(message["content"])

    typed_prompt = st.chat_input(
        "Ex.: Quantes plaques hem retirat a TE durant setembre de 2026?",
        disabled=not has_key,
    )
    prompt = typed_prompt or st.session_state.pending_prompt
    st.session_state.pending_prompt = None

    if prompt and has_key:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            status = st.status("Consultant l’agent…", expanded=True)
            with status:
                st.caption("La traça de les eines es mostrarà quan acabi la consulta.")
            try:
                result = run_agent(
                    prompt, model=model,
                    today=datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat(),
                )
            except Exception:
                # Keep provider details and credentials out of the chat and logs.
                status.update(label="Consulta fallida", state="error", expanded=True)
                message = "No s’ha pogut completar la consulta. Revisa la configuració i la connexió i torna-ho a provar."
                st.error(message)
                st.session_state.messages.append({
                    "role": "assistant", "content": message, "error": True,
                })
            else:
                with status:
                    render_trace(result["tool_calls"])
                status.update(label="Consulta completada", state="complete", expanded=True)
                st.markdown(result["answer"])
                render_metadata(result)
                st.session_state.messages.append({
                    "role": "assistant", "content": result["answer"], "result": result,
                })
        # Rebuild from persisted state, removing the previous suggestion buttons.
        st.rerun()

    messages = st.session_state.messages
    if messages and "result" in messages[-1]:
        questions = suggested_questions(messages[-1]["result"])
        if questions:
            st.caption("Consultes relacionades amb la mateixa secció i període")
            for index, (column, (label, question)) in enumerate(zip(st.columns(len(questions)), questions)):
                column.button(
                    label, key=f"followup_{len(messages)}_{index}",
                    on_click=queue_prompt, args=(question,), disabled=not has_key,
                    use_container_width=True,
                )


if __name__ == "__main__":
    main()
