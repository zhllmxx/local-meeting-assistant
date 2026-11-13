from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from local_agent import redact
from settings import value


@dataclass(frozen=True)
class ContextChunk:
    source: str
    text: str
    tokens: frozenset[str]
    ordinal: int


TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z][a-zA-Z0-9_+#.-]{1,}|\d+(?:\.\d+)?")


def _tokens(text: str) -> frozenset[str]:
    return frozenset(TOKEN_RE.findall(text.lower()))


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader

        return "\n\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    except Exception:
        try:
            import fitz

            return "\n\n".join(page.get_text() for page in fitz.open(path))
        except Exception:
            return ""


def _read_source(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        text = _extract_pdf(path)
    else:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""
    return redact(text)


def _chunk(source: str, text: str, max_chars: int = 2400) -> list[ContextChunk]:
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text:
        return []
    paragraphs = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n+", text)]
    paragraphs = [p for p in paragraphs if p]
    chunks: list[ContextChunk] = []
    buffer = ""
    ordinal = 0
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if buffer:
                chunks.append(ContextChunk(source, buffer, _tokens(buffer), ordinal))
                ordinal += 1
                buffer = ""
            for start in range(0, len(paragraph), max_chars - 240):
                part = paragraph[start : start + max_chars]
                if part:
                    chunks.append(ContextChunk(source, part, _tokens(part), ordinal))
                    ordinal += 1
            continue
        candidate = f"{buffer}\n{paragraph}" if buffer else paragraph
        if len(candidate) > max_chars and buffer:
            chunks.append(ContextChunk(source, buffer, _tokens(buffer), ordinal))
            ordinal += 1
            buffer = paragraph
        else:
            buffer = candidate
    if buffer:
        chunks.append(ContextChunk(source, buffer, _tokens(buffer), ordinal))
    return chunks


class KnowledgeBase:
    """Small deterministic local retriever for resume and interview materials."""

    def __init__(self, root: str | Path, sources=None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.chunks: list[ContextChunk] = []
        self.loaded_sources: list[str] = []
        if sources is None:
            sources = value("MEETING_KNOWLEDGE_SOURCES", [])
            if isinstance(sources, str):
                import json
                sources = json.loads(sources)
            if not sources and self.root.is_dir():
                sources = [(path.name, path.name) for path in sorted(self.root.iterdir())
                           if path.suffix.lower() in {".md", ".txt", ".pdf"} and path.is_file()]
        for label, relative_path in sources:
            relative = Path(relative_path)
            path = (self.root / relative).resolve()
            if relative.is_absolute() or ".." in relative.parts or self.root not in path.parents:
                raise ValueError("Knowledge sources must stay beneath the material directory.")
            if (self.root / relative).is_symlink():
                continue
            text = _read_source(path)
            if not text:
                continue
            self.loaded_sources.append(label)
            self.chunks.extend(_chunk(label, text))

    def retrieve(self, query: str, max_chars: int = 14000, limit: int = 8) -> str:
        if not self.chunks:
            return "（当前 session 没有可读取的简历或面经材料。）"
        query_tokens = _tokens(query)
        scored: list[tuple[float, int, ContextChunk]] = []
        for chunk in self.chunks:
            overlap = len(query_tokens & chunk.tokens)
            phrase_bonus = 2.0 if query.strip() and query.strip().lower() in chunk.text.lower() else 0.0
            source_bonus = 0.35 if chunk.source.startswith("简历") else 0.0
            score = overlap * 3.0 + phrase_bonus + source_bonus
            scored.append((score, -chunk.ordinal, chunk))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected: list[ContextChunk] = []
        resume = [item for item in scored if item[2].source.startswith("简历")]
        if resume:
            selected.append(resume[0][2])
        selected.extend(item[2] for item in scored if item[0] > 0 and item[2] not in selected)
        selected = selected[:limit]
        if not selected:
            selected = [chunk for chunk in self.chunks if chunk.ordinal == 0][:3]
        output: list[str] = []
        used = 0
        for chunk in selected:
            block = f"[{chunk.source}]\n{chunk.text}"
            if used + len(block) > max_chars:
                break
            output.append(block)
            used += len(block)
        return "\n\n".join(output)
