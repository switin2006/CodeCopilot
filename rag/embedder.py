"""
Local embedding model wrapper using sentence-transformers.

Model: all-MiniLM-L6-v2
  - Size:      ~22 MB
  - Dimension: 384 floats
  - Speed:     ~14k sentences/sec on CPU
  - Quality:   Strong for code semantic similarity
  - Cost:      FREE — runs 100% locally, no API key

The model is lazy-loaded on first use and cached in memory for the session.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

_MODEL_CACHE: dict = {}   # module-level cache so model loads once per process


class Embedder:
    """
    Thin wrapper around sentence-transformers SentenceTransformer.

    Usage:
        emb = Embedder()
        vectors = emb.embed(["def foo():", "import os"])
        single  = emb.embed_one("JWT authentication")
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    def _load(self):
        """Lazy-load the model on first call."""
        if self.model_name in _MODEL_CACHE:
            self._model = _MODEL_CACHE[self.model_name]
            return

        try:
            from sentence_transformers import SentenceTransformer   # type: ignore
        except ImportError:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            )

        self._model = SentenceTransformer(self.model_name)
        _MODEL_CACHE[self.model_name] = self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of strings.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (each is a list of 384 floats).
        """
        if not texts:
            return []
        self._load()
        vectors = self._model.encode(
            texts,
            batch_size=64,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return vectors.tolist()

    def embed_one(self, text: str) -> list[float]:
        """Embed a single string. Returns a flat list of floats."""
        result = self.embed([text])
        return result[0] if result else []

    @property
    def dimension(self) -> int:
        """Return the embedding dimension (384 for MiniLM)."""
        self._load()
        return self._model.get_sentence_embedding_dimension()
