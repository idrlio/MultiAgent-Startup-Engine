"""
tools/web_search.py
===================
Web search tool with Tavily backend and automatic mock fallback.

- If TAVILY_API_KEY is set: calls the real Tavily API.
- If not set (or on API error): falls back to a deterministic mock that
  returns realistic-looking placeholder results so the rest of the system
  can be exercised without an API key.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    url: str
    content: str
    score: float = 0.0

    def __str__(self) -> str:
        return f"[{self.score:.2f}] {self.title}\n{self.url}\n{self.content[:300]}"


class MockSearchBackend:
    """
    Deterministic mock search backend — no API key required.
    Returns plausible placeholder results derived from the query hash.
    Useful for local development and CI.
    """

    _TEMPLATES = [
        ("{query} Market Report 2025",
         "https://example-research.com/{slug}",
         "The {query} market is projected to reach $12.4B by 2027, "
         "growing at a CAGR of 18.3%. Key players include incumbents and "
         "emerging AI-native startups competing on automation and integrations."),
        ("Top {query} Competitors & Alternatives",
         "https://g2.com/categories/{slug}",
         "Leading solutions in the {query} space include established SaaS "
         "platforms and newer entrants. Feature differentiation centres on "
         "AI capabilities, pricing model, and ecosystem integrations."),
        ("{query} Industry Trends 2025",
         "https://example-insights.com/{slug}-trends",
         "Three macro trends are reshaping {query}: (1) AI-first workflows "
         "replacing manual processes, (2) API-first architectures enabling "
         "composable stacks, (3) usage-based pricing replacing seat licences."),
        ("How to build a {query} startup",
         "https://techcrunch.com/{slug}-startup-guide",
         "Founders entering the {query} space should focus on a narrow ICP, "
         "ship a functional MVP within 8 weeks, and validate willingness-to-pay "
         "before expanding the feature set."),
        ("{query} Venture Capital Funding Landscape",
         "https://crunchbase.com/discover/{slug}",
         "VC investment in {query} totalled $3.2B in 2024. Seed rounds "
         "average $1.8M; Series A averages $12M. Investors prioritise "
         "retention metrics, NRR, and AI differentiation."),
    ]

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        slug = query.lower().replace(" ", "-")[:30]
        h = int(hashlib.md5(query.encode()).hexdigest(), 16)
        results = []
        for i, (title_t, url_t, content_t) in enumerate(self._TEMPLATES[:max_results]):
            score = round(0.95 - i * 0.07, 2)
            results.append(SearchResult(
                title=title_t.format(query=query.title(), slug=slug),
                url=url_t.format(slug=slug),
                content=content_t.format(query=query.lower()),
                score=score,
            ))
        return results


class TavilyBackend:
    """Live Tavily API backend."""

    def __init__(self, api_key: str) -> None:
        try:
            from tavily import TavilyClient  # type: ignore
            self._client = TavilyClient(api_key=api_key)
        except ImportError as exc:
            raise RuntimeError("pip install tavily-python") from exc

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        response = self._client.search(
            query=query,
            max_results=min(max_results, 10),
            search_depth="basic",
        )
        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
                score=r.get("score", 0.0),
            )
            for r in response.get("results", [])
        ]


class WebSearch:
    """
    Unified web search interface.

    Automatically uses TavilyBackend when TAVILY_API_KEY is configured,
    and falls back to MockSearchBackend otherwise.

    Usage::

        ws = WebSearch()
        results = ws.search("B2B SaaS CRM market size", max_results=5)
        for r in results:
            print(r)

        # Get pre-formatted text block for prompt injection
        block = ws.search_as_context("competitor analysis CRM tools")
    """

    def __init__(self) -> None:
        from config import settings
        if settings.tavily_api_key:
            try:
                self._backend = TavilyBackend(settings.tavily_api_key)
                self._using_mock = False
                logger.info("web_search.backend", backend="tavily")
            except Exception as exc:
                logger.warning("web_search.tavily_init_failed", error=str(exc))
                self._backend = MockSearchBackend()
                self._using_mock = True
        else:
            self._backend = MockSearchBackend()
            self._using_mock = True
            logger.info("web_search.backend", backend="mock")

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """
        Search the web (or mock) for *query*.

        Args:
            query:       Search query string.
            max_results: Maximum number of results (1–10).

        Returns:
            List of SearchResult sorted by relevance.
        """
        logger.info("web_search.query", query=query, max_results=max_results, mock=self._using_mock)
        results = self._backend.search(query, max_results=max_results)
        logger.info("web_search.done", returned=len(results))
        return results

    def search_as_context(self, query: str, max_results: int = 5) -> str:
        """
        Return search results as a Markdown context block for prompt injection.

        Returns an empty string when no results are found.
        """
        results = self.search(query, max_results=max_results)
        if not results:
            return ""
        source = "mock" if self._using_mock else "web"
        lines = [f"## Web Search Results [{source}] — Query: {query!r}\n"]
        for i, r in enumerate(results, 1):
            lines.append(
                f"### Result {i}: {r.title}\n"
                f"Source: {r.url}  (relevance: {r.score:.2f})\n"
                f"{r.content}\n"
            )
        return "\n".join(lines)

    @property
    def using_mock(self) -> bool:
        return self._using_mock
