import json
import ollama
from pydantic import BaseModel
from src.detector.diff_parser import ChangedSymbol
from src.detector.staleness_eval import StalenessResult
from src.indexer.doc_parser import DocSection

class PatchedSection(BaseModel):
    heading_title: str
    repaired_content: str
    summary_of_changes: str

class DocPatcher:
    def __init__(self, model_name: str = "qwen2.5-coder:7b", host: str = "http://localhost:11434"):
        self.model_name = model_name
        self.client = ollama.Client(host=host)

    def generate_repair(
        self,
        doc_section: DocSection,
        changed_symbol: ChangedSymbol,
        staleness: StalenessResult
    ) -> PatchedSection:
        prompt = f"""
You are a documentation repair system.
Update the documentation section to fix identified inaccuracies while preserving tone, style, and untouched content.

REASON FOR INACCURACY:
{staleness.inaccuracy_explanation}

NEW CODE:
{changed_symbol.new_raw_code}

CURRENT DOC SECTION:
Heading: {doc_section.heading_title}
Content:
{doc_section.content}

INSTRUCTIONS:
- Rewrite ONLY the parts of the documentation that are no longer accurate.
- Do NOT rewrite or rephrase sentences that are still accurate.
- Maintain identical markdown conventions and code-block formatting.
- Return the full repaired section content under repaired_content.
"""
        response = self.client.chat(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            format=PatchedSection.model_json_schema(),
            options={"temperature": 0.1}
        )

        try:
            data = json.loads(response.message.content)
            return PatchedSection(**data)
        except Exception:
            return PatchedSection(
                heading_title=doc_section.heading_title,
                repaired_content=doc_section.content,
                summary_of_changes="Patch generation failed"
            )