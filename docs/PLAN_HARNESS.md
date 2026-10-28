# Plan: the harness

The brief in `docs/HARNESS.md`: the UnderCover Agent stops being fed one claim at a time and runs the queue itself. A queue agent plans the run as a to-do list, hands each claim to a fresh claim agent, looks up the policy wording and the claims manual section by section, and recovers from failures on its own. The pilot's plan, `docs/PLAN.md`, stays as it is; this plan is ticked off here.

## The approach

- **Two agents, both on `create_agent`.** No new agent framework, as the brief asks. The **queue agent** reads the queue, keeps the to-do list, works each claim through one tool, `work_claim`, and finishes the run with a summary. The **claim agent** is the pilot's agent with new tools: it decides one claim from an empty message history and never sees the rest of the run. The queue agent only ever sees a one-line report per claim, so its context grows by a line per claim rather than by a whole claim's worth of documents.
- **The backend still enforces the rules; the agents are told about them.** The cap on a run, "one claim, one worker", "two failures and it goes to a handler", "no decision or payment twice" and "don't finish while claims are missed" are all checks in backend operations that return 409. The instructions explain them so the agent rarely hits them, but a model that ignores its instructions still can't break them.
- **Failure handling lives in code, around the agent, not in the model.** `work_claim` never raises: whatever goes wrong inside the claim agent becomes a one-line report, the claim goes back to the queue (or to a handler on the second failure), and the queue agent moves on. Provider errors and timeouts are retried by LangChain's `ModelRetryMiddleware` before they count as a failure, and `ModelCallLimitMiddleware` stops a claim agent that loops. A claim left `in_progress` by a backend restart is released on startup.
- **The one-line report is written by code from the claim record**, not by the claim agent: "CLM-1001: approve, $420.00 paid". The queue agent's summary then rests on what the backend holds, not on what a model said.
- **Documents are looked up, not handed over.** The backend splits `data/policy_wording.md` and `data/claims_manual.md` on their numbered `##` headings. The claim agent gets a contents list, a section reader and a word search, so it reads, say, wording section 5 and manual sections 7 and 9 for a baggage claim instead of 24 KB of text every time. The `read_section` calls are recorded as steps, so the claim page can list what was read without anything new in the backend.
- **The to-do list is the agent's, stored in the backend.** LangChain's `TodoListMiddleware` keeps its list in the agent's own state, where the dashboard can't see it, and has no "left for a handler" state. So the queue agent gets its own `write_todos` tool that saves the whole list on the run each time, and the queue page polls it.
- **Tests never call a model.** The pilot's scripted `StubModel` drives both agents. The model is chosen by two small functions, `queue_model()` and `claim_model()`, that tests replace; a stub can also raise, to stand in for a timeout or a provider error.

### Claim states

One new state, for a claim that failed twice.

| State | Meaning | Set by |
|---|---|---|
| `waiting` | In the queue | Seeding, or a first failure |
| `in_progress` | A claim agent is working on it | `start_claim`, `run_agent` |
| `waiting_for_signoff` | Approved over $1,000; payment held | `record_decision` |
| `decided` | Declined, referred, approved within the limit, or signed off | `record_decision`, `sign_off` |
| `needs_handler` | Failed twice before a decision; left for a handler | A second failure |

Each claim gains `attempts` (how many times a claim agent has started on it) and `run_id` (the run that last started it). The schema changes, so the database is reseeded: a new `npm run reseed` drops and reseeds the tables in place, which works on Windows while the backend is running.

### Runs and the to-do list

A run is a row in a new `runs` table: `run_id`, `max_claims`, `status` (`running`, `finished` or `stopped`), `todos`, `summary`, `problem`, and start and finish times. A to-do is `{task, status}`, with status `to_do`, `in_progress`, `done` or `for_handler`. Only one run can be running at a time.

- **The cap.** `start_claim` refuses a claim from a run that has already started `max_claims` different claims. A retry of a claim the run already started doesn't count again.
- **The missed-claims check.** `finish_run` refuses, listing the claims, while any claim this run started is back in `waiting`, or while the run has started fewer than `max_claims` claims and claims are still waiting.
- **Working the whole queue** is a run with `max_claims` at the number of waiting claims; the dashboard fills that in. `max_claims` is required, keeping to the rule of no optional inputs.

### API operations

New and changed operations; the rest stay as they are.

| Operation | Route | Used by |
|---|---|---|
| `start_run` | `POST /api/runs` with `max_claims` | dashboard |
| `get_latest_run` | `GET /api/runs/latest` (the run, or null) | dashboard |
| `write_todos` | `PUT /api/runs/{run_id}/todos` | queue agent |
| `finish_run` | `POST /api/runs/{run_id}/finish` with the summary | queue agent |
| `start_claim` | `POST /api/claims/{claim_id}/start` with the run id | queue agent's `work_claim` |
| `release_claim` | `POST /api/claims/{claim_id}/release` with the thread id and the problem | `work_claim` |
| `list_sections` | `GET /api/documents` (the headings of both documents) | claim agent |
| `read_section` | `GET /api/documents/{document}/sections/{section}` | claim agent, dashboard |
| `search_documents` | `GET /api/documents/search?words=` | claim agent |
| `get_instructions` | `GET /api/instructions` now returns `queue` and `claim` | both agents, dashboard |
| `run_agent` | `POST /api/claims/{claim_id}/run`, unchanged for the dashboard | dashboard |
| ~~`get_policy_wording`~~ | removed; the sections replace it | |

`document` is `policy_wording` or `claims_manual`; `section` is the heading's number, such as `7`.

### The agents' tools

- **Queue agent:** `list_waiting_claims` (id, type, amount, submitted date and attempts, from `list_claims`), `write_todos`, `work_claim(claim_id)` and `finish_run(summary)`. The run id is bound into the tools when the run starts.
- **Claim agent:** `get_claim`, `get_policy`, `get_customer`, `list_sections`, `read_section`, `search_documents`, `record_decision` and `pay_claim`.

### Not in this build

The brief's scope only: no scoring against `data/evals/`, no sign-in, no change to the sign-off rule, and no parallel claim agents. `data/evals/` stays unopened, and the instructions are written from the wording and the manual alone.

## Phase 1: claim attempts, release and recovery in the backend

Add `attempts`, `run_id` and the `needs_handler` state to the claims table, and `npm run reseed` (`uv run -m backend.db`). Add `start_claim` and `release_claim`. `start_claim` moves a `waiting` claim to `in_progress` in one `UPDATE ... WHERE status = 'waiting'`, adds one to `attempts`, sets the run and a new thread id, and returns the thread id; anything else is a 409. `release_claim` only acts on an `in_progress` claim with that thread id: it records the problem as an error step, then puts the claim back to `waiting`, or to `needs_handler` if this was its second attempt. `run_agent` uses the same start for a single named claim. On startup the backend releases every claim left `in_progress` and marks any `running` run `stopped`, since the work behind them died with the old process.

Why first: every later piece, the queue agent's retries included, rests on these state changes, and they can be tested without an agent.

- [x] Tests: `start_claim` on a waiting claim returns a thread id, sets `in_progress` and `attempts` 1; on any other state it returns 409
- [x] Tests: a first `release_claim` puts the claim back to `waiting` with an error step; a second start and release leaves it `needs_handler`
- [x] Tests: `release_claim` on a decided claim, or with the wrong thread id, returns 409 and changes nothing
- [x] Test: a claim left `in_progress` is released on startup, with an error step saying the backend restarted
- [x] Test: a decided claim can't be started again, so it can't be decided or paid twice
- [x] `npm run reseed` with the backend running leaves 25 waiting claims with `attempts` 0
- [x] `npm run check:python` passes

## Phase 2: the claim agent looks things up

Add `list_sections`, `read_section` and `search_documents` to the backend, splitting both documents on their numbered `##` headings. `search_documents` returns each section that contains every given word, with the paragraph where they occur. Remove `get_policy_wording`. Give the claim agent its new tools, `ModelRetryMiddleware` (3 retries with backoff, then raise) and `ModelCallLimitMiddleware` (30 calls a claim, then end). Make DeepSeek V4.1 Flash (`deepseek/deepseek-v4.1-flash`, low reasoning effort) the default, with a 120-second timeout; `MODEL_NAME` still overrides it. Rewrite the claim instructions as `backend/instructions/claim.md`, from the wording and the manual: the order of work from manual section 4, which sections to read for each benefit, and the manual's rules on repeat claims, wild animals, meals without receipts and when to refer. Update `docs/SPEC.md`: the manual moves out of "Not for now", and the rules say decisions follow the wording first and the manual where the wording is silent.

Why here: the claim agent is what the queue agent will call, so it should be finished and working on its own, on one named claim, before anything drives it.

- [x] Tests: `list_sections` returns 12 wording sections and 14 manual sections with their titles; `read_section("claims_manual", "10")` returns "Meals without receipts" in full; an unknown document or section returns 404
- [x] Test: `search_documents?words=wild animal` returns manual section 7 with the wild-animals paragraph
- [x] Test: a stub claim agent that reads two sections, records a decision and pays it leaves `read_section` tool calls in the claim's steps
- [x] Test: a stub model that raises a provider error once and then answers still decides the claim, with no error step
- [x] Test: no tool or instruction mentions `data/evals`
- [x] `docs/SPEC.md` describes the manual as in use
- [x] With the real default model, `Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/claims/CLM-1001/run` decides CLM-1001, and its steps show `list_sections` and `read_section` calls rather than the whole wording
- [x] `npm run check:python` passes

## Phase 3: runs and the to-do list in the backend

Add the `runs` table and `start_run`, `get_latest_run`, `write_todos` and `finish_run`, with the cap in `start_claim` and the missed-claims check in `finish_run`. `start_run` refuses while another run is running, creates the run and starts the queue agent as a background task (stubbed in this phase's tests); if that task raises or ends without `finish_run`, the run is marked `stopped` with the problem. `write_todos` replaces the whole list and refuses on a run that isn't running.

Why here: as in the pilot, the rules are built and tested before an agent exists to break them.

- [ ] Tests: `start_run` with `max_claims` 2 creates a running run; a second `start_run` returns 409 until it ends
- [ ] Test (the cap): with `max_claims` 2, `start_claim` works for two claims and refuses the third with 409; a retry of one of the first two is allowed
- [ ] Test (missed claims): `finish_run` returns 409 naming the claims while the run has started fewer than its cap and claims are waiting, or while a claim it started is back in `waiting`; once they are worked, it succeeds and stores the summary
- [ ] Test: `write_todos` stores the list and `get_latest_run` returns it in order; on a finished run it returns 409
- [ ] Test: a queue task that raises leaves the run `stopped` with the error as its problem
- [ ] `npm run check:python` passes

## Phase 4: the queue agent

Add `run_queue(run_id)` with its four tools and `backend/instructions/queue.md`: list the waiting claims, write a to-do item for each claim it means to work within the cap (choosing the order, oldest first unless it has a reason), mark each item in progress, call `work_claim`, mark it done or left for a handler, try a claim that came back once more, then add and tick off "Check for missed claims" and finish with a summary of a few lines for the handlers. `work_claim` calls `start_claim`, runs the claim agent from a fresh start on the new thread id, and if the claim is still `in_progress` afterwards, whatever happened, calls `release_claim`. It returns a single line built from the claim record. `run_agent` for a single claim uses the same function. `get_instructions` returns both sets of instructions, and both agents fetch theirs at the start of the run.

Why this shape: the queue agent organizes the work and the code around it keeps that safe. A bad claim costs one line in the queue agent's history and nothing else.

- [ ] Test: a stub queue run with `max_claims` 3 works three claims, each with its own thread id and its steps on its own claim, and leaves the other 22 waiting
- [ ] Test (the to-do list): the stored list goes through `to_do`, `in_progress` and `done` for each claim as the stub run goes on, and the run ends `finished` with the summary
- [ ] Test (a failed claim doesn't stop the run): the claim agent for the first claim raises a timeout; `work_claim` returns "CLM-…: failed …, back in the queue", and the next claims are still decided
- [ ] Test (tried again): the claim that failed once is worked again in the same run and decided, with one error step and `attempts` 2
- [ ] Test (fails twice): a claim whose claim agent raises both times ends `needs_handler`, its to-do item is `for_handler`, and the run still finishes
- [ ] Test (missed claims): a stub that calls `finish_run` too early gets the 409 back as a tool result, works the missed claim and then finishes
- [ ] Test: a claim agent that hits its model-call limit without a decision is released like any other failure
- [ ] `npm run check:python` passes with coverage at or above 80%

## Phase 5: the dashboard

On the queue page, a run panel: a number field for the cap (5 by default, with a "Whole queue" choice that fills in the number waiting) and a "Start run" button; then the latest run's state, its to-do list with each item's state in the brand colors (to do Cerulean, in progress Marigold, done Sea Green, left for a handler Raspberry), and its summary once it finishes. The panel polls every 2 seconds while the run is running. The state tiles gain "Left for a handler". On the claim page, a "What the agent read" panel lists the sections read on the latest attempt (from the `read_section` steps), each opening the section's text; the page shows the attempts, and steps are grouped by attempt. The instructions page shows the queue agent's and the claim agent's instructions under their own headings.

Why: handlers should be able to see what the agent means to do, how far it has got, and what each decision rests on, all from the screens they already use.

- [ ] Vitest tests: the run panel starts a run with the cap entered; the to-do list renders each state; the summary shows on a finished run; "Whole queue" fills in the waiting count
- [ ] Vitest tests: the claim page lists the sections read and shows a `needs_handler` claim with its error steps; the instructions page shows both sets
- [ ] In the browser via the Playwright MCP server, with stubbed data from a test run: the queue page shows the to-do list and five states of tiles in light and dark mode, and at phone width has no horizontal scroll
- [ ] `npm run check:ts` passes with coverage at or above 80%

## Phase 6: end-to-end tests, the live run and handover

Playwright tests that stand in for the queue agent by calling its operations (`start_claim`, `write_todos`, `record_step`, `record_decision`, `release_claim`, `finish_run`), as the pilot's e2e tests stand in for the claim agent; `start_run` isn't called, so no model runs. Then a live run on the default model, and the docs.

- [ ] E2E: a run's to-do list appears on the queue page and is ticked off as items change
- [ ] E2E: a claim with `read_section` steps shows the sections on its page
- [ ] E2E: a claim released twice shows as left for a handler on the queue and on its page
- [ ] E2E: the instructions page shows both sets of instructions
- [ ] Live, after `npm run reseed`: a run capped at five from the dashboard works five claims on its own; in the browser the to-do list fills in and is ticked off, each claim's steps show the sections it read, the run finishes with a summary, and the other 20 claims are still waiting
- [ ] `docs/SPEC.md`, `docs/TECH_STACK.md` (the two agents, their entry points `run_queue(run_id)` and `run_claim(claim_id, thread_id)`, the middleware and the default model) and `docs/STATUS.md` describe the product as it now is
- [ ] `npm run check` passes
