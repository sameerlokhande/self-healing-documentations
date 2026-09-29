import os
import sys
from pathlib import Path
from github import Github
from src.indexer.graph_indexer import Indexer
from src.detector.diff_parser import DiffAnalyzer
from src.detector.staleness_eval import StalenessEvaluator
from src.repair.patcher import DocPatcher
from src.repair.verifier import DocVerifier
import subprocess


def apply_section_patch_to_file(file_path: Path, heading_title: str, new_content: str):
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    new_lines = []
    inside_target = False

    for line in lines:
        if line.startswith("#") and heading_title.lower() in line.lower():
            inside_target = True
            new_lines.append(line)
            new_lines.append(new_content)
            continue
        elif inside_target and line.startswith("#"):
            inside_target = False

        if not inside_target:
            new_lines.append(line)

    file_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def main():
    # Allow git access to mounted workspaces across different container UIDs
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", "*"], check=False)
    repo_root = Path(os.getenv("GITHUB_WORKSPACE", ".")).resolve()
    cache_dir = repo_root / ".cache"
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model_name = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
    confidence_threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.80"))

    github_token = os.getenv("GITHUB_TOKEN")
    gh_repo_name = os.getenv("GITHUB_REPOSITORY")
    pr_number = os.getenv("PR_NUMBER")

    print("[*] Phase 1: Indexing codebase and documentation...")
    indexer = Indexer(repo_root=repo_root, cache_dir=cache_dir)
    graph = indexer.build_graph()

    print("[*] Phase 2: Analyzing diff and evaluating staleness...")
    diff_analyzer = DiffAnalyzer(repo_root=repo_root)
    
    # In GitHub Action CI, compare HEAD~1 with HEAD
    changed_symbols = diff_analyzer.extract_modified_symbols(
        base_ref="HEAD~1",
        head_ref="HEAD",
        current_chunks=graph.code_chunks
    )

    if not changed_symbols:
        print("[+] No Python symbol modifications detected.")
        sys.exit(0)

    evaluator = StalenessEvaluator(model_name=model_name, host=ollama_host)
    patcher = DocPatcher(model_name=model_name, host=ollama_host)
    verifier = DocVerifier(model_name=model_name, host=ollama_host)

    results_table = []
    files_to_update = {}

    for sym in changed_symbols:
        # Find links connected to this symbol
        linked_docs = [l.doc_section_id for l in graph.links if l.code_chunk_id == sym.chunk_id]
        for doc_id in linked_docs:
            section = graph.doc_sections.get(doc_id)
            if not section:
                continue

            staleness = evaluator.evaluate(sym, section)
            if staleness.is_stale:
                print(f"[!] Stale doc section found: {section.section_id}")
                patch = patcher.generate_repair(section, sym, staleness)
                verdict = verifier.verify(sym, section.content, patch)

                if verdict.is_accurate and verdict.final_confidence >= confidence_threshold:
                    results_table.append(f"| `{section.file_path}` | ⚠️ Stale | {staleness.inaccuracy_explanation} | Auto-applied fix (Conf: {verdict.final_confidence}) |")
                    files_to_update[(section.file_path, section.heading_title)] = patch.repaired_content
                else:
                    results_table.append(f"| `{section.file_path}` | ❌ Complex Drift | {staleness.inaccuracy_explanation} | Flagged for manual review |")

    # Apply updates
    for (rel_path, heading), new_content in files_to_update.items():
        apply_section_patch_to_file(repo_root / rel_path, heading, new_content)

    # Post GitHub comment if running in PR workflow
    if github_token and gh_repo_name and pr_number and results_table:
        gh = Github(github_token)
        repo = gh.get_repo(gh_repo_name)
        pr = repo.get_pull(int(pr_number))
        comment_body = "### 📚 Documentation Drift Report\n\n"
        comment_body += "| File | Status | Issue | Action Taken |\n| :--- | :--- | :--- | :--- |\n"
        comment_body += "\n".join(results_table)
        pr.create_issue_comment(comment_body)

    print("[+] Done.")

if __name__ == "__main__":
    main()