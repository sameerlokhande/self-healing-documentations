import ast
from pathlib import Path
from pydantic import BaseModel, Field

class CodeChunk(BaseModel):
    chunk_id: str = Field(description="Unique identifier: filepath::symbol_name")
    file_path: str
    symbol_name: str
    symbol_type: str  # 'function', 'async_function', or 'class'
    signature: str
    docstring: str | None = None
    line_start: int
    line_end: int
    raw_code: str

class ASTSymbolVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str, source_code: str):
        self.file_path = file_path
        self.lines = source_code.splitlines()
        self.chunks: list[CodeChunk] = []

    def _extract_raw(self, start: int, end: int) -> str:
        return "\n".join(self.lines[start - 1 : end])

    def _format_function_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        args_str = ast.unparse(node.args)
        returns_str = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return f"{prefix} {node.name}({args_str}){returns_str}"

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.chunks.append(CodeChunk(
            chunk_id=f"{self.file_path}::{node.name}",
            file_path=self.file_path,
            symbol_name=node.name,
            symbol_type="function",
            signature=self._format_function_signature(node),
            docstring=ast.get_docstring(node),
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            raw_code=self._extract_raw(node.lineno, node.end_lineno or node.lineno)
        ))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self.chunks.append(CodeChunk(
            chunk_id=f"{self.file_path}::{node.name}",
            file_path=self.file_path,
            symbol_name=node.name,
            symbol_type="async_function",
            signature=self._format_function_signature(node),
            docstring=ast.get_docstring(node),
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            raw_code=self._extract_raw(node.lineno, node.end_lineno or node.lineno)
        ))
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        bases = [ast.unparse(b) for b in node.bases]
        bases_str = f"({', '.join(bases)})" if bases else ""
        self.chunks.append(CodeChunk(
            chunk_id=f"{self.file_path}::{node.name}",
            file_path=self.file_path,
            symbol_name=node.name,
            symbol_type="class",
            signature=f"class {node.name}{bases_str}:",
            docstring=ast.get_docstring(node),
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            raw_code=self._extract_raw(node.lineno, node.end_lineno or node.lineno)
        ))
        self.generic_visit(node)

def parse_python_file(file_path: Path, repo_root: Path) -> list[CodeChunk]:
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
        # .as_posix() forces forward slashes on Windows (e.g. src/auth.py)
        relative_path = file_path.relative_to(repo_root).as_posix()
        visitor = ASTSymbolVisitor(file_path=relative_path, source_code=source)
        visitor.visit(tree)
        return visitor.chunks
    except (SyntaxError, UnicodeDecodeError):
        return []