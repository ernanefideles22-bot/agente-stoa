"""
stoa_memory.py — Memória vetorial persistente para o Agente STOA
"""
import uuid
from datetime import datetime
from typing import Optional
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

EMBED_MODEL = "all-MiniLM-L6-v2"
DB_PATH = "./stoa_memory_db"
TOP_K = 5


class StoaMemory:
    FACT_PATTERNS = [
        r"meu projeto (se chama|é|usa|chama-se)",
        r"eu (prefiro|uso|trabalho com|gosto de)",
        r"o projeto (usa|é|tem|se chama)",
        r"minha (empresa|stack|linguagem|ferramenta)",
        r"sempre (use|faça|responda)",
        r"nunca (use|faça|responda)",
    ]

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self.embedder = SentenceTransformer(EMBED_MODEL)
        self.client = chromadb.PersistentClient(
            path=DB_PATH,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collections = {
            cat: self.client.get_or_create_collection(
                name=f"stoa_{cat}_{user_id}",
                metadata={"hnsw:space": "cosine"},
            )
            for cat in ("episodic", "semantic", "project")
        }

    def save(self, text: str, category: str = "episodic", metadata: Optional[dict] = None) -> str:
        if category not in self.collections:
            raise ValueError(f"Categoria inválida: {category}")
        mem_id = str(uuid.uuid4())
        embedding = self.embedder.encode(text).tolist()
        meta = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": self.user_id,
            "category": category,
            **(metadata or {}),
        }
        self.collections[category].add(
            ids=[mem_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[meta],
        )
        return mem_id

    def search(self, query: str, categories: Optional[list] = None, top_k: int = TOP_K) -> list[dict]:
        cats = categories or list(self.collections.keys())
        embedding = self.embedder.encode(query).tolist()
        results = []
        for cat in cats:
            col = self.collections.get(cat)
            if col is None or col.count() == 0:
                continue
            k = min(top_k, col.count())
            res = col.query(query_embeddings=[embedding], n_results=k)
            for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
                results.append({
                    "text": doc,
                    "category": cat,
                    "relevance": round(1 - dist, 4),
                    "timestamp": meta.get("timestamp"),
                    "meta": meta,
                })
        results.sort(key=lambda x: x["relevance"], reverse=True)
        return results[:top_k]

    def build_context_block(self, query: str, top_k: int = TOP_K) -> str:
        memories = self.search(query, top_k=top_k)
        if not memories:
            return ""
        lines = ["<memory_context>"]
        for m in memories:
            ts = m["timestamp"][:10] if m["timestamp"] else "?"
            lines.append(
                f'  <memory category="{m["category"]}" date="{ts}" '
                f'relevance="{m["relevance"]}">{m["text"]}</memory>'
            )
        lines.append("</memory_context>")
        return "\n".join(lines)

    def learn_from_turn(self, user_msg: str, assistant_msg: str, project: Optional[str] = None):
        text = f"Usuário: {user_msg}\nAgente: {assistant_msg}"
        self.save(text, category="episodic")
        if project:
            self.save(f"[{project}] {user_msg}", category="project", metadata={"project": project})

    def save_fact(self, fact: str, project: Optional[str] = None):
        meta = {"project": project} if project else {}
        self.save(fact, category="semantic", metadata=meta)

    def extract_and_save_facts(self, user_msg: str, project: Optional[str] = None) -> list[str]:
        """
        Detecta frases de fato na mensagem do usuário e salva como memória semântica.
        Retorna lista de fatos salvos.
        """
        import re
        saved = []
        for pattern in self.FACT_PATTERNS:
            if re.search(pattern, user_msg, re.IGNORECASE):
                self.save_fact(user_msg.strip(), project=project)
                saved.append(user_msg.strip())
                break
        return saved

    def stats(self) -> dict:
        return {cat: col.count() for cat, col in self.collections.items()}
