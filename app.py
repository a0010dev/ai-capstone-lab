"""Streamlit UI for the existing asynchronous industrial reporting agent."""

import asyncio
import json
import os
from copy import deepcopy
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
        try:
            arguments = json.loads(call["arguments"])
        except (ValueError, TypeError):
            arguments = call["arguments"]
        st.json(arguments, expanded=False)
        if call.get("result") is None:
            st.caption("Execució interrompuda abans d’obtenir el resultat.")
            continue
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
    usage = result.get("usage")
    if usage is not None:
        cost = usage["estimated_cost_usd"]
        estimate = f"${cost:.8f} USD" if cost is not None else "desconegut"
        st.caption(
            f"Tokens: {usage['input_tokens']} entrada · {usage['output_tokens']} sortida"
            f" · Cost estimat de la consulta: {estimate}"
        )
    if result.get("trace_id"):
        st.caption(f"Traça: {result['trace_id']}")


def queue_prompt(prompt):
    st.session_state.pending_prompt = prompt


class LiveResponse:
    """Render async events on Streamlit's script thread, without rerunning calls."""

    def __init__(self, status, answer):
        self.status = status
        self.answer = answer
        self.text = ""
        self.calls = {}
        self.placeholders = {}

    async def on_event(self, event):
        kind = event["type"]
        if kind == "round_start":
            self.text = ""
            self.answer.empty()
            self.status.update(label="Consultant l’agent…", expanded=True)
        elif kind == "text_delta":
            self.text += event["delta"]
            self.answer.markdown(self.text + " ▌")
        elif kind == "tool_start":
            call_id = event["call_id"]
            self.calls[call_id] = {"name": event["name"], "arguments": event["arguments"]}
            self.status.update(label=f"Executant {event['name']}…", expanded=True)
            with self.status:
                placeholder = st.empty()
                self.placeholders[call_id] = placeholder
                with placeholder.container():
                    st.markdown(f"**{event['name']}**")
                    st.json(event["arguments"], expanded=False)
                    st.caption("En execució…")
        elif kind == "tool_end":
            call_id = event["call_id"]
            self.calls[call_id] = event["call"]
            with self.placeholders[call_id].container():
                render_trace([event["call"]])
            self.status.update(label="Preparant la resposta…", expanded=True)
        elif kind == "completed":
            # Replace provisional text with the authoritative assembled answer.
            self.answer.markdown(event["result"]["answer"])


def main():
    st.set_page_config(page_title="Reporting industrial", page_icon="📊", layout="wide")
    load_dotenv(Path(__file__).resolve().parent / ".env")
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("pending_prompt", None)
    # Recover the visible conversation for sessions opened before history support.
    # New turns retain native PydanticAI messages, including tool evidence.
    if "agent_history" not in st.session_state:
        st.session_state.agent_history = [
            {"role": message["role"], "content": message["content"]}
            for message in st.session_state.messages
        ]
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    has_key = bool(os.getenv("OPENAI_API_KEY"))

    with st.sidebar:
        st.title("Reporting industrial")
        st.caption("Prototip amb dades sintètiques · només lectura")
        st.caption(f"Model: {model}")
        if st.button("Esborra la conversa", key="clear_conversation", use_container_width=True):
            st.session_state.messages = []
            st.session_state.pending_prompt = None
            st.session_state.agent_history = []
            st.rerun()

    st.title("Assistent de reporting industrial")
    st.info("Dades sintètiques de demostració. Indica la secció i el període a la primera consulta o quan vulguis canviar-los.")
    st.caption(
        "Pots consultar resums, detall i Pareto. L’agent conserva el context "
        "de la conversa durant aquesta sessió. Esborra-la per començar de nou."
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
                with st.status("Consulta fallida", state="error", expanded=True):
                    render_trace(message.get("tool_calls", []))
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
        previous_history = deepcopy(st.session_state.agent_history)
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            status = st.status("Consultant l’agent…", expanded=True)
            answer = st.empty()
            live = LiveResponse(status, answer)
            try:
                result = asyncio.run(
                    run_agent(
                        prompt, model=model,
                        today=datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat(),
                        on_event=live.on_event,
                        message_history=previous_history,
                    )
                )
            except Exception:
                # Keep provider details and credentials out of the chat and logs.
                status.update(label="Consulta fallida", state="error", expanded=True)
                answer.empty()
                message = "No s’ha pogut completar la consulta. Revisa la configuració i la connexió i torna-ho a provar."
                st.error(message)
                st.session_state.messages.append({
                    "role": "assistant", "content": message, "error": True,
                    "tool_calls": list(live.calls.values()),
                })
                # Keep the question's context, never replay unfinished tool calls.
                st.session_state.agent_history = previous_history + [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": message},
                ]
            else:
                if not live.calls:
                    with status:
                        render_trace(result["tool_calls"])
                status.update(label="Consulta completada", state="complete", expanded=True)
                answer.markdown(result["answer"])
                render_metadata(result)
                st.session_state.messages.append({
                    "role": "assistant", "content": result["answer"],
                    "result": {key: value for key, value in result.items()
                               if key != "message_history"},
                })
                st.session_state.agent_history = deepcopy(result.get("message_history", [
                    *previous_history, {"role": "user", "content": prompt},
                    {"role": "assistant", "content": result["answer"]},
                ]))
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
