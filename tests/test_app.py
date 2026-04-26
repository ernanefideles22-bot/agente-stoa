import importlib.util
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
    temp_dir = Path(tempfile.mkdtemp(prefix="safe-stoa-", dir=temp_root))
    os.environ["STOA_ACCESS_TOKEN"] = "test-token"
    os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"
    os.environ["SESSION_STORE_PATH"] = str(temp_dir / "sessions.json")
    os.environ["PREVIEW_STORE_PATH"] = str(temp_dir / "previews.json")
    os.environ["COWORKER_STORE_PATH"] = str(temp_dir / "coworker.json")
    os.environ["AUDIT_LOG_PATH"] = str(temp_dir / "audit.log")
    os.environ["WORKSPACE_ROOT"] = str(temp_dir / "workspace")
    os.environ["STOA_AVATAR_REFERENCE_PATH"] = str(PROJECT_ROOT / "static" / "pwa-icons" / "icon-any.svg")
    os.environ["ALLOWED_HOSTS"] = "127.0.0.1,localhost,testserver"

    spec = importlib.util.spec_from_file_location("safe_stoa_app_under_test", APP_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.app.router.on_startup.clear()
    return module, temp_dir


class SafeStoaAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module, cls.temp_dir = load_app_module()
        cls.client = TestClient(cls.module.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def auth_headers(self):
        return {"Authorization": "Bearer test-token"}

    def setUp(self):
        self.module.session_store.clear()
        self.module.preview_store.clear()
        self.module.coworker_store = self.module.empty_coworker_store()
        self.module.persist_session_store = lambda: None
        self.module.persist_preview_store = lambda: None
        self.module.persist_coworker_store = lambda: None
        self.module.config.AUTO_SAVE_ARTIFACTS = False
        self.audit_events = []
        self.module.audit_log = lambda event_type, request, details: self.audit_events.append(
            {"event_type": event_type, "details": details}
        )

    def test_health_endpoint_is_public(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "online")
        self.assertEqual(payload["agent"], "Safe STOA Agent")

    def test_protected_session_endpoint_requires_bearer_token(self):
        response = self.client.get("/api/session/demo-session")
        self.assertEqual(response.status_code, 401)

        authorized = self.client.get("/api/session/demo-session", headers=self.auth_headers())
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.json()["session_id"], "demo-session")

    def test_manifest_exposes_install_metadata(self):
        response = self.client.get("/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["display"], "standalone")
        self.assertEqual(payload["start_url"], "/")
        icon_purposes = {icon["purpose"] for icon in payload["icons"]}
        self.assertIn("any", icon_purposes)
        self.assertIn("maskable", icon_purposes)

    def test_root_shell_registers_service_worker(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('rel="manifest" href="/manifest.webmanifest"', html)
        self.assertIn("navigator.serviceWorker.register('/sw.js')", html)

    def test_root_shell_exposes_preview_controls(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('id="previewPanel"', html)
        self.assertIn('id="previewApplyBtn"', html)
        self.assertIn('id="previewCancelBtn"', html)
        self.assertIn("/api/pending-preview/", html)
        self.assertIn("setPendingPreview(", html)
        self.assertIn("clearPendingPreview(", html)

    def test_root_shell_blocks_ambiguous_commands_while_preview_is_pending(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("Existe um preview pendente. Use apply para executar ou cancel para descartar antes de enviar outro comando.", html)
        self.assertIn("previewApplyBtn.addEventListener('click'", html)
        self.assertIn("previewCancelBtn.addEventListener('click'", html)
        self.assertIn("if (route.endpoint === '/api/command')", html)

    def test_root_shell_persists_command_mode_settings_across_reload(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("function persistCommandModeSettings()", html)
        self.assertIn("function restoreCommandModeSettings()", html)
        self.assertIn("sessionStorage.setItem('stoa_coworker_mode'", html)
        self.assertIn("sessionStorage.setItem('stoa_autopilot_mode'", html)
        self.assertIn("sessionStorage.setItem('stoa_super_mode'", html)
        self.assertIn("restoreCommandModeSettings();", html)

    def test_service_worker_skips_authenticated_api_cache(self):
        response = self.client.get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertIn("requestUrl.pathname.startsWith('/api/')", response.text)
        self.assertIn("STOA_SHELL_CACHE", response.text)

    def test_session_history_persists_and_trims_to_configured_limit(self):
        original_limit = self.module.config.MAX_SESSION_MESSAGES
        original_persist = self.module.persist_session_store
        self.module.config.MAX_SESSION_MESSAGES = 3
        self.module.persist_session_store = lambda: None
        try:
            for index in range(5):
                self.module.append_session_message("trim-session", "user", f"mensagem {index}")
            history = self.module.get_session_history("trim-session")
            self.assertEqual(len(history), 3)
            self.assertEqual([item["content"] for item in history], ["mensagem 2", "mensagem 3", "mensagem 4"])
        finally:
            self.module.config.MAX_SESSION_MESSAGES = original_limit
            self.module.persist_session_store = original_persist

    def test_resolve_workspace_target_blocks_path_escape(self):
        with self.assertRaises(self.module.HTTPException) as captured:
            self.module.resolve_workspace_target("demo-session", "../fora.txt")
        self.assertEqual(captured.exception.status_code, 400)

    def test_command_creates_pending_preview(self):
        response = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "que horas são?", "session_id": "preview-session", "mode": "builder"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["action_type"], "preview")
        preview = payload["data"]["pending_preview"]
        self.assertEqual(preview["session_id"], "preview-session")
        self.assertEqual(preview["module"], "time")

        state_response = self.client.get("/api/pending-preview/preview-session", headers=self.auth_headers())
        self.assertEqual(state_response.status_code, 200)
        self.assertEqual(state_response.json()["pending_preview"]["id"], preview["id"])

    def test_apply_executes_exact_pending_preview_and_clears_state(self):
        created = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "que horas são?", "session_id": "apply-session", "mode": "builder"},
        )
        preview = created.json()["data"]["pending_preview"]

        applied = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "apply", "session_id": "apply-session", "mode": "builder"},
        )
        self.assertEqual(applied.status_code, 200)
        payload = applied.json()
        self.assertEqual(payload["action_type"], "applied")
        self.assertEqual(payload["module"], "time")
        self.assertEqual(payload["data"]["applied_preview"]["id"], preview["id"])

        state_response = self.client.get("/api/pending-preview/apply-session", headers=self.auth_headers())
        self.assertIsNone(state_response.json()["pending_preview"])

        session_response = self.client.get("/api/session/apply-session", headers=self.auth_headers())
        messages = session_response.json()["messages"]
        system_events = [message for message in messages if message["role"] == "system"]
        self.assertTrue(any("preview_created" in item["content"] for item in system_events))
        self.assertTrue(any("preview_applied" in item["content"] for item in system_events))

        self.assertTrue(any(item["event_type"] == "command_preview_created" for item in self.audit_events))
        self.assertTrue(any(item["event_type"] == "command_preview_applied" for item in self.audit_events))

    def test_cancel_clears_pending_preview_without_execution(self):
        created = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "que horas são?", "session_id": "cancel-session", "mode": "builder"},
        )
        preview = created.json()["data"]["pending_preview"]

        cancelled = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "cancel", "session_id": "cancel-session", "mode": "builder"},
        )
        self.assertEqual(cancelled.status_code, 200)
        payload = cancelled.json()
        self.assertEqual(payload["action_type"], "cancelled")
        self.assertEqual(payload["data"]["cancelled_preview"]["id"], preview["id"])

        state_response = self.client.get("/api/pending-preview/cancel-session", headers=self.auth_headers())
        self.assertIsNone(state_response.json()["pending_preview"])

        session_response = self.client.get("/api/session/cancel-session", headers=self.auth_headers())
        messages = session_response.json()["messages"]
        system_events = [message for message in messages if message["role"] == "system"]
        self.assertTrue(any("preview_cancelled" in item["content"] for item in system_events))

        self.assertTrue(any(item["event_type"] == "command_preview_cancelled" for item in self.audit_events))

    def test_failed_apply_clears_broken_preview_state(self):
        preview = self.module.PendingPreview(
            id="broken-preview",
            session_id="error-session",
            original_text="executar ação inválida",
            prompt="pedido inválido",
            module="forbidden-module",
            mode="builder",
            created_at="2026-04-13T00:00:00",
        )
        self.module.preview_store["error-session"] = preview.model_dump()

        response = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "apply", "session_id": "error-session", "mode": "builder"},
        )
        self.assertEqual(response.status_code, 403)

        state_response = self.client.get("/api/pending-preview/error-session", headers=self.auth_headers())
        self.assertIsNone(state_response.json()["pending_preview"])

        session_response = self.client.get("/api/session/error-session", headers=self.auth_headers())
        messages = session_response.json()["messages"]
        system_events = [message for message in messages if message["role"] == "system"]
        self.assertTrue(any("preview_apply_failed" in item["content"] for item in system_events))

    def test_apply_without_pending_preview_returns_409(self):
        response = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "apply", "session_id": "no-preview-apply", "mode": "builder"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Nenhum preview pendente para aplicar.")

        state_response = self.client.get("/api/pending-preview/no-preview-apply", headers=self.auth_headers())
        self.assertIsNone(state_response.json()["pending_preview"])

    def test_cancel_without_pending_preview_returns_409(self):
        response = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "cancel", "session_id": "no-preview-cancel", "mode": "builder"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Nenhum preview pendente para cancelar.")

        state_response = self.client.get("/api/pending-preview/no-preview-cancel", headers=self.auth_headers())
        self.assertIsNone(state_response.json()["pending_preview"])

    def test_double_apply_rejects_second_execution(self):
        self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "que horas são?", "session_id": "double-apply", "mode": "builder"},
        )
        first_apply = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "apply", "session_id": "double-apply", "mode": "builder"},
        )
        self.assertEqual(first_apply.status_code, 200)

        second_apply = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "apply", "session_id": "double-apply", "mode": "builder"},
        )
        self.assertEqual(second_apply.status_code, 409)
        self.assertEqual(second_apply.json()["detail"], "Nenhum preview pendente para aplicar.")

    def test_double_cancel_rejects_second_cancellation(self):
        self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "que horas são?", "session_id": "double-cancel", "mode": "builder"},
        )
        first_cancel = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "cancel", "session_id": "double-cancel", "mode": "builder"},
        )
        self.assertEqual(first_cancel.status_code, 200)

        second_cancel = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "cancel", "session_id": "double-cancel", "mode": "builder"},
        )
        self.assertEqual(second_cancel.status_code, 409)
        self.assertEqual(second_cancel.json()["detail"], "Nenhum preview pendente para cancelar.")

    def test_pending_previews_are_isolated_between_sessions(self):
        first = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "que horas são?", "session_id": "session-a", "mode": "builder"},
        )
        second = self.client.post(
            "/api/command",
            headers=self.auth_headers(),
            json={"text": "explique filas", "session_id": "session-b", "mode": "builder"},
        )

        first_preview = first.json()["data"]["pending_preview"]
        second_preview = second.json()["data"]["pending_preview"]

        self.assertNotEqual(first_preview["id"], second_preview["id"])
        self.assertEqual(first_preview["session_id"], "session-a")
        self.assertEqual(second_preview["session_id"], "session-b")

        first_state = self.client.get("/api/pending-preview/session-a", headers=self.auth_headers())
        second_state = self.client.get("/api/pending-preview/session-b", headers=self.auth_headers())
        self.assertEqual(first_state.json()["pending_preview"]["id"], first_preview["id"])
        self.assertEqual(second_state.json()["pending_preview"]["id"], second_preview["id"])


if __name__ == "__main__":
    unittest.main()
