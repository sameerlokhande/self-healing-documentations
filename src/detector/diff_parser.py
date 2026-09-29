from pathlib import Path
import git
from pydantic import BaseModel
from src.indexer.ast_parser import CodeChunk

class ChangedSymbol(BaseModel):
    chunk_id: str
    symbol_name: str
    file_path: str
    old_signature: str | None = None
    new_signature: str
    new_raw_code: str
    diff_text: str

class DiffAnalyzer:
    def __init__(self, repo_root: Path):
        self.repo = git.Repo(repo_root)

    def extract_modified_symbols(
        self,
        base_ref: str,
        head_ref: str,
        current_chunks: dict[str, CodeChunk]
    ) -> list[ChangedSymbol]:
        diff_index = self.repo.commit(base_ref).diff(head_ref, create_patch=True)
        changed_symbols: list[ChangedSymbol] = []

        for diff_item in diff_index:
            raw_path = diff_item.b_path or diff_item.a_path
            if not raw_path:
                continue

            # Normalize to POSIX forward slashes
            path_str = Path(raw_path).as_posix()
            if not path_str.endswith(".py") or path_str.startswith("tests/"):
                continue

            diff_text = diff_item.diff.decode("utf-8", errors="replace")
            
            # Check for meaningful changes (ignore comment/whitespace only diffs)
            cleaned_lines = [
                line[1:].strip() for line in diff_text.splitlines()
                if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
            ]
            meaningful = [l for l in cleaned_lines if l and not l.startswith("#")]
            if not meaningful:
                continue

            for chunk_id, chunk in current_chunks.items():
                chunk_file = Path(chunk.file_path).as_posix()
                if chunk_file == path_str:
                    # Check if symbol appears in diff patch
                    if f"def {chunk.symbol_name}" in diff_text or f"class {chunk.symbol_name}" in diff_text or chunk.symbol_name in diff_text:
                        changed_symbols.append(ChangedSymbol(
                            chunk_id=chunk_id,
                            symbol_name=chunk.symbol_name,
                            file_path=chunk.file_path,
                            new_signature=chunk.signature,
                            new_raw_code=chunk.raw_code,
                            diff_text=diff_text
                        ))

        return changed_symbols