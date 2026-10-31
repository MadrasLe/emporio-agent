# AGENTS.md

Instructions for coding assistants (Claude Code, Codex, Cursor, ...) working on
this repository. The customer-service agent itself never reads this file.

## What this project is

A customer-service agent for *Empório da Música*, a fictional musical
instrument store in Campo Grande/MS. Customers chat in Brazilian Portuguese;
code, comments and docs are in English.

## Commands

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows (use bin/activate elsewhere)
pip install -e ".[ui,dev]"
pytest                                           # must pass before every commit
python -m emporio.data.quality                   # data-quality report
emporio                                          # CLI chat
streamlit run src/emporio/ui/app.py              # web UI
```

## Architecture rules (do not break)

1. **The LLM never computes business facts.** Prices, PIX discounts,
   installments, shipping, deadlines and eligibility are computed in
   `src/emporio/domain/` and returned by tools. The LLM only explains them.
2. **Domain code is pure Python.** No LLM or LangGraph imports in `domain/`,
   `data/` or `decisions/`. Every rule there has a unit test.
3. **Decisions are explainable.** Business rules with precedence are expressed
   with `emporio.decisions` (`RulePolicy`, `StateMachinePolicy`) and return a
   `Decision` plus a trace. Tools forward the reason to the LLM.
4. **Knowledge lives in markdown.** Store policies are in
   `knowledge/policies/*.md` (one file per topic, YAML frontmatter). Behaviour
   rules for the assistant are in `knowledge/persona.md` and
   `knowledge/constitution.md`. Do not hard-code policy text in Python.
5. **Money is `Decimal`**, rounded half-up to cents, formatted with
   `emporio.domain.money.brl`.
6. **Tools stay thin.** A tool validates input, calls the domain, and returns
   compact JSON. Access control lives in the constitution gate, not in prompts.

## Data assumptions

Documented in README → "Assumptions". If you find a new inconsistency in
`data/`, add a check to `src/emporio/data/quality.py` instead of silently
fixing the data.
