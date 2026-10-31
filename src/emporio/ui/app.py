"""Web chat with Lia: ``streamlit run src/emporio/ui/app.py``.

Customer view on the left; a "behind the scenes" panel shows the tools, the
constitution gate and the business rules behind every answer.
"""

from __future__ import annotations

import json
import uuid

import streamlit as st

from emporio.agent import Assistant, MissingAPIKey, load_runtime, open_checkpointer
from emporio.config import load_settings

st.set_page_config(page_title="Empório da Música · Lia", page_icon="🎸", layout="centered")

EXAMPLES = [
    "Quais violões vocês têm até R$ 1000?",
    "Quanto custa o Takamine GD20?",
    "Tem violão bom pra tocar choro?",
    "Me arrependi da compra, posso devolver o pedido?",
    "Vocês vendem cordas e pedais?",
]
IDENTITY_LABEL = {"verified": "✅ verificado", "locked": "⛔ bloqueado (3 tentativas)"}


@st.cache_resource
def get_assistant() -> Assistant:
    settings = load_settings()
    return Assistant(load_runtime(settings), open_checkpointer(settings))


def md(text: str) -> str:
    """Streamlit renders $...$ as LaTeX; prices like 'R$ 10' must be escaped."""
    return text.replace("$", "\\$")


def render_audit(audit: list[dict]) -> None:
    with st.expander("🔧 Bastidores desta resposta"):
        for event in audit:
            kind = event.get("type")
            if kind == "tool":
                gate = event["gate"]
                args = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in event["args"].items())
                if gate["outcome"] == "reject":
                    st.markdown(md(f"⛔ **{event['tool']}**({args}) — bloqueado pela constituição: "
                                   f"{gate['reason']} `{gate['rule_id']}`"))
                else:
                    line = f"🔧 **{event['tool']}**({args})"
                    if decision := event.get("decision"):
                        line += f" → regra `{decision['rule_id']}`"
                    st.markdown(md(line))
                    st.json(event.get("result", {}), expanded=False)
            elif kind == "llm_fallback":
                st.markdown(f"↪ modelo principal indisponível; respondido por `{event['model']}`")
            elif kind == "constitution":
                if event.get("fallback"):
                    st.markdown("🛡️ Constituição: revisão falhou de novo → resposta trocada por encaminhamento")
                elif not event.get("ok"):
                    issues = "; ".join(f"{v['principle']}: {v['message']}" for v in event["violations"])
                    st.markdown(md(f"🛡️ Constituição **barrou o rascunho** ({issues}) e pediu revisão"))
                else:
                    st.markdown("🛡️ Constituição: resposta aprovada" + (" após revisão" if event.get("revised") else ""))


try:
    assistant = get_assistant()
except MissingAPIKey as exc:
    st.error(str(exc))
    st.code("cp .env.example .env   # then set LLM_API_KEY", language="bash")
    st.stop()

runtime = assistant.runtime
st.session_state.setdefault("thread_id", f"web-{uuid.uuid4().hex[:8]}")
st.session_state.setdefault("audits", {})  # thread -> {assistant turn index: audit}

with st.sidebar:
    st.header("🎸 Empório da Música")
    st.caption("Protótipo do agente de atendimento · Lia")
    if st.button("➕ Nova conversa", use_container_width=True):
        st.session_state.thread_id = f"web-{uuid.uuid4().hex[:8]}"
        st.rerun()
    thread_id = st.text_input("Sessão (retome pelo id)", value=st.session_state.thread_id).strip()
    st.session_state.thread_id = thread_id
    show_internals = st.toggle("Mostrar bastidores", value=True)

    session = assistant.session_state(thread_id)
    st.markdown(f"**Cliente:** {IDENTITY_LABEL.get(session.get('identity_state'), 'não verificado')}")
    if session.get("tickets"):
        st.markdown("**Chamados:** " + ", ".join(session["tickets"]))

    st.divider()
    st.markdown("**Experimente:**")
    for example in EXAMPLES:
        if st.button(example, use_container_width=True):
            st.session_state.pending = example

    st.divider()
    settings = runtime.settings
    clock = "simulado" if settings.now_override else "real"
    st.caption(f"Modelo: `{settings.llm_model}`")
    st.caption(f"Agora: {runtime.now():%d/%m/%Y %H:%M} (relógio {clock})")

st.title("Fale com a Lia 🎶")
audits = st.session_state.audits.setdefault(thread_id, {})

assistant_turn = 0
for role, text in assistant.history(thread_id):
    with st.chat_message(role, avatar="🎸" if role == "assistant" else "🙂"):
        st.markdown(md(text))
        if role == "assistant":
            if show_internals and assistant_turn in audits:
                render_audit(audits[assistant_turn])
            assistant_turn += 1

prompt = st.chat_input("Escreva sua mensagem…") or st.session_state.pop("pending", None)
if prompt:
    with st.chat_message("user", avatar="🙂"):
        st.markdown(md(prompt))
    with st.chat_message("assistant", avatar="🎸"):
        try:
            with st.spinner("Lia está digitando…"):
                result = assistant.reply(thread_id, prompt)
        except Exception as exc:  # provider errors: rate limit, model not found, network
            st.error(f"Não consegui falar com o modelo ({type(exc).__name__}): {exc}")
            st.stop()
        audits[assistant_turn] = result.audit
    st.rerun()
