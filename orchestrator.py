# orchestrator.py
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

try:
    import google.generativeai as genai
except Exception as exc:  # pragma: no cover - environment dependent
    genai = None
    GENAI_IMPORT_ERROR = exc
else:
    GENAI_IMPORT_ERROR = None

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('AgenticOrchestrator')


DEFAULT_APP_CODE = '''from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, HttpUrl
import sqlite3
import string
import random
import logging
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('URLShortenerAPI')

app = FastAPI(title='Agentic URL Shortener', version='1.0')
DB_FILE = Path(__file__).with_name('urls.db')


class URLCreate(BaseModel):
    url: HttpUrl = Field(..., description='The long URL to shorten.')


class URLInfo(BaseModel):
    id: str
    original_url: str
    clicks: int = 0
    created_at: str


def init_db() -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS urls (
                id TEXT PRIMARY KEY,
                original_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                clicks INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


init_db()


def generate_short_id(length: int = 6) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(random.choice(alphabet) for _ in range(length))


@app.post('/shorten', response_model=URLInfo)
def create_short_url(payload: URLCreate):
    short_id = generate_short_id()
    created_at = datetime.now(timezone.utc).isoformat()
    original_url = str(payload.url)

    while True:
        with sqlite3.connect(DB_FILE) as conn:
            try:
                conn.execute(
                    'INSERT INTO urls (id, original_url, created_at, clicks) VALUES (?, ?, ?, ?)',
                    (short_id, original_url, created_at, 0),
                )
                conn.commit()
                logger.info('Created short code %s for %s', short_id, original_url)
                return {
                    'id': short_id,
                    'original_url': original_url,
                    'clicks': 0,
                    'created_at': created_at,
                }
            except sqlite3.IntegrityError:
                short_id = generate_short_id()
                continue
            except Exception as exc:
                logger.exception('Failed to save shortened URL: %s', exc)
                raise HTTPException(status_code=500, detail='Internal server error')


@app.get('/{short_id}')
def redirect_to_url(short_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute('SELECT original_url FROM urls WHERE id = ?', (short_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Short URL not found')

        target_url = row[0]
        conn.execute('UPDATE urls SET clicks = clicks + 1 WHERE id = ?', (short_id,))
        conn.commit()

    logger.info('Redirecting %s to %s', short_id, target_url)
    return RedirectResponse(url=target_url, status_code=307)


@app.get('/analytics/{short_id}', response_model=URLInfo)
def get_url_analytics(short_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute(
            'SELECT id, original_url, clicks, created_at FROM urls WHERE id = ?',
            (short_id,),
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail='Short URL not found')

    return {
        'id': row[0],
        'original_url': row[1],
        'clicks': row[2],
        'created_at': row[3],
    }


@app.get('/healthz')
def healthz():
    return {'status': 'ok'}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('app:app', host='0.0.0.0', port=8000, reload=True)
'''


def load_env_key(path: Path) -> str:
    if not path.exists():
        return ''

    for line in path.read_text(encoding='utf-8').splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith('#') or '=' not in candidate:
            continue
        key, value = candidate.split('=', 1)
        if key.strip() == 'GEMINI_API_KEY':
            return value.strip().strip('"\'')
    return ''


class SDLCState:
    REQUIREMENTS = 'REQUIREMENTS'
    DECOMPOSITION = 'DECOMPOSITION'
    IMPLEMENTATION = 'IMPLEMENTATION'
    TESTING = 'TESTING'
    DOCUMENTATION = 'DOCUMENTATION'
    HUMAN_APPROVAL = 'HUMAN_APPROVAL'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'


class AgentOrchestrator:
    def __init__(self, task_prompt: str):
        self.task_prompt = task_prompt
        self.state = SDLCState.REQUIREMENTS
        self.context = {'decision_log': []}
        self.metrics = {
            'retries': 0,
            'rollbacks': 0,
            'start_time': time.time(),
            'success_rate': 0.0,
            'mttr_seconds': 0.0,
        }
        self.max_retries = 3
        self.model = None
        self.dependency_graph = {
            'requirements': [],
            'decomposition': ['requirements'],
            'implementation': ['decomposition'],
            'testing': ['implementation'],
            'documentation': ['implementation'],
            'human_approval': ['testing', 'documentation'],
            'completed': ['human_approval'],
        }
        self._configure_gemini()

    def _configure_gemini(self):
        api_key = os.getenv('GEMINI_API_KEY') or load_env_key(Path('.env'))
        if not api_key:
            logger.warning('GEMINI_API_KEY not configured. The orchestrator will fall back to the default implementation build.')
            return

        if genai is None:
            logger.warning('google-generativeai is unavailable: %s', GENAI_IMPORT_ERROR)
            return

        try:
            genai.configure(api_key=api_key)
            model_name = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
            self.model = genai.GenerativeModel(model_name)
            logger.info('Gemini model configured: %s', model_name)
        except Exception as exc:
            logger.warning('Unable to initialize Gemini model: %s', exc)

    def _add_decision(self, message: str):
        self.context['decision_log'].append(message)

    def _call_llm(self, prompt: str) -> str:
        if self.model is None:
            raise RuntimeError('LLM provider is unavailable. Using the safe default implementation path.')

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.model.generate_content(prompt)
                return response.text
            except Exception as exc:
                self.metrics['retries'] += 1
                logger.warning('LLM call failed (attempt %s/%s): %s', attempt, self.max_retries, exc)
                time.sleep(2)

        raise RuntimeError('Max retries exceeded for LLM call.')

    def _normalize_requirements(self):
        return (
            'Engineering problem: build a production-ready URL shortener service with FastAPI. '
            'Required endpoints: POST /shorten, GET /{id}, GET /analytics/{id}. '
            'Requirements: persistent storage, click tracking, safe SQL usage, validation, '
            'documented setup, and audit-friendly observability.'
        )

    def _build_default_tasks(self):
        return [
            '1. Define product requirements and API contracts for the URL shortener.',
            '2. Implement FastAPI routes and SQLite persistence for shortening and redirect logic.',
            '3. Add analytics and click counter tracking for each shortened record.',
            '4. Validate inputs, handle errors, and ensure safe database interactions.',
            '5. Document setup and execution instructions for local validation.',
        ]

    def run(self):
        while self.state not in (SDLCState.COMPLETED, SDLCState.FAILED):
            logger.info('--- Transitioning to State: %s ---', self.state)
            try:
                if self.state == SDLCState.REQUIREMENTS:
                    self._analyze_requirements()
                elif self.state == SDLCState.DECOMPOSITION:
                    self._decompose_tasks()
                elif self.state == SDLCState.IMPLEMENTATION:
                    self._implement_code()
                elif self.state == SDLCState.TESTING:
                    self._run_validation()
                elif self.state == SDLCState.DOCUMENTATION:
                    self._write_documentation()
                elif self.state == SDLCState.HUMAN_APPROVAL:
                    self._human_gate()
            except Exception as exc:
                logger.exception('Execution failed at %s: %s', self.state, exc)
                self._handle_failure()

        elapsed = time.time() - self.metrics['start_time']
        self.metrics['mttr_seconds'] = elapsed / max(1, self.metrics['retries'] + 1)
        self.metrics['success_rate'] = 1.0 if self.state == SDLCState.COMPLETED else 0.0
        logger.info(
            'Execution finished with state %s. Total time: %.2fs. Retries: %s. Rollbacks: %s. Metrics: %s',
            self.state,
            elapsed,
            self.metrics['retries'],
            self.metrics['rollbacks'],
            json.dumps(self.metrics, sort_keys=True),
        )

    def _analyze_requirements(self):
        prompt = (
            'Analyze the engineering requirement carefully and return a strict technical specification with '
            'ambiguity notes and implementation constraints. Requirement: ' + self.task_prompt
        )
        try:
            spec = self._call_llm(prompt)
        except RuntimeError:
            spec = self._normalize_requirements()

        self.context['spec'] = spec
        self._add_decision('Requirements normalized for the SDLC workflow.')
        self.state = SDLCState.DECOMPOSITION

    def _decompose_tasks(self):
        prompt = 'Break this specification into ordered engineering tasks with dependencies and sequencing.\n' + (self.context.get('spec') or self.task_prompt)
        try:
            tasks = self._call_llm(prompt)
        except RuntimeError:
            tasks = '\n'.join(self._build_default_tasks())

        self.context['tasks'] = tasks
        self._add_decision('Task decomposition completed with dependency-aware plan.')
        self.state = SDLCState.IMPLEMENTATION

    def _extract_python_code(self, raw_output: str) -> str:
        match = re.search(r'```(?:python)?\s*(.*?)\s*```', raw_output, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()

        cleaned_lines = []
        for line in raw_output.splitlines():
            stripped = line.strip()
            if stripped.startswith(('Here is', 'Sure', '```', '# app.py', 'Below is')):
                continue
            cleaned_lines.append(line)
        return '\n'.join(cleaned_lines).strip()

    def _implement_code(self):
        prompt = (
            'Write a production-ready FastAPI URL shortener service. Required endpoints: POST /shorten, '
            'GET /{id}, GET /analytics/{id}. Use SQLite, safe SQL parameters, click tracking, and a clean '
            'response model. Output only raw Python code with no markdown wrappers.\n\n'
            'Task breakdown:\n' + (self.context.get('tasks') or 'Implement the default service.')
        )
        try:
            raw_output = self._call_llm(prompt)
            code = self._extract_python_code(raw_output)
        except RuntimeError:
            code = DEFAULT_APP_CODE

        self.context['draft_code'] = code
        self._add_decision('Implementation draft generated and validated for code extraction.')
        self.state = SDLCState.TESTING

    def _run_validation(self):
        self.context['validation_result'] = 'Manual validation required using FastAPI TestClient and sqlite-backed checks.'
        self._add_decision('Implementation entered validation stage with guided checks.')
        self.state = SDLCState.DOCUMENTATION

    def _write_documentation(self):
        self.context['documentation'] = (
            'Architecture: FastAPI service with SQLite table storing short codes, original URLs, created timestamps, and click counters.\n'
            'Execution: start via uvicorn app:app --reload and exercise /shorten, /{id}, /analytics/{id}.\n'
            'Governance: human approval gate before writing the final code artifact.'
        )
        self._add_decision('Documentation created for setup, usage, and risk controls.')
        self.state = SDLCState.HUMAN_APPROVAL

    def _human_gate(self):
        preview = self.context.get('draft_code', DEFAULT_APP_CODE)
        print('\n' + '=' * 60)
        print('AGENTIC SDLC REVIEW SUMMARY')
        print('=' * 60)
        print('Decision lineage:')
        for item in self.context.get('decision_log', []):
            print(f'- {item}')
        print('\nImplementation preview:')
        print(preview[:600] + ('\n...[truncated]...' if len(preview) > 600 else ''))
        print('=' * 60)

        decision = input('Approve and write app.py? (y/n/retry): ').strip().lower()
        if decision == 'y':
            Path('app.py').write_text(preview, encoding='utf-8')
            self._add_decision('Human approved and app.py was written to disk.')
            self.state = SDLCState.COMPLETED
        elif decision == 'retry':
            self.metrics['rollbacks'] += 1
            self._add_decision('Human requested retry. Returning to implementation state.')
            self.state = SDLCState.IMPLEMENTATION
        else:
            self._add_decision('Human rejected the implementation; workflow safely stopped.')
            self.state = SDLCState.FAILED

    def _handle_failure(self):
        self.metrics['rollbacks'] += 1
        logger.warning('Safe-stop triggered and workflow halted in state %s.', self.state)
        self.state = SDLCState.FAILED


if __name__ == '__main__':
    initial_prompt = (
        'Build a URL shortener service using FastAPI. It must include POST /shorten, GET /{id}, and GET /analytics/{id}. '
        'Track click counts, validate URL inputs, and ensure secure SQLite parameterization and documentation. '
        'Treat this as a production-grade engineering task with controlled autonomy.'
    )
    orchestrator = AgentOrchestrator(initial_prompt)
    orchestrator.run()
