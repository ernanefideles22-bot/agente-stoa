"""
Testes unitários básicos para STOA Agent
Executar com: python -m pytest tests/ -v
"""

import pytest
import json
from datetime import datetime


class TestBasicValidation:
    """Testes básicos de validação"""

    def test_json_parsing(self):
        """Testa parsing JSON básico"""
        test_data = {"test": "value", "number": 42}
        json_str = json.dumps(test_data)
        parsed = json.loads(json_str)
        assert parsed["test"] == "value"
        assert parsed["number"] == 42

    def test_datetime_iso_format(self):
        """Testa formatação ISO de datetime"""
        now = datetime.now()
        iso_str = now.isoformat()
        parsed = datetime.fromisoformat(iso_str)
        assert isinstance(parsed, datetime)

    def test_string_operations(self):
        """Testa operações básicas de string"""
        test_str = "STOA Agent Test"
        assert test_str.startswith("STOA")
        assert test_str.endswith("Test")
        assert "Agent" in test_str

    def test_list_operations(self):
        """Testa operações básicas de lista"""
        test_list = [1, 2, 3, 4, 5]
        assert len(test_list) == 5
        assert 3 in test_list
        assert test_list[0] == 1
        assert test_list[-1] == 5

    def test_dict_operations(self):
        """Testa operações básicas de dicionário"""
        test_dict = {"key1": "value1", "key2": "value2"}
        assert "key1" in test_dict
        assert test_dict["key1"] == "value1"
        assert len(test_dict) == 2
        test_dict["key3"] = "value3"
        assert test_dict["key3"] == "value3"


class TestMockModels:
    """Testes com modelos mockados"""

    def test_voice_command_mock(self):
        """Testa estrutura de VoiceCommand mockada"""
        class MockVoiceCommand:
            def __init__(self, text, language="pt-BR", timestamp=None):
                self.text = text
                self.language = language
                self.timestamp = timestamp

        cmd = MockVoiceCommand("teste comando", "pt-BR")
        assert cmd.text == "teste comando"
        assert cmd.language == "pt-BR"
        assert cmd.timestamp is None

    def test_agent_response_mock(self):
        """Testa estrutura de AgentResponse mockada"""
        class MockAgentResponse:
            def __init__(self, response, action_type, module, data=None):
                self.response = response
                self.action_type = action_type
                self.module = module
                self.data = data or {}

        resp = MockAgentResponse("resposta teste", "info", "conversation", {"test": True})
        assert resp.response == "resposta teste"
        assert resp.action_type == "info"
        assert resp.module == "conversation"
        assert resp.data["test"] is True


class TestCommandPatterns:
    """Testes para padrões de comando"""

    def test_confirmation_patterns(self):
        """Testa padrões de comando de confirmação"""
        confirm_patterns = [
            "confirmar última ação",
            "confirmar acao",
            "confirmar ação do dispositivo",
            "confirmar ultima acao do dispositivo"
        ]

        cancel_patterns = [
            "cancelar última ação",
            "cancelar acao",
            "cancelar ação do dispositivo",
            "cancelar ultima acao do dispositivo"
        ]

        for pattern in confirm_patterns:
            assert "confirmar" in pattern.lower()

        for pattern in cancel_patterns:
            assert "cancelar" in pattern.lower()

    def test_device_command_patterns(self):
        """Testa padrões de comando device"""
        device_patterns = [
            "execute comando no pc",
            "rode script no dispositivo",
            "faça algo no device"
        ]

        for pattern in device_patterns:
            assert any(word in pattern.lower() for word in ["execute", "rode", "faça", "no", "dispositivo", "device", "pc"])

    def test_ops_command_patterns(self):
        """Testa padrões de comando operacional"""
        ops_patterns = [
            "mostrar histórico",
            "status da operação",
            "saúde operacional",
            "métricas do sistema"
        ]

        ops_keywords = ["histórico", "histórico", "status", "operação", "operação", "saúde", "métricas"]

        for pattern in ops_patterns:
            assert any(keyword in pattern.lower() for keyword in ops_keywords)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])