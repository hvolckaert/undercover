# Status

The claims pilot from `docs/PLAN.md` is built: all six phases are done.

## Built

- `backend/`: FastAPI and SQLite. On first start it seeds `backend/undercover.db` (or the file in `UNDERCOVER_DB`) from `data/`, leaving out `data/evals/` and `data/security/`. Every operation has an `operation_id`, a one-line docstring and no optional inputs.
  - Read: `list_claims`, `get_claim`, `get_policy` (with the plan's limits and add-ons), `get_customer`, `get_policy_wording`, `get_instructions`, `list_handlers`, `list_steps`.
  - Workflow: `run_agent`, `record_step`, `record_decision`, `pay_claim`, `sign_off`.
  - A claim is `waiting`, `in_progress`, `waiting_for_signoff` or `decided`. An approved payout over $1,000 (from `data/company.json`) goes to `waiting_for_signoff`, and `pay_claim` refuses it until a handler signs off; the sign-off makes the payment. Payments are records only.
  - The agent's instructions are in `backend/instructions.md`.
- `agent/`: the UnderCover Agent, `run(claim_id, thread_id)`, on LangChain's `create_agent` with `openai/gpt-6-luna` at low reasoning effort, or `MODEL_NAME`. It fetches its instructions from the backend and works only through the API: `get_claim`, `get_policy`, `get_customer`, `get_policy_wording`, `record_decision` and `pay_claim`. Each tool call, result and reply is posted to the backend as a step. `run_agent` starts it as a background task; a run that fails or ends without a decision puts the claim back to `waiting` with an error step.
- `dashboard/`: React, Vite and TypeScript in the UnderCover brand, light and dark, with a hash router:
  - `#/`: the queue with counts by state, refreshed every 3 seconds.
  - `#/claims/<id>`: the claim in full with its policy, the customer's earlier claims, the decision and the agent's steps, polled every second while the agent works. A button runs the agent on a waiting claim, and a sign-off control releases a payout over $1,000.
  - `#/instructions`: the agent's instructions, read only.
- `e2e/`: Playwright tests of the queue, a decided claim, the sign-off rule and the instructions. They run on ports 8001 and 5174 against a fresh database in the temp folder, standing in for the agent by calling its API operations, so they never call a model or touch the dev database.

## Running it

- `npm run dev` starts the backend on port 8000 and the dashboard on http://localhost:5173. Open a claim and press "Run the agent".
- Delete `backend/undercover.db` to start again from `data/`.
- `npm run check` runs every check.
- On Windows the backend's auto-reload can hang after a change and keep serving old code; stop and restart `npm run dev`.

## Not built yet

Scoring the agent against `data/evals/`, the claims manual, sign-in, real payments and customer messages.
