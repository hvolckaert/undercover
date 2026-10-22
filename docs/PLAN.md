# Plan: the claims pilot

The pilot from `docs/SPEC.md`: a backend that holds the claims queue, the UnderCover Agent that decides claims through the backend's API, and a dashboard where the handlers watch the queue, follow the agent and sign off large payouts.

## The approach

- **The backend is the system of record.** On first start it loads `data/` into a SQLite file (`backend/undercover.db`, not in git). It never reads `data/evals/` or `data/security/`, so nothing the agent can reach holds the answer key. The stdlib `sqlite3` module is enough; each table keeps the record as JSON next to the few columns we query on (id, status).
- **The backend enforces the rules, not the agent.** The $1,000 sign-off rule lives in the payment operation: if the payout is over the limit in `data/company.json` and no handler has signed off, the payment is refused, whatever the agent does. The agent's instructions mention the rule, but the system doesn't rely on them.
- **The agent only talks HTTP.** Its tools are thin wrappers over API operations, and it fetches its instructions from the backend at the start of each run. That keeps one source of truth and lets the dashboard show the instructions the agent actually uses.
- **Steps are recorded by the runner, not by the model.** `run(claim_id, thread_id)` streams the agent's progress and posts each tool call, tool result and final reply to the backend. The model can't skip or invent a step, and the dashboard polls the steps while the claim is in progress.
- **Tests never call a model.** Agent tests use a scripted stub model; the end-to-end tests drive the agent's API operations directly to simulate a run.

### Claim states

| State | Meaning | Set by |
|---|---|---|
| `waiting` | In the queue (the seed data's `open`) | Seeding, or a failed run |
| `in_progress` | The agent is working on it | `run_agent` |
| `waiting_for_signoff` | Approved with a payout over $1,000; payment held | `record_decision` |
| `decided` | Declined, referred, approved within the limit, or signed off | `record_decision`, `sign_off` |

### API operations

Every operation has an `operation_id`, a one-line docstring and no optional inputs.

| Operation | Route | Used by |
|---|---|---|
| `health` | `GET /api/health` | dashboard |
| `list_claims` | `GET /api/claims` | dashboard |
| `get_claim` | `GET /api/claims/{claim_id}` | agent, dashboard |
| `get_policy` | `GET /api/policies/{policy_id}` (with its plan's limits and add-ons) | agent, dashboard |
| `get_customer` | `GET /api/customers/{customer_id}` (with claim history) | agent, dashboard |
| `get_policy_wording` | `GET /api/policy-wording` | agent |
| `get_instructions` | `GET /api/instructions` | agent, dashboard |
| `list_handlers` | `GET /api/handlers` | dashboard |
| `run_agent` | `POST /api/claims/{claim_id}/run` | dashboard |
| `list_steps` | `GET /api/claims/{claim_id}/steps` | dashboard |
| `record_step` | `POST /api/claims/{claim_id}/steps` | agent runner |
| `record_decision` | `POST /api/claims/{claim_id}/decision` | agent |
| `pay_claim` | `POST /api/claims/{claim_id}/payment` with the amount | agent |
| `sign_off` | `POST /api/claims/{claim_id}/sign-off` with the handler id | dashboard |

A decision is `approve`, `decline` or `refer`, with the payout (0 unless approved), the calculation, a reason of two or three sentences and the policy section it rests on.

### Not in the pilot

As the spec says: no claims manual, no sign-in, no real payments, no customer messages. Scoring the agent against `data/evals/` is also left for a later build; the pilot only guarantees the agent can't see it.

## Phase 1: the records and the read API

Build `backend/db.py` to create and seed the database from `data/` (claims, policies, customers, plans and add-ons, handlers, company settings), and the read operations: `list_claims`, `get_claim`, `get_policy`, `get_customer`, `get_policy_wording`, `get_instructions` and `list_handlers`. The agent's instructions live in `backend/instructions.md`, a first version that tells the agent how to work a claim from the policy wording. The database path comes from the `UNDERCOVER_DB` environment variable, defaulting to `backend/undercover.db`, so tests and e2e use their own files.

Why first: everything else reads these records, and the data shapes settle here.

- [x] `uv run pytest backend` passes, with tests for each read operation using a temporary database
- [x] A test seeds the database and asserts it holds 25 claims, all `waiting`, and that no claim, policy or customer from `data/evals/` or `data/security/` is in it (for example, CLM-1901 returns 404)
- [x] With `npm run dev:backend` running, `Invoke-RestMethod http://127.0.0.1:8000/api/claims` returns 25 claims with id, customer name, type, amount claimed and status
- [x] `GET /api/claims/CLM-1001` returns the story, three items totaling $420.00 and the documents
- [x] `GET /api/policies/POL-2001` returns the Premium plan with its limits and a $50.00 deductible
- [x] `GET /api/customers/CUS-3001` returns Maya Patel with the earlier claim CLM-0412
- [x] `GET /api/claims/CLM-9999` returns 404
- [x] `/openapi.json` shows an `operation_id` and a summary on every operation, and no optional parameters
- [x] `npm run check:python` passes

## Phase 2: the claim workflow and the sign-off rule

Add the write operations: `record_step`, `list_steps`, `record_decision`, `pay_claim` and `sign_off`, with the state changes in the table above. `pay_claim` takes the amount and refuses (409) when the claim isn't approved, when the amount isn't the approved payout, when it's already paid, or when the payout is over $1,000 and no handler has signed off. `sign_off` takes a handler id, only works on a claim waiting for sign-off, records who signed and when, makes the payment and moves the claim to `decided`. Payments are records in a `payments` table; nothing leaves the system.

Why here: the rules belong to the backend, so they are built and tested before an agent exists to break them.

- [x] Tests cover every state change in the table, and each refusal of `pay_claim` and `sign_off`
- [x] A test approves a $1,250.00 payout: the claim goes to `waiting_for_signoff`, `pay_claim` for $1,250.00 returns 409 and no payment exists; after `sign_off` by HND-01 the claim is `decided` and one $1,250.00 payment exists
- [x] A test approves a $420.00 payout: the claim is `decided` and `pay_claim` for $420.00 succeeds once, then returns 409 the second time
- [x] A decline or refer with a payout above 0 is rejected (422)
- [x] `GET /api/claims/{claim_id}` now includes the decision, the sign-off and the payment
- [x] `npm run check:python` passes with coverage at or above 80%

## Phase 3: the UnderCover Agent

Rebuild `agent/main.py`. Its tools call the API: `get_claim`, `get_policy`, `get_customer`, `get_policy_wording`, `record_decision` and `pay_claim`. `run(claim_id, thread_id)` fetches the instructions from `get_instructions`, streams the agent with `create_agent`, posts each step with `record_step` and returns the final reply. The model stays `openai/gpt-6-luna` at low reasoning effort, or `MODEL_NAME` if set. The backend's `run_agent` sets the claim `in_progress`, makes a new thread id and runs the agent as a background task; if the run raises or ends without a decision, it records that as a step and puts the claim back to `waiting`.

Why this shape: the agent stays a thin loop over the API, so the backend's rules apply to it like anyone else, and later builds can grow its harness without touching the backend.

- [ ] Agent tests with a stub model and the backend's `TestClient` (no model calls): a scripted run reads the claim, policy, customer and wording, records a decision and pays it; the steps appear in `list_steps` in order
- [ ] A stub run that approves $1,250.00 and then calls `pay_claim` gets the refusal back as a tool result, the claim ends `waiting_for_signoff` and no payment exists
- [ ] A test for `run_agent` with the runner stubbed: the claim goes `in_progress`, and a run that raises puts it back to `waiting` with an error step
- [ ] A test asserts no agent tool or instruction mentions `data/evals`
- [ ] With a real model (`MODEL_NAME=openrouter/free` or the default), `Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/claims/CLM-1001/run` leads to a decision on CLM-1001 with a payout, a reason and a policy section, and the steps show each tool call
- [ ] `npm run check:python` passes

## Phase 4: the dashboard shell and the queue

Replace the skeleton page with the UnderCover dashboard: Instrument Sans, Instrument Serif and JetBrains Mono from Google Fonts, the brand colors and light and dark surfaces from `docs/BRAND.md`, rounded panels with no outlines. A small hash router (`#/`, `#/claims/CLM-1001`, `#/instructions`) keeps us off an extra dependency. The queue page lists every claim with its id, customer, type, amount claimed and state, with counts for each state; states use Sea Green, Marigold, Coral and Cerulean. The instructions page shows the agent's instructions, read only. A typed `api.ts` holds every fetch.

Why: the queue is the handlers' home screen, and building the shell first fixes the look for the claim page.

- [ ] Vitest tests for the queue (renders claims and state counts from a mocked API) and the instructions page
- [ ] In the browser via the Playwright MCP server, `http://localhost:5173` shows 25 claims, the counts by state, amounts like $420.00 and the brand fonts and colors, in light and dark mode
- [ ] The instructions page shows the text of `backend/instructions.md` with no way to edit it
- [ ] At phone width the queue has no horizontal page scroll
- [ ] `npm run check:ts` passes with coverage at or above 80%

## Phase 5: the claim page, live steps and sign-off

The claim page shows the claim in full (story, items, documents), the policy and plan, the customer's claim history, and the agent's decision with its payout, calculation, reason and policy section. A "Run agent" button starts the agent on a waiting claim. While the claim is in progress the page polls `list_steps` every second and shows each step as it lands. A claim waiting for sign-off shows the held payment and a sign-off control where a handler picks their name and confirms; the page then shows who signed off and the payment.

Why: this is where handlers check the agent's work, so the decision, its reasons and how it got there sit together.

- [ ] Vitest tests for the claim page in each state, the step list updating while polling, and the sign-off control
- [ ] In the browser via the Playwright MCP server: running the agent on CLM-1001 shows steps appearing while it works, then the decision, reason and policy section
- [ ] In the browser, a claim approved over $1,000 shows the payment held, and signing off as Dana Whitfield moves it to decided with the payment shown
- [ ] `npm run check:ts` passes

## Phase 6: end-to-end tests and handover

Playwright tests that run against a fresh database on their own ports (backend 8001, dashboard 5174, with the Vite proxy target from an environment variable), so they never touch the dev database or clash with other software on 8000 and 5173. The tests stand in for the agent by calling its API operations directly: they record steps and a decision, then check the dashboard. Update `docs/STATUS.md` with what's built and how to run it, and add `backend/undercover.db` to `.gitignore`.

Why: the e2e tests prove the screens and the rules work together, and do it without a model.

- [ ] E2E: the queue shows 25 claims and the state counts
- [ ] E2E: a claim with recorded steps and a decline shows them on its page, and the queue shows it decided
- [ ] E2E: a claim approved at $1,250.00 shows the payment held; a direct `pay_claim` call returns 409; signing off in the UI moves it to decided with the payment
- [ ] E2E: the instructions page shows the agent's instructions
- [ ] `npm run e2e` passes, and `npm run dev` afterwards still shows the dev database untouched
- [ ] With a real model, the agent decides at least three claims of different types from the dashboard, each with a payout, a reason and a policy section
- [ ] `docs/STATUS.md` describes the pilot and how to run it
- [ ] `npm run check` passes
