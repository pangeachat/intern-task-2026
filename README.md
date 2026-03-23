# Language Feedback API (Intern Task Submission)

This repository contains my implementation of an LLM-powered language feedback API using **Python + FastAPI + OpenAI**.

The system analyzes a learner-written sentence and returns:

- a minimally edited corrected sentence
- a structured list of errors
- a boolean indicating whether the sentence is already correct
- a CEFR difficulty level (`A1`-`C2`)

The implementation was developed with two priorities in mind: **correctness of structured output** and **practical production behavior** under imperfect model responses.

---

## What I built

### Endpoints

- `GET /health`  
  Returns `200` with `{"status": "ok"}`.

- `POST /feedback`  
  Accepts request payload:

  ```json
  {
    "sentence": "Yo soy fue al mercado ayer.",
    "target_language": "Spanish",
    "native_language": "English"
  }
  ```

  Returns response payload:

  ```json
  {
    "corrected_sentence": "Yo fui al mercado ayer.",
    "is_correct": false,
    "errors": [
      {
        "original": "soy fue",
        "correction": "fui",
        "error_type": "conjugation",
        "explanation": "You mixed two verb forms."
      }
    ],
    "difficulty": "A2"
  }
  ```

---

## Design decisions

### 1) Strong output constraints in code and prompt

- Pydantic models use strict enums (`Literal`) for:
  - allowed `error_type` values
  - allowed CEFR `difficulty` values
- Models also enforce response consistency:
  - `is_correct = true` requires `errors = []`
  - `is_correct = false` requires at least one error
- Prompt instructions are explicit about:
  - minimal edits
  - explanation language (native language)
  - exact JSON-only output
  - no extra keys or markdown

I made these constraints intentionally so output quality is not left to model behavior alone. The API should either return a predictable shape or fail clearly, not drift silently.

### 2) Reliability safeguards

- **Request timeout budget** for `/feedback` to avoid long-running failures.
- **Retry on transient provider errors** (timeouts/rate limits/connection issues).
- **Defensive JSON parsing** with clear HTTP 502 responses on malformed model output.
- **Payload repair/sanitization** before strict validation, so minor format drift from the model is handled deterministically.

These safeguards are included to keep runtime behavior stable. In practice, LLM responses are not always perfectly compliant, so the service normalizes known failure patterns before enforcing schema rules.

### 3) Cost/performance improvement

- Added an in-memory **TTL cache** keyed by `(sentence, target_language, native_language)`.
- Repeated requests return cached results, reducing latency and API cost.

This decision is primarily about production feasibility: avoiding duplicate model calls improves both responsiveness and token efficiency.

---

## Prompt strategy

The prompt is written to reduce common failure modes in structured LLM output:

- It explicitly defines behavior for already-correct sentences.
- It constrains valid `error_type` and `difficulty` enums.
- It asks for short spans (`original` and `correction`) instead of full rewrites.
- It requires concise, learner-friendly explanations in the specified native language.
- It forbids extra prose and markdown wrappers to improve parse reliability.

I treated prompt design as part of the API contract, not just model guidance. The objective was to make output behavior as predictable as possible across languages and scripts.

---

## Project structure

```text
app/
  main.py         # FastAPI app and routes
  feedback.py     # Prompting, OpenAI call, timeout/retry/cache, normalization
  models.py       # Strict request/response models
schema/
  request.schema.json
  response.schema.json
tests/
  test_feedback_unit.py
  test_feedback_integration.py
  test_schema.py
```

---

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# add OPENAI_API_KEY to .env
uvicorn app.main:app --reload
```

Test the API:

```bash
curl -X POST http://localhost:8000/feedback \
  -H "Content-Type: application/json" \
  -d '{"sentence":"Yo soy fue al mercado ayer.","target_language":"Spanish","native_language":"English"}'
```

---

## Run with Docker

```bash
cp .env.example .env
# add OPENAI_API_KEY to .env
docker compose up --build
```

Service name is `feedback-api` and server is exposed on port `8000`.

---

## Tests

### Unit + schema tests (no API key required)

```bash
pytest tests/test_feedback_unit.py tests/test_schema.py -v
```

### Integration tests (requires `OPENAI_API_KEY`)

```bash
pytest tests/test_feedback_integration.py -v
```

### Test coverage highlights

- correct sentence handling (`errors` empty, corrected sentence unchanged)
- multiple-error sentence
- non-Latin script case (Japanese)
- transient timeout retry path
- malformed JSON error path
- schema and enum validation
- cache behavior (duplicate request does not hit LLM twice)
- malformed provider payload recovery (missing fields and extra nested keys)

---

## Configurable environment variables

- `OPENAI_API_KEY` (required)
- `OPENAI_MODEL` (default: `gpt-4o-mini`)
- `OPENAI_TEMPERATURE` (default: `0.1`)
- `OPENAI_MAX_TOKENS` (default: `700`)
- `OPENAI_MAX_RETRIES` (default: `1`)
- `OPENAI_REQUEST_TIMEOUT_SECONDS` (default: `12`)
- `FEEDBACK_TOTAL_TIMEOUT_SECONDS` (default: `28`)
- `FEEDBACK_CACHE_TTL_SECONDS` (default: `300`)

---

## Assumptions

- Linguistic feedback quality is generated by the LLM; application code enforces response structure and consistency.
- CEFR labels are estimated from sentence complexity and may vary slightly across model versions.
- The cache is in-memory and process-local, which is appropriate for this assignment scope and simple deployment scenarios.
- For malformed model output, I prefer controlled normalization and explicit validation over permissive parsing, so failure modes remain observable and bounded.
