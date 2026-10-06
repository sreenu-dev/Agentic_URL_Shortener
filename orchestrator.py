# orchestrator.py
import ast
import importlib.util
import json
import logging
import os
import re
import subprocess
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


APP_PACKAGE_DISTRIBUTIONS = {
    'pydantic_settings': 'pydantic-settings',
    'pytest_asyncio': 'pytest-asyncio',
}
APP_RUNTIME_MODULES = {
    'aiosqlite',
    'fastapi',
    'pydantic',
    'pydantic_settings',
    'uvicorn',
}
REQUIRED_APP_ROUTES = {
    ('POST', '/shorten'),
    ('GET', '/{id}'),
    ('GET', '/analytics/{id}'),
    ('GET', '/health'),
    ('GET', '/urls')
}


def install_app_dependencies(app_path: Path) -> None:
    """Install third-party packages imported by app.py if they are missing."""
    tree = ast.parse(app_path.read_text(encoding='utf-8'), filename=str(app_path))
    imported_modules = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split('.', 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported_modules.add(node.module.split('.', 1)[0])

    missing_distributions = set()
    for module_name in sorted(imported_modules):
        if module_name in sys.stdlib_module_names:
            continue
        if (app_path.parent / f'{module_name}.py').exists() or (
            app_path.parent / module_name / '__init__.py'
        ).exists():
            continue
        if importlib.util.find_spec(module_name) is None:
            missing_distributions.add(
                APP_PACKAGE_DISTRIBUTIONS.get(module_name, module_name)
            )

    if not missing_distributions:
        logger.info('All third-party app.py dependencies are already installed.')
        return

    packages = sorted(missing_distributions)
    logger.info('Installing missing app.py dependencies: %s', ', '.join(packages))
    subprocess.run(
        [sys.executable, '-m', 'pip', 'install', *packages],
        check=True,
    )


def validate_app_code(code: str) -> str:
    """Check generated source syntax, runtime imports, app object, and required routes."""
    try:
        tree = ast.parse(code, filename='app.py')
        compile(tree, 'app.py', 'exec')
    except SyntaxError as exc:
        raise ValueError(f'Generated app.py has invalid Python syntax: {exc}') from exc

    app_is_fastapi = any(
        isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == 'app'
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
        )
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == 'FastAPI'
        for node in tree.body
    )
    if not app_is_fastapi:
        raise ValueError('Generated app.py must define app = FastAPI(...).')

    routes = set()
    route_positions = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                not isinstance(decorator, ast.Call)
                or not isinstance(decorator.func, ast.Attribute)
                or not isinstance(decorator.func.value, ast.Name)
                or decorator.func.value.id != 'app'
                or decorator.func.attr.lower() not in {'get', 'post'}
                or not decorator.args
                or not isinstance(decorator.args[0], ast.Constant)
                or not isinstance(decorator.args[0].value, str)
            ):
                continue
            method = decorator.func.attr.upper()
            route = re.sub(r'\{[^{}]+\}', '{id}', decorator.args[0].value)
            routes.add((method, route))
            route_positions.setdefault((method, route), node.lineno)

    missing_routes = REQUIRED_APP_ROUTES - routes
    if missing_routes:
        formatted_routes = ', '.join(
            f'{method} {route}' for method, route in sorted(missing_routes)
        )
        raise ValueError(f'Generated app.py is missing required routes: {formatted_routes}.')

    catch_all_position = route_positions[('GET', '/{id}')]
    for static_route in ('/health', '/analytics/{id}', '/urls'):
        if route_positions[('GET', static_route)] > catch_all_position:
            raise ValueError(
                f'Define GET {static_route} before GET /{{id}}; otherwise the dynamic route may shadow it.'
            )

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split('.', 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported_modules.add(node.module.split('.', 1)[0])

    test_modules = imported_modules & {'pytest', 'pytest_asyncio', 'httpx'}
    if test_modules:
        names = ', '.join(sorted(test_modules))
        raise ValueError(
            f'Generated app.py must not import test-only packages ({names}); '
            'keep tests under tests/.'
        )

    unsupported_modules = (
        imported_modules - sys.stdlib_module_names - APP_RUNTIME_MODULES
    )
    if unsupported_modules:
        names = ', '.join(sorted(unsupported_modules))
        raise ValueError(
            f'Generated app.py imports unsupported third-party packages: {names}. '
            'Use only the standard library, FastAPI, Pydantic, and Uvicorn.'
        )

    return 'Python syntax, FastAPI app object, runtime imports, and required routes validated.'


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


class ShortenedURLListItem(BaseModel):
    id: str
    short_url: str
    long_url: str


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


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.get('/urls', response_model=list[ShortenedURLListItem])
def list_urls():
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            'SELECT id, original_url FROM urls ORDER BY created_at DESC, id'
        ).fetchall()

    base_url = os.getenv('BASE_URL', 'http://localhost:8000').rstrip('/')
    return [
        {
            'id': row[0],
            'short_url': f'{base_url}/{row[0]}',
            'long_url': row[1],
        }
        for row in rows
    ]


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
            value = value.strip().strip('"\'')
            if value.lower() == 'replace-with-your-own-key':
                return ''
            return value
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
        api_key = os.getenv('GEMINI_API_KEY', '').strip() or load_env_key(
            Path(__file__).resolve().parent / '.env'
        )
        if not api_key:
            logger.warning(
                'GEMINI_API_KEY is missing. Create a key in Google AI Studio and set it '
                'in the environment or in .env beside orchestrator.py. The orchestrator '
                'will fall back to the default implementation build.'
            )
            return

        if genai is None:
            logger.warning('google-generativeai is unavailable: %s', GENAI_IMPORT_ERROR)
            return

        try:
            genai.configure(api_key=api_key)
            model_name = os.getenv('GEMINI_MODEL', 'gemini-3.5-flash')
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
            'Write one complete, directly runnable FastAPI application for a URL shortener. '
            'It must define a module-level `app = FastAPI(...)` and these routes: POST /shorten, '
            'GET /{short_id}, GET /analytics/{short_id}, GET /urls, and GET /health. '
            'GET /urls must return every short code, its full short URL, and its destination as long_url. '
            'Register all fixed paths before the catch-all GET /{short_id}. Use SQLite from the Python standard '
            'library, parameterized SQL, URL validation, consistent response models, and explicit '
            '404 handling. Keep all test code in separate files '
            'under tests/; do not import pytest, pytest_asyncio, or httpx in app.py. '
            'Use only standard-library modules plus FastAPI, Pydantic, Uvicorn, '
            'aiosqlite, and pydantic-settings. '
            'Do not use extra third-party packages, external services, or network calls. '
            'If using Pydantic Settings to read .env, configure it to ignore unrelated variables '
            '(for example SettingsConfigDict(env_file=".env", extra="ignore")) so Gemini and other '
            'environment settings do not prevent the API from starting. '
            'Initialize storage safely and make `python -m uvicorn app:app --reload` work from '
            'the project directory. Do not execute database initialization as an import side effect; '
            'use FastAPI lifespan startup where needed. Return only complete Python source code, '
            'without markdown fences or commentary.\n\n'
            'Task breakdown:\n' + (self.context.get('tasks') or 'Implement the default service.')
        )
        try:
            raw_output = self._call_llm(prompt)
            code = self._extract_python_code(raw_output)
        except RuntimeError:
            code = DEFAULT_APP_CODE
            self._add_decision('Gemini unavailable; using the built-in FastAPI implementation.')

        try:
            validation = validate_app_code(code)
        except ValueError as exc:
            logger.warning('Generated implementation did not pass validation: %s', exc)
            self._add_decision(
                f'Generated implementation failed validation ({exc}); using the built-in implementation.'
            )
            code = DEFAULT_APP_CODE
            validation = validate_app_code(code)

        self.context['draft_code'] = code
        self.context['validation_result'] = validation
        self._add_decision(validation)
        self.state = SDLCState.TESTING

    def _run_validation(self):
        code = self.context.get('draft_code', DEFAULT_APP_CODE)
        try:
            self.context['validation_result'] = validate_app_code(code)
        except ValueError as exc:
            logger.warning('Draft failed validation before approval: %s', exc)
            self.context['draft_code'] = DEFAULT_APP_CODE
            self.context['validation_result'] = validate_app_code(DEFAULT_APP_CODE)
            self._add_decision(
                f'Draft failed pre-approval validation ({exc}); replaced with the built-in implementation.'
            )
        self._add_decision('Draft passed pre-approval static validation.')
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
        print('\nValidation:')
        print(self.context.get('validation_result', 'No validation result recorded.'))
        print('\nImplementation preview:')
        print(preview[:600] + ('\n...[truncated]...' if len(preview) > 600 else ''))
        print('=' * 60)

        decision = input('Approve and write app.py? (y/n/retry): ').strip().lower()
        if decision == 'y':
            target = Path(__file__).resolve().with_name('app.py')
            target.write_text(preview, encoding='utf-8')
            self._add_decision(f'Human approved and {target} was written to disk.')
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
    install_app_dependencies(Path(__file__).resolve().with_name('app.py'))
    initial_prompt = (
        'Build a URL shortener service using FastAPI. It must include POST /shorten, GET /{id}, and GET /analytics/{id}. '
        'Track click counts, validate URL inputs, and ensure secure SQLite parameterization and documentation. '
        'Treat this as a production-grade engineering task with controlled autonomy.'
    )
    orchestrator = AgentOrchestrator(initial_prompt)
    orchestrator.run()
