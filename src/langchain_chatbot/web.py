"""Local HTTP interface for Hybrid RAG Assistant."""

import argparse
import json
import math
import mimetypes
import os
import re
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dotenv import load_dotenv

from .filereader import read_pdf_pages
from .indexing import Page, split_pages


STATIC = Path(__file__).with_name("static")
MAX_FILE = 10 * 1024 * 1024
MAX_TEXT = 2_000_000
STOP_WORDS = set("a an and are as at be by can did do does for from how in into is it me of on or that the these this to was what when where which who why with would".split())


def read_upload(name: str, data: bytes) -> list[str]:
    suffix = Path(name).suffix.lower()
    if suffix == ".pdf":
        try:
            pages = read_pdf_pages(BytesIO(data))
        except Exception as exc:
            raise ValueError("This PDF could not be read. Try an unlocked, text-based PDF.") from exc
    elif suffix in {".md", ".txt"}:
        try:
            pages = [data.decode("utf-8-sig")]
        except UnicodeDecodeError as exc:
            raise ValueError("Save the text file in UTF-8 and try again.") from exc
    else:
        raise ValueError("Choose a PDF, TXT, or Markdown file.")
    if not any(p.strip() for p in pages):
        raise ValueError("No readable text was found. Scanned PDFs need text recognition first.")
    if sum(map(len, pages)) > MAX_TEXT:
        raise ValueError("This file contains too much text. Try a shorter document.")
    return pages


def checked_pages(sources: list) -> tuple[Page, ...]:
    if not isinstance(sources, list) or not 1 <= len(sources) <= 12:
        raise ValueError("Choose between 1 and 12 sources.")
    result = []
    total = 0
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Invalid source.")
        key, name, pages = source.get("id"), source.get("name"), source.get("pages")
        if not isinstance(key, str) or not isinstance(name, str) or not isinstance(pages, list):
            raise ValueError("Invalid source.")
        pdf = name.lower().endswith(".pdf")
        for number, value in enumerate(pages, 1):
            if not isinstance(value, str):
                raise ValueError("Invalid page.")
            total += len(value)
            if total > MAX_TEXT:
                raise ValueError("This workspace is full. Remove a source and try again.")
            if value.strip():
                result.append((key, name, number if pdf else 0, value))
    if not result:
        raise ValueError("Add a source with readable text first.")
    return tuple(result)


def terms(text: str) -> list[str]:
    words = re.findall(r"[^\W_]+", text.casefold())
    return [w.removesuffix("s") if len(w) > 4 else w for w in words if len(w) > 1 and w not in STOP_WORDS]


def search_passages(pages: tuple[Page, ...], question: str) -> dict:
    chunks = split_pages(pages)
    query = set(terms(question))
    counts = [Counter(terms(doc.page_content)) for doc in chunks]
    weights = {term: math.log(1 + len(chunks) / (1 + sum(term in c for c in counts))) for term in query}
    scores = [
        sum(weights[t] * c[t] / (c[t] + 1) for t in query) / (1 + math.log1p(sum(c.values())) / 6)
        for c in counts
    ]
    ranked = sorted(range(len(chunks)), key=scores.__getitem__, reverse=True)
    matches = [chunks[i] for i in ranked if scores[i] > 0][:4]
    passages = [dict(id=d.metadata["source_id"], name=d.metadata["source"], page=d.metadata["page"], text=d.page_content) for d in matches]
    if passages:
        answer = "These passages match your search terms."
    else:
        answer = "No passages matched those words. Try a name or phrase from the source."
    return {"text": answer, "passages": passages}


class Handler(BaseHTTPRequestHandler):
    def send_content(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(content)

    def reply(self, status, data):
        self.send_content(status, json.dumps(data).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/config":
            return self.reply(200, {"agentAvailable": bool(os.getenv("OPENAI_API_KEY"))})
        name = path.lstrip("/") or "index.html"
        if name not in {"index.html", "app.js", "style.css", "landscape.js", "sample.md", "favicon.svg"}:
            return self.reply(404, {"error": "Page not found."})
        file = STATIC / name
        self.send_content(200, file.read_bytes(), mimetypes.guess_type(file.name)[0] or "text/plain")

    def do_POST(self):
        target = urlsplit(self.path)
        # A custom header plus same-origin requests keeps other sites out of the local API.
        origin = self.headers.get("Origin")
        if self.headers.get("X-Folio") != "workspace" or (origin and urlsplit(origin).netloc != self.headers.get("Host")):
            return self.reply(403, {"error": "Open the app locally to use this workspace."})
        try:
            size = int(self.headers.get("Content-Length", 0))
            limit = MAX_FILE if target.path == "/api/read" else 16 * 1024 * 1024
            if size <= 0 or size > limit:
                return self.reply(413, {"error": "The request is empty or too large."})
            body = self.rfile.read(size)
            if target.path == "/api/read":
                name = parse_qs(target.query).get("name", [""])[0]
                return self.reply(200, {"pages": read_upload(name, body)})
            if target.path != "/api/ask":
                return self.reply(404, {"error": "Unknown action."})
            request = json.loads(body)
            if not isinstance(request, dict):
                raise ValueError("Invalid request.")
            pages = checked_pages(request.get("sources"))
            question = request.get("question")
            if not isinstance(question, str) or not 1 <= len(question.strip()) <= 6000:
                raise ValueError("Enter a question of up to 6,000 characters.")
            if request.get("mode") == "search":
                return self.reply(200, search_passages(pages, question))
            if request.get("mode") != "agent":
                raise ValueError("Choose a valid answer mode.")
            if not os.getenv("OPENAI_API_KEY"):
                raise ValueError("Set OPENAI_API_KEY in .env and restart the server to use Agent chat.")
            from .agent import ask_agent
            history = request.get("history", [])
            if not isinstance(history, list) or any(
                not isinstance(m, dict) or m.get("role") not in {"user", "assistant"} or not isinstance(m.get("text"), str)
                for m in history
            ):
                raise ValueError("Invalid conversation history.")
            self.reply(200, ask_agent(pages, question, history[-16:]))
        except (ValueError, UnicodeError) as exc:
            self.reply(400, {"error": str(exc)})
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            reason = {
                401: "The model provider rejected the API key.",
                403: "The API key does not have access to the selected model.",
                404: "The selected model is unavailable. Check RAG_CHAT_MODEL in .env.",
                429: "The model provider's rate or quota limit was reached.",
            }.get(status, "The model request could not finish. Check your connection and model settings.")
            self.reply(HTTPStatus.BAD_GATEWAY, {"error": f"{reason} You can also use Passage search."})


def main():
    parser = argparse.ArgumentParser(description="Start Hybrid RAG Assistant locally.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    load_dotenv()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"Hybrid RAG Assistant is ready at http://127.0.0.1:{server.server_port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
