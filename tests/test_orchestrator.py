from types import SimpleNamespace

import orchestrator
import pytest


def test_install_app_dependencies_installs_only_missing_external_modules(
    monkeypatch, tmp_path
):
    app_path = tmp_path / 'app.py'
    app_path.write_text(
        'import os\n'
        'import missing_lib\n'
        'from pydantic_settings import BaseSettings\n'
        'from local_helper import helper\n',
        encoding='utf-8',
    )
    (tmp_path / 'local_helper.py').write_text('', encoding='utf-8')
    checked_modules = []

    def module_is_missing(name):
        checked_modules.append(name)
        return None

    monkeypatch.setattr(orchestrator.importlib.util, 'find_spec', module_is_missing)

    install_calls = []

    def record_install(*args, **kwargs):
        install_calls.append((args, kwargs))

    monkeypatch.setattr(orchestrator.subprocess, 'run', record_install)

    orchestrator.install_app_dependencies(app_path)

    assert install_calls == [
        (
            (
                [
                    orchestrator.sys.executable,
                    '-m',
                    'pip',
                    'install',
                    'missing_lib',
                    'pydantic-settings',
                ],
            ),
            {'check': True},
        )
    ]
    assert checked_modules == ['missing_lib', 'pydantic_settings']


def test_install_app_dependencies_propagates_pip_errors(monkeypatch, tmp_path):
    app_path = tmp_path / 'app.py'
    app_path.write_text('import missing_lib\n', encoding='utf-8')

    checked_modules = []

    def module_is_missing(name):
        checked_modules.append(name)
        return None

    monkeypatch.setattr(
        orchestrator.importlib.util, 'find_spec', module_is_missing
    )
    attempted_installs = []

    def fail_install(*args, **kwargs):
        attempted_installs.append((args, kwargs))
        raise orchestrator.subprocess.CalledProcessError(1, 'pip install')

    monkeypatch.setattr(orchestrator.subprocess, 'run', fail_install)

    with pytest.raises(orchestrator.subprocess.CalledProcessError):
        orchestrator.install_app_dependencies(app_path)
    assert checked_modules == ['missing_lib']
    assert attempted_installs


def test_configure_gemini_loads_project_env_from_any_working_directory(
    monkeypatch, tmp_path
):
    project_dir = tmp_path / 'project'
    launch_dir = tmp_path / 'launch'
    project_dir.mkdir()
    launch_dir.mkdir()
    (project_dir / '.env').write_text(
        'GEMINI_API_KEY="test-key"\n', encoding='utf-8'
    )
    monkeypatch.setattr(orchestrator, '__file__', str(project_dir / 'orchestrator.py'))
    monkeypatch.chdir(launch_dir)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)

    configured_keys = []
    created_models = []
    model = object()
    fake_genai = SimpleNamespace(
        configure=lambda *, api_key: configured_keys.append(api_key),
        GenerativeModel=lambda model_name: created_models.append(model_name) or model,
    )
    monkeypatch.setattr(orchestrator, 'genai', fake_genai)

    agent = orchestrator.AgentOrchestrator.__new__(orchestrator.AgentOrchestrator)
    agent._configure_gemini()

    assert configured_keys == ['test-key']
    assert created_models == ['gemini-3.5-flash']
    assert agent.model is model


def test_load_env_key_ignores_example_placeholder(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text(
        'GEMINI_API_KEY=replace-with-your-own-key\n', encoding='utf-8'
    )

    assert orchestrator.load_env_key(env_file) == ''


def test_validate_app_code_accepts_builtin_implementation():
    result = orchestrator.validate_app_code(orchestrator.DEFAULT_APP_CODE)

    assert 'required routes validated' in result


@pytest.mark.parametrize(
    ('source', 'message'),
    [
        ('def broken(:\n', 'invalid Python syntax'),
        (
            'from fastapi import FastAPI\n'
            'app = FastAPI()\n'
            '@app.post("/shorten")\n'
            'def shorten(): pass\n',
            'missing required routes',
        ),
        (
            'import pytest\n'
            'from fastapi import FastAPI\n'
            'app = FastAPI()\n'
            '@app.post("/shorten")\n'
            'def shorten(): pass\n'
            '@app.get("/health")\n'
            'def health(): pass\n'
            '@app.get("/urls")\n'
            'def list_urls(): pass\n'
            '@app.get("/analytics/{short_id}")\n'
            'def analytics(short_id): pass\n'
            '@app.get("/{short_id}")\n'
            'def redirect(short_id): pass\n',
            'test-only packages',
        ),
        (
            'import requests\n'
            'from fastapi import FastAPI\n'
            'app = FastAPI()\n'
            '@app.post("/shorten")\n'
            'def shorten(): pass\n'
            '@app.get("/health")\n'
            'def health(): pass\n'
            '@app.get("/urls")\n'
            'def list_urls(): pass\n'
            '@app.get("/analytics/{short_id}")\n'
            'def analytics(short_id): pass\n'
            '@app.get("/{short_id}")\n'
            'def redirect(short_id): pass\n',
            'unsupported third-party packages',
        ),
    ],
)
def test_validate_app_code_rejects_invalid_or_unsupported_code(source, message):
    with pytest.raises(ValueError, match=message):
        orchestrator.validate_app_code(source)


def test_implement_code_uses_builtin_when_generated_code_fails_validation():
    agent = orchestrator.AgentOrchestrator.__new__(orchestrator.AgentOrchestrator)
    agent.context = {'decision_log': [], 'tasks': 'Implement the API.'}
    agent.state = orchestrator.SDLCState.IMPLEMENTATION
    prompts = []

    def return_invalid_code(prompt):
        prompts.append(prompt)
        return 'not a FastAPI application'

    agent._call_llm = return_invalid_code

    agent._implement_code()

    assert agent.context['draft_code'] == orchestrator.DEFAULT_APP_CODE
    assert 'required routes validated' in agent.context['validation_result']
    assert agent.state == orchestrator.SDLCState.TESTING
    assert 'do not import pytest' in prompts[0]
    assert 'GET /urls' in prompts[0]


def test_validate_app_code_rejects_health_route_shadowed_by_catch_all():
    source = (
        'from fastapi import FastAPI\n'
        'app = FastAPI()\n'
        '@app.post("/shorten")\n'
        'def shorten(): pass\n'
        '@app.get("/urls")\n'
        'def list_urls(): pass\n'
        '@app.get("/analytics/{short_id}")\n'
        'def analytics(short_id): pass\n'
        '@app.get("/{short_id}")\n'
        'def redirect(short_id): pass\n'
        '@app.get("/health")\n'
        'def health(): pass\n'
    )

    with pytest.raises(ValueError, match='may shadow it'):
        orchestrator.validate_app_code(source)
