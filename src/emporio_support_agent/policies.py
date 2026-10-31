"""Page-aware PDF policy extraction and deterministic whole-section retrieval."""

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


class PolicyLoadError(ValueError):
    """A policy source cannot establish readable, versioned policy sections."""


@dataclass(frozen=True)
class PolicySource:
    filename: str
    sha256: str
    version: str


@dataclass(frozen=True)
class PolicyPage:
    page_number: int
    text: str


@dataclass(frozen=True)
class PolicySection:
    section_id: str
    title: str
    text: str
    page_start: int
    page_end: int


@dataclass(frozen=True)
class PolicyCorpus:
    source: PolicySource
    pages: tuple[PolicyPage, ...]
    sections: tuple[PolicySection, ...]


@dataclass
class _SectionBuilder:
    section_id: str
    title: str
    lines: list[str]
    page_start: int
    page_end: int


# Layout extraction retains the indentation distinguishing workflow steps
# from the supplied manual's left-aligned section/subsection headings.
_HEADING = re.compile(r"^([1-9][0-9]*(?:\.[0-9]+)*)\.?\s+(\S.*)$")
_VERSION = re.compile(r"\b(?:versão|versao|version)\s*[:\-]?\s*(\d+(?:\.\d+)*)\b", re.IGNORECASE)
_STOP_WORDS = frozenset("a as o os de da das do dos e em para por com the and of to in on for".split())


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _terms(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", _normalize(text))) - _STOP_WORDS


def _version(pages: tuple[PolicyPage, ...]) -> str:
    versions = {match for page in pages for match in _VERSION.findall(page.text)}
    if not versions:
        raise PolicyLoadError("policy version not found in source text")
    if len(versions) != 1:
        raise PolicyLoadError("conflicting policy version markers in source text")
    return versions.pop()


def _sections(pages: tuple[PolicyPage, ...]) -> tuple[PolicySection, ...]:
    first_lines = Counter(
        next((" ".join(line.split()) for line in page.text.splitlines() if line.strip()), "")
        for page in pages
    )
    running_headers = {
        line for line, count in first_lines.items()
        if line and count > 1 and not _HEADING.match(line)
    }
    builders: list[_SectionBuilder] = []
    active: list[_SectionBuilder] = []
    seen_ids = set()
    for page in pages:
        first_nonblank = True
        for raw_line in page.text.splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            is_running_header = first_nonblank and line in running_headers
            first_nonblank = False
            if is_running_header:
                continue
            if re.fullmatch(r"(?:pagina|page)\s+\d+", _normalize(line)):
                continue
            heading = _HEADING.match(raw_line)
            if heading:
                section_id, title = heading.groups()
                if section_id in seen_ids:
                    raise PolicyLoadError("duplicate section identifier in policy structure")
                active = [item for item in active if section_id.startswith(item.section_id + ".")]
                parent = section_id.rpartition(".")[0]
                if parent and (not active or active[-1].section_id != parent):
                    raise PolicyLoadError("policy subsection has no active parent section")
                builder = _SectionBuilder(section_id, " ".join(title.split()), [], page.page_number, page.page_number)
                builders.append(builder)
                active.append(builder)
                seen_ids.add(section_id)
            for item in active:
                item.lines.append(line)
                item.page_end = page.page_number
    if not builders:
        raise PolicyLoadError("numbered policy section structure not found")
    # A parent contains its complete subtree. A peer or higher-level heading
    # closes it. Subsections also remain separately retrievable in source order.
    return tuple(
        PolicySection(item.section_id, item.title, "\n".join(item.lines), item.page_start, item.page_end)
        for item in builders
    )


def load_policy_pdf(path: Path) -> PolicyCorpus:
    """Read one byte snapshot, hash it, and extract versioned sections.

    This parser targets numbered, left-aligned policy headings in text PDFs.
    Indented numbered lists are body text. It is not an OCR or universal PDF
    layout parser. Raw page text is retained alongside normalized sections.
    """
    try:
        source_bytes = path.read_bytes()
    except (OSError, ValueError):
        raise PolicyLoadError(f"{path.name}: could not read policy PDF") from None
    if not source_bytes.lstrip().startswith(b"%PDF-"):
        raise PolicyLoadError(f"{path.name}: invalid PDF source")
    try:
        reader = PdfReader(BytesIO(source_bytes))
        if reader.is_encrypted:
            raise ValueError("encrypted policy PDF")
        pages = tuple(
            PolicyPage(number, page.extract_text(
                extraction_mode="layout", layout_mode_space_vertically=False,
            ) or "")
            for number, page in enumerate(reader.pages, start=1)
        )
    except Exception:
        # Normalize third-party reader/extraction failures at this boundary;
        # do not include PDF contents or low-level source dumps in errors.
        raise PolicyLoadError(f"{path.name}: could not extract readable PDF pages") from None
    if not any(page.text.strip() for page in pages):
        raise PolicyLoadError(f"{path.name}: no extractable policy text")
    source = PolicySource(path.name, hashlib.sha256(source_bytes).hexdigest(), _version(pages))
    return PolicyCorpus(source, pages, _sections(pages))


def search_policy_sections(
    corpus: PolicyCorpus,
    query: str,
    *,
    limit: int = 3,
) -> tuple[PolicySection, ...]:
    """Match whole lexical terms after case/accent/punctuation normalization.

    Score = distinct matching text terms + twice the matching title terms.
    Common PT/EN stop words are ignored, with no stemming or semantic aliases.
    Equal scores retain source order. Return original complete section objects.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be non-blank text")
    if type(limit) is not int or limit <= 0:
        raise ValueError("limit must be a positive integer")
    terms = _terms(query)
    scored = []
    for position, section in enumerate(corpus.sections):
        score = len(terms & _terms(section.text)) + 2 * len(terms & _terms(section.title))
        if score:
            scored.append((score, position, section))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return tuple(section for _, _, section in scored[:limit])


def policy_section_provenance(corpus: PolicyCorpus, section: PolicySection) -> str:
    """Describe a member section's source without copying its policy text."""
    if section not in corpus.sections:
        raise ValueError("section does not belong to this corpus")
    pages = str(section.page_start) if section.page_start == section.page_end else f"{section.page_start}-{section.page_end}"
    source = corpus.source
    return f"{source.filename}; version={source.version}; section={section.section_id}; pages={pages}; sha256={source.sha256}"
