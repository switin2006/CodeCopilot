"""
ChromaDB-based vector store for codebase indexing and semantic search.

Architecture:
    CodebaseIndexer
        ├── ChromaDB persistent client  (.chroma/ directory)
        ├── Embedder (sentence-transformers, local)
        └── Chunker (AST-aware for Python, window for others)

The collection stores:
    documents   = chunk content text
    metadatas   = {file_path, start_line, end_line, language, symbol}
    ids         = unique string IDs per chunk (hash-based)
    embeddings  = computed by Embedder (not ChromaDB's built-in embedder)
"""

import os
import json
import hashlib
import time
from typing import Optional
from .chunker import chunk_directory, chunk_file
from .embedder import Embedder


# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------
_DEFAULT_CHROMA_DIR   = ".chroma"
_COLLECTION_NAME      = "codebase"
_DEFAULT_N_RESULTS    = 5
_INDEX_BATCH_SIZE     = 50    # chunks per ChromaDB upsert batch
_MIN_CHUNK_LEN        = 30    # chars — skip tiny chunks


def _chunk_id(chunk: dict) -> str:
    """Deterministic ID for a chunk based on its file path and line range."""
    key = f"{chunk['file_path']}:{chunk['start_line']}:{chunk['end_line']}"
    return hashlib.md5(key.encode()).hexdigest()


class CodebaseIndexer:
    """
    Manages indexing and searching a codebase using ChromaDB + sentence-transformers.

    Args:
        chroma_dir: Directory for ChromaDB persistence (default: '.chroma').
        embed_model: sentence-transformers model name.
    """

    def __init__(
        self,
        chroma_dir: str = _DEFAULT_CHROMA_DIR,
        embed_model: str = "all-MiniLM-L6-v2",
    ):
        self.chroma_dir  = chroma_dir
        self.embedder    = Embedder(model_name=embed_model)
        self._client     = None
        self._collection = None

    # ------------------------------------------------------------------
    # INTERNAL: ChromaDB client (lazy)
    # ------------------------------------------------------------------

    def _get_collection(self):
        """Lazy-init ChromaDB client and collection."""
        if self._collection is not None:
            return self._collection

        try:
            import chromadb   # type: ignore
        except ImportError:
            raise ImportError(
                "chromadb is not installed. Run: pip install chromadb"
            )

        self._client = chromadb.PersistentClient(path=self.chroma_dir)
        self._collection = self._client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},   # cosine similarity
        )
        return self._collection

    # ------------------------------------------------------------------
    # INDEXING
    # ------------------------------------------------------------------

    def index(
        self,
        directory: str = ".",
        force: bool = False,
    ) -> dict:
        """
        Index all code files in a directory.

        Args:
            directory: Root directory to walk (default: current dir).
            force:     If True, clears existing index before re-indexing.

        Returns:
            Stats dict: {files_indexed, chunks_added, chunks_skipped, duration_sec}
        """
        collection = self._get_collection()
        start_time = time.time()

        if force:
            # Clear existing data
            try:
                self._client.delete_collection(_COLLECTION_NAME)
                self._collection = self._client.get_or_create_collection(
                    name=_COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
                collection = self._collection
            except Exception:
                pass

        # Get existing IDs to support incremental indexing
        existing_ids: set = set()
        try:
            existing = collection.get(include=[])
            existing_ids = set(existing.get("ids", []))
        except Exception:
            pass

        files_seen    = set()
        chunks_added  = 0
        chunks_skip   = 0

        batch_ids        = []
        batch_docs       = []
        batch_metas      = []
        batch_embeddings = []

        def _flush():
            nonlocal chunks_added
            if not batch_ids:
                return
            collection.upsert(
                ids=batch_ids[:],
                documents=batch_docs[:],
                metadatas=batch_metas[:],
                embeddings=batch_embeddings[:],
            )
            chunks_added += len(batch_ids)
            batch_ids.clear()
            batch_docs.clear()
            batch_metas.clear()
            batch_embeddings.clear()

        for chunk in chunk_directory(directory):
            # Skip tiny chunks
            if len(chunk["content"]) < _MIN_CHUNK_LEN:
                chunks_skip += 1
                continue

            chunk_id = _chunk_id(chunk)
            files_seen.add(chunk["file_path"])

            # Skip if already indexed (incremental mode)
            if not force and chunk_id in existing_ids:
                chunks_skip += 1
                continue

            # Embed
            embedding = self.embedder.embed_one(chunk["content"])
            if not embedding:
                chunks_skip += 1
                continue

            batch_ids.append(chunk_id)
            batch_docs.append(chunk["content"])
            batch_metas.append({
                "file_path":  chunk["file_path"],
                "start_line": chunk["start_line"],
                "end_line":   chunk["end_line"],
                "language":   chunk["language"],
                "symbol":     chunk.get("symbol", ""),
            })
            batch_embeddings.append(embedding)

            if len(batch_ids) >= _INDEX_BATCH_SIZE:
                _flush()

        _flush()  # flush remaining

        return {
            "files_indexed":  len(files_seen),
            "chunks_added":   chunks_added,
            "chunks_skipped": chunks_skip,
            "duration_sec":   round(time.time() - start_time, 1),
            "collection_size": collection.count(),
        }

    def index_file(self, file_path: str, root: str = ".") -> int:
        """Index (or re-index) a single file. Returns number of chunks added."""
        collection = self._get_collection()
        chunks_added = 0
        for chunk in chunk_file(file_path, root=root):
            if len(chunk["content"]) < _MIN_CHUNK_LEN:
                continue
            embedding = self.embedder.embed_one(chunk["content"])
            if not embedding:
                continue
            chunk_id = _chunk_id(chunk)
            collection.upsert(
                ids=[chunk_id],
                documents=[chunk["content"]],
                metadatas=[{
                    "file_path":  chunk["file_path"],
                    "start_line": chunk["start_line"],
                    "end_line":   chunk["end_line"],
                    "language":   chunk["language"],
                    "symbol":     chunk.get("symbol", ""),
                }],
                embeddings=[embedding],
            )
            chunks_added += 1
        return chunks_added

    # ------------------------------------------------------------------
    # SEARCHING
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        n_results: int = _DEFAULT_N_RESULTS,
        language_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Semantic search over the indexed codebase.

        Args:
            query:           Natural language or code query string.
            n_results:       Number of top results to return.
            language_filter: Optionally restrict to one language (e.g., 'python').

        Returns:
            List of result dicts:
            {
              "rank":       int,
              "file_path":  str,
              "start_line": int,
              "end_line":   int,
              "language":   str,
              "symbol":     str,
              "score":      float,   # cosine similarity (higher = more relevant)
              "snippet":    str,     # first 300 chars of the chunk
            }
        """
        collection = self._get_collection()

        if not query or not query.strip():
            return []

        if collection.count() == 0:
            return []

        query_embedding = self.embedder.embed_one(query)
        if not query_embedding:
            return []

        where_filter = {"language": language_filter} if language_filter else None

        try:
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=min(n_results, collection.count()),
                where=where_filter if where_filter else None,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            return []

        hits = []
        docs      = results.get("documents", [[]])[0]
        metas     = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for rank, (doc, meta, dist) in enumerate(zip(docs, metas, distances), 1):
            # ChromaDB with cosine space returns distance (0=identical, 2=opposite)
            # Convert to similarity score [0, 1]
            score = round(1 - (dist / 2), 4)
            hits.append({
                "rank":       rank,
                "file_path":  meta.get("file_path", "?"),
                "start_line": meta.get("start_line", 0),
                "end_line":   meta.get("end_line", 0),
                "language":   meta.get("language", ""),
                "symbol":     meta.get("symbol", ""),
                "score":      score,
                "snippet":    doc[:300] + ("..." if len(doc) > 300 else ""),
            })

        return hits

    # ------------------------------------------------------------------
    # UTILITIES
    # ------------------------------------------------------------------

    def is_indexed(self) -> bool:
        """Returns True if the collection has at least one chunk."""
        try:
            return self._get_collection().count() > 0
        except Exception:
            return False

    def stats(self) -> dict:
        """Returns basic stats about the current index."""
        try:
            col = self._get_collection()
            return {
                "total_chunks": col.count(),
                "chroma_dir":   self.chroma_dir,
                "embed_model":  self.embedder.model_name,
            }
        except Exception:
            return {"total_chunks": 0, "chroma_dir": self.chroma_dir}

    def clear(self) -> None:
        """Wipe the entire index."""
        try:
            col = self._get_collection()
            # Delete all by getting all IDs
            existing = col.get(include=[])
            ids = existing.get("ids", [])
            if ids:
                col.delete(ids=ids)
        except Exception:
            pass
