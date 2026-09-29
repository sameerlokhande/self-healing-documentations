import json
from pathlib import Path
from pydantic import BaseModel
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from src.indexer.ast_parser import CodeChunk, parse_python_file
from src.indexer.doc_parser import DocSection, parse_markdown_file

class Link(BaseModel):
    code_chunk_id: str
    doc_section_id: str
    link_type: str  # 'explicit' or 'semantic'
    score: float

class HybridCodeDocGraph(BaseModel):
    code_chunks: dict[str, CodeChunk]
    doc_sections: dict[str, DocSection]
    links: list[Link]

class Indexer:
    def __init__(self, repo_root: Path, cache_dir: Path):
        self.repo_root = repo_root.resolve()
        self.cache_dir = cache_dir.resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.embed_fn = SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2",
            device="cpu"
        )
        self.chroma_client = chromadb.PersistentClient(path=str(self.cache_dir / "chroma"))
        self.collection = self.chroma_client.get_or_create_collection(
            name="doc_sections",
            embedding_function=self.embed_fn
        )

    def scan_repository(self) -> tuple[list[CodeChunk], list[DocSection]]:
        code_chunks: list[CodeChunk] = []
        doc_sections: list[DocSection] = []

        for py_file in self.repo_root.rglob("*.py"):
            parts = py_file.parts
            if any(p.startswith(".") or p in ("tests", "venv", ".venv", "build", "dist") for p in parts):
                continue
            code_chunks.extend(parse_python_file(py_file, self.repo_root))

        for md_file in self.repo_root.rglob("*.md"):
            if any(p.startswith(".") or p in ("venv", ".venv") for p in md_file.parts):
                continue
            doc_sections.extend(parse_markdown_file(md_file, self.repo_root))

        return code_chunks, doc_sections

    def build_graph(self, similarity_threshold: float = 0.50) -> HybridCodeDocGraph:
        code_chunks, doc_sections = self.scan_repository()
        code_map = {chunk.chunk_id: chunk for chunk in code_chunks}
        doc_map = {sec.section_id: sec for sec in doc_sections}
        links: list[Link] = []

        if not doc_sections:
            return HybridCodeDocGraph(code_chunks=code_map, doc_sections=doc_map, links=[])

        self.collection.upsert(
            ids=[sec.section_id for sec in doc_sections],
            documents=[f"{sec.heading_title}\n{sec.content}" for sec in doc_sections],
            metadatas=[{"file_path": sec.file_path, "heading": sec.heading_title} for sec in doc_sections]
        )

        for chunk in code_chunks:
            for sec in doc_sections:
                if chunk.symbol_name in sec.code_references:
                    links.append(Link(
                        code_chunk_id=chunk.chunk_id,
                        doc_section_id=sec.section_id,
                        link_type="explicit",
                        score=1.0
                    ))

        for chunk in code_chunks:
            query_text = f"{chunk.signature}\n{chunk.docstring or ''}".strip()
            results = self.collection.query(
                query_texts=[query_text],
                n_results=min(3, len(doc_sections))
            )

            if results["ids"] and results["distances"]:
                for doc_id, dist in zip(results["ids"][0], results["distances"][0]):
                    sim = 1.0 - dist
                    if sim >= similarity_threshold:
                        if not any(l.code_chunk_id == chunk.chunk_id and l.doc_section_id == doc_id for l in links):
                            links.append(Link(
                                code_chunk_id=chunk.chunk_id,
                                doc_section_id=doc_id,
                                link_type="semantic",
                                score=round(sim, 3)
                            ))

        graph = HybridCodeDocGraph(code_chunks=code_map, doc_sections=doc_map, links=links)
        graph_file = self.cache_dir / "code_docs_graph.json"
        graph_file.write_text(graph.model_dump_json(indent=2), encoding="utf-8")
        return graph