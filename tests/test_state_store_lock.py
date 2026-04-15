"""
Testes para StateStore com lock
"""

import pytest
import tempfile
import time
from pathlib import Path
from state_store import StateStore


class TestStateStoreLock:
    """Testes para mecanismo de lock do StateStore"""

    @pytest.fixture
    def temp_db(self):
        """Cria banco temporário para testes"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test.db"
            yield str(db_path)

    def test_lock_acquire_release(self, temp_db):
        """Testa adquirir e liberar lock"""
        store = StateStore(temp_db)
        assert store._acquire_lock() is True
        store._release_lock()
        # Arquivo de lock deve ser removido
        assert not store.lock_path.exists()

    def test_lock_timeout(self, temp_db):
        """Testa timeout do lock"""
        store1 = StateStore(temp_db)
        store2 = StateStore(temp_db)

        # Store1 adquire lock
        assert store1._acquire_lock() is True

        # Store2 deve falhar após timeout
        start_time = time.time()
        result = store2._acquire_lock()
        elapsed = time.time() - start_time

        assert result is False
        assert elapsed >= store2.lock_timeout * 0.8  # Pelo menos 80% do timeout

        # Liberar lock
        store1._release_lock()

    def test_save_with_lock(self, temp_db):
        """Testa salvar dados com lock"""
        store = StateStore(temp_db)
        test_data = {"test": "value", "number": 42}

        # Deve funcionar sem erro
        store.save_pending_preview(test_data)

        # Verificar se foi salvo
        loaded = store.load_pending_preview()
        assert loaded == test_data

    def test_concurrent_access_simulation(self, temp_db):
        """Simula acesso concorrente"""
        store = StateStore(temp_db)

        # Primeiro acesso
        store.save_pending_preview({"first": "access"})

        # Simular que lock está ocupado (criar arquivo manualmente)
        store.lock_path.touch()

        # Segundo acesso deve falhar
        with pytest.raises(RuntimeError, match="Não foi possível adquirir lock"):
            store._with_lock(lambda: store.save_pending_preview({"second": "access"}))

        # Após liberar lock, deve funcionar
        store._release_lock()
        store.save_pending_preview({"third": "access"})
        loaded = store.load_pending_preview()
        assert loaded == {"third": "access"}

    def test_lock_file_cleanup(self, temp_db):
        """Testa limpeza do arquivo de lock"""
        store = StateStore(temp_db)

        # Criar lock
        assert store._acquire_lock() is True
        assert store.lock_path.exists()

        # Liberar
        store._release_lock()
        assert not store.lock_path.exists()

        # Mesmo se houver erro, deve tentar liberar
        assert store._acquire_lock() is True
        store._release_lock()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])