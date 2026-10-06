# Agentic URL Shortener

This project demonstrates an agentic software engineering workflow for building a production-style URL shortener service using FastAPI. The repository includes:

- A working FastAPI prototype in app.py
- An orchestration layer in orchestrator.py that models SDLC stages, retries, rollback, and human approval
- Supporting documentation describing architecture, scenarios, risks, and validation practice
- Automated tests covering the required URL-shortening behaviors

## 1. Objective

Build a working prototype that turns a requirement into a reviewable engineering outcome using an agentic execution model. The system must show requirement understanding, decomposition, implementation, validation, and reviewability while staying within safe autonomy boundaries.

## 2. Prototype Overview

The application exposes three core behaviors:

1. POST /shorten
   - Accepts a URL payload
   - Creates a short code and stores metadata in SQLite
   - Returns the short code plus analytics metadata

2. GET /{id}
   - Resolves a short code to its original URL
   - Performs a redirect with HTTP 307
   - Increments the click counter in storage

3. GET /analytics/{id}
   - Returns the record for a short URL including original URL, click count, and creation timestamp
   - Returns 404 when the identifier does not exist

## 3. Architecture Overview

### Core Components

- FastAPI app layer
  - Handles HTTP requests and response validation
  - Exposes endpoint contract for shorten, redirect, and analytics behaviors

- SQLite persistence layer
  - Stores rows with: id, original_url, created_at, clicks
  - Uses parameterized SQL to minimize injection risk

- Observability and logging
  - Logs key lifecycle events such as creation, redirect, and analytic lookups

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

## 4. Setup Instructions

### Prerequisites

- Python 3.10+
- A virtual environment
- Project dependencies installed from the environment used for this repo

### Recommended Local Setup

1. Activate the project virtual environment.
2. Install dependencies if needed:
   - fastapi
   - pydantic
   - uvicorn
   - pytest
   - google-generativeai (optional for the orchestration agent)
3. Run the app:

   uvicorn app:app --reload

4. Test the endpoints with curl or a tool such as Postman / FastAPI TestClient.

Example:

- POST request to /shorten with JSON payload {"url": "<https://example.com"}>
- GET /{short_id}
- GET /analytics/{short_id}

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
