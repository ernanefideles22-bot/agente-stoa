"""
Testes unitários para STOA Agent API
Executar com: python -m pytest tests/ -v
"""

import pytest
# from fastapi.testclient import TestClient
# from main import app, brain, config
import json
from datetime import datetime


# @pytest.fixture
# def client():
#     """Cliente de teste FastAPI"""
#     return TestClient(app)


class TestUtilityFunctions:
    """Testes para funções utilitárias"""

    def test_datetime_formatting(self):
        """Testa formatação de datetime"""
        from main import STOAQuantumBrain
        brain = STOAQuantumBrain.__new__(STOAQuantumBrain)  # Instancia sem __init__
        timestamp = brain._now_response_timestamp()
        assert isinstance(timestamp, str)
        # Deve ser um ISO format válido
        datetime.fromisoformat(timestamp)

    def test_preview_id_generation(self):
        """Testa geração de preview ID"""
        from main import STOAQuantumBrain
        preview_id = STOAQuantumBrain._generate_preview_id()
        assert preview_id.startswith("preview-")
        assert len(preview_id) == len("preview-") + 8  # 8 chars hex

    def test_operation_id_generation(self):
        """Testa geração de operation ID"""
        from main import STOAQuantumBrain
        op_id = STOAQuantumBrain._generate_operation_id()
        assert op_id.startswith("op_")
        assert len(op_id) == len("op_") + 10  # 10 chars hex

    def test_goal_id_generation(self):
        """Testa geração de goal ID"""
        from main import STOAQuantumBrain
        goal_id = STOAQuantumBrain._generate_goal_id()
        assert goal_id.startswith("goal_")
        assert len(goal_id) == len("goal_") + 10  # 10 chars hex


class TestModelValidation:
    """Testes para validação de modelos"""

    def test_voice_command_model(self):
        """Testa modelo VoiceCommand"""
        from main import VoiceCommand
        cmd = VoiceCommand(text="teste", language="pt-BR")
        assert cmd.text == "teste"
        assert cmd.language == "pt-BR"
        assert cmd.timestamp is None

    def test_agent_response_model(self):
        """Testa modelo AgentResponse"""
        from main import AgentResponse
        resp = AgentResponse(
            response="teste",
            action_type="info",
            module="conversation",
            data={"test": True}
        )
        assert resp.response == "teste"
        assert resp.action_type == "info"
        assert resp.module == "conversation"
        assert resp.data["test"] is True


class TestStaticLogic:
    """Testes para lógica estática"""

    def test_mode_detection_conversation(self):
        """Testa detecção de modo conversation"""
        from main import STOAQuantumBrain
        mode = STOAQuantumBrain._detect_mode_from_command("qual é o clima hoje")
        assert mode == "conversation"

    def test_mode_detection_ops(self):
        """Testa detecção de modo ops"""
        from main import STOAQuantumBrain
        mode = STOAQuantumBrain._detect_mode_from_command("mostrar histórico de operações")
        assert mode == "ops"

    def test_mode_detection_dev(self):
        """Testa detecção de modo dev"""
        from main import STOAQuantumBrain
        mode = STOAQuantumBrain._detect_mode_from_command("criar arquivo teste.py")
        assert mode == "dev"

    def test_mode_detection_planner(self):
        """Testa detecção de modo planner"""
        from main import STOAQuantumBrain
        mode = STOAQuantumBrain._detect_mode_from_command("organize isso em um plano")
        assert mode == "planner"

    def test_mode_detection_preview(self):
        """Testa detecção de modo preview"""
        from main import STOAQuantumBrain
        mode = STOAQuantumBrain._detect_mode_from_command("planeje essas mudanças")
        assert mode == "preview"

    def test_mode_detection_stoa(self):
        """Testa detecção de modo stoa"""
        from main import STOAQuantumBrain
        mode = STOAQuantumBrain._detect_mode_from_command("stoa: crie um plano de ação")
        assert mode == "stoa"

    def test_mode_detection_stoa_command_variations(self):
        """Testa detecção de modo stoa com subcomandos"""
        from main import STOAQuantumBrain
        assert STOAQuantumBrain._detect_mode_from_command("stoa: defina objetivo entregar MVP") == "stoa"
        assert STOAQuantumBrain._detect_mode_from_command("modo stoa") == "stoa"
        assert STOAQuantumBrain._detect_mode_from_command("ativar stoa") == "stoa"


class TestDeviceLogic:
    """Testes para lógica de device"""

    def test_device_command_detection(self):
        """Testa detecção de comando device"""
        from main import STOAQuantumBrain
        brain = STOAQuantumBrain.__new__(STOAQuantumBrain)
        # Mock do DeviceCommandRouter
        import main
        original_is_device_command = main.DeviceCommandRouter.is_device_command
        main.DeviceCommandRouter.is_device_command = lambda cmd: "execute" in cmd

        try:
            assert brain._is_device_command("execute dir no pc")
            assert not brain._is_device_command("qual é a hora")
        finally:
            main.DeviceCommandRouter.is_device_command = original_is_device_command

    def test_confirmation_command_detection(self):
        """Testa detecção de comando de confirmação"""
        from main import STOAQuantumBrain
        assert STOAQuantumBrain.is_confirmation_command("confirmar última ação")
        assert STOAQuantumBrain.is_confirmation_command("cancelar ação")
        assert not STOAQuantumBrain.is_confirmation_command("qual é o clima")


# class TestHealthEndpoints:
#     """Testes para endpoints de saúde"""
#
#     def test_health_endpoint(self, client):
#         """Testa /api/health"""
#         response = client.get("/api/health")
#         assert response.status_code == 200
#         data = response.json()
#         assert data["status"] == "online"
#         assert "agent" in data
#         assert "timestamp" in data
#         assert "devices_registered" in data
#         assert isinstance(data["devices_registered"], int)


class TestPlannerApiEndpoints:
    def test_planner_health(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from planner_main import router

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)
        response = client.get("/api/planner/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_planner_preview_cancel_and_status(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from planner_main import router

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)

        response = client.get("/api/planner/status")
        assert response.status_code == 200
        assert response.json()["preview_status"]["exists"] is False

        response = client.post("/api/planner/preview", params={"command": "planeje criar rota get /rota-teste"})
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] in {"success", "error"}

        response = client.get("/api/planner/status")
        assert response.status_code == 200
        assert isinstance(response.json()["preview_status"], dict)

        response = client.post("/api/planner/cancel")
        assert response.status_code == 200
        assert response.json()["details"]["operation"] in {"cancel_preview", "cancel_preview_missing"}

        response = client.get("/api/planner/status")
        assert response.json()["preview_status"]["exists"] is False

    def test_executor_list_files(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from planner_main import router

        app = FastAPI()
        app.include_router(router)

        client = TestClient(app)
        response = client.post("/api/executor/execute", params={"command": "listar arquivos"})
        assert response.status_code == 200
        assert response.json()["details"]["operation"] == "list_files"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])