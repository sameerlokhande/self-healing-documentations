import os
import json
import ollama
from pydantic import BaseModel, Field
from src.detector.diff_parser import ChangedSymbol
from src.indexer.doc_parser import DocSection

class StalenessResult(BaseModel):
    is_stale: bool
    confidence_score: float = Field(ge=0.0, le=1.0)
    inaccuracy_explanation: str | None = None
    affected_doc_snippets: list[str] = Field(default_factory=list)

class StalenessEvaluator:
    def __init__(self, model_name: str = "qwen2.5-coder:7b", host: str = "http://localhost:11434"):
        self.model_name = model_name
        self.client = ollama.Client(host=host)

    def evaluate(self, changed_symbol: ChangedSymbol, doc_section: DocSection) -> StalenessResult:
        prompt = f"""
You are an expert technical documentation verification agent.
Analyze whether the code changes invalidate the linked documentation section.

CODE DIFF:
{changed_symbol.diff_text}

NEW CODE IMPLEMENTATION:
{changed_symbol.new_raw_code}

CURRENT DOCUMENTATION SECTION:
Heading: {doc_section.heading_title}
Content:
{doc_section.content}

TASK:
1. Determine if the documentation contains statements, parameter names, default values, signatures, or behavior descriptions that are now INACCURATE given the code change.
2. If internal implementation changed without altering public behavior or documented facts, set is_stale to false.
3. Return your verdict strictly conforming to the requested schema.
"""
        response = self.client.chat(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            format=StalenessResult.model_json_schema(),
            options={"temperature": 0.0}
        )

        try:
            data = json.loads(response.message.content)
            return StalenessResult(**data)
        except Exception:
            return StalenessResult(is_stale=False, confidence_score=0.0, inaccuracy_explanation="Parsing failed")