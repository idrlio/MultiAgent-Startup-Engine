"""
tools/web_search.py
Web search integration via Tavily API.
Provides a clean interface for agents to query the web.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    score: float = 0.0

    def __str__(self) -> str:
        return f"[{self.score:.2f}] {self.title}\n{self.url}\n{self.content[:300]}"


class WebSearch:
    """
    Thin wrapper around the Tavily search API.

    Usage:
        searcher = WebSearch()
        results = searcher.search("AI startup tools 2025", max_results=5)
        for r in results:
            print(r)
    """

    def __init__(self, api_key: str | None = None) -> None:
        from config import settings

        key = api_key or settings.tavily_api_key
        if not key:
            raise ValueError("TAVILY_API_KEY is not set. Add it to your .env file.")

        try:
            from tavily import TavilyClient  # type: ignore

            self._client = TavilyClient(api_key=key)
        except ImportError as exc:
            raise RuntimeError("Install tavily: pip install tavily-python") from exc

        logger.info("web_search.ready")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
    ) -> list[SearchResult]:
        """
        Execute a web search.

        Args:
            query:        Search query string.
            max_results:  Number of results to return (max 10).
            search_depth: "basic" (fast) or "advanced" (thorough).

        Returns:
            List of SearchResult objects sorted by relevance score.
        """
        logger.info("web_search.query", query=query, max_results=max_results)
        response = self._client.search(
            query=query,
            max_results=min(max_results, 10),
            search_depth=search_depth,
        )

        results = [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
                score=r.get("score", 0.0),
            )
            for r in response.get("results", [])
        ]
        logger.info("web_search.results", count=len(results))
        return results

    def search_as_text(self, query: str, max_results: int = 5) -> str:
        """Return search results as a formatted string block."""
        results = self.search(query, max_results=max_results)
        if not results:
            return "No results found."
        lines = [f"Search results for: {query!r}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.title}\n   {r.url}\n   {r.content[:200]}\n")
        return "\n".join(lines)
