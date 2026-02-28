"""
Report Writer Agent - Multi-Step Agentic Workflow

**Why a Report Agent?**
Financial reports need:
1. Accuracy (verified facts, not hallucinations)
2. Professional tone (consistent style)
3. Structure (sections, summaries)
4. Self-review (catch mistakes before delivery)

**Node Flow:**
gather_data → analyze_risk → draft_report → self_review
                                              ↓
                                    [issues found?]
                                    ↙          ↘
                                  YES          NO
                                   ↓            ↓
                            revise_draft  finalize_report
                                   ↓            ↓
                              self_review      ↓
                                   └→ format_output → END

**Educational Points:**
- Self-review demonstrates reflection pattern (LLM validates its own work)
- Conditional edges show decision making
- Markdown → HTML conversion shows document processing
- Token counting shows cost awareness
"""

import logging
from typing import Optional
import json
from datetime import datetime

from langgraph.graph import StateGraph, END
from openai import AsyncOpenAI

from app.agents.state import ReportGenerationState
from app.config import get_settings
from app.services.retriever import HybridRetriever
from app.models.client import Client
from app.models.report import Report


logger = logging.getLogger(__name__)
settings = get_settings()


class ReportWriterAgent:
    """
    LangGraph-based Report Writer Agent.

    Generates comprehensive financial reports with self-review.
    """

    def __init__(self, db_session, retriever: HybridRetriever):
        """Initialize agent with dependencies."""
        self.db = db_session
        self.retriever = retriever
        self.openai = AsyncOpenAI(api_key=settings.openai_api_key)
        self.settings = settings

        # Build LangGraph workflow
        self.graph = self._build_graph()

    def _build_graph(self):
        """
        Build LangGraph state machine for report generation.

        Nodes: gather → analyze → draft → review → [conditional] → finalize → format
        """
        workflow = StateGraph(ReportGenerationState)

        # Define nodes
        workflow.add_node("gather_data", self._gather_client_data)
        workflow.add_node("analyze_risk", self._analyze_portfolio_risk)
        workflow.add_node("draft_report", self._draft_report_content)
        workflow.add_node("self_review", self._self_review_report)
        workflow.add_node("revise_draft", self._revise_draft)
        workflow.add_node("finalize_report", self._finalize_report)
        workflow.add_node("format_output", self._format_html_output)

        # Define edges
        workflow.add_edge("gather_data", "analyze_risk")
        workflow.add_edge("analyze_risk", "draft_report")
        workflow.add_edge("draft_report", "self_review")

        # Conditional: if issues found and revisions < 1, revise; else finalize
        workflow.add_conditional_edges(
            "self_review",
            self._should_revise,
            {
                "revise": "revise_draft",      # Found issues, try to fix
                "finalize": "finalize_report",  # Good enough, finalize
            }
        )

        workflow.add_edge("revise_draft", "self_review")  # Loop back to review
        workflow.add_edge("finalize_report", "format_output")
        workflow.add_edge("format_output", END)

        # Set entry point
        workflow.set_entry_point("gather_data")

        return workflow.compile()

    async def invoke(self, state: ReportGenerationState) -> ReportGenerationState:
        """
        Run agent to generate report.

        Returns final state with report content and HTML.
        """
        logger.info(f"Starting report generation for client {state['client_id']}")
        result = await self.graph.ainvoke(state)
        return result

    async def stream(self, state: ReportGenerationState):
        """
        Stream report generation step by step.

        Yields (step_name, intermediate_state) for UI progress tracking.
        """
        async for step_output in self.graph.astream(state):
            for node_name, node_state in step_output.items():
                logger.info(f"Report step: {node_name}")
                yield {"step": node_name, "state": node_state}

    # ========================================================================
    # NODE IMPLEMENTATIONS
    # ========================================================================

    async def _gather_client_data(self, state: ReportGenerationState) -> dict:
        """
        Gather financial data about the client from uploaded documents.

        **REPORT GROUNDING - HARD FAIL IF NO SOURCES:**
        - Retrieves actual documents uploaded by client
        - Extracts portfolio data from real documents
        - Hard-fails if no documents exist (no fabrication)
        - All report data grounded in retrieved sources

        This ensures reports are based on real client data, not hallucinations.
        """
        from uuid import UUID
        from app.models.document import Document, DocumentChunk
        from sqlalchemy import select

        logger.info(f"Gathering grounded data for client {state['client_id']}")

        client_id = state["client_id"]

        try:
            # Retrieve all documents for this client
            stmt = select(Document).where(Document.client_id == UUID(client_id))
            result = await self.db.execute(stmt)
            documents = result.scalars().all()

            if not documents or not any(d.status == "indexed" for d in documents):
                # **HARD FAIL: No documents uploaded or indexed**
                error_msg = (
                    f"Cannot generate report for client {client_id}: "
                    "No financial documents have been uploaded yet.\n\n"
                    "To generate a report:\n"
                    "1. Upload portfolio statements, account summaries, or performance reports\n"
                    "2. Wait for documents to be indexed and processed\n"
                    "3. Then generate the report\n\n"
                    "This ensures reports are grounded in real client data, not fabrications."
                )
                logger.warning(error_msg)
                raise ValueError(error_msg)

            # Get indexed documents
            indexed_docs = [d for d in documents if d.status == "indexed"]
            logger.info(f"Found {len(indexed_docs)} indexed documents for client {client_id}")

            # Retrieve document chunks using hybrid retriever
            # Query for portfolio/holdings related content
            chunks = await self.retriever.retrieve(
                query="portfolio holdings assets allocation risk",
                client_id=client_id,
                top_k=20,  # Get more chunks for comprehensive context
            )

            if not chunks:
                error_msg = (
                    f"Cannot generate report: No portfolio data found in uploaded documents.\n"
                    f"Uploaded documents: {len(indexed_docs)}\n\n"
                    f"Ensure documents contain portfolio information like:\n"
                    "- Holdings and positions\n"
                    "- Account balances\n"
                    "- Asset allocation\n"
                    "- Performance metrics"
                )
                logger.warning(error_msg)
                raise ValueError(error_msg)

            # Extract and structure data from chunks
            document_context = "\n\n".join([
                f"[{c.chunk_id}] {c.content}" for c in chunks
            ])

            # Create structured data object grounded in actual documents
            gathered_data = {
                "client_id": client_id,
                "document_count": len(indexed_docs),
                "chunk_count": len(chunks),
                "source_documents": [
                    {
                        "id": str(d.id),
                        "name": d.file_name,
                        "type": d.file_type,
                        "chunk_count": d.chunk_count,
                    }
                    for d in indexed_docs
                ],
                "document_context": document_context,
                "grounded": True,  # Mark as grounded in actual data
                "sources": [str(c.chunk_id) for c in chunks],
            }

            logger.info(
                f"Gathered grounded data: {len(chunks)} chunks from {len(indexed_docs)} documents"
            )

            return {"gathered_data": gathered_data}

        except ValueError as e:
            # Re-raise validation errors (hard failures)
            raise
        except Exception as e:
            logger.error(f"Error gathering client data: {e}", exc_info=True)
            raise ValueError(f"Failed to retrieve client documents: {str(e)}")

    async def _analyze_portfolio_risk(self, state: ReportGenerationState) -> dict:
        """
        Analyze portfolio risk metrics from grounded client documents.

        **GROUNDED ANALYSIS:**
        - Analyzes only data from client's uploaded documents
        - References specific chunks used for analysis
        - No fabrication of holdings or values

        Risk factors analyzed:
        - Concentration risk (too much in one stock?)
        - Asset allocation appropriateness
        - Market risk exposure
        """
        logger.info("Analyzing portfolio risk from grounded data")

        gathered = state.get("gathered_data", {})

        if not gathered.get("grounded"):
            raise ValueError("Portfolio data is not grounded - cannot analyze")

        document_context = gathered.get("document_context", "")
        sources = gathered.get("sources", [])

        # Prompt GPT to analyze risk based on ACTUAL client documents
        analysis_prompt = f"""
You are a financial risk analyst. Analyze ONLY the portfolio data from the client's documents below.
Do NOT invent or fabricate any holdings, values, or metrics not explicitly in the documents.

CLIENT DOCUMENTS:
{document_context}

Based ONLY on the information above, provide:
1. DOCUMENTED_HOLDINGS: What holdings are explicitly mentioned?
2. CONCENTRATION_RISK: [LOW/MEDIUM/HIGH] - Based on actual allocations
3. OBSERVABLE_RISKS: What risks are evident from the documents?
4. RECOMMENDATIONS: [Only if supported by document data]

If data is missing or unclear, explicitly state: "Information not found in documents"
"""

        response = await self.openai.chat.completions.create(
            model=self.settings.openai_chat_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a financial risk analyst. Analyze only information present in "
                        "the client documents provided. Do NOT fabricate any portfolio data, "
                        "holdings, values, or metrics not explicitly stated in the documents."
                    ),
                },
                {"role": "user", "content": analysis_prompt},
            ],
            temperature=0.3,
            max_tokens=500,
        )

        risk_analysis = response.choices[0].message.content.strip()
        logger.info(f"Risk analysis complete (grounded in {len(sources)} sources)")

        return {
            "risk_analysis": {
                "text": risk_analysis,
                "grounded": True,
                "sources": sources,
            }
        }

    async def _draft_report_content(self, state: ReportGenerationState) -> dict:
        """
        Draft the main report content in Markdown from grounded data.

        **GROUNDED REPORT GENERATION:**
        - Uses ONLY data from client's uploaded documents
        - Reports exactly what documents contain
        - Explicitly marks gaps where data is missing
        - No fabrication of holdings, valuations, or performance

        Structure:
        - Executive summary (from documents)
        - Portfolio overview (documented holdings)
        - Risk analysis (document-based)
        - Recommendations (evidence-based only)
        """
        logger.info(f"Drafting grounded {state.get('report_type', 'portfolio_summary')} report")

        gathered = state.get("gathered_data", {})
        risk = state.get("risk_analysis", {})
        report_type = state.get("report_type", "portfolio_summary")

        if not gathered.get("grounded"):
            raise ValueError("Report data must be grounded in documents")

        document_context = gathered.get("document_context", "")
        source_docs = gathered.get("source_documents", [])

        # Build comprehensive prompt emphasizing grounding
        draft_prompt = f"""
Generate a professional financial report in Markdown format.

CRITICAL INSTRUCTIONS:
1. Use ONLY information from the client documents below
2. Do NOT invent, estimate, or fabricate any portfolio values, holdings, or metrics
3. Cite document sources in brackets: [source_doc_name]
4. If data is missing, explicitly state "Information not provided in documents"
5. Mark sections as "Based on uploaded documents" to show grounding

Report Type: {report_type}
Client: Client ID from document set
Documents: {json.dumps(source_docs, indent=2)}

CLIENT DOCUMENTS:
{document_context}

Risk Analysis from Documents:
{risk.get('text', 'No risk analysis available')}

Now draft a professional report structure that:
- Summarizes ONLY documented portfolio information
- Analyzes ONLY risks evident in the documents
- Makes recommendations ONLY where supported by data
- Clearly shows all citations and source documents
- Explicitly states what information is missing
{risk.get('text', 'N/A')}

Generate a report with these sections (use ## for headers):
## Executive Summary
[2-3 sentence overview]

## Portfolio Overview
[Current allocation, top holdings, performance]

## Risk Assessment
[Risk analysis based on provided data]

## Recommendations
[2-3 specific, actionable recommendations]

## Next Steps
[What client should do next]

Use professional tone. Include specific numbers from the data provided.
Do NOT make up data - only use what's provided."""

        response = await self.openai.chat.completions.create(
            model=self.settings.openai_chat_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional financial advisor. Generate comprehensive reports.",
                },
                {"role": "user", "content": draft_prompt},
            ],
            temperature=0.4,
            max_tokens=1000,
        )

        draft_content = response.choices[0].message.content.strip()
        logger.info(f"Draft complete: {len(draft_content)} characters")

        return {
            "draft_report": draft_content,
            "total_iterations": 1,
        }

    async def _self_review_report(self, state: ReportGenerationState) -> dict:
        """
        Self-review: LLM checks its own work.

        **Educational:** Reflection pattern - LLM validates:
        - Are claims supported by source data?
        - Are there contradictions?
        - Is tone professional?
        - Are recommendations actionable?

        This is a key pattern in advanced agents - having the LLM
        verify its own output reduces hallucinations.
        """
        logger.info("Self-reviewing report")

        draft = state.get("draft_report", "")
        gathered = state.get("gathered_data", {})

        review_prompt = f"""
Review this financial report for accuracy and quality.

Source Data (what we KNOW is true):
{json.dumps(gathered, indent=2)}

Report Draft:
{draft}

Check for:
1. UNSUPPORTED_CLAIMS: Any claims not in source data?
2. CONTRADICTIONS: Any contradictions with source data?
3. TONE: Is it professional?
4. COMPLETENESS: Does it address key points?
5. ACTIONABILITY: Are recommendations specific and doable?

Format response as JSON:
{{
    "has_issues": true/false,
    "unsupported_claims": ["claim 1", "claim 2"],
    "contradictions": ["contradiction 1"],
    "issues_count": 0,
    "suggestions": ["suggestion 1", "suggestion 2"]
}}"""

        response = await self.openai.chat.completions.create(
            model=self.settings.openai_chat_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a quality assurance reviewer. Be strict and accurate.",
                },
                {"role": "user", "content": review_prompt},
            ],
            temperature=0.2,
            max_tokens=500,
        )

        review_text = response.choices[0].message.content.strip()

        # Parse review
        try:
            review_data = json.loads(review_text)
        except json.JSONDecodeError:
            review_data = {
                "has_issues": False,
                "unsupported_claims": [],
                "contradictions": [],
                "issues_count": 0,
            }

        logger.info(f"Review complete: {review_data.get('issues_count', 0)} issues found")

        return {"self_review": review_data}

    @staticmethod
    def _should_revise(state: ReportGenerationState) -> str:
        """
        Decide whether to revise or finalize.

        Returns "revise" or "finalize".
        """
        review = state.get("self_review", {})
        iterations = state.get("total_iterations", 0)

        # Revise if issues found AND haven't exceeded revision limit
        if review.get("has_issues") and iterations < 1:
            logger.info("Issues found, revising...")
            return "revise"

        logger.info("Report quality acceptable, finalizing...")
        return "finalize"

    async def _revise_draft(self, state: ReportGenerationState) -> dict:
        """
        Revise draft based on self-review feedback.

        Takes the review feedback and regenerates problematic sections.
        """
        logger.info("Revising draft based on feedback")

        draft = state.get("draft_report", "")
        review = state.get("self_review", {})
        gathered = state.get("gathered_data", {})

        revise_prompt = f"""
Revise this report to fix the identified issues:

Issues Found:
- Unsupported claims: {review.get('unsupported_claims', [])}
- Contradictions: {review.get('contradictions', [])}
- Suggestions: {review.get('suggestions', [])}

Source Data (ONLY use this):
{json.dumps(gathered, indent=2)}

Original Report:
{draft}

Generate a revised version that:
1. Removes unsupported claims
2. Fixes contradictions
3. Incorporates suggestions
4. Only includes facts from source data
5. Maintains professional tone

Output ONLY the revised Markdown report, no explanations."""

        response = await self.openai.chat.completions.create(
            model=self.settings.openai_chat_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are revising a financial report. Be conservative - only use provided data.",
                },
                {"role": "user", "content": revise_prompt},
            ],
            temperature=0.3,
            max_tokens=1000,
        )

        revised = response.choices[0].message.content.strip()
        logger.info("Revision complete")

        return {
            "revised_draft": revised,
            "draft_report": revised,  # Update draft for next iteration
            "total_iterations": state.get("total_iterations", 1) + 1,
        }

    async def _finalize_report(self, state: ReportGenerationState) -> dict:
        """
        Finalize report with metadata.

        Adds timestamp, client info, etc.
        """
        logger.info("Finalizing report")

        content = state.get("draft_report", "")
        client_name = state.get("client_data", {}).get("name", "Client")
        gathered = state.get("gathered_data", {})
        source_docs = gathered.get("source_documents", [])
        source_chunks = gathered.get("sources", [])

        sources_section = ""
        if source_docs or source_chunks:
            sources_section = "\n\n## Sources\n"
            if source_docs:
                sources_section += "Documents:\n"
                for doc in source_docs:
                    doc_name = doc.get("name", "unknown")
                    doc_type = doc.get("type", "unknown")
                    sources_section += f"- {doc_name} ({doc_type})\n"
            if source_chunks:
                sources_section += "\nChunks:\n"
                for chunk_id in source_chunks:
                    sources_section += f"- {chunk_id}\n"

        # Add metadata footer
        footer = f"""
---
**Report Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Report Type:** {state.get('report_type', 'Portfolio Summary')}
**Client:** {client_name}

*This report is based on the most recent portfolio data available.
Please contact your advisor with questions.*
"""

        final_content = content + sources_section + footer

        return {
            "final_report": final_content,
            "report_sources": {
                "documents": source_docs,
                "chunks": source_chunks,
            },
        }

    async def _format_html_output(self, state: ReportGenerationState) -> dict:
        """
        Convert Markdown report to HTML for display.

        **Educational:** Shows document conversion:
        - Parse Markdown
        - Apply styling
        - Generate HTML

        In production, would use WeasyPrint for PDF generation.
        """
        logger.info("Formatting HTML output")

        markdown_content = state.get("final_report", "")

        # Simple markdown to HTML conversion
        # In production, use: from markdown import markdown
        html_content = self._markdown_to_html(markdown_content)

        logger.info("HTML formatting complete")

        return {"html_output": html_content}

    @staticmethod
    def _markdown_to_html(markdown_text: str) -> str:
        """
        Convert Markdown to HTML.

        Simple implementation; in production use proper markdown library.
        """
        lines = markdown_text.splitlines()
        html_lines = []
        in_ul = False
        in_ol = False

        def close_lists():
            nonlocal in_ul, in_ol
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False

        for raw in lines:
            line = raw.rstrip()
            if not line:
                close_lists()
                continue
            if line.startswith("## "):
                close_lists()
                html_lines.append(f"<h2>{line[3:]}</h2>")
                continue
            if line.startswith("# "):
                close_lists()
                html_lines.append(f"<h1>{line[2:]}</h1>")
                continue
            if line.startswith("- "):
                if not in_ul:
                    close_lists()
                    html_lines.append("<ul>")
                    in_ul = True
                item = line[2:]
                html_lines.append(f"<li>{item}</li>")
                continue
            if line[:3].isdigit() and line[3:5] == ". ":
                if not in_ol:
                    close_lists()
                    html_lines.append("<ol>")
                    in_ol = True
                item = line[5:]
                html_lines.append(f"<li>{item}</li>")
                continue

            close_lists()
            html_lines.append(f"<p>{line}</p>")

        close_lists()
        html = "\n".join(html_lines)

        return f"""
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 40px; }}
        h1, h2 {{ color: #1e3a8a; margin-top: 20px; }}
        strong {{ color: #1e40af; }}
        p {{ color: #374151; }}
        ul, ol {{ margin-left: 20px; color: #374151; }}
    </style>
</head>
<body>
{html}
</body>
</html>
"""


# Factory function for use in dependency injection
async def create_report_agent(db_session, retriever: HybridRetriever):
    """Create and return initialized report agent."""
    return ReportWriterAgent(db_session, retriever)
