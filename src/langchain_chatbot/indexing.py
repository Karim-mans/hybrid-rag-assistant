from functools import lru_cache
from typing import TYPE_CHECKING

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

if TYPE_CHECKING:
    from .hybrid_search import HybridIndex


# Each row holds the source ID, filename, page number (0 for plain text), and text.
Page = tuple[str, str, int, str]


@lru_cache(maxsize=4)
def split_pages(pages: tuple[Page, ...]) -> list[Document]:
    documents = [
        Document(page_content=text, metadata={"source_id": source_id, "source": name, "page": page})
        for source_id, name, page, text in pages
    ]
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200, add_start_index=True)
    return splitter.split_documents(documents)


@lru_cache(maxsize=4)
def build_index(pages: tuple[Page, ...]) -> "HybridIndex":
    from .hybrid_search import EMBEDDING_MODEL, HybridIndex

    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    return HybridIndex(split_pages(pages), embeddings)
