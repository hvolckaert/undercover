# Status

The claims pilot from `docs/PLAN.md`, in progress. Phases 1 to 3 are done.

## Built

- `backend/`: FastAPI and SQLite. On first start it seeds `backend/undercover.db` (or the file in `UNDERCOVER_DB`) from `data/`, leaving out `data/evals/` and `data/security/`. Read operations: `list_claims`, `get_claim`, `get_policy`, `get_customer`, `get_policy_wording`, `get_instructions`, `list_handlers`. Workflow operations: `record_step`, `list_steps`, `record_decision`, `pay_claim` and `sign_off`. A claim is `waiting`, `in_progress`, `waiting_for_signoff` or `decided`; an approved payout over $1,000 waits for a handler's sign-off, and `pay_claim` refuses it until then. Payments are records only. The agent's instructions are in `backend/instructions.md`.
- `agent/`: the UnderCover Agent, `run(claim_id, thread_id)`, on LangChain's `create_agent` with `openai/gpt-6-luna` at low reasoning effort, or `MODEL_NAME`. It fetches its instructions from the backend and works only through the API: `get_claim`, `get_policy`, `get_customer`, `get_policy_wording`, `record_decision` and `pay_claim`. Each tool call, result and reply is posted to the backend as a step. The backend's `run_agent` starts it as a background task; a run that fails or ends without a decision puts the claim back to `waiting` with an error step.
- `dashboard/`: the skeleton page that shows whether the backend is up.
- `e2e/`: one test of that page.

## Running it

- `npm run dev` starts the backend on port 8000 and the dashboard on 5173.
- Delete `backend/undercover.db` to start again from `data/`.
- `npm run check` runs every check.
- On Windows the backend's auto-reload can hang after a change and keep serving old code; stop and restart `npm run dev`.
