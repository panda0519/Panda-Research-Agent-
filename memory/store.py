"""Local vector store backed by Voyage AI embeddings and local file storage."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import numpy as np

logger = logging.getLogger(__name__)

VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings"
DEFAULT_STORE_PATH = "memory/vector_index.json"


class VoyageEmbeddingClient:
    def __init__(self, api_key: Optional[str] = None, model: str = "voyage-3-lite") -> None:
        self._api_key = api_key
        self.model = model

    @property
    def api_key(self) -> str:
        return self._api_key or os.environ.get("VOYAGE_API_KEY", "")


    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not self.api_key:
            logger.warning("VOYAGE_API_KEY not set; using deterministic mock embeddings for testing.")
            # Deterministic pseudo-embedding for testing/fallback
            return [self._mock_embed(t) for t in texts]

        try:
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            payload = {"input": texts, "model": self.model}
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(VOYAGE_API_URL, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return [item["embedding"] for item in data.get("data", [])]
        except Exception as exc:
            logger.error("Voyage AI embedding failed: %s", exc)
            return [self._mock_embed(t) for t in texts]

    def _mock_embed(self, text: str, dim: int = 512) -> List[float]:
        # Bag-of-words pseudo-embedding for testing/offline mode
        import hashlib
        import re
        vec = np.zeros(dim, dtype=float)
        words = re.findall(r"\w+", text.lower())
        for w in words:
            h_val = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16)
            idx = h_val % dim
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()



class VectorMemoryStore:
    def __init__(
        self,
        store_path: str = DEFAULT_STORE_PATH,
        embedding_client: Optional[VoyageEmbeddingClient] = None,
    ) -> None:
        self.store_path = Path(store_path)
        self.client = embedding_client or VoyageEmbeddingClient()
        self.entries: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.store_path.exists():
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    self.entries = json.load(f)
            except Exception as e:
                logger.warning("Could not read vector store from %s: %s", self.store_path, e)
                self.entries = []

    def _save(self) -> None:
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, indent=2)

    def add_run_digest(
        self,
        run_id: str,
        topic: str,
        digest: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Embeds and saves a run digest with reference to SQLite run_id."""
        embeddings = self.client.embed_texts([f"{topic}\n{digest}"])
        if not embeddings:
            return

        entry = {
            "run_id": run_id,
            "topic": topic,
            "digest": digest,
            "metadata": metadata or {},
            "embedding": embeddings[0],
        }
        # Replace if existing run_id exists
        self.entries = [e for e in self.entries if e.get("run_id") != run_id]
        self.entries.append(entry)
        self._save()

    def search_similar(
        self, query: str, top_k: int = 3, min_similarity: float = 0.1
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Queries store and returns top-k matching run digests with cosine similarity."""
        if not self.entries:
            return []

        embeddings = self.client.embed_texts([query])
        if not embeddings:
            return []

        query_vec = np.array(embeddings[0])
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []

        scored: List[Tuple[Dict[str, Any], float]] = []
        for entry in self.entries:
            vec = np.array(entry["embedding"])
            # Dimension Guard: skip incompatible embeddings from stale indices
            if len(vec) != len(query_vec):
                logger.warning("Skipping incompatible embedding of dimension %d (expected %d)", len(vec), len(query_vec))
                continue
            
            vec_norm = np.linalg.norm(vec)
            if vec_norm == 0:
                continue
            sim = float(np.dot(query_vec, vec) / (query_norm * vec_norm))
            if sim >= min_similarity:
                scored.append((entry, round(sim, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
