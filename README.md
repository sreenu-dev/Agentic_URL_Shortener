# Agentic URL Shortener

This project contains an asynchronous FastAPI URL shortener and an agentic software engineering workflow. The repository includes:

- The URL shortener API in `app.py`
- An orchestration layer in orchestrator.py that models SDLC stages, retries, rollback, and human approval
- Supporting documentation describing architecture, scenarios, risks, and validation practice
- Automated tests covering the required URL-shortening behaviors

## 1. Objective

Build a working prototype that turns a requirement into a reviewable engineering outcome using an agentic execution model. The system must show requirement understanding, decomposition, implementation, validation, and reviewability while staying within safe autonomy boundaries.

## 2. `app.py` Overview

`app.py` is the runnable FastAPI service. It uses asynchronous SQLite access through
`aiosqlite`, creates its database tables during application startup, and runs an
hourly background cleanup task for expired links.

### API endpoints

- `POST /shorten` accepts a JSON object with an absolute HTTP(S) `url` and returns
  the short code, short URL, original URL, and creation time. Invalid or unsafe
  URLs are rejected.
- `GET /urls` lists all shortened URL mappings as an array with `id`, `short_url`,
  and `long_url` fields. It returns an empty array when no URLs have been created.
- `GET /{short_id}` redirects to the destination with HTTP 307. Unknown short
  codes return HTTP 404.
- `GET /analytics/{short_id}` returns the destination, creation time, active
  status, and click count. Unknown IDs return HTTP 404.
- `GET /health` returns `{"status":"healthy"}` with HTTP 200.

Example: `GET http://127.0.0.1:8000/urls` returns entries like:

```json
[
  {
    "id": "Ab12xYz9",
    "short_url": "http://localhost:8000/Ab12xYz9",
    "long_url": "https://example.com/page"
  }
]
```

Interactive API documentation is available at `http://127.0.0.1:8000/docs` after
the service starts.

### Configuration and persistence

`app.py` reads these settings from environment variables or `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ENV` | `production` | Environment label (`development`, `production`, or `testing`) |
| `LOG_LEVEL` | `INFO` | Application logging level |
| `BASE_URL` | `http://localhost:8000` | Base URL used to construct returned short links |
| `API_KEY_ROTATION_SALT` | Development default | Hex salt used when hashing client IPs; set a private value of at least 32 hex characters for deployments |
| `SQLITE_DB_FILE` | `shortener.db` | SQLite database file path |

The SQLite database stores short URL mappings and click events. SQLite WAL mode
and foreign-key enforcement are enabled for connections.

## 3. Architecture Overview

### Core Components

- FastAPI app layer in `app.py`
  - Handles request validation, URL creation, redirects, analytics, and health checks
  - Uses a lifespan handler to initialize the database and manage the expiration sweeper

- SQLite persistence layer
  - Stores URL mappings and click-event records
  - Uses parameterized SQL and foreign-key relationships

- Observability and logging
  - Reports application events and database health

- Agentic orchestration layer
  - Captures SDLC stages: requirements, decomposition, implementation, testing, documentation, human approval
  - Tracks retries, rollback, and decision lineage
  - Uses safe fallback behavior when the LLM is unavailable

### Control Flow

1. Requirements are normalized into a technical specification.
2. The task is broken into ordered steps with dependencies.
3. Implementation is drafted.
4. Validation and documentation steps are entered.
5. Human approval decides whether code is written to disk.
6. Safe-stop and rollback behaviors handle failure or rejected output.

## 4. Run the URL Shortener

### Prerequisites

- Python 3.10 or later
- `pip`
- Network access for the initial dependency installation

### Install and start

From the repository root, create and activate a virtual environment, then install
the packages used by `app.py`:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install fastapi uvicorn pydantic pydantic-settings aiosqlite pytest httpx
```

`pytest` and `httpx` are needed only for the test suite; they are not imported by
the running API. Start the API from the repository root:

```powershell
python -m uvicorn app:app --reload
```

The service is available at `http://127.0.0.1:8000`; open
`http://127.0.0.1:8000/docs` to try its endpoints. The database file is created
at the path configured by `SQLITE_DB_FILE` (by default, `shortener.db` in the
working directory).

Example requests:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/shorten `
  -ContentType 'application/json' `
  -Body '{"url":"https://example.com/path","ttl_seconds":3600}'

Invoke-RestMethod -Uri http://127.0.0.1:8000/health
```

Use the returned `id` to query `http://127.0.0.1:8000/analytics/{id}` or open
`http://127.0.0.1:8000/{id}` to follow the redirect. If you change
`API_KEY_ROTATION_SALT`, use a private hex value of at least 32 characters; do
not commit deployment secrets.

To run the repository test suite, use:

```powershell
python -m pytest
```

### Run the orchestrator

Run `python orchestrator.py` separately when you want the SDLC workflow and its
human approval step. On startup, it checks the third-party imports in `app.py`
and installs any missing packages into the Python environment running the
orchestrator. This requires `pip` and network access. Starting the API directly
with Uvicorn does not perform that dependency check.

Generated implementations are checked for valid Python syntax, the FastAPI
application object, and the three required routes before they can be approved.
The generator is instructed to keep test-only imports out of `app.py` and to
ignore unrelated values in `.env`; invalid generated code is replaced with the
built-in implementation.

### Configure Gemini for the orchestrator

The orchestrator does not retrieve or create API keys. Create one in
[Google AI Studio](https://aistudio.google.com/app/apikey), then configure it locally:

1. Copy `.env.example` to `.env` in the same directory as `orchestrator.py`.
2. Replace `replace-with-your-own-key` with your key in `.env`.
3. Run `python orchestrator.py`. The `.env` file is found beside the script even if
   you launch it from a different working directory.

Alternatively, set `GEMINI_API_KEY` in your process environment. Keep `.env` private
and do not commit your real key. If no key is configured, the orchestrator uses its
default implementation path.

## 5. Agentic Orchestration Model

The orchestration script demonstrates controlled autonomy rather than raw linear chaining.

### Stages

- REQUIREMENTS
  - Normalizes the requirement into implementation constraints.

- DECOMPOSITION
  - Converts the specification into a task plan.

- IMPLEMENTATION
  - Drafts a working FastAPI service.

- TESTING
  - Prepares validation checks and expected behavioral assertions.

- DOCUMENTATION
  - Produces setup and architecture guidance.

- HUMAN_APPROVAL
  - Asks for approval before writing the final app artifact to disk.

### Governance Features

- Bounded retry logic for LLM failures
- Fallback path when the Gemini client is unavailable
- Safe-stop and rollback behavior
- Decision log for traceability
- Metrics tracking for retries, rollback count, and elapsed execution time

## 6. Three Scenario Walkthroughs

### 6.1 Greenfield Scenario

Scenario: Build the URL shortener from scratch.

Decomposition:

- Define API contract for shorten and analytics endpoints
- Create SQLite schema and storage logic
- Implement redirect and click tracking
- Validate with tests and FastAPI checks

Orchestration response:

- Requirements are normalized
- Task plan is generated
- Service is implemented and reviewed before approval

Validation:

- Unit/integration tests assert shorten, redirect, and analytics behavior

### 6.2 Brownfield Scenario

Scenario: Extend or repair an existing URL shortener service.

Decomposition:

- Review impacted modules and data flow
- Assess database schema, URL validation, and analytics behavior
- Apply a minimal and safe fix
- Re-run validation across the changed paths

Orchestration response:

- The system has a governance checkpoint before writing the code artifact
- Rollback and fallback logic support safe recovery when a change fails review

Validation:

- Regression tests confirm that redirect and analytics logic keep working after a change

### 6.3 Ambiguous Requirement Scenario

Scenario: Requirement is underspecified or partially contradictory.

Decomposition:

- Clarify expected behaviors
- Identify the core endpoints and reliability expectations
- Convert ambiguity into a technical specification

Orchestration response:

- The orchestrator normalizes assumptions and records them in a decision log
- Human approval is preserved before implementation is accepted

Validation:

- Tests validate the default requirement set rather than hidden assumptions

## 7. Testing Approach

Automated validation is implemented with pytest and FastAPI TestClient.

Covered checks:

- shorten endpoint creates a short URL and returns expected fields
- redirect endpoint returns 307 and updates click count
- analytics endpoint returns correct record and 404 for missing keys

Test pattern:

- Each test uses a temporary SQLite file so the main database is not polluted across runs
- The app is exercised through its HTTP interface instead of direct DB manipulation

## 8. Risks, Trade-offs, Assumptions, and Limitations

### Risks and Trade-offs

- SQLite is chosen for simplicity and rapid prototyping, but it is not a production-scale distributed datastore.
- The redirect flow is synchronous and adequate for a prototype; a production system may move analytics writes to async processing.
- The orchestration layer uses a fallback implementation when the Gemini API is unavailable, reducing dependency risk but limiting full agentic autonomy in offline environments.

### Assumptions

- The user needs a working prototype and demonstration of governance, not a full production deployment.
- Short URLs are compact and primarily need correctness and traceability.

### Limitations

- No authentication or authorization layer is included.
- No rate limiting or abuse protection is included.
- No distributed caching or high-scale analytics pipeline is implemented.
- The project is intentionally scoped for demonstrable engineering quality rather than full-scale production hardening.

## 9. Final Engineering Summary

This project demonstrates a practical agentic engineering workflow: requirement interpretation, decomposition, implementation, validation, documentation, and human-governed approval. The working prototype satisfies the core URL shortener requirements, while the orchestration layer emphasizes controlled autonomy, traceability, rollback, and safe-stop behaviors expected in a production-grade SDLC workflow.

The delivered artifacts provide a coherent engineering story: a working service, a governance-focused orchestrator, and supporting documentation and tests that show how the system behaves under realistic scenarios.
