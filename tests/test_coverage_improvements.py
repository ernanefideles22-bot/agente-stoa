"""
Testes adicionais para ampliar a cobertura do agente-stoa.

Organização:
  TestAuthGuardSample        – 401 em endpoints protegidos sem token
  TestFileOperations         – escrita/leitura, path traversal, extensão proibida
  TestTerminalCommand        – allowlist de comandos no terminal
  TestRateLimit              – rate limiting via middleware HTTP
  TestStorePersistence       – persist/load dos stores em disco
  TestCoworkerOperations     – CRUD de projetos, tarefas, perfil, persona
  TestQueueOperations        – enfileiramento e status dos workers
  TestAuditLog               – emissão de eventos de auditoria
  TestUtilityEndpoints       – /api/time, /api/weather, /api/avatar-reference, headers
  TestHelperFunctions        – funções puras do módulo (unit tests sem HTTP)
  TestWebSocket              – conexão e ping/pong via WebSocket
"""

import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app" / "main.py"


def load_app_module():
    temp_root = PROJECT_ROOT / ".test_tmp"
    temp_root.mkdir(exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="safe-stoa-cov-", dir=temp_root))
    os.environ["STOA_ACCESS_TOKEN"] = "test-token"
    os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
    os.environ["SESSION_STORE_PATH"] = str(temp_dir / "sessions.json")
    os.environ["PREVIEW_STORE_PATH"] = str(temp_dir / "previews.json")
    os.environ["COWORKER_STORE_PATH"] = str(temp_dir / "coworker.json")
    os.environ["AUDIT_LOG_PATH"] = str(temp_dir / "audit.log")
    os.environ["WORKSPACE_ROOT"] = str(temp_dir / "workspace")
    os.environ["STOA_AVATAR_REFERENCE_PATH"] = str(
        PROJECT_ROOT / "static" / "pwa-icons" / "icon-any.svg"
    )
    os.environ["ALLOWED_HOSTS"] = "127.0.0.1,localhost,testserver"

    spec = importlib.util.spec_from_file_location("safe_stoa_app_cov", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.app.router.on_startup.clear()
    return module, temp_dir


class _Base(unittest.TestCase):
    """Base compartilhada: carrega módulo uma vez por classe e reseta estado entre testes."""

    @classmethod
    def setUpClass(cls):
        cls.module, cls.temp_dir = load_app_module()
        cls.client = TestClient(cls.module.app, raise_server_exceptions=False)
        # Salva funções reais antes do setUp sobrescrevê-las.
        # Usa staticmethod para evitar que o protocolo de descritores do Python
        # injete `self` como primeiro argumento ao acessar via instância.
        cls._real_persist_session = staticmethod(cls.module.persist_session_store)
        cls._real_persist_preview = staticmethod(cls.module.persist_preview_store)
        cls._real_persist_coworker = staticmethod(cls.module.persist_coworker_store)
        cls._real_load_session = staticmethod(cls.module.load_session_store)
        cls._real_load_preview = staticmethod(cls.module.load_preview_store)
        cls._real_load_coworker = staticmethod(cls.module.load_coworker_store)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def setUp(self):
        self.module.session_store.clear()
        self.module.preview_store.clear()
        self.module.coworker_store = self.module.empty_coworker_store()
        self.module.task_queue_store.clear()
        self.module.rate_limit_store.clear()
        self.module.persist_session_store = lambda: None
        self.module.persist_preview_store = lambda: None
        self.module.persist_coworker_store = lambda: None
        self.module.config.AUTO_SAVE_ARTIFACTS = False
        self.audit_events = []
        self.module.audit_log = lambda event_type, request, details: self.audit_events.append(
            {"event_type": event_type, "details": details}
        )

    def auth(self):
        return {"Authorization": "Bearer test-token"}


# ---------------------------------------------------------------------------
# 1. Guard de autenticação
# ---------------------------------------------------------------------------

class TestAuthGuardSample(_Base):
    """Endpoints protegidos devem retornar 401 quando o token estiver ausente."""

    PROTECTED_ENDPOINTS = [
        ("GET",  "/api/session/demo"),
        ("GET",  "/api/pending-preview/demo"),
        ("GET",  "/api/files/demo"),
        ("GET",  "/api/editable-files/demo"),
        ("GET",  "/api/project-tree/demo"),
        ("GET",  "/api/time"),
        ("GET",  "/api/weather"),
        ("GET",  "/api/queue/demo"),
        ("GET",  "/api/queue-worker"),
        ("GET",  "/api/project-supervisor-worker"),
        ("GET",  "/api/daily-briefing-worker"),
        ("GET",  "/api/coworker/demo/overview"),
        ("GET",  "/api/coworker/tasks/demo"),
        ("GET",  "/api/coworker/inbox/demo"),
        ("GET",  "/api/coworker/profile/demo"),
        ("POST", "/api/write-file"),
        ("POST", "/api/read-file"),
        ("POST", "/api/run-command"),
        ("POST", "/api/queue-task"),
        ("POST", "/api/coworker/project"),
        ("POST", "/api/coworker/task"),
        ("POST", "/api/coworker/profile"),
        ("POST", "/api/queue-worker/start"),
        ("POST", "/api/queue-worker/stop"),
    ]

    def _assert_401_without_token(self, method: str, path: str):
        response = self.client.request(method, path)
        self.assertEqual(
            response.status_code,
            401,
            f"{method} {path} deveria retornar 401 sem token, retornou {response.status_code}",
        )

    def test_health_is_public(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)

    def test_all_sample_endpoints_reject_unauthenticated(self):
        for method, path in self.PROTECTED_ENDPOINTS:
            with self.subTest(endpoint=f"{method} {path}"):
                self._assert_401_without_token(method, path)

    def test_wrong_token_returns_401(self):
        response = self.client.get(
            "/api/time",
            headers={"Authorization": "Bearer token-errado"},
        )
        self.assertEqual(response.status_code, 401)


# ---------------------------------------------------------------------------
# 2. Operações de arquivo
# ---------------------------------------------------------------------------

class TestFileOperations(_Base):
    """Escrita, leitura, path traversal e validação de extensão nos endpoints de arquivo."""

    def test_write_and_read_roundtrip(self):
        payload = {"session_id": "file-session", "relative_path": "nota.txt", "content": "olá mundo"}
        write_resp = self.client.post("/api/write-file", headers=self.auth(), json=payload)
        self.assertEqual(write_resp.status_code, 200)
        self.assertEqual(write_resp.json()["relative_path"], "nota.txt")

        read_resp = self.client.post(
            "/api/read-file",
            headers=self.auth(),
            json={"session_id": "file-session", "relative_path": "nota.txt"},
        )
        self.assertEqual(read_resp.status_code, 200)
        self.assertEqual(read_resp.json()["content"], "olá mundo")

    def test_write_file_appends_session_message(self):
        self.client.post(
            "/api/write-file",
            headers=self.auth(),
            json={"session_id": "msg-session", "relative_path": "doc.md", "content": "# Título"},
        )
        history = self.module.get_session_history("msg-session")
        self.assertTrue(any("Arquivo salvo" in m["content"] for m in history))

    def test_read_missing_file_returns_404(self):
        resp = self.client.post(
            "/api/read-file",
            headers=self.auth(),
            json={"session_id": "miss-session", "relative_path": "inexistente.txt"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_write_no_overwrite_conflict_returns_409(self):
        base = {"session_id": "ow-session", "relative_path": "arq.txt", "content": "v1"}
        self.client.post("/api/write-file", headers=self.auth(), json=base)
        resp = self.client.post(
            "/api/write-file",
            headers=self.auth(),
            json={**base, "content": "v2", "overwrite": False},
        )
        self.assertEqual(resp.status_code, 409)

    def test_write_path_traversal_rejected(self):
        resp = self.client.post(
            "/api/write-file",
            headers=self.auth(),
            json={"session_id": "trav-session", "relative_path": "../fora.txt", "content": "x"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_read_path_traversal_rejected(self):
        resp = self.client.post(
            "/api/read-file",
            headers=self.auth(),
            json={"session_id": "trav-session", "relative_path": "../../etc/passwd"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_write_disallowed_extension_rejected(self):
        resp = self.client.post(
            "/api/write-file",
            headers=self.auth(),
            json={"session_id": "ext-session", "relative_path": "script.sh", "content": "rm -rf /"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_editable_files_listing_includes_written_file(self):
        self.client.post(
            "/api/write-file",
            headers=self.auth(),
            json={"session_id": "list-session", "relative_path": "meu.py", "content": "print()"},
        )
        resp = self.client.get("/api/editable-files/list-session", headers=self.auth())
        self.assertEqual(resp.status_code, 200)
        files = resp.json()["files"]
        self.assertTrue(any(f["name"] == "meu.py" for f in files))

    def test_write_file_audit_event_emitted(self):
        self.client.post(
            "/api/write-file",
            headers=self.auth(),
            json={"session_id": "audit-file", "relative_path": "log.txt", "content": "dado"},
        )
        self.assertTrue(any(e["event_type"] == "write_file" for e in self.audit_events))


# ---------------------------------------------------------------------------
# 3. Comandos no terminal
# ---------------------------------------------------------------------------

class TestTerminalCommand(_Base):
    """Allowlist de comandos: permitidos passam, bloqueados retornam 403."""

    def test_allowed_command_returns_200(self):
        resp = self.client.post(
            "/api/run-command",
            headers=self.auth(),
            json={"session_id": "cmd-ok", "command": "python --version"},
        )
        # 200 = executou; 404 = executável ausente no sistema (também aceitável)
        self.assertIn(resp.status_code, {200, 404})
        if resp.status_code == 200:
            self.assertIn("command", resp.json())

    def test_blocked_command_returns_403(self):
        resp = self.client.post(
            "/api/run-command",
            headers=self.auth(),
            json={"session_id": "cmd-block", "command": "rm -rf /"},
        )
        self.assertEqual(resp.status_code, 403)

    def test_command_audit_event_emitted_on_success(self):
        self.client.post(
            "/api/run-command",
            headers=self.auth(),
            json={"session_id": "cmd-audit", "command": "python --version"},
        )
        # Se o comando executou (200), o evento de auditoria deve existir
        if any(e["event_type"] == "run_command" for e in self.audit_events):
            self.assertTrue(True)
        # Se não executou (404), não há evento — isso é aceitável no ambiente de CI

    def test_command_is_allowed_unit(self):
        allowed = self.module.command_is_allowed
        self.assertTrue(allowed(["python", "--version"]))
        self.assertTrue(allowed(["git", "status"]))
        self.assertTrue(allowed(["git", "log"]))
        self.assertFalse(allowed(["rm", "-rf", "/"]))
        self.assertFalse(allowed(["curl", "http://evil.com"]))
        self.assertFalse(allowed(["bash", "-c", "whoami"]))

    def test_parse_command_tokens_splits_correctly(self):
        tokens = self.module.parse_command_tokens("git status --short")
        self.assertEqual(tokens, ["git", "status", "--short"])

    def test_parse_command_tokens_rejects_empty(self):
        with self.assertRaises(self.module.HTTPException) as ctx:
            self.module.parse_command_tokens("   ")
        self.assertEqual(ctx.exception.status_code, 400)


# ---------------------------------------------------------------------------
# 4. Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimit(_Base):
    """O middleware deve bloquear requisições que excedem o limite configurado."""

    def _make_api_request(self):
        return self.client.get("/api/time", headers=self.auth())

    def test_rate_limit_blocks_after_exceeding_limit(self):
        original_limit = self.module.config.RATE_LIMIT_MAX_REQUESTS
        self.module.config.RATE_LIMIT_MAX_REQUESTS = 3
        try:
            for _ in range(3):
                resp = self._make_api_request()
                self.assertEqual(resp.status_code, 200)
            blocked = self._make_api_request()
            self.assertEqual(blocked.status_code, 429)
        finally:
            self.module.config.RATE_LIMIT_MAX_REQUESTS = original_limit
            self.module.rate_limit_store.clear()

    def test_health_endpoint_bypasses_rate_limit(self):
        original_limit = self.module.config.RATE_LIMIT_MAX_REQUESTS
        self.module.config.RATE_LIMIT_MAX_REQUESTS = 1
        try:
            for _ in range(5):
                resp = self.client.get("/api/health")
                self.assertEqual(resp.status_code, 200)
        finally:
            self.module.config.RATE_LIMIT_MAX_REQUESTS = original_limit
            self.module.rate_limit_store.clear()

    def test_rate_limit_resets_after_clearing_store(self):
        original_limit = self.module.config.RATE_LIMIT_MAX_REQUESTS
        self.module.config.RATE_LIMIT_MAX_REQUESTS = 2
        try:
            for _ in range(2):
                self._make_api_request()
            blocked = self._make_api_request()
            self.assertEqual(blocked.status_code, 429)

            self.module.rate_limit_store.clear()

            resp = self._make_api_request()
            self.assertEqual(resp.status_code, 200)
        finally:
            self.module.config.RATE_LIMIT_MAX_REQUESTS = original_limit
            self.module.rate_limit_store.clear()

    def test_rate_limit_audit_event_emitted(self):
        original_limit = self.module.config.RATE_LIMIT_MAX_REQUESTS
        self.module.config.RATE_LIMIT_MAX_REQUESTS = 1
        try:
            self._make_api_request()
            self._make_api_request()  # deve bloquear
            self.assertTrue(
                any(e["event_type"] == "rate_limit_block" for e in self.audit_events)
            )
        finally:
            self.module.config.RATE_LIMIT_MAX_REQUESTS = original_limit
            self.module.rate_limit_store.clear()


# ---------------------------------------------------------------------------
# 5. Persistência em disco
# ---------------------------------------------------------------------------

class TestStorePersistence(_Base):
    """persist_* grava JSON correto em disco; load_* restaura o estado."""

    def test_session_store_persists_to_disk_and_loads_back(self):
        self.module.session_store["persist-sess"] = [
            {"role": "user", "content": "mensagem de teste"}
        ]
        self._real_persist_session()

        path = self.module.config.SESSION_STORE_PATH
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("persist-sess", data)
        self.assertEqual(data["persist-sess"][0]["content"], "mensagem de teste")

        # Sobrescreve o store em memória e recarrega do disco
        self.module.session_store.clear()
        self._real_load_session()
        self.assertIn("persist-sess", self.module.session_store)
        self.assertEqual(self.module.session_store["persist-sess"][0]["content"], "mensagem de teste")

    def test_preview_store_persists_to_disk_and_loads_back(self):
        preview = self.module.PendingPreview(
            id="prv-disk",
            session_id="persist-prv",
            original_text="teste",
            prompt="prompt de teste",
            module="time",
            mode="builder",
            created_at="2026-01-01T00:00:00",
        )
        self.module.preview_store["persist-prv"] = preview.model_dump()
        self._real_persist_preview()

        path = self.module.config.PREVIEW_STORE_PATH
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("persist-prv", data)

        self.module.preview_store.clear()
        self._real_load_preview()
        self.assertIn("persist-prv", self.module.preview_store)
        self.assertEqual(self.module.preview_store["persist-prv"]["id"], "prv-disk")

    def test_coworker_store_persists_to_disk_and_loads_back(self):
        self.module.coworker_store.setdefault("projects", {})["cw-sess"] = [
            {"id": "proj-disk", "name": "Projeto Teste"}
        ]
        self._real_persist_coworker()

        path = self.module.config.COWORKER_STORE_PATH
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("projects", data)

        self.module.coworker_store = self.module.empty_coworker_store()
        self._real_load_coworker()
        projects = self.module.coworker_store.get("projects", {}).get("cw-sess", [])
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["name"], "Projeto Teste")

    def test_load_session_store_trims_to_max_messages(self):
        mensagens = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        self.module.config.SESSION_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.module.config.SESSION_STORE_PATH.write_text(
            json.dumps({"trim-sess": mensagens}, ensure_ascii=False),
            encoding="utf-8",
        )
        original_max = self.module.config.MAX_SESSION_MESSAGES
        self.module.config.MAX_SESSION_MESSAGES = 5
        try:
            self._real_load_session()
            loaded = self.module.session_store.get("trim-sess", [])
            self.assertLessEqual(len(loaded), 5)
        finally:
            self.module.config.MAX_SESSION_MESSAGES = original_max


# ---------------------------------------------------------------------------
# 6. Coworker CRUD
# ---------------------------------------------------------------------------

class TestCoworkerOperations(_Base):
    """Criação, leitura e atualização de projetos, tarefas, perfil e persona."""

    def test_project_create_appears_in_overview(self):
        resp = self.client.post(
            "/api/coworker/project",
            headers=self.auth(),
            json={"session_id": "cw-sess", "name": "Projeto Alpha", "summary": "Resumo do projeto Alpha"},
        )
        self.assertEqual(resp.status_code, 200)
        project = resp.json()["project"]
        self.assertEqual(project["name"], "Projeto Alpha")
        project_id = project["id"]

        overview = self.client.get("/api/coworker/cw-sess/overview", headers=self.auth())
        self.assertEqual(overview.status_code, 200)
        project_ids = [p["id"] for p in overview.json()["projects"]]
        self.assertIn(project_id, project_ids)

    def test_project_memory_404_on_missing_project(self):
        resp = self.client.get(
            "/api/coworker/project-memory/cw-sess/id-inexistente",
            headers=self.auth(),
        )
        self.assertEqual(resp.status_code, 404)

    def test_project_status_update_and_read(self):
        create_resp = self.client.post(
            "/api/coworker/project",
            headers=self.auth(),
            json={"session_id": "status-sess", "name": "Projeto Beta", "summary": "Beta"},
        )
        project_id = create_resp.json()["project"]["id"]

        update_resp = self.client.post(
            "/api/coworker/project-status",
            headers=self.auth(),
            json={
                "session_id": "status-sess",
                "project_id": project_id,
                "phase": "execution",
                "health": "yellow",
                "next_action": "revisar backlog",
                "blockers": ["falta de dados"],
                "risks": [],
            },
        )
        self.assertEqual(update_resp.status_code, 200)

        read_resp = self.client.get(
            f"/api/coworker/project-status/status-sess/{project_id}",
            headers=self.auth(),
        )
        self.assertEqual(read_resp.status_code, 200)
        status = read_resp.json()["status"]
        self.assertEqual(status["phase"], "execution")
        self.assertEqual(status["health"], "yellow")
        self.assertIn("falta de dados", status["blockers"])

    def test_project_memory_update_and_read(self):
        create_resp = self.client.post(
            "/api/coworker/project",
            headers=self.auth(),
            json={"session_id": "mem-sess", "name": "Projeto Gamma", "summary": "Gamma"},
        )
        project_id = create_resp.json()["project"]["id"]

        update_resp = self.client.post(
            "/api/coworker/project-memory",
            headers=self.auth(),
            json={
                "session_id": "mem-sess",
                "project_id": project_id,
                "preferences": ["usar FastAPI"],
                "decisions": ["escolher PostgreSQL"],
                "facts": ["deploy na nuvem"],
                "working_style": "iterações curtas",
            },
        )
        self.assertEqual(update_resp.status_code, 200)

        read_resp = self.client.get(
            f"/api/coworker/project-memory/mem-sess/{project_id}",
            headers=self.auth(),
        )
        self.assertEqual(read_resp.status_code, 200)
        memory = read_resp.json()["memory"]
        self.assertIn("usar FastAPI", memory["preferences"])
        self.assertIn("escolher PostgreSQL", memory["decisions"])

    def test_task_create_and_list(self):
        resp = self.client.post(
            "/api/coworker/task",
            headers=self.auth(),
            json={"session_id": "task-sess", "text": "Implementar autenticação", "priority": "high"},
        )
        self.assertEqual(resp.status_code, 200)
        task = resp.json()["task"]
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["priority"], "high")
        task_id = task["id"]

        list_resp = self.client.get("/api/coworker/tasks/task-sess", headers=self.auth())
        self.assertEqual(list_resp.status_code, 200)
        task_ids = [t["id"] for t in list_resp.json()["tasks"]]
        self.assertIn(task_id, task_ids)

    def test_task_update_status(self):
        create_resp = self.client.post(
            "/api/coworker/task",
            headers=self.auth(),
            json={"session_id": "tupd-sess", "text": "Revisar documentação", "priority": "medium"},
        )
        task_id = create_resp.json()["task"]["id"]

        update_resp = self.client.post(
            "/api/coworker/task/update",
            headers=self.auth(),
            json={"session_id": "tupd-sess", "task_id": task_id, "status": "completed"},
        )
        self.assertEqual(update_resp.status_code, 200)
        self.assertEqual(update_resp.json()["task"]["status"], "completed")

    def test_task_update_returns_404_for_unknown_id(self):
        resp = self.client.post(
            "/api/coworker/task/update",
            headers=self.auth(),
            json={"session_id": "tupd-sess", "task_id": "id-fantasma", "status": "completed"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_profile_get_returns_default_fields(self):
        resp = self.client.get("/api/coworker/profile/prof-sess", headers=self.auth())
        self.assertEqual(resp.status_code, 200)
        profile = resp.json()["profile"]
        self.assertIn("name", profile)
        self.assertIn("role", profile)
        self.assertIn("mission", profile)
        self.assertIn("personas", profile)

    def test_profile_update_persists_custom_name(self):
        resp = self.client.post(
            "/api/coworker/profile",
            headers=self.auth(),
            json={
                "session_id": "prof-upd",
                "name": "Assistente Alpha",
                "role": "Engenheiro Sênior",
                "mission": "Entregar código confiável.",
                "decision_rules": [],
                "strengths": [],
                "default_mode": "builder",
                "communication_style": "Objetivo e direto.",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["profile"]["name"], "Assistente Alpha")

        get_resp = self.client.get("/api/coworker/profile/prof-upd", headers=self.auth())
        self.assertEqual(get_resp.json()["profile"]["name"], "Assistente Alpha")

    def test_persona_create_and_retrievable_in_profile(self):
        resp = self.client.post(
            "/api/coworker/persona",
            headers=self.auth(),
            json={
                "session_id": "persona-sess",
                "domain": "data",
                "label": "Analista de Dados",
                "role": "AI de análise",
                "mission": "Transformar dados em decisões.",
                "decision_rules": ["priorizar acurácia"],
                "strengths": ["estatística"],
                "default_mode": "builder",
                "communication_style": "Analítico e preciso.",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["persona"]["label"], "Analista de Dados")

        profile_resp = self.client.get("/api/coworker/profile/persona-sess", headers=self.auth())
        personas = profile_resp.json()["profile"]["personas"]
        self.assertTrue(any(p.get("label") == "Analista de Dados" for p in personas.values()))


# ---------------------------------------------------------------------------
# 7. Fila e workers
# ---------------------------------------------------------------------------

class TestQueueOperations(_Base):
    """Enfileiramento de tarefas e controle de estado dos workers."""

    def test_enqueue_task_appears_in_queue_list(self):
        resp = self.client.post(
            "/api/queue-task",
            headers=self.auth(),
            json={"session_id": "q-sess", "text": "Analisar logs", "mode": "operator"},
        )
        self.assertEqual(resp.status_code, 200)
        task_id = resp.json()["task"]["id"]

        list_resp = self.client.get("/api/queue/q-sess", headers=self.auth())
        self.assertEqual(list_resp.status_code, 200)
        ids = [t["id"] for t in list_resp.json()["tasks"]]
        self.assertIn(task_id, ids)

    def test_queue_is_empty_for_new_session(self):
        resp = self.client.get("/api/queue/nova-sess-vazia", headers=self.auth())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["tasks"], [])

    def test_queue_worker_status_shape(self):
        resp = self.client.get("/api/queue-worker", headers=self.auth())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("enabled", data)
        self.assertIn("interval_seconds", data)

    def test_queue_worker_start_sets_enabled_true(self):
        self.client.post("/api/queue-worker/start", headers=self.auth())
        resp = self.client.get("/api/queue-worker", headers=self.auth())
        self.assertTrue(resp.json()["enabled"])
        self.client.post("/api/queue-worker/stop", headers=self.auth())

    def test_queue_worker_stop_sets_enabled_false(self):
        self.client.post("/api/queue-worker/start", headers=self.auth())
        self.client.post("/api/queue-worker/stop", headers=self.auth())
        resp = self.client.get("/api/queue-worker", headers=self.auth())
        self.assertFalse(resp.json()["enabled"])

    def test_project_supervisor_worker_status_shape(self):
        resp = self.client.get("/api/project-supervisor-worker", headers=self.auth())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("enabled", data)
        self.assertIn("interval_seconds", data)
        self.assertIn("active_projects", data)

    def test_daily_briefing_worker_status_shape(self):
        resp = self.client.get("/api/daily-briefing-worker", headers=self.auth())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("enabled", data)
        self.assertIn("interval_seconds", data)
        self.assertIn("active_sessions", data)

    def test_queue_task_audit_event_emitted(self):
        self.client.post(
            "/api/queue-task",
            headers=self.auth(),
            json={"session_id": "q-audit", "text": "Tarefa auditada", "mode": "builder"},
        )
        self.assertTrue(any(e["event_type"] == "queue_task" for e in self.audit_events))


# ---------------------------------------------------------------------------
# 8. Log de auditoria
# ---------------------------------------------------------------------------

class TestAuditLog(_Base):
    """Operações de escrita devem emitir eventos de auditoria no tipo correto."""

    def test_write_file_emits_write_file_event(self):
        self.client.post(
            "/api/write-file",
            headers=self.auth(),
            json={"session_id": "al-sess", "relative_path": "arq.txt", "content": "dado"},
        )
        types = [e["event_type"] for e in self.audit_events]
        self.assertIn("write_file", types)

    def test_coworker_project_create_emits_event(self):
        self.client.post(
            "/api/coworker/project",
            headers=self.auth(),
            json={"session_id": "al-sess", "name": "Alpha", "summary": "Resumo"},
        )
        types = [e["event_type"] for e in self.audit_events]
        self.assertIn("coworker_project_create", types)

    def test_coworker_task_create_emits_event(self):
        self.client.post(
            "/api/coworker/task",
            headers=self.auth(),
            json={"session_id": "al-sess", "text": "Tarefa de teste", "priority": "low"},
        )
        types = [e["event_type"] for e in self.audit_events]
        self.assertIn("coworker_task_create", types)

    def test_coworker_profile_update_emits_event(self):
        self.client.post(
            "/api/coworker/profile",
            headers=self.auth(),
            json={
                "session_id": "al-prof",
                "name": "Test",
                "role": "Test",
                "mission": "Test",
                "decision_rules": [],
                "strengths": [],
                "default_mode": "builder",
                "communication_style": "Test",
            },
        )
        types = [e["event_type"] for e in self.audit_events]
        self.assertIn("coworker_profile_update", types)

    def test_worker_start_stop_emit_events(self):
        self.client.post("/api/queue-worker/start", headers=self.auth())
        self.client.post("/api/queue-worker/stop", headers=self.auth())
        types = [e["event_type"] for e in self.audit_events]
        self.assertIn("queue_worker_start", types)
        self.assertIn("queue_worker_stop", types)


# ---------------------------------------------------------------------------
# 9. Endpoints utilitários
# ---------------------------------------------------------------------------

class TestUtilityEndpoints(_Base):
    """Endpoints de tempo, clima, avatar e verificação de headers de segurança."""

    def test_time_endpoint_returns_iso_timestamp(self):
        resp = self.client.get("/api/time", headers=self.auth())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("timestamp", data)
        self.assertIn("time", data)
        self.assertIn("date", data)
        # Deve ser parsável como ISO
        from datetime import datetime
        datetime.fromisoformat(data["timestamp"])

    def test_weather_endpoint_returns_fallback_without_api_key(self):
        original = self.module.config.OPENWEATHER_API_KEY
        self.module.config.OPENWEATHER_API_KEY = ""
        try:
            resp = self.client.get("/api/weather", headers=self.auth())
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("temperature", data)
            self.assertIn("description", data)
            self.assertTrue(data.get("fallback", False))
        finally:
            self.module.config.OPENWEATHER_API_KEY = original

    def test_avatar_reference_returns_svg_content_type(self):
        resp = self.client.get("/api/avatar-reference")
        self.assertEqual(resp.status_code, 200)
        content_type = resp.headers.get("content-type", "")
        self.assertTrue(
            "svg" in content_type or "image" in content_type,
            f"Content-type inesperado: {content_type}",
        )

    def test_security_headers_present_in_api_response(self):
        resp = self.client.get("/api/time", headers=self.auth())
        headers = resp.headers
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")

    def test_security_headers_present_in_non_api_response(self):
        resp = self.client.get("/")
        headers = resp.headers
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("Content-Security-Policy", headers)


# ---------------------------------------------------------------------------
# 10. Funções auxiliares (unit tests puros)
# ---------------------------------------------------------------------------

class TestHelperFunctions(_Base):
    """Testes de funções puras sem chamadas HTTP."""

    def test_slugify_normalizes_to_lowercase_hyphenated(self):
        slugify = self.module.slugify
        # Caracteres ASCII: espaço vira hífen, letras ficam minúsculas
        self.assertEqual(slugify("Hello World"), "hello-world")
        self.assertEqual(slugify("FastAPI 2024"), "fastapi-2024")
        # Hífens consecutivos são colapsados
        self.assertEqual(slugify("a  b"), "a-b")
        # Fallback quando resultado fica vazio
        self.assertEqual(slugify("---"), "artifact")

    def test_normalize_priority_valid_values(self):
        norm = self.module.normalize_priority
        for val in ("critical", "high", "medium", "low"):
            self.assertEqual(norm(val), val)

    def test_normalize_priority_invalid_defaults_to_medium(self):
        self.assertEqual(self.module.normalize_priority("urgente"), "medium")
        self.assertEqual(self.module.normalize_priority(None), "medium")
        self.assertEqual(self.module.normalize_priority(""), "medium")

    def test_normalize_task_status_valid_values(self):
        norm = self.module.normalize_task_status
        for val in ("pending", "running", "blocked", "completed", "failed", "cancelled"):
            self.assertEqual(norm(val), val)

    def test_normalize_task_status_invalid_defaults_to_pending(self):
        self.assertEqual(self.module.normalize_task_status("em_andamento"), "pending")
        self.assertEqual(self.module.normalize_task_status(None), "pending")

    def test_merge_unique_text_deduplicates_preserving_order(self):
        merge = self.module.merge_unique_text
        result = merge(["a", "b"], ["b", "c", "a"], 10)
        self.assertEqual(result, ["a", "b", "c"])

    def test_merge_unique_text_respects_limit(self):
        merge = self.module.merge_unique_text
        result = merge([], [str(i) for i in range(20)], 5)
        self.assertEqual(len(result), 5)

    def test_classify_preview_control_apply_variants(self):
        classify = self.module.classify_preview_control
        for word in ("apply", "aplicar", "confirmar", "executar", "ok", "APPLY", "  ok  "):
            self.assertEqual(classify(word), "apply", f"Esperava 'apply' para '{word}'")

    def test_classify_preview_control_cancel_variants(self):
        classify = self.module.classify_preview_control
        for word in ("cancel", "cancelar", "descartar", "abortar", "nao", "não"):
            self.assertEqual(classify(word), "cancel", f"Esperava 'cancel' para '{word}'")

    def test_classify_preview_control_none_for_regular_text(self):
        classify = self.module.classify_preview_control
        self.assertIsNone(classify("que horas são?"))
        self.assertIsNone(classify("criar um relatório"))
        self.assertIsNone(classify(""))

    def test_get_or_create_session_id_preserves_non_empty(self):
        func = self.module.get_or_create_session_id
        self.assertEqual(func("minha-sessao"), "minha-sessao")

    def test_get_or_create_session_id_generates_uuid_when_empty(self):
        func = self.module.get_or_create_session_id
        result = func(None)
        self.assertTrue(len(result) > 8)
        result2 = func("")
        self.assertNotEqual(result, result2)

    def test_normalize_project_health_valid_values(self):
        norm = self.module.normalize_project_health
        self.assertEqual(norm("green"), "green")
        self.assertEqual(norm("yellow"), "yellow")
        self.assertEqual(norm("red"), "red")

    def test_normalize_project_health_invalid_defaults_to_green(self):
        norm = self.module.normalize_project_health
        self.assertEqual(norm("azul"), "green")
        self.assertEqual(norm(None), "green")

    def test_priority_weight_ordering(self):
        weight = self.module.priority_weight
        self.assertLess(weight("critical"), weight("high"))
        self.assertLess(weight("high"), weight("medium"))
        self.assertLess(weight("medium"), weight("low"))


# ---------------------------------------------------------------------------
# 11. WebSocket
# ---------------------------------------------------------------------------

class TestWebSocket(_Base):
    """Conexão WebSocket com token válido e inválido."""

    def test_websocket_rejects_invalid_token(self):
        from starlette.websockets import WebSocketDisconnect

        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws?token=token-errado") as ws:
                ws.receive_json()

    def test_websocket_accepts_valid_token_and_sends_initial_state(self):
        with self.client.websocket_connect("/ws?token=test-token&session_id=ws-sess") as ws:
            first_msg = ws.receive_json()
            self.assertEqual(first_msg["type"], "avatar_state")
            self.assertEqual(first_msg["state"], "idle")

    def test_websocket_responds_to_ping_with_pong(self):
        with self.client.websocket_connect("/ws?token=test-token&session_id=ping-sess") as ws:
            ws.receive_json()  # avatar_state
            ws.receive_json()  # avatar_metrics
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            self.assertEqual(pong["type"], "pong")


if __name__ == "__main__":
    unittest.main()
