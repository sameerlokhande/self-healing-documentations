import re
from pathlib import Path
from pydantic import BaseModel, Field

class DocSection(BaseModel):
    section_id: str = Field(description="Unique ID: filepath#heading-slug")
    file_path: str
    heading_title: str
    heading_level: int
    content: str
    code_references: list[str] = Field(default_factory=list)

def extract_code_references(text: str) -> list[str]:
    raw_tokens = re.findall(r"`([a-zA-Z_][a-zA-Z0-9_.]*)`", text)
    return sorted(list(set(token.split(".")[-1] for token in raw_tokens)))

def parse_markdown_file(file_path: Path, repo_root: Path) -> list[DocSection]:
    # .as_posix() forces forward slashes on Windows
    relative_path = file_path.relative_to(repo_root).as_posix()
    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    sections: list[DocSection] = []
    current_title = "Overview"
    current_level = 1
    current_lines: list[str] = []

    def flush_section():
        content = "\n".join(current_lines).strip()
        if content:
            slug = re.sub(r"[^a-zA-Z0-9_-]", "", current_title.lower().replace(" ", "-"))
            sections.append(DocSection(
                section_id=f"{relative_path}#{slug}",
                file_path=relative_path,
                heading_title=current_title,
                heading_level=current_level,
                content=content,
                code_references=extract_code_references(content)
            ))

    for line in lines:
        header_match = re.match(r"^(#{1,4})\s+(.*)$", line)
        if header_match:
            flush_section()
            current_level = len(header_match.group(1))
            current_title = header_match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    flush_section()
    return sections