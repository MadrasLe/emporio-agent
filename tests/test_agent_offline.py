"""Graph wiring, constitution gate and validators, with a scripted model (no API key needed)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from emporio.agent import Assistant, Runtime
from emporio.agent.constitution import FALLBACK_ANSWER, check_answer
from emporio.agent.tools import build_tools
from emporio.config import PROJECT_ROOT, Settings


class ScriptedChatModel(BaseChatModel):
    """Returns pre-written messages in order and records what it was sent."""

    script: list[Any]
    calls: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append(messages)
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])


def call(name: str, call_id: str = "c1", **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def calls(*items: tuple[str, dict]) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": n, "args": a, "id": f"c{i}"} for i, (n, a) in enumerate(items)])


@pytest.fixture
def make_assistant(data, knowledge, now, tmp_path):
    def factory(*script: AIMessage) -> tuple[Assistant, ScriptedChatModel]:
        settings = Settings(PROJECT_ROOT / "data", PROJECT_ROOT / "knowledge", tmp_path, "http://fake", "k",
                            "scripted", 0.0, now)
        model = ScriptedChatModel(script=list(script))
        return Assistant(Runtime(settings, data, knowledge, model, build_tools(data, knowledge))), model
    return factory


def test_tool_schemas_are_valid_openai_functions(data, knowledge):
    for spec in build_tools(data, knowledge).values():
        schema = spec.openai_schema()
        assert schema["function"]["name"] == spec.name
        assert schema["function"]["parameters"]["type"] == "object"
    policy_schema = build_tools(data, knowledge)["get_policy"].openai_schema()
    assert "trocas-devolucoes" in policy_schema["function"]["parameters"]["properties"]["topic"]["enum"]


def test_price_question_is_answered_from_a_tool(make_assistant):
    assistant, model = make_assistant(
        call("get_product", product="Takamine GD20"),
        AIMessage("O Takamine GD20 sai por R$ 2.199,00, ou R$ 2.089,05 no PIX."),
    )
    result = assistant.reply("t1", "Quanto custa o Takamine GD20?")
    assert result.tools_called == ["get_product"]
    assert "2.199,00" in result.answer
    assert result.audit[-1] == {"type": "constitution", "ok": True, "revised": False}
    tool_message = [m for m in model.calls[1] if isinstance(m, ToolMessage)][0]
    assert json.loads(tool_message.content)["precos"]["pix"].startswith("R$ 2.089,05")


def test_order_data_is_blocked_without_identity(make_assistant):
    assistant, model = make_assistant(
        call("get_orders", order_id=7),
        AIMessage("Para ver o pedido, me passa o número e o e-mail do cadastro?"),
    )
    result = assistant.reply("t1", "cadê meu pedido 7?")
    gate = result.audit[0]["gate"]
    assert gate["outcome"] == "reject" and gate["rule_id"] == "G_IDENTITY_REQUIRED"
    tool_message = [m for m in model.calls[1] if isinstance(m, ToolMessage)][0]
    assert "bloqueado_pela_constituicao" in tool_message.content


def test_verify_then_fetch_in_the_same_turn(make_assistant):
    assistant, _ = make_assistant(
        calls(("verify_customer", {"order_id": 7, "email": "leticia.rocha@jmail.com"}),
              ("get_orders", {"order_id": 7})),
        AIMessage("Achei, Letícia! Seu pedido 7 foi entregue."),
    )
    result = assistant.reply("t1", "pedido 7, email leticia.rocha@jmail.com")
    assert [e["gate"]["outcome"] for e in result.audit if e["type"] == "tool"] == ["action", "action"]
    assert assistant.session_state("t1")["customer_id"] == 14


def test_check_return_without_reason_evaluates_every_path(make_assistant):
    assistant, model = make_assistant(
        calls(("verify_customer", {"order_id": 7, "email": "leticia.rocha@jmail.com"}),
              ("check_return", {"order_id": 7})),
        AIMessage("O prazo de arrependimento terminou, mas a garantia legal ainda vale."),
    )
    assistant.reply("t1", "pedido 7, leticia.rocha@jmail.com, posso devolver?")
    tool_message = [m for m in model.calls[1] if isinstance(m, ToolMessage) and m.name == "check_return"][0]
    rules = [a["regra_aplicada"] for a in json.loads(tool_message.content)["avaliacoes"]]
    assert rules == ["RET_REGRET_EXPIRED", "RET_DEFECT_LEGAL", "RET_PREF_EXPIRED"]


def test_someone_elses_order_is_blocked(make_assistant):
    assistant, _ = make_assistant(
        calls(("verify_customer", {"order_id": 7, "phone": "(67) 99789-0123"}), ("get_orders", {"order_id": 1})),
        AIMessage("Esse pedido não aparece no seu cadastro. Pode conferir o número?"),
    )
    result = assistant.reply("t1", "quero ver o pedido 1")
    assert result.audit[1]["gate"]["rule_id"] == "G_ORDER_OWNERSHIP"


def test_invented_price_is_revised_with_a_tool_call(make_assistant):
    assistant, _ = make_assistant(
        AIMessage("O Takamine GD20 custa R$ 1.999,00."),          # draft without a tool: C1
        call("get_product", product="Takamine GD20"),             # revision fetches the data
        AIMessage("O Takamine GD20 custa R$ 2.199,00."),
    )
    result = assistant.reply("t1", "Quanto custa o Takamine GD20?")
    assert "2.199,00" in result.answer
    violation = next(e for e in result.audit if e["type"] == "constitution" and not e["ok"])
    assert violation["violations"][0]["principle"] == "C1"
    assert result.audit[-1] == {"type": "constitution", "ok": True, "revised": True}
    # the customer-visible history has neither the bad draft nor the internal critique
    assert assistant.history("t1") == [("user", "Quanto custa o Takamine GD20?"), ("assistant", result.answer)]


def test_second_violation_falls_back_to_escalation(make_assistant):
    assistant, _ = make_assistant(AIMessage("Custa R$ 1.999,00."), AIMessage("Custa R$ 1.888,00."))
    result = assistant.reply("t1", "Quanto custa o Takamine GD20?")
    assert result.answer == FALLBACK_ANSWER
    assert result.audit[-1] == {"type": "constitution", "fallback": True}


def test_promotional_price_needs_original_price_and_discount(make_assistant):
    assistant, _ = make_assistant(
        call("get_product", product="Ohana CK-20"),
        AIMessage("O Ohana CK-20 está saindo por R$ 439,20!"),
        AIMessage("O Ohana CK-20 está com 20% off: de R$ 549,00 por R$ 439,20."),
    )
    result = assistant.reply("t1", "e o ukulele ohana ck-20?")
    assert "549,00" in result.answer
    principles = [v["principle"] for e in result.audit if e["type"] == "constitution" and not e["ok"]
                  for v in e["violations"]]
    assert principles == ["C2"]


def test_history_persists_across_turns(make_assistant):
    assistant, _ = make_assistant(AIMessage("Oi! Sou a Lia, como posso ajudar?"),
                                  AIMessage("Nosso horário é de segunda a sexta, das 9h às 18h."))
    assistant.reply("t1", "oi")
    assistant.reply("t1", "que horas vocês abrem?")
    assert [role for role, _ in assistant.history("t1")] == ["user", "assistant", "user", "assistant"]


def test_ticket_is_written_and_counted(make_assistant, tmp_path):
    assistant, _ = make_assistant(
        call("open_ticket", kind="reclamacao", summary="pedido 8 atrasado", contact="(67) 99654-7821"),
        AIMessage("Registrei sua reclamação. A equipe retorna em até 24 horas úteis."),
    )
    assistant.reply("t1", "meu pedido está atrasado, quero reclamar")
    lines = (tmp_path / "tickets.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["tipo"] == "reclamacao"
    assert len(assistant.session_state("t1")["tickets"]) == 1


def test_privacy_validator_blocks_other_customers_data(data):
    violations = check_answer("O pedido é do Pedro Henrique Oliveira (pedro.oliveira@jmail.com).",
                              evidence="", customer_text="de quem é o pedido 1?", data=data,
                              verified_customer_id=14)
    assert {v.principle for v in violations} == {"C4"}
    assert check_answer("Fale com a gente: (67) 3341-4444 ou contato@emporiodamusica.com.br",
                        evidence="", customer_text="contato?", data=data, verified_customer_id=None) == []


@pytest.mark.parametrize("answer, flagged", [
    ("Temos 5 unidades. Quer que eu reserve uma para você?", True),
    ("Posso separar um pra você até amanhã.", True),
    ("Quer que eu já feche o pedido?", True),
    ("Não posso reservar produtos, mas a equipe finaliza sua compra pelo WhatsApp.", False),
    ("Posso abrir um chamado para a equipe avaliar seu caso?", False),
    ("A loja está fechada agora; posso te ajudar com outra coisa?", False),
])
def test_unsupported_offers_are_caught(data, answer, flagged):
    violations = check_answer(answer, evidence="", customer_text="", data=data, verified_customer_id=None)
    assert any(v.principle == "C6" for v in violations) is flagged


def test_customer_typed_values_are_grounded(data):
    assert check_answer("Separei opções até R$ 1.000,00 pra você:", evidence="",
                        customer_text="violões até 1000 reais", data=data, verified_customer_id=None) == []
