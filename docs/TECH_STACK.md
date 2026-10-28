# Tech stack

- `backend/`: FastAPI and SQLite. Every API operation has an `operation_id`, a one-line docstring and no optional inputs. Paying a claim is a separate operation that takes the amount.
- `agent/`: LangChain's `create_agent` on OpenRouter, with no other agent framework. Two entry points: `run_queue(run_id, max_claims)`, the queue agent, which keeps a to-do list and hands each claim to a fresh claim agent through a tool; and `run_claim(claim_id, thread_id)`, the claim agent, which decides one claim. Both reach claims, documents and their instructions only through the backend's API, at `BACKEND_URL` (`http://localhost:8000` by default). LangChain's `ModelRetryMiddleware` retries provider errors and timeouts, and `ModelCallLimitMiddleware` caps a claim agent's model calls. They use `deepseek/deepseek-v4.1-flash` with low reasoning effort by default, or the model in the environment variable `MODEL_NAME` if set, such as `openrouter/free`.
- `dashboard/`: React, Vite and TypeScript.
- `e2e/`: Playwright tests.
- `data/`: the business data the backend starts from. The agent never sees `data/evals/`, which holds the answer key.

Python 3.12 with uv, all in the root `pyproject.toml`. Node 26. The OpenRouter key is `OPENROUTER_API_KEY` in `.env`.
