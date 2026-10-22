import ast
import io
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pypdf import PdfReader

from adam.knowledge.contracts import Chunk, ParsedBlock

TEXT = {".txt", ".md", ".rst", ".csv", ".json", ".yaml", ".yml", ".toml", ".ini"}
CODE = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".c",
    ".cpp",
    ".h",
    ".rs",
    ".go",
    ".java",
    ".sh",
    ".ps1",
    ".sql",
}


class IngestionError(ValueError):
    """Safe diagnostics without file contents or arbitrary parser exception messages."""


def parse(path: Path, raw: bytes) -> tuple[str, list[ParsedBlock]]:
    if path.suffix.casefold() == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted or len(reader.pages) > 300:
                raise IngestionError("Encrypted or oversized PDF is unsupported.")
            blocks = [
                ParsedBlock(text=page.extract_text() or "", locator=f"page:{index + 1}")
                for index, page in enumerate(reader.pages)
            ]
        except IngestionError:
            raise
        except Exception:
            raise IngestionError("PDF parsing failed. Text-based PDFs are required.") from None
        return "pdf", blocks
    if path.suffix.casefold() not in TEXT | CODE:
        raise IngestionError("Unsupported file type.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise IngestionError("Text/code files must be UTF-8.") from None
    lines = text.splitlines(keepends=True)
    boundaries = [0]
    if path.suffix.casefold() == ".py":
        try:
            tree = ast.parse(text)
            boundaries += [
                node.lineno - 1
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
        except SyntaxError:
            pass  # Syntax-incomplete project files still have a safe line parser.
    else:
        boundaries += [
            i for i, line in enumerate(lines) if line.startswith("#") or not line.strip()
        ]
    boundaries = sorted(set([*boundaries, len(lines)]))
    return "code" if path.suffix.casefold() in CODE else "text", [
        ParsedBlock(text="".join(lines[start:end]), locator=f"lines:{start + 1}-{end}")
        for start, end in zip(boundaries, boundaries[1:], strict=False)
        if start < end
    ]


class LineChunker:
    def __init__(self, maximum: int) -> None:
        self.maximum = maximum

    def chunks(self, source_id: str, version: int, blocks: list[ParsedBlock]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for block in blocks:
            # Exact excerpt offsets within a page/line block, never invented line coordinates.
            for start in range(0, len(block.text), self.maximum):
                text = block.text[start : start + self.maximum].strip()
                if not text:
                    continue
                ordinal = len(chunks)
                chunks.append(
                    Chunk(
                        chunk_id=str(uuid5(NAMESPACE_URL, f"adam:{source_id}:{version}:{ordinal}")),
                        source_id=source_id,
                        version=version,
                        ordinal=ordinal,
                        text=text,
                        locator=f"{block.locator};chars:{start}-"
                        f"{min(start + self.maximum, len(block.text))}",
                    )
                )
        return chunks
