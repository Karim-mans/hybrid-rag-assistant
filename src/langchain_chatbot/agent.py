import argparse
import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.messages import AIMessage, HumanMessage

from .filereader import read_pdf_pages
from .indexing import Page, build_index
from .prompts import CHUNK_ANALYST_INSTRUCTIONS, RAG_WORKFLOW_INSTRUCTIONS, SUBAGENT_DELEGATION_INSTRUCTIONS
from .tools import make_search_tool, passage_info


def ask_agent(pages: tuple[Page, ...], question: str, history: list[dict]) -> dict:
    backend = StateBackend()
    passages = {}
    search = make_search_tool(build_index(pages), backend, passages)
    instructions = RAG_WORKFLOW_INSTRUCTIONS + "\n\n" + SUBAGENT_DELEGATION_INSTRUCTIONS.format(
        max_concurrent_analysts=3
    )
    model_name = os.getenv("RAG_CHAT_MODEL") or os.getenv("FOLIO_CHAT_MODEL") or "openai:gpt-5.5"
    model = init_chat_model(model_name)
    agent = create_deep_agent(
        model=model,
        tools=[search],
        backend=backend,
        system_prompt=instructions,
        subagents=[{
            "name": "chunk_analyst",
            "description": "Read one retrieved passage and find evidence for the user's question.",
            "system_prompt": CHUNK_ANALYST_INSTRUCTIONS,
        }],
    )
    messages = [
        (HumanMessage if item["role"] == "user" else AIMessage)(content=item["text"])
        for item in history
    ]
    result = agent.invoke({"messages": [*messages, HumanMessage(content=question)]})
    answer = result["messages"][-1].text
    if not answer.strip():
        raise ValueError("The model returned an empty answer. Try asking again.")
    return {"text": answer, "passages": [passage_info(doc) for doc in passages.values()]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ask a question about local PDFs.")
    parser.add_argument("pdf", nargs="+", type=Path)
    parser.add_argument("-q", "--question", required=True)
    args = parser.parse_args()
    load_dotenv()
    pages = tuple(
        (str(path), path.name, number, text)
        for path in args.pdf
        for number, text in enumerate(read_pdf_pages(path), 1) if text.strip()
    )
    if not pages:
        parser.error("The selected PDFs contain no readable text.")
    print(ask_agent(pages, args.question, [])["text"])
