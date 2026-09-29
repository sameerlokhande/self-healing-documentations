import json
import ollama
from pydantic import BaseModel, Field
from src.detector.diff_parser import ChangedSymbol
from src.repair.patcher import PatchedSection

class VerificationVerdict(BaseModel):
    is_accurate: bool
    integrity_preserved: bool
    final_confidence: float = Field(ge=0.0, le=1.0)
    critique: str

class DocVerifier:
    def __init__(self, model_name: str = "qwen2.5-coder:7b", host: str = "http://localhost:11434"):
        self.model_name = model_name
        self.client = ollama.Client(host=host)

    def verify(
        self,
        changed_symbol: ChangedSymbol,
        original_doc: str,
        patched_doc: PatchedSection
    ) -> VerificationVerdict:
        prompt = f"""
You are an independent Quality Gate Inspector for automated documentation edits.
Verify whether the proposed documentation patch is accurate and did not corrupt surrounding content.

NEW CODE:
{changed_symbol.new_raw_code}

ORIGINAL DOC:
{original_doc}

PROPOSED PATCH:
{patched_doc.repaired_content}

CHECKLIST:
1. Is the patch technically accurate against the new code?
2. Did the patch preserve the untouched parts of the original documentation without hallucinating extra details?
"""
        response = self.client.chat(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            format=VerificationVerdict.model_json_schema(),
            options={"temperature": 0.0}
        )

        try:
            data = json.loads(response.message.content)
            return VerificationVerdict(**data)
        except Exception:
            return VerificationVerdict(
                is_accurate=False,
                integrity_preserved=False,
                final_confidence=0.0,
                critique="Verification parsing failed"
            )