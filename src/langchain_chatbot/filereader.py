from pathlib import Path
from typing import BinaryIO, List
from langchain_core.documents import Document
from pypdf import PdfReader


def read_pdf_pages(source: str | Path | BinaryIO) -> list[str]:
    """Extract pages in order so the UI can preserve PDF page numbers."""
    return [page.extract_text() or "" for page in PdfReader(source).pages]


def read_pdf_text(pdf_path: str | Path) -> str:
    """Read and return the text in a pdf file"""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"pdf not found: {path}")

    return "\n".join(read_pdf_pages(path))

def read_multiple_pdfs(pdf_paths: List[str|Path]) -> List[Document]:
    """Read text from multiple pdf files and return a list of documents"""
    docs: List[Document] = []

    for path in pdf_paths:
        path_obj = Path(path)
        text = read_pdf_text(path_obj)
        docs.append(Document(page_content=text, metadata={"source": str(path_obj)}))

    return docs
