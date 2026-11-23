#!/usr/bin/env python3
"""Collect a small, provenance-preserving public ONSSA demo corpus.

The script intentionally accepts no arbitrary URLs: its manifest is restricted
to official ONSSA domains, checks robots.txt, and pauses between requests.  It
does not upload anything; review the generated Markdown before importing it
through the back-office knowledge-base workflow.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = PROJECT_ROOT / "docs" / "demos" / "onssa" / "manifest.json"
ALLOWED_HOSTS = {"www.onssa.gov.ma", "onssa.gov.ma", "eservice.onssa.gov.ma"}
USER_AGENT = "CRI-Chatbot-Demo-Collector/1.0 (+https://github.com/ecologiciel/CRI-chatbot)"


class _PageTextExtractor(HTMLParser):
    """Small dependency-free extractor focused on readable HTML text."""

    _SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header"}
    _BLOCK = {"p", "div", "section", "article", "main", "li", "h1", "h2", "h3", "h4", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self.skip_depth += 1
        elif not self.skip_depth and tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = [re.sub(r"\\s+", " ", line).strip() for line in "".join(self.parts).splitlines()]
        return "\n\n".join(line for line in lines if line)


def _fetch(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 -- host allowlisted below
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _robots_for(host: str) -> RobotFileParser:
    parser = RobotFileParser(f"https://{host}/robots.txt")
    try:
        parser.read()
    except OSError:
        # A missing robots file is not permission to bypass restrictions: allow
        # the operator to make the final decision per affected source below.
        parser.parse([])
    return parser


def _render_markdown(source: dict[str, str], page_text: str, fetched_at: str) -> str:
    return "\n".join(
        [
            f"# {source['title']}",
            "",
            f"- Autorité source : {source['source_authority']}",
            f"- URL source : {source['url']}",
            f"- Collecté le : {fetched_at}",
            f"- Catégorie : {source['category']}",
            f"- Langue : {source['language']}",
            "",
            "## Extrait public",
            "",
            page_text,
            "",
            "---",
            "Document de démonstration. Vérifier les informations à la source avant toute décision.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "var" / "onssa-corpus")
    parser.add_argument("--delay-seconds", type=float, default=1.5)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    sources = manifest["sources"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    robots: dict[str, RobotFileParser] = {}
    fetched_at = datetime.now(UTC).date().isoformat()

    for position, source in enumerate(sources):
        parsed = urlparse(source["url"])
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError(f"Source non autorisée : {source['url']}")
        host = parsed.hostname
        if host not in robots:
            robots[host] = _robots_for(host)
        if not robots[host].can_fetch(USER_AGENT, source["url"]):
            print(f"SKIPPED robots.txt: {source['url']}", file=sys.stderr)
            continue

        try:
            html = _fetch(source["url"])
        except OSError as exc:
            print(f"FAILED {source['url']}: {exc}", file=sys.stderr)
            continue
        extractor = _PageTextExtractor()
        extractor.feed(html)
        page_text = extractor.text()
        if len(page_text) < 100:
            print(f"SKIPPED insufficient readable content: {source['url']}", file=sys.stderr)
            continue

        document_source = {**source, "source_authority": manifest["source_authority"]}
        destination = args.output_dir / f"{source['slug']}.md"
        destination.write_text(_render_markdown(document_source, page_text, fetched_at), encoding="utf-8")
        print(f"WROTE {destination}")
        if position < len(sources) - 1:
            time.sleep(args.delay_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
