"""BM25 and dense retrieval with reciprocal rank fusion and optional Cohere reranking."""

from collections import defaultdict
from collections.abc import Mapping
from contextlib import contextmanager
from hashlib import sha256
from itertools import batched
import os
from pathlib import Path

import bm25s
import chromadb
from cohere import ClientV2
from filelock import FileLock
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings


TOKEN_OPTIONS = {"stopwords": "en", "token_pattern": r"(?u)\b\w+\b", "show_progress": False}
BRANCH_CANDIDATES = 50
FUSED_CANDIDATES = 20
RERANK_MODEL = "rerank-v5.0-pro"
EMBEDDING_MODEL = "text-embedding-3-large"


@contextmanager
def open_collection(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    # The local server and CLI may open the same embedded database.
    with FileLock(str(directory / "chroma.lock")), chromadb.PersistentClient(path=str(directory)) as client:
        yield client.get_or_create_collection(
            name=f"passages-{EMBEDDING_MODEL}-v1",
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )


def reciprocal_rank_fusion(*rankings: Mapping[str, int], k: int = 60) -> list[tuple[str, float]]:
    """Take one {passage_id: one-based rank} mapping per retriever and return (id, score) pairs."""
    if k < 0:
        raise ValueError("The RRF smoothing constant must be nonnegative.")

    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for passage_id, rank in ranking.items():
            if rank < 1:
                raise ValueError("Passage ranks start at 1.")
            scores[passage_id] += 1 / (k + rank)

    # Break equal scores by passage ID so the result has a stable order.
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def redundant(hit: Document, previous: Document) -> bool:
    """Collapse heavily overlapping chunks only within the same source and page."""
    a, b = hit.metadata, previous.metadata
    if (a["source_id"], a["page"]) != (b["source_id"], b["page"]):
        return False
    x, y = hit.page_content, previous.page_content
    if x == y:
        return True
    start, prior_start = a.get("start_index", -1), b.get("start_index", -1)
    if min(start, prior_start) < 0 or start + len(x) <= prior_start or prior_start + len(y) <= start:
        return False
    first, second = x.split(), y.split()
    shorter = min(len(first), len(second))
    for size in range(shorter, max(4, (shorter * 3 + 3) // 4) - 1, -1):
        if first[-size:] == second[:size] or second[-size:] == first[:size]:
            return True
    return False


def rerank(question: str, candidates: list[Document], client: ClientV2, top_n: int) -> list[Document]:
    """Map Cohere's ranked indices back to the original documents and their citations."""
    if top_n < 1 or not question.strip():
        raise ValueError("Enter a question and a positive number of results.")
    if not candidates:
        return []
    response = client.rerank(
        model=RERANK_MODEL,
        query=question,
        documents=[doc.page_content for doc in candidates],
        top_n=min(top_n, len(candidates)),
    )
    return [candidates[row.index] for row in response.results]


class HybridIndex:
    def __init__(self, documents: list[Document], embeddings: Embeddings):
        self.documents = documents
        self.embeddings = embeddings
        directory = os.getenv("RAG_CHROMA_DIR") or os.getenv("FOLIO_CHROMA_DIR") or "data/chroma"
        self.directory = Path(directory).expanduser().resolve()
        # Browser upload IDs change on re-upload. Content and position survive a restart.
        self.chunk_ids = [
            sha256(f"{doc.metadata['page']}:{doc.metadata.get('start_index', -1)}:{doc.page_content}".encode()).hexdigest()
            for doc in documents
        ]
        self.bm25 = None
        if documents:
            self.index_passages()
            tokens = bm25s.tokenize([doc.page_content for doc in documents], **TOKEN_OPTIONS)
            if tokens.vocab:
                self.bm25 = bm25s.BM25(method="lucene", csc_backend="auto")
                self.bm25.index(tokens, show_progress=False)

    def index_passages(self):
        records = dict(zip(self.chunk_ids, self.documents, strict=True))
        with open_collection(self.directory) as collection:
            for batch in batched(records, 64):
                existing = set(collection.get(ids=list(batch), include=[])["ids"])
                missing = [key for key in batch if key not in existing]
                if missing:
                    texts = [records[key].page_content for key in missing]
                    collection.upsert(ids=missing, documents=texts, embeddings=self.embeddings.embed_documents(texts))

    def vector_ranks(self, query: str, limit: int) -> dict[str, int]:
        # Query only current chunks. Resolve citations from this workspace's documents.
        active_ids = list(dict.fromkeys(self.chunk_ids))
        embedding = self.embeddings.embed_query(query)
        with open_collection(self.directory) as collection:
            result = collection.query(
                ids=active_ids, query_embeddings=[embedding], n_results=min(limit, len(active_ids)), include=[]
            )
        ranks = {key: rank for rank, key in enumerate(result["ids"][0], 1)}
        return {str(i): ranks[key] for i, key in enumerate(self.chunk_ids) if key in ranks}

    def keyword_ranks(self, query: str, limit: int) -> dict[str, int]:
        tokens = bm25s.tokenize([query], return_ids=False, **TOKEN_OPTIONS)[0]
        if self.bm25 is None or not any(t in self.bm25.vocab_dict for t in tokens):
            return {}
        positions, scores = self.bm25.retrieve([tokens], k=limit, show_progress=False)
        return {
            str(pos): rank
            for rank, (pos, score) in enumerate(zip(positions[0], scores[0], strict=True), 1)
            if score > 0
        }

    def search(self, query: str, *, reranker: ClientV2 | None = None, limit: int = 4) -> list[Document]:
        if not 1 <= limit <= FUSED_CANDIDATES:
            raise ValueError(f"Choose between 1 and {FUSED_CANDIDATES} results.")
        if not self.documents or not query.strip():
            return []
        count = min(BRANCH_CANDIDATES, len(self.documents))
        keyword = self.keyword_ranks(query, count)
        vector = self.vector_ranks(query, count)
        selected = []
        for passage_id, _score in reciprocal_rank_fusion(keyword, vector):
            doc = self.documents[int(passage_id)]
            if not any(redundant(doc, prior) for prior in selected):
                selected.append(doc)
                if len(selected) == FUSED_CANDIDATES:
                    break
        if reranker is not None:
            return rerank(query, selected, reranker, limit)
        return selected[:limit]
