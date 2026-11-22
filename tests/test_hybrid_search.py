import json
import os
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from cohere import ClientV2
from langchain_core.embeddings import Embeddings

from langchain_chatbot.hybrid_search import HybridIndex
from langchain_chatbot.indexing import split_pages
from langchain_chatbot.tools import make_search_tool


class HybridSearchTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.enterContext(patch.dict(os.environ, {"RAG_CHROMA_DIR": directory}))
        pages = tuple(
            ("report", "report.pdf", page, "needle" if page == 55 else f"Entry {page}")
            for page in range(1, 56)
        )
        self.docs = split_pages(pages)
        embeddings = Mock(spec=Embeddings)
        embeddings.embed_documents.return_value = [[1, page] for page in range(1, 56)]
        embeddings.embed_query.return_value = [1, 0]
        self.index = HybridIndex(self.docs, embeddings)

    def test_fusion_can_recover_a_passage_outside_the_dense_candidates(self):
        ranks = self.index.vector_ranks("needle", limit=50)
        dense = [self.docs[int(i)] for i in sorted(ranks, key=ranks.get)]
        self.assertNotIn("needle", [doc.page_content for doc in dense])
        hits = self.index.search("needle")
        self.assertEqual(len(hits), 4)
        self.assertIn(self.docs[54], hits)
        self.assertEqual(self.index.search(""), [])
        self.assertEqual([doc.page_content for doc in self.index.search("the")],
                         [doc.page_content for doc in dense[:4]])

    def test_reopened_index_embeds_only_new_chunks_and_searches_only_active_sources(self):
        pages = (("new-upload", "renamed.pdf", 55, "needle"), ("other", "extra.txt", 0, "fresh text"))
        embeddings = Mock(spec=Embeddings)
        embeddings.embed_documents.return_value = [[2, 1]]
        embeddings.embed_query.return_value = [1, 0]
        reopened = HybridIndex(split_pages(pages), embeddings)
        embeddings.embed_documents.assert_called_once_with(["fresh text"])
        found = reopened.search("Entry")
        self.assertEqual({doc.metadata["source_id"] for doc in found}, {"new-upload", "other"})
        citation = next(doc for doc in found if doc.page_content == "needle")
        self.assertEqual((citation.metadata["source"], citation.metadata["page"]), ("renamed.pdf", 55))

    def test_tool_writes_reranked_passages_with_original_citations(self):
        expected = []

        def respond(request):
            body = json.loads(request.content)
            self.assertEqual(body["model"], "rerank-v5.0-pro")
            self.assertEqual(body["query"], "needle")
            self.assertEqual(body["top_n"], 4)
            self.assertEqual(len(body["documents"]), 20)
            order = [19, 5, 2, 0]
            expected.extend(body["documents"][i] for i in order)
            return httpx.Response(200, json={"id": "test", "results": [
                {"index": i, "relevance_score": 1 / rank} for rank, i in enumerate(order, 1)
            ]})

        backend = Mock()
        backend.upload_files.side_effect = lambda files: [
            SimpleNamespace(path=path, error=None) for path, _ in files
        ]
        passages = {}
        with httpx.Client(transport=httpx.MockTransport(respond)) as http:
            client = ClientV2(api_key="test", httpx_client=http)
            with patch.dict(os.environ, {"COHERE_API_KEY": "test"}), patch(
                "langchain_chatbot.tools.ClientV2", return_value=client
            ):
                paths = make_search_tool(self.index, backend, passages).invoke({"query": "needle"})

        files = backend.upload_files.call_args.args[0]
        self.assertEqual(paths.splitlines(), [path for path, _ in files])
        self.assertEqual([doc.page_content for doc in passages.values()], expected)
        by_text = {doc.page_content: doc for doc in self.docs}
        for (_, content), text in zip(files, expected, strict=True):
            page = by_text[text].metadata["page"]
            self.assertEqual(content.decode(), f"# Source: report.pdf, page {page}\n\n{text}")

    def test_only_successfully_saved_passages_reach_the_answer(self):
        store = Mock()
        store.search.return_value = self.docs[:2]
        backend = Mock()
        for errors in ((None, "permission_denied"), ("permission_denied", "permission_denied")):
            with self.subTest(errors=errors), patch.dict(os.environ, {"COHERE_API_KEY": ""}):
                backend.upload_files.return_value = [
                    SimpleNamespace(path=f"/retrieved/{i}.md", error=error)
                    for i, error in enumerate(errors)
                ]
                passages = {}
                result = make_search_tool(store, backend, passages).invoke({"query": "entry"})
                if errors[0]:
                    self.assertFalse(passages)
                    self.assertIn("could not be saved", result)
                else:
                    self.assertEqual(result, "/retrieved/0.md")
                    self.assertEqual(list(passages.values()), self.docs[:1])
