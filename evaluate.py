import json
import shutil
import tempfile
from pathlib import Path
import git
from pydantic import BaseModel

from src.indexer.graph_indexer import Indexer
from src.detector.diff_parser import DiffAnalyzer
from src.detector.staleness_eval import StalenessEvaluator
from src.repair.patcher import DocPatcher
from src.repair.verifier import DocVerifier

class TestCase(BaseModel):
    name: str
    description: str
    expected_stale: bool
    initial_code: str
    initial_doc: str
    modified_code: str
    doc_heading: str

# Define 4 core real-world test scenarios
EVAL_CASES = [
    TestCase(
        name="signature_default_param_change",
        description="Default timeout changed from 30 to 60. Should flag as stale (True Positive).",
        expected_stale=True,
        doc_heading="Session Setup",
        initial_code="""
def init_session(user_id: str, timeout: int = 30) -> str:
    \"\"\"Initializes a session.\"\"\"
    return f"session_{user_id}_{timeout}"
""",
        initial_doc="""# Core API
## Session Setup
Call `init_session` to start. The default timeout is 30 seconds.
""",
        modified_code="""
def init_session(user_id: str, timeout: int = 60) -> str:
    \"\"\"Initializes a session.\"\"\"
    return f"session_{user_id}_{timeout}"
"""
    ),
    TestCase(
        name="internal_refactor_no_contract_change",
        description="Internal implementation changed for speed, public signature intact. Should NOT flag (True Negative).",
        expected_stale=False,
        doc_heading="Data Hashing",
        initial_code="""
def hash_payload(data: str) -> str:
    \"\"\"Hashes an incoming string.\"\"\"
    result = ""
    for char in data:
        result += hex(ord(char))
    return result
""",
        initial_doc="""# Utilities
## Data Hashing
Use `hash_payload` with any string to retrieve a formatted hexadecimal representation.
""",
        modified_code="""
def hash_payload(data: str) -> str:
    \"\"\"Hashes an incoming string.\"\"\"
    return "".join(hex(ord(c)) for c in data)
"""
    ),
    TestCase(
        name="param_renamed",
        description="Parameter 'auth_key' renamed to 'api_key'. Should flag as stale (True Positive).",
        expected_stale=True,
        doc_heading="Client Credentials",
        initial_code="""
def configure_client(auth_key: str) -> bool:
    \"\"\"Configures the internal client.\"\"\"
    return True
""",
        initial_doc="""# Configuration
## Client Credentials
Set up your client by passing `auth_key` to `configure_client`.
""",
        modified_code="""
def configure_client(api_key: str) -> bool:
    \"\"\"Configures the internal client.\"\"\"
    return True
"""
    ),
    TestCase(
        name="whitespace_and_comment_only",
        description="Only whitespace and internal comments added. Should NOT flag (True Negative).",
        expected_stale=False,
        doc_heading="Health Check",
        initial_code="""
def ping() -> str:
    \"\"\"Checks server status.\"\"\"
    return "PONG"
""",
        initial_doc="""# Monitoring
## Health Check
Invoke `ping` to receive a PONG acknowledgment string.
""",
        modified_code="""
def ping() -> str:
    # Adding diagnostic comment
    
    \"\"\"Checks server status.\"\"\"
    return "PONG"
"""
    ),
]

def run_evaluation():
    print("=" * 60)
    print("Starting Automated Staleness Detection Evaluation Suite")
    print("=" * 60)

    evaluator = StalenessEvaluator()
    patcher = DocPatcher()
    verifier = DocVerifier()

    tp = fp = tn = fn = 0
    repair_successes = 0

    for i, test in enumerate(EVAL_CASES, start=1):
        temp_dir = Path(tempfile.mkdtemp(prefix=f"eval_{test.name}_"))
        try:
            repo = git.Repo.init(temp_dir)
            with repo.config_writer() as config:
                config.set_value("user", "name", "Eval Runner")
                config.set_value("user", "email", "eval@runner.local")

            src_dir = temp_dir / "src"
            docs_dir = temp_dir / "docs"
            src_dir.mkdir()
            docs_dir.mkdir()

            code_file = src_dir / "module.py"
            doc_file = docs_dir / "guide.md"

            # 1. Base commit
            code_file.write_text(test.initial_code, encoding="utf-8")
            doc_file.write_text(test.initial_doc, encoding="utf-8")
            repo.index.add(["src/module.py", "docs/guide.md"])
            commit1 = repo.index.commit("Base state")

            # 2. Index base state
            indexer = Indexer(repo_root=temp_dir, cache_dir=temp_dir / ".cache")
            graph = indexer.build_graph()

            # 3. Modified commit
            code_file.write_text(test.modified_code, encoding="utf-8")
            repo.index.add(["src/module.py"])
            commit2 = repo.index.commit("Apply changes")

            # 4. Detect diff
            analyzer = DiffAnalyzer(repo_root=temp_dir)
            changed = analyzer.extract_modified_symbols(
                base_ref=commit1.hexsha,
                head_ref=commit2.hexsha,
                current_chunks=graph.code_chunks
            )

            predicted_stale = False
            explanation = ""

            for sym in changed:
                linked = [l.doc_section_id for l in graph.links if l.code_chunk_id == sym.chunk_id]
                for doc_id in linked:
                    sec = graph.doc_sections.get(doc_id)
                    if sec:
                        res = evaluator.evaluate(sym, sec)
                        if res.is_stale:
                            predicted_stale = True
                            explanation = res.inaccuracy_explanation

                            # If stale, run repair pass
                            patch = patcher.generate_repair(sec, sym, res)
                            verdict = verifier.verify(sym, sec.content, patch)
                            if verdict.is_accurate:
                                repair_successes += 1

            # 5. Score Matrix
            if test.expected_stale and predicted_stale:
                tp += 1
                status = "PASS (True Positive)"
            elif not test.expected_stale and not predicted_stale:
                tn += 1
                status = "PASS (True Negative)"
            elif not test.expected_stale and predicted_stale:
                fp += 1
                status = "FAIL (False Positive)"
            else:
                fn += 1
                status = "FAIL (False Negative)"

            print(f"\n[Test {i}/{len(EVAL_CASES)}] {test.name}: {status}")
            print(f"  Description: {test.description}")
            if explanation:
                print(f"  Diagnosis: {explanation}")

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    total = len(EVAL_CASES)
    accuracy = (tp + tn) / total if total > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0

    print("\n" + "=" * 60)
    print("EVALUATION BENCHMARK METRICS")
    print("=" * 60)
    print(f"Total Scenarios Tested : {total}")
    print(f"Accuracy               : {accuracy * 100:.1f}%")
    print(f"Precision              : {precision * 100:.1f}%")
    print(f"Recall                 : {recall * 100:.1f}%")
    print(f"True Positives (TP)    : {tp}")
    print(f"True Negatives (TN)    : {tn}")
    print(f"False Positives (FP)   : {fp}")
    print(f"False Negatives (FN)   : {fn}")
    print(f"Successful Doc Repairs : {repair_successes}/{tp}")
    print("=" * 60)

if __name__ == "__main__":
    run_evaluation()