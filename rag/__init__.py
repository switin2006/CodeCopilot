"""
RAG (Retrieval-Augmented Generation) package for CodeCopilot.

Provides semantic search over a local codebase using:
  - sentence-transformers (local embedding model, no API key needed)
  - ChromaDB (local persistent vector store)

Usage:
    from rag import CodebaseIndexer

    indexer = CodebaseIndexer()
    indexer.index(".")              # index the project
    results = indexer.search("JWT token validation", n_results=5)
"""

from .indexer import CodebaseIndexer
from .chunker import chunk_file, chunk_directory
from .embedder import Embedder

__all__ = ["CodebaseIndexer", "chunk_file", "chunk_directory", "Embedder"]
