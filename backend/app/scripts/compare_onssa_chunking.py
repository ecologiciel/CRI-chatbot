"""Compare source coverage for nine ONSSA chunking configurations, offline.

Run from the backend directory: python -m app.scripts.compare_onssa_chunking
This is not a retrieval or answer-quality evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import time
from pathlib import Path

import structlog

from app.services.rag.chunker import ChunkingService

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "docs" / "demos" / "onssa"


def validate_chunks(source: str, chunks: list, target: int) -> None:
    """Reject missing text, altered slices, gaps, and overlong chunks."""
    if not chunks or chunks[0].start_char != 0 or chunks[-1].end_char != len(source):
        raise ValueError("Chunks do not cover the complete source")
    if any(source[c.start_char : c.end_char] != c.content for c in chunks):
        raise ValueError("A chunk does not match its source offsets")
    if any(a.end_char < b.start_char for a, b in zip(chunks, chunks[1:], strict=False)):
        raise ValueError("There is a gap between source chunks")
    if any(c.token_count > target for c in chunks):
        raise ValueError("A chunk exceeds the target token limit")


def compare(root: Path = DEFAULT_ROOT) -> dict:
    """Measure deterministic chunk structure and exact candidate-span coverage."""
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    cases = json.loads((root / "evaluation-candidats.json").read_text(encoding="utf-8"))["cases"]
    documents = {
        source["slug"] + ".md": (root / "corpus" / (source["slug"] + ".md")).read_text(
            encoding="utf-8"
        )
        for source in manifest["sources"]
    }
    answerable = [case for case in cases if case["answerable"]]
    for case in answerable:
        if case["expected_passage"] not in documents[case["expected_document"]]:
            raise ValueError(f"Candidate passage is absent: {case['id']}")
    rows = []
    for target in (256, 512, 768):
        for percent in (0, 10, 20):
            overlap = target * percent // 100
            chunker = ChunkingService(chunk_size=target, overlap=overlap, max_chunk_size=target)
            by_document = {name: chunker.chunk_text(text) for name, text in documents.items()}
            chunks = [chunk for doc_chunks in by_document.values() for chunk in doc_chunks]
            for name, source in documents.items():
                doc_chunks = by_document[name]
                validate_chunks(source, doc_chunks, target)
            missing = [
                case["id"]
                for case in answerable
                if not any(
                    case["expected_passage"] in chunk.content
                    for chunk in by_document[case["expected_document"]]
                )
            ]
            rows.append(
                {
                    "target_tokens": target,
                    "overlap_percent": percent,
                    "overlap_tokens": overlap,
                    "chunk_count": len(chunks),
                    "indexed_tokens": sum(c.token_count for c in chunks),
                    "max_chunk_tokens": max(c.token_count for c in chunks),
                    "candidate_spans_contained": len(answerable) - len(missing),
                    "candidate_spans_total": len(answerable),
                    "candidate_spans_split": missing,
                }
            )
    return {
        "documents": len(documents),
        "candidate_labels_human_reviewed": sum(bool(c.get("human_reviewed")) for c in cases),
        "negative_cases_excluded": len(cases) - len(answerable),
        "results": rows,
        "limitations": "Structural span coverage only; not retrieval, citation, or answer accuracy.",
    }


def compare_pdf(path: Path) -> dict:
    """Measure extraction and chunk coverage on an explicitly supplied long PDF."""
    from app.services.rag.extractors import extract_document
    from app.services.rag.ingestion import _attach_pages

    data = path.read_bytes()
    extracted = extract_document(data, path.name)
    # Only standalone French article headings; this does not assess legal meaning.
    article_headings = list(
        re.finditer(r"(?im)^[ \t]*article[ \t]+[0-9]+[ \t]*[.:-]?[ \t]*\r?$", extracted.text)
    )
    articles = [
        (a.start(), b.start()) for a, b in zip(article_headings, article_headings[1:], strict=False)
    ]
    rows = []
    for target in (256, 512, 768):
        for percent in (0, 10, 20):
            started = time.perf_counter()
            chunker = ChunkingService(target, target * percent // 100, target)
            chunks = _attach_pages(chunker.chunk_text(extracted.text), extracted.pages)
            duration = time.perf_counter() - started
            validate_chunks(extracted.text, chunks, target)
            fit_articles = [
                (a, b) for a, b in articles if chunker.count_tokens(extracted.text[a:b]) <= target
            ]
            split_articles = [
                (a, b)
                for a, b in fit_articles
                if not any(chunk.start_char <= a and b <= chunk.end_char for chunk in chunks)
            ]
            rows.append(
                {
                    "target_tokens": target,
                    "overlap_percent": percent,
                    "chunk_count": len(chunks),
                    "indexed_tokens": sum(c.token_count for c in chunks),
                    "max_chunk_tokens": max(c.token_count for c in chunks),
                    "chunks_with_pages": sum(bool(c.page_numbers) for c in chunks),
                    "articles_fit": len(fit_articles),
                    "articles_split_despite_fit": len(split_articles),
                    "elapsed_seconds_single_run": round(duration, 3),
                }
            )
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "pages_with_extracted_text": len(extracted.pages),
        "extracted_characters": len(extracted.text),
        "standalone_article_headings": len(article_headings),
        "results": rows,
        "limitations": "One PDF, one timing per configuration; no OCR or semantic accuracy assessment.",
    }


def main() -> None:
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, help="Optional local PDF, not uploaded")
    args = parser.parse_args()
    report = {"onssa_fiches": compare()}
    if args.pdf:
        report["pdf"] = compare_pdf(args.pdf)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
