"""Terminal chat with Lia. Shows which tools ran and what the constitution decided.

Usage: ``emporio [--session NAME] [--trace]`` (or ``python -m emporio.cli``).
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from .agent import Assistant, MissingAPIKey, load_runtime, open_checkpointer
from .config import load_settings

console = Console()


def _args_preview(args: dict) -> str:
    return ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items() if v not in (None, "", []))


def print_audit(audit: list[dict], trace: bool) -> None:
    for event in audit:
        if event.get("type") == "tool":
            gate = event["gate"]
            if gate["outcome"] == "reject":
                console.print(f"  [red]⛔ {event['tool']}({_args_preview(event['args'])}) bloqueado: "
                              f"{gate['reason']} [{gate['rule_id']}][/red]")
                continue
            line = f"  [dim]🔧 {event['tool']}({_args_preview(event['args'])})"
            if decision := event.get("decision"):
                line += f" → {decision['outcome']} [{decision['rule_id']}]"
            console.print(line + "[/dim]")
            if trace:
                console.print_json(json.dumps(event, ensure_ascii=False, default=str))
        elif event.get("type") == "constitution":
            if event.get("fallback"):
                console.print("  [yellow]🛡️  revisão falhou de novo: resposta substituída por encaminhamento[/yellow]")
            elif not event.get("ok"):
                issues = "; ".join(f"{v['principle']}: {v['message']}" for v in event["violations"])
                console.print(f"  [yellow]🛡️  constituição barrou o rascunho ({issues}); revisando...[/yellow]")
            elif event.get("revised"):
                console.print("  [green]🛡️  resposta revisada aprovada[/green]")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Chat with Lia, Empório da Música's assistant.")
    parser.add_argument("--session", help="conversation id to create or resume (history is kept in SQLite)")
    parser.add_argument("--trace", action="store_true", help="print full tool results and decision traces")
    args = parser.parse_args(argv)

    settings = load_settings()
    try:
        runtime = load_runtime(settings)
    except MissingAPIKey as exc:
        console.print(f"[red]{exc}[/red]")
        return 1

    assistant = Assistant(runtime, open_checkpointer(settings))
    thread_id = args.session or f"cli-{uuid.uuid4().hex[:8]}"
    clock = "relógio simulado" if settings.now_override else "relógio real"
    console.print(Panel.fit(
        f"[bold]Empório da Música[/bold] — chat com a Lia\n"
        f"modelo: {settings.llm_model} · sessão: {thread_id} · agora: {runtime.now():%d/%m/%Y %H:%M} ({clock})\n"
        "comandos: /sair · /trace (liga/desliga detalhes) · /estado",
        border_style="cyan"))

    for role, text in assistant.history(thread_id):
        console.print(f"[bold]{'você' if role == 'user' else 'Lia'}>[/bold] {text}")

    trace = args.trace
    while True:
        try:
            text = console.input("\n[bold cyan]você>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text in ("/sair", "/exit", "/quit"):
            break
        if text == "/trace":
            trace = not trace
            console.print(f"[dim]trace {'ligado' if trace else 'desligado'}[/dim]")
            continue
        if text == "/estado":
            console.print(assistant.session_state(thread_id))
            continue

        try:
            with console.status("Lia está digitando..."):
                result = assistant.reply(thread_id, text)
        except Exception as exc:  # provider errors: rate limit, model not found, network
            console.print(f"[red]Erro ao falar com o modelo ({type(exc).__name__}): {exc}[/red]")
            continue
        print_audit(result.audit, trace)
        console.print(Panel(Markdown(result.answer), title="Lia", title_align="left", border_style="magenta"))

    console.print(f"[dim]Até mais! Para retomar: emporio --session {thread_id}[/dim]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
