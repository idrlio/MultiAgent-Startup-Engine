"""
agents/research_agent.py
========================
Research agent — gathers market intelligence via web search and
synthesises it with Claude into a structured research report.
"""

from __future__ import annotations

from agents.base_agent import AgentResult, BaseAgent


class ResearchAgent(BaseAgent):
    name = "research"
    role = "Market Researcher — trends, competitors, data, web search"

    system_prompt = """You are a senior market research analyst at a venture-backed startup.
You have access to real market data, competitor information, and industry trends.

Using the search results and memory context provided, write a comprehensive research report.
Structure your output EXACTLY as follows:

## Market Overview
Estimated TAM, SAM, SOM. Growth rate and trajectory. Key market drivers.

## Competitor Landscape
| Competitor | Strengths | Weaknesses | Pricing | Differentiation |
(Include 4-6 competitors in table format)

## Key Trends
- Trend 1: [description and implication]
- Trend 2: ...
(List 4-6 actionable trends)

## Customer Pain Points
List the top 5 underserved pain points this startup could address.

## Risks & Opportunities
Two columns: Risks (with severity) | Opportunities (with potential impact)

## Research Conclusion
2-3 sentence synthesis: what does this market data mean for the startup?

Be specific, data-driven, and cite sources where possible.
"""

    def run(self, objective: str, context: dict[str, AgentResult]) -> AgentResult:
        """
        Search the web for market data, then synthesise a research report.

        The web search results are indexed in vector memory so all downstream
        agents can retrieve relevant snippets via RAG.

        Args:
            objective: The top-level startup goal.
            context:   Results from any prior agents (typically empty for research).

        Returns:
            AgentResult containing the structured research report.
        """
        from tools.web_search import WebSearch

        self._log.info("research.run.start")
        ws = WebSearch()

        # Derive search queries from the objective
        queries = [
            objective,
            f"{objective} market size trends 2025",
            f"{objective} competitors analysis",
            f"{objective} customer pain points",
        ]

        search_context_parts: list[str] = []
        for query in queries:
            block = ws.search_as_context(query, max_results=3)
            if block:
                search_context_parts.append(block)
                # Index search results in vector memory for downstream RAG
                if self.memory:
                    self.memory.index(block, source="web_search", query=query)

        search_context = "\n\n".join(search_context_parts)

        prompt = (
            f"## Objective\n{objective}\n\n"
            f"{self._build_context_block(context)}\n\n"
            f"{search_context}\n\n"
            "## Your Task\n"
            "Write the full research report now using the data above."
        )

        content = self._call_claude(prompt, index_response=True)
        self._log.info("research.run.complete", content_chars=len(content))

        return AgentResult(
            agent=self.name,
            content=content,
            metadata={"queries": queries, "mock_search": ws.using_mock},
        )
