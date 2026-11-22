import os
from uuid import uuid4

from cohere import ClientV2
from deepagents.backends import StateBackend
from langchain.tools import tool
from langchain_core.documents import Document

from .hybrid_search import HybridIndex


def make_search_tool(store: HybridIndex, backend: StateBackend, passages: dict):
    key = os.getenv("COHERE_API_KEY")
    reranker = ClientV2(api_key=key) if key else None

    @tool
    def search_documents(query: str) -> str:
        """Search the workspace documents for relevant passages and return their file paths."""
        matches = store.search(query, reranker=reranker, limit=4)
        batch = uuid4().hex
        uploads = []
        for index, doc in enumerate(matches):
            path = f"/retrieved/{batch}/chunk_{index}.md"
            label = doc.metadata["source"]
            if doc.metadata["page"]:
                label += f", page {doc.metadata['page']}"
            content = f"# Source: {label}\n\n{doc.page_content}"
            uploads.append((path, content.encode("utf-8")))

        if not uploads:
            return "No matching passages."
        results = backend.upload_files(uploads)
        paths = []
        for doc, result in zip(matches, results, strict=True):
            if not result.error:
                paths.append(result.path)
                passages.setdefault((doc.metadata["source_id"], doc.metadata["page"], doc.page_content), doc)
        return "\n".join(paths) or "Retrieved passages could not be saved for analysis."

    return search_documents


def passage_info(doc: Document) -> dict:
    return {
        "id": doc.metadata["source_id"],
        "name": doc.metadata["source"],
        "page": doc.metadata["page"],
        "text": doc.page_content,
    }
