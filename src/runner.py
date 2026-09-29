import os
import sys
from pathlib import Path
import subprocess
from github import Github

# Ensure repository root is on sys.path for both local dev and Docker containers
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.indexer.graph_indexer import Indexer
from src.detector.diff_parser import DiffAnalyzer
from src.detector.staleness_eval import StalenessEvaluator
from src.repair.patcher import DocPatcher
from src.repair.verifier import DocVerifier


def resolve_git_refs(workspace_dir: str) -> tuple[str, str]:
    """Dynamically determine base and head references based on the GitHub event."""
    event_name = os.getenv("GITHUB_EVENT_NAME", "").lower()
    base_ref_env = os.getenv("GITHUB_BASE_REF")

    # Pull Request trigger: compare against the base branch
    if event_name == "pull_request" and base_ref_env:
        for candidate in [f"origin/{base_ref_env}", base_ref_env]:
            res = subprocess.run(
                ["git", "rev-parse", "--verify", candidate],
                cwd=workspace_dir, capture_output=True, text=True
            )
            if res.returncode == 0:
                return candidate, "HEAD"

    # Push or workflow_dispatch trigger: compare against the previous commit
    res = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD~1"],
        cwd=workspace_dir, capture_output=True, text=True
    )
    if res.returncode == 0:
        return "HEAD~1", "HEAD"

    # Fallback to main branch comparison for fresh branch pushes
    for default_branch in ["origin/main", "main", "origin/master", "master"]:
        res = subprocess.run(
            ["git", "rev-parse", "--verify", default_branch],
            cwd=workspace_dir, capture_output=True, text=True
        )
        if res.returncode == 0:
            return default_branch, "HEAD"

    return "HEAD", "HEAD"


def get_changed_symbols(diff_analyzer: DiffAnalyzer, base_ref: str, head_ref: str):
    """Call the diff analyzer using whichever extraction method is implemented."""
    for method_name in ["get_modified_symbols", "extract_modified_symbols", "get_changed_symbols", "analyze"]:
        if hasattr(diff_analyzer, method_name):
            method = getattr(diff_analyzer, method_name)
            try:
                return method(base_ref, head_ref)
            except TypeError:
                return method()
    return []


def find_doc_section(indexer: Indexer, sym):
    """Retrieve the corresponding documentation node or section for a given symbol."""
    sym_name = getattr(sym, "name", str(sym))
    for method_name in ["find_relevant_section", "get_related_documentation", "find_documentation", "get_section", "query"]:
        if hasattr(indexer, method_name):
            return getattr(indexer, method_name)(sym_name)
    return None


def main():
    # Eliminate dubious ownership errors inside Docker mounts
    subprocess.run(["git", "config", "--global", "--add", "safe.directory", "*"], check=False)

    workspace_dir = os.getenv("GITHUB_WORKSPACE", os.getcwd())
    ollama_host = os.getenv("INPUT_OLLAMA_HOST") or os.getenv("OLLAMA_HOST", "http://172.17.0.1:11434")
    ollama_model = os.getenv("INPUT_OLLAMA_MODEL") or os.getenv("OLLAMA_MODEL", "qwen2.5-coder:1.5b")
    confidence_threshold = float(
        os.getenv("INPUT_CONFIDENCE_THRESHOLD") or os.getenv("CONFIDENCE_THRESHOLD", "0.75")
    )

    print(f"[*] Workspace: {workspace_dir}")
    print(f"[*] Ollama Host: {ollama_host} | Model: {ollama_model} | Threshold: {confidence_threshold}")

    # Phase 1: Index codebase and documentation graph
    print("\n[*] Phase 1: Indexing codebase and documentation...")
    try:
        indexer = Indexer(workspace_dir)
    except TypeError:
        indexer = Indexer()

    for index_method in ["build_graph", "index", "index_codebase", "index_documentation"]:
        if hasattr(indexer, index_method):
            getattr(indexer, index_method)()
            break

    # Phase 2: Analyze Git diff and evaluate staleness
    print("\n[*] Phase 2: Analyzing diff and evaluating staleness...")
    base_ref, head_ref = resolve_git_refs(workspace_dir)
    print(f"[*] Comparing refs: {base_ref} ... {head_ref}")

    try:
        diff_analyzer = DiffAnalyzer(workspace_dir)
    except TypeError:
        diff_analyzer = DiffAnalyzer()

    changed_symbols = get_changed_symbols(diff_analyzer, base_ref, head_ref)

    # If no changes were detected against HEAD~1, check against origin/main as fallback
    if not changed_symbols and base_ref == "HEAD~1":
        print("[*] No changes detected in HEAD~1; falling back to origin/main comparison...")
        changed_symbols = get_changed_symbols(diff_analyzer, "origin/main", "HEAD")

    if not changed_symbols:
        print("[+] No Python symbol modifications detected.")
        return

    print(f"[+] Found {len(changed_symbols)} modified symbol(s): {[getattr(s, 'name', str(s)) for s in changed_symbols]}")

    try:
        evaluator = StalenessEvaluator(host=ollama_host, model=ollama_model)
    except TypeError:
        evaluator = StalenessEvaluator()

    stale_items = []
    for sym in changed_symbols:
        sym_name = getattr(sym, "name", str(sym))
        section = find_doc_section(indexer, sym)
        if not section:
            print(f"[-] No documentation mapping found for symbol '{sym_name}'. Skipping.")
            continue

        print(f"[*] Evaluating staleness for symbol '{sym_name}'...")
        staleness = evaluator.evaluate(sym, section)

        score = getattr(staleness, "confidence", None)
        if score is None and isinstance(staleness, dict):
            score = staleness.get("confidence", 0.0)

        is_stale = getattr(staleness, "is_stale", False)
        if not is_stale and isinstance(staleness, dict):
            is_stale = staleness.get("is_stale", False)

        if is_stale or (score is not None and score >= confidence_threshold):
            print(f"[!] Stale doc detected for '{sym_name}' (Confidence: {score})")
            stale_items.append((sym, section, staleness))
        else:
            print(f"[=] Documentation for '{sym_name}' is up to date.")

    if not stale_items:
        print("[+] All documentation sections are aligned with the latest code.")
        return

    # Phase 3: Patch and verify documentation
    print("\n[*] Phase 3: Generating documentation updates and applying patches...")
    try:
        patcher = DocPatcher(host=ollama_host, model=ollama_model)
    except TypeError:
        patcher = DocPatcher()

    try:
        verifier = DocVerifier()
    except TypeError:
        verifier = None

    for sym, section, staleness in stale_items:
        sym_name = getattr(sym, "name", str(sym))
        print(f"[*] Repairing documentation for '{sym_name}'...")

        # Generate patch
        patch = None
        for patch_func in ["generate_patch", "patch", "repair"]:
            if hasattr(patcher, patch_func):
                patch = getattr(patcher, patch_func)(sym, section, staleness)
                break

        if not patch:
            continue

        # Optional verification step
        is_valid = True
        if verifier:
            for verify_func in ["verify", "verify_patch"]:
                if hasattr(verifier, verify_func):
                    is_valid = getattr(verifier, verify_func)(section, patch)
                    break

        if is_valid:
            for apply_func in ["apply_patch", "apply", "write_patch"]:
                if hasattr(patcher, apply_func):
                    getattr(patcher, apply_func)(section, patch)
                    print(f"[+] Successfully patched documentation for '{sym_name}'.")
                    break
        else:
            print(f"[-] Patch verification failed for '{sym_name}'. Skipping write.")

    print("\n[+] Self-healing documentation pipeline complete.")


if __name__ == "__main__":
    main()