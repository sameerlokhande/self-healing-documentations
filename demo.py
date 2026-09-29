import os
import stat
import shutil
from pathlib import Path
import git

from src.indexer.graph_indexer import Indexer
from src.detector.diff_parser import DiffAnalyzer
from src.detector.staleness_eval import StalenessEvaluator
from src.repair.patcher import DocPatcher
from src.repair.verifier import DocVerifier
from src.runner import apply_section_patch_to_file

def _remove_readonly(func, path, _):
    os.chmod(path, stat.S_IWRITE)
    func(path)

def run_local_demo():
    workspace = Path("./demo_workspace").resolve()
    if workspace.exists():
        shutil.rmtree(workspace, onerror=_remove_readonly)
    workspace.mkdir()

    repo = git.Repo.init(workspace)
    (workspace / "src").mkdir()
    (workspace / "docs").mkdir()

    try:
        # Commit 1: Initial state
        auth_py = workspace / "src" / "auth.py"
        auth_py.write_text("""
def issue_token(user_id: str, timeout: int = 30) -> str:
    \"\"\"Generates a session token.\"\"\"
    return f"token_{user_id}_{timeout}"
""", encoding="utf-8")

        doc_md = workspace / "docs" / "auth.md"
        doc_md.write_text("""# Authentication

## Session Token
Call `issue_token` with the user ID. Tokens expire in 30 seconds by default.
""", encoding="utf-8")

        repo.index.add(["src/auth.py", "docs/auth.md"])
        commit1 = repo.index.commit("Initial setup")

        # Step 1: Build Index on base commit
        print("\n--- Step 1: Building Code-Doc Index ---")
        indexer = Indexer(repo_root=workspace, cache_dir=workspace / ".cache")
        graph = indexer.build_graph()
        print(f"Links found: {len(graph.links)}")

        # Step 2: Breaking signature change (default timeout changed to 60)
        print("\n--- Step 2: Modifying code (timeout changed from 30 to 60) ---")
        auth_py.write_text("""
def issue_token(user_id: str, timeout: int = 60) -> str:
    \"\"\"Generates a session token.\"\"\"
    return f"token_{user_id}_{timeout}"
""", encoding="utf-8")
        repo.index.add(["src/auth.py"])
        commit2 = repo.index.commit("Increase default timeout to 60")

        # Re-scan chunks so current_chunks reflects the new commit
        new_chunks, _ = indexer.scan_repository()
        new_chunk_map = {c.chunk_id: c for c in new_chunks}

        # Step 3: Diff Analysis
        print("\n--- Step 3: Parsing Git Diff ---")
        diff_analyzer = DiffAnalyzer(repo_root=workspace)
        changed_symbols = diff_analyzer.extract_modified_symbols(
            base_ref=commit1.hexsha,
            head_ref=commit2.hexsha,
            current_chunks=new_chunk_map
        )
        print(f"Changed Symbols detected: {[s.symbol_name for s in changed_symbols]}")

        # Step 4: Staleness Check with Ollama
        print("\n--- Step 4: Evaluating Staleness via Ollama ---")
        evaluator = StalenessEvaluator()
        patcher = DocPatcher()
        verifier = DocVerifier()

        for sym in changed_symbols:
            linked_docs = [l.doc_section_id for l in graph.links if l.code_chunk_id == sym.chunk_id]
            for doc_id in linked_docs:
                sec = graph.doc_sections[doc_id]
                staleness = evaluator.evaluate(sym, sec)
                print(f"Stale: {staleness.is_stale} | Conf: {staleness.confidence_score}")
                print(f"Reason: {staleness.inaccuracy_explanation}")

                if staleness.is_stale:
                    print("\n--- Step 5: Repairing Documentation ---")
                    patch = patcher.generate_repair(sec, sym, staleness)
                    print(f"Proposed patch:\n{patch.repaired_content}")

                    print("\n--- Step 6: Verifying Patch with Quality Gate ---")
                    verdict = verifier.verify(sym, sec.content, patch)
                    print(f"Accurate: {verdict.is_accurate} | Conf: {verdict.final_confidence}")

                    if verdict.is_accurate and verdict.final_confidence >= 0.70:
                        apply_section_patch_to_file(workspace / sec.file_path, sec.heading_title, patch.repaired_content)
                        print("\n[SUCCESS] Applied documentation patch to file!")
                        print("Updated file contents:")
                        print(doc_md.read_text(encoding="utf-8"))
    finally:
        repo.close()

if __name__ == "__main__":
    run_local_demo()