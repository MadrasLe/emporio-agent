# Empório da Música — customer-service agent

A text-message agent ("**Lia**") that answers customers of *Empório da Música*, a
musical-instrument store in Campo Grande/MS: catalog, prices, stock, payment
conditions, order status, returns and store policies — in Brazilian Portuguese,
in the store's tone, and without ever making up a price or a rule.

Built for the Artefact AI Engineer technical case.

**The one-line idea:** *the LLM understands and talks; Python decides.* Every
price, installment plan, deadline and eligibility comes from deterministic,
tested code. The model only chooses which tool to call and explains the result —
and a code-enforced "constitution" checks both its tool calls and its answers.

- [Quick start](#quick-start) · [Architecture](#architecture) · [Technical decisions](#technical-decisions)
- [Assumptions](#assumptions) · [Evaluation](#evaluation) · [Example conversations](conversations/)
- [Limitations and next steps](#known-limitations-and-what-i-would-do-with-more-time) · [Use of AI assistants](#use-of-ai-coding-assistants)

---

## Quick start

Requirements: Python 3.10+ and an [OpenRouter](https://openrouter.ai/keys) key (free models work).

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows · use `source .venv/bin/activate` on macOS/Linux
pip install -e ".[ui,dev]"
cp .env.example .env              # then set LLM_API_KEY=sk-or-...
```

| What | Command |
|---|---|
| Chat in the terminal | `emporio` (or `python -m emporio.cli`) · `--session NAME` resumes a conversation · `--trace` shows rule traces |
| Chat in the browser | `streamlit run src/emporio/ui/app.py` |
| Unit + offline graph tests (no API key needed) | `pytest` |
| Scenario evals against the real model | `python -m emporio.evals` |
| Data-quality report | `python -m emporio.data.quality` |

Configuration (`.env`):

| Variable | Default | Notes |
|---|---|---|
| `LLM_API_KEY` | — | OpenRouter key (`OPENROUTER_API_KEY` also works) |
| `LLM_MODEL` | `nvidia/nemotron-3.5-super-vl:free` | any OpenRouter model id |
| `LLM_FALLBACK_MODELS` | two other free models | OpenRouter tries them when the main one fails (free models often return HTTP 429) |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | any OpenAI-compatible endpoint, e.g. Ollama `http://localhost:11434/v1` |
| `EMPORIO_NOW` | `2026-03-25T14:30` | pinned clock (see [Assumptions](#assumptions)); remove to use the real clock |

---

## What the agent does

| Case requirement | How |
|---|---|
| Persona aligned with the store | Persona built from the manual's own customer-service guidelines (section 7): informal but professional, "a friend who knows music", the 5-step service flow. |
| Answer from the provided context | 9 tools over the CSVs and the policy manual; nothing price-related comes from the model's memory. |
| Know when to query **data** vs **policies** | Data tools (`search_products`, `get_product`, `quote_order`, `shipping_quote`, `get_orders`, `check_return`) vs `get_policy` (loads one policy document on demand). The choice is visible in the CLI/UI "behind the scenes" panel. |
| Handle out-of-scope questions | Accessories are redirected (the store only sells instruments — but "7-string guitar" and "orchestral strings" *are* instruments); empty categories never get invented items; unrelated topics and prompt injection are declined. |

Extras that a real store would need: identity verification before showing any
order (LGPD), late-order detection, complaint tickets with a 24-business-hour
SLA, store open/closed awareness (with holidays), and conversation history that
survives restarts.

---

## Architecture

```
customer message
     │
     ▼
┌──────────────────────── LangGraph (one customer turn) ─────────────────────────┐
│  agent (LLM) ──tool calls──▶ tools ──▶ agent ──answer──▶ constitution ──ok──▶ END │
│                               │                              │                 │
│                     constitution GATE              answer VALIDATORS            │
│                     (before each tool)             C1 money · C2 promo ·        │
│                     identity, ownership,           C4 privacy · C6 offers       │
│                     write budget                   → revise once → safe fallback │
└───────────────────────────────┬────────────────────────────────────────────────┘
                                │ thin tools (JSON in Portuguese)
                                ▼
      domain/ — pure Python, no LLM ─────────────────────────────────────────────
        catalog (filters + BM25)   pricing (promo, PIX, installments)
        orders (identity FSM, return/warranty rules)   store (hours, holidays, freight)
                                │ uses
                                ▼
      decisions/ — RulePolicy & StateMachinePolicy → Decision + trace (from JadeAgent)
      data/      — typed CSV loader, Decimal money, data-quality report
      knowledge/ — policies as markdown (one file per topic), persona, constitution
```

```
src/emporio/
├── agent/        graph.py · tools.py · constitution.py · prompts.py · runtime.py · session.py
├── domain/       catalog.py · bm25.py · pricing.py · orders.py · store.py · money.py
├── decisions/    types.py · rules.py · state_machine.py   (trimmed port from JadeAgent)
├── data/         loader.py · quality.py
├── ui/app.py     Streamlit
├── cli.py        terminal chat
├── evals.py      scenario evals
└── knowledge.py  markdown knowledge base loader
knowledge/        persona.md · constitution.md · policies/*.md
evals/            scenarios.yaml · results/ · REPORT.md
conversations/    example conversations (generated from real runs)
```

---

## Technical decisions

### 1. Approach: function calling over a deterministic domain (not RAG-only, not a SQL agent)

The store's questions are mostly **structured** (price, stock, order status) and
the manual is explicit: *"never give prices, stock or deadlines without checking
the system"*. So:

- **Function calling** with 9 narrow, typed tools. The model picks the tool and the
  arguments; Python does the lookup and the math.
- **No SQL agent.** Letting the model write SQL over prices and stock is exactly the
  failure mode the manual forbids. Typed tools give the same flexibility for the
  questions customers actually ask, with no injection surface.
- **The LLM never computes.** PIX discount, "promotion is not cumulative with PIX",
  installment tiers (R$ 50 / 80 / 100 minimums), free-shipping threshold, 7/30/90-day
  windows — all in `domain/`, all unit-tested. Example: Ohana CK-20 costs R$ 549,00
  with 20% off = R$ 439,20; PIX does not stack; 6x would be R$ 73,20 (< R$ 80), so the
  maximum is **5x of R$ 87,84**. Models get this wrong surprisingly often; code doesn't.

### 2. Framework: LangGraph, with a custom graph

LangGraph gives a small, explicit state machine, a checkpointer for conversation
history and good provider portability. I did **not** use the prebuilt ReAct agent
because I needed two custom nodes:

- a **tool node** that runs every call through the constitution gate and updates
  session state (identity, tickets) between calls in the same turn, and
- a **constitution node** that validates the final answer and can send it back to
  the agent (with the critique) once.

### 3. Explainable decisions — reused from my framework JadeAgent

Business rules with precedence are written as `RulePolicy` (ordered rules, first
match wins, fails closed) and the identity flow as a `StateMachinePolicy`. Both
return a `Decision` plus a trace (which rules were checked, which matched). These
primitives are a trimmed port of the `deterministic` package of
[JadeAgent](https://github.com/MadrasLe/JadeAgent), my open-source agent runtime.

- **Identity (LGPD) is a state machine**: `anon → verified` with two factors (order
  number + e-mail/phone, or e-mail + phone); 3 failures → `locked` → human handoff.
  It is enforced in code, not in the prompt.
- **Returns/exchanges/warranty** are 11 ordered rules from manual sections 4 and 8.
  When the customer does not say why, the tool evaluates every path, so the model
  never computes a deadline (in a live test it had "forgotten" the 90-day legal
  warranty when reasoning on its own).

### 4. The constitution (`knowledge/constitution.md`, enforced in `agent/constitution.py`)

Seven principles; each one states how it is enforced:

| | Principle | Enforced by |
|---|---|---|
| C1 | Only numbers that came from a tool (or the customer) | validator: every `R$` amount in the answer must appear in this conversation's tool results |
| C2 | Promotional price always with the original price and the % | validator |
| C3 | Order data only for its verified owner | **gate** before the tool runs (identity, ownership — without confirming that someone else's order exists) |
| C4 | No personal data of other customers | validator (e-mails, phones, full names) |
| C5 | Nothing invented (products, policies, partner stores) | prompt |
| C6 | No promises only the team can keep (refunds, reservations, closing a sale) | prompt + validator |
| C7 | Fixed role; injection attempts ignored | prompt |

A failing answer is sent back **once** with the exact violation; if it fails
again, it is replaced by a safe hand-off to the team. Validators are cheap
regex/lookup checks — no extra LLM call, which matters on free-tier rate limits.

### 5. Retrieval

- **Policies: routed markdown, no vector store.** The manual became 8 markdown files
  (one per topic, YAML front-matter with *when to use*). The prompt carries only the
  index; the model loads the relevant file with `get_policy`. With 8 short documents
  (~3k tokens in total) this is exact, explainable and needs zero infrastructure;
  embeddings would add a dependency and a way to miss the right section.
  Customer-facing policy and assistant *behaviour* rules were separated: section 7 of
  the manual (tone, service flow) is instruction for the assistant, so it lives in
  `persona.md`, always loaded.
- **Products: hybrid search.** Hard filters (category, price, availability) decide
  what *may* be shown; **BM25** over name (double weight), description and specs
  decides the order; fuzzy matching covers typos; the category is inferred from the
  text only when unambiguous ("violão 7 cordas" is not forced into "Cordas
  Orquestrais"). Before BM25, a descriptive request like *"violão bom pra tocar
  choro"* returned nothing; now it returns the three 7-string guitars whose
  descriptions mention *choro*. Implemented in ~35 lines without a new dependency
  (64 products don't need a search engine).

### 6. Model and provider

OpenRouter (OpenAI-compatible) so the evaluator can use **free** models with one key
and switch to any paid model by changing `LLM_MODEL`. Free models are frequently
rate-limited upstream (HTTP 429), so the client passes OpenRouter's native
`models` fallback list; the CLI/UI show when a fallback model answered. The default
model was chosen by running the scenario evals (see [Evaluation](#evaluation)).

### 7. Prompt strategy

The system prompt is rebuilt **every turn** from: persona → constitution → policy
index → live context (current time and whether the store is open, catalog counts
per category — including the empty ones —, identity state, open tickets). Tool
descriptions carry the "when to use" guidance, and tool results include short
`instrucao` hints where the model tends to slip (e.g. *"don't say which identity
field is wrong"*). Customer-facing text is Portuguese; code and docs are English.

### 8. Conversation persistence

Yes — a customer coming back on WhatsApp expects context. LangGraph's SQLite
checkpointer stores each conversation by session id (`.state/conversations.sqlite`),
including identity state. The internal critique and rejected drafts are removed
from the history the customer sees.

### 9. Data handling

CSVs are loaded into typed, immutable records (money as `Decimal`). No database:
64 products and 20 orders fit in memory, and an evaluator should not need to run
one. In production `data/loader.py` would become a repository over Postgres; the
domain would not change. `python -m emporio.data.quality` reports what the agent
has to handle instead of hiding — see [Assumptions](#assumptions).

### 10. Interface

A terminal chat (shows each tool call, gate decision and revision) and a Streamlit
chat with a per-answer **"Bastidores"** (behind the scenes) panel — useful to see
*why* the agent answered what it answered.

---

## Assumptions

The case says to assume reasonable interpretations and document them.

**Time.** The data ends in March 2026. With the real clock every order would be
months old and no return/delay scenario would be meaningful, so the clock is pinned
to **Wednesday 2026-03-25 14:30** (`EMPORIO_NOW`, America/Campo_Grande). Remove it
to use the real clock.

**Policy interpretations**

| Manual says | Interpretation |
|---|---|
| Two WhatsApp numbers: (67) 3341-4444 (cover, company data) and (67) 3321-4500 (section 7) | Use **3341-4444** (appears twice, in the official company table) |
| E-mail written with and without accent | Use `contato@emporiodamusica.com.br` (valid domain) |
| Credit-card table: "minimum installment R$ 100"; section 3.1: tiers | Follow the **tiers** (more specific): up to 3x min. R$ 50 ("no minimum, except below R$ 50"), 4–6x min. R$ 80, 7–12x min. R$ 100; 1x always allowed |
| Regret right counts from *receipt* | The data has no delivery date; the **estimated delivery** is used as receipt date |
| Preference exchange "within 7 days" | Counted from receipt, like the regret right |
| Defect exchange: 30 days from *purchase*; legal warranty: 90 days from *receipt* | Applied literally; after 30 days the store can broker the manufacturer warranty |
| Orders in the system | Treated as online orders (regret right applies) |
| Order cancellation | Not covered by the manual → the agent opens a ticket for the team |
| "Região metropolitana de Campo Grande" | Only Campo Grande is confirmed by the data; other cities get the carrier table (list is configurable) |
| Holidays | National + MS state + Campo Grande holidays (configurable) |
| Several promotions per product | Only active rows count; if several were active, the best applies (not cumulative) |
| Product status vs stock | Status wins: `discontinued` with stock is not sold; `coming_soon` is shown as "em breve" |

**Data-quality findings** (from `python -m emporio.data.quality`) — reported, not silently fixed:

- 3 categories (woodwinds, brass, orchestral strings) have **no products**, although the manual says the store sells them → the agent says so and never invents items.
- 6 products have a **description citing another brand** (e.g. "Music Man Bass 1X" described as a "Fender Jazz Bass") → `get_product` warns the model to stick to the product name.
- Ibanez Bass 2X is `discontinued` with 13 in stock; Kala KA-ABP-CTG is `coming_soon` with stock and appears in a *delivered* order.
- Orders 3 and 20: recorded total differs from the items at current prices (no price history in the data) → totals are reported as recorded.
- Orders 9, 16, 18 break the installment minimums (historical; new quotes follow the policy).
- Two customers share one e-mail → e-mail alone never identifies a customer.
- Order 8 is late; several orders are stuck in `pending`/`confirmed` → the agent flags them and offers a ticket.

---

## Evaluation

- **94 unit and offline tests** (`pytest`, no API key): every business rule, the
  identity state machine, search, the constitution gate and validators, and the
  full graph driven by a scripted model (verify-then-fetch in one turn, someone
  else's order blocked, invented price revised with a tool call, second violation →
  safe fallback, history persistence).
- **Scenario evals against the real model** (`python -m emporio.evals`): 14
  conversations / 20 turns / 78 checks in `evals/scenarios.yaml` — which tools ran
  (or were blocked), required facts in the answer (e.g. *"5x de R$ 87,84"*, the
  18/05 warranty date) and forbidden content (out-of-stock items, someone else's
  order, a "50% off" price from a prompt injection). Results:
  [`evals/REPORT.md`](evals/REPORT.md).

| Run | Scenarios | Checks | Avg latency / turn | Notes |
|---|---|---|---|---|
| `nvidia/nemotron-3.5-super-vl:free` + fallbacks (**default**) | **14/14** | **78/78** | 8.4 s | 2 turns served by a fallback model; no revisions needed |
| `google/gemma-4-31b-it:free`, no fallback | 0/14 | 6/27 | — | 18 of 20 turns failed with HTTP 429 (free endpoint saturated) — this measures availability, not quality |

How the evals were actually used:

- **The first full run scored 11/14 and exposed three real bugs** (fixed in the commit
  *"fix: bugs found by the first scenario-eval run"*):
  1. the C4 privacy validator read the date inside a ticket protocol
     (`EM-20260325-…`) as a phone number, so the customer's answer with the protocol was
     replaced by the generic hand-off;
  2. *"violão Yamaha C40"* did not resolve to the product (exact model-code matching
     added before fuzzy matching);
  3. when asked only about *regret*, the answer omitted that the 90-day legal warranty
     was still valid (`check_return` now adds the other paths when the asked one is closed).
- **Model choice.** Gemma 4 31B (free) was the first default; its free endpoint
  kept returning 429 in sequence (table above). Nemotron 3.5 Super (free) made correct
  tool calls in a probe and passes the whole suite; OpenRouter fallbacks keep the agent
  available when it is saturated. Any other model can be compared with
  `python -m emporio.evals --model <id> --no-fallback`.
- Each scenario runs once, so a pass is evidence, not a guarantee (one failure in a
  re-run of the first suite did not reproduce — model variance).

---

## Example conversations

Generated from real runs (`python -m emporio.evals --write-conversations`), each
with a collapsible "Bastidores" section showing the tools, gate decisions and
rules behind every answer:

1. [Catalog: guitars up to R$ 1,000](conversations/01-catalogo-violoes.md)
2. [Price, PIX and installments (incl. a promotion and a rejected 6x)](conversations/02-preco-e-parcelamento.md)
3. [Return for regret: identity check + return/warranty rules](conversations/03-devolucao-arrependimento.md) — non-trivial
4. [Late order and complaint ticket](conversations/04-pedido-atrasado.md) — non-trivial
5. [Out of scope: accessories and an unrelated question](conversations/05-fora-do-escopo.md)

---

## Known limitations and what I would do with more time

- **Semantic search.** BM25 does not know that *viagem* ≈ *viajante* ("ukulele for
  travelling" falls back to the whole category). With more time: embeddings over
  the 64 products as a re-ranker, or LLM query expansion.
- **Free models.** Upstream rate limits make free models slow or flaky at peak
  times; fallbacks help but don't remove it. For production: a paid model with
  prompt caching (the system prompt is stable) and streaming responses.
- **Static data.** CSVs are read at start-up. Production would read live
  inventory/orders from the store's systems through the same repository interface.
- **The agent informs, it doesn't transact.** No reservations, payments or
  cancellations — by design (C6); tickets go to a JSONL file instead of a helpdesk.
  Next step: integrate a ticketing API and WhatsApp Business.
- **Validators are lexical.** C1/C2/C4/C6 catch the high-risk failures cheaply but
  not every hallucination (e.g. a wrong spec without a price). Next: an LLM-as-judge
  in the eval suite (not in the hot path) and more adversarial scenarios.
- **Evals are small** (14 scenarios) and run one sample per scenario; I would add
  repeated runs to measure variance and track regressions in CI.
- **Observability.** Audit events are shown in the UI/CLI but not shipped anywhere;
  next would be tracing (e.g. Langfuse/LangSmith) and the decision trace hashes
  persisted per answer.

---

## Use of AI coding assistants

I used **Claude Code** (Anthropic) as a pair programmer throughout, and I'm
describing the workflow because the case asks for it:

- **I drove the design.** I defined the architecture and the decisions above:
  LangGraph only for orchestration, a pure-Python domain, OpenRouter with free
  models, Streamlit + CLI, the pinned clock, and — after first being told to skip
  it — reusing the explainable-decision primitives, state machines and
  "constitution" ideas from my own framework, JadeAgent. I also pushed for BM25
  when the first search turned out to be keyword-only.
- **The assistant implemented under that direction**, in small steps, each one a
  commit (see the history), guided by repository conventions written for coding
  assistants in [`AGENTS.md`](AGENTS.md) (e.g. "the LLM never computes business
  facts", "every rule has a unit test").
- **Live testing drove the fixes.** Several commits come from running the agent
  against the real model and reading the transcripts: it offered to "reserve" items
  (→ C6), computed return deadlines itself (→ `check_return` evaluates every path),
  didn't pass descriptive words to search (→ tool description), and free models hit
  429s (→ OpenRouter fallbacks).
- I reviewed the code and the test results at each step.
