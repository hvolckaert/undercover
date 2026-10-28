# Status

The claims pilot from `docs/PLAN.md` is built: all six phases are done. The harness from `docs/PLAN_HARNESS.md` is in progress: phases 1 to 5 are done.

## Built

- `backend/`: FastAPI and SQLite. On first start it seeds `backend/undercover.db` (or the file in `UNDERCOVER_DB`) from `data/`, leaving out `data/evals/` and `data/security/`. Every operation has an `operation_id`, a one-line docstring and no optional inputs.
  - Read: `list_claims`, `get_claim`, `get_policy` (with the plan's limits and add-ons), `get_customer`, `get_instructions`, `list_handlers`, `list_steps`.
  - Documents: `list_sections`, `read_section` and `search_documents` over the policy wording and the claims manual, split on their numbered headings.
  - Workflow: `run_agent`, `record_step`, `record_decision`, `pay_claim`, `sign_off`.
  - Runs: `start_run` (with `max_claims`), `get_latest_run`, `write_todos` and `finish_run`. One run at a time. `start_claim` refuses a new claim once the run has started `max_claims` claims, and `finish_run` refuses while a claim within the cap is still waiting. A run whose agent ends without finishing is `stopped`.
  - Attempts: `start_claim` (for a run) and `release_claim`. A claim agent that stops before a decision releases the claim: back to `waiting` the first time, `needs_handler` the second. On startup the backend releases claims left `in_progress`.
  - A claim is `waiting`, `in_progress`, `waiting_for_signoff`, `decided` or `needs_handler`. An approved payout over $1,000 (from `data/company.json`) goes to `waiting_for_signoff`, and `pay_claim` refuses it until a handler signs off; the sign-off makes the payment. Payments are records only.
  - The agent's instructions are in `backend/instructions/queue.md` (running the queue) and `backend/instructions/claim.md` (working a claim), written from the wording and the manual.
- `agent/`: the UnderCover Agent. `run_queue(run_id, max_claims)` is the queue agent: it lists the waiting claims, keeps a to-do list on the run (`write_todos`), hands each claim to `work_claim` and ends with `finish_run` and a summary. `work_claim` starts the claim, runs a fresh claim agent and returns one line built from the claim record; if the claim is still in progress afterwards it releases it. `run_claim(claim_id, thread_id)` is the claim agent, on LangChain's `create_agent` with `deepseek/deepseek-v4.1-flash` at low reasoning effort, or `MODEL_NAME`. It fetches its instructions from the backend and works only through the API: `get_claim`, `get_policy`, `get_customer`, `list_sections`, `read_section`, `search_documents`, `record_decision` and `pay_claim`. `ModelRetryMiddleware` retries provider errors and timeouts three times, and `ModelCallLimitMiddleware` ends a claim after 30 model calls. Each tool call, result and reply is posted to the backend as a step. The backend's URL is `BACKEND_URL`, `http://localhost:8000` by default. `run_agent` starts it as a background task; a run that fails or ends without a decision releases the claim.
- `dashboard/`: React, Vite and TypeScript in the UnderCover brand, light and dark, with a hash router:
  - `#/`: the queue with counts by state, refreshed every 3 seconds, and the agent run panel: a cap (5 by default, or "Whole queue"), "Start run", and the latest run with its to-do list and summary, refreshed every 2 seconds while it runs.
  - `#/claims/<id>`: the claim in full with its policy, the customer's earlier claims, the decision and the agent's steps, polled every second while the agent works, grouped by attempt, with "What the agent read": the sections of the wording and the manual it read on its latest attempt. A button runs the agent on a waiting claim, and a sign-off control releases a payout over $1,000.
  - `#/instructions`: the instructions for running the queue and for working a claim, read only.
- `e2e/`: Playwright tests of the queue, a decided claim, the sign-off rule and the instructions. They run on ports 8001 and 5174 against a fresh database in the temp folder, standing in for the agent by calling its API operations, so they never call a model or touch the dev database.

## Running it

- `npm run dev` starts the backend on port 8000 and the dashboard on http://localhost:5173. Open a claim and press "Run the agent".
- `npm run reseed` starts the database again from `data/`, even while the backend is running.
- `npm run check` runs every check.
- On Windows the backend's auto-reload can hang after a change and keep serving old code; stop and restart `npm run dev`.

## Not built yet

Scoring the agent against `data/evals/`, sign-in, real payments and customer messages.
