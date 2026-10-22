# Status

The claims pilot from `docs/PLAN.md`, in progress. Phase 1 is done.

## Built

- `backend/`: FastAPI and SQLite. On first start it seeds `backend/undercover.db` (or the file in `UNDERCOVER_DB`) from `data/`, leaving out `data/evals/` and `data/security/`. Read operations: `list_claims`, `get_claim`, `get_policy`, `get_customer`, `get_policy_wording`, `get_instructions`, `list_handlers`. The agent's instructions are in `backend/instructions.md`.
- `agent/`: the skeleton entry point `run(claim_id, thread_id)`.
- `dashboard/`: the skeleton page that shows whether the backend is up.
- `e2e/`: one test of that page.

## Running it

- `npm run dev` starts the backend on port 8000 and the dashboard on 5173.
- Delete `backend/undercover.db` to start again from `data/`.
- `npm run check` runs every check.
