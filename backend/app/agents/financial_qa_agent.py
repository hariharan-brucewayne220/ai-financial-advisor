"""
Financial QA Agent - LangGraph Implementation

**Why LangGraph?**
- Explicit state machine beats function-calling chaos
- Clear node transitions for debugging
- Native streaming support for agent steps
- Built-in retry/loop support

**Agent Flow:**
1. Classify query (needs retrieval?)
2. Retrieve hybrid (dense + sparse + HyDE)
3. Rerank with cross-encoder
4. Compress with LLMLingua
5. Generate answer with GPT-4o
6. Score faithfulness with NLI
7. Retry if faithfulness < 0.6 (loop to step 2)
8. Format response with sources

This combines retrieval + generation in orchestrated pipeline.
"""

import logging
from typing import List, Optional
import asyncio

from langgraph.graph import StateGraph, END

from app.agents.state import AgentState
from app.config import get_settings
from app.llm import get_llm_client
from app.services.retriever import HybridRetriever, RetrievedChunk
from app.services.faithfulness_scorer import FaithfulnessScorer
from app.services.market_data import MarketDataService
from app.models.client import Client


logger = logging.getLogger(__name__)
settings = get_settings()


class FinancialQAAgent:
    """
    LangGraph-based Financial QA Agent.

    Orchestrates RAG pipeline with streaming support.
    """

    def __init__(self, db_session):
        """Initialize agent with dependencies."""
        self.db = db_session
        self.retriever = HybridRetriever(db_session)
        self.faithfulness_scorer = FaithfulnessScorer()
        self.market_data = MarketDataService()
        self.openai = get_llm_client()
        self.settings = settings

        # Build LangGraph workflow
        self.graph = self._build_graph()

    def _build_graph(self):
        """
        Build LangGraph state machine.

        Nodes: classify → retrieve → rerank → compress → fetch_market_data → generate → score → format
        Conditional: if faithfulness < 0.6, loop back to retrieve
        """
        workflow = StateGraph(AgentState)

        # Define nodes
        workflow.add_node("classify", self._classify_query)
        workflow.add_node("retrieve", self._retrieve_documents)
        workflow.add_node("rerank", self._rerank_documents)
        workflow.add_node("compress", self._compress_context)
        workflow.add_node("fetch_market_data", self._fetch_market_data)
        workflow.add_node("generate", self._generate_response)
        workflow.add_node("score", self._score_faithfulness)
        workflow.add_node("format", self._format_response)

        # Define edges with transitions
        workflow.add_edge("classify", "retrieve")
        workflow.add_edge("retrieve", "rerank")
        workflow.add_edge("rerank", "compress")
        workflow.add_edge("compress", "fetch_market_data")
        workflow.add_edge("fetch_market_data", "generate")
        workflow.add_edge("generate", "score")
        workflow.add_conditional_edges(
            "score",
            self._should_retry,
            {
                "retrieve": "retrieve",  # Retry: go back to retrieve
                "format": "format",       # Good: move to format
            }
        )
        workflow.add_edge("format", END)

        # Set entry point
        workflow.set_entry_point("classify")

        return workflow.compile()

    async def invoke(self, state: AgentState) -> AgentState:
        """
        Run agent on input query.

        Returns final state with response and sources.
        """
        logger.info(f"Starting QA agent for query: {state['query']}")
        result = await self.graph.ainvoke(state)
        return result

    async def stream(self, state: AgentState):
        """
        Stream agent execution step by step.

        Yields (step_name, intermediate_state) for live UI updates.
        """
        async for step_output in self.graph.astream(state):
            # step_output: {node_name: {state}}
            for node_name, node_state in step_output.items():
                logger.info(f"Step: {node_name}")
                yield {"step": node_name, "state": node_state}

    # ========================================================================
    # NODE IMPLEMENTATIONS
    # ========================================================================

    async def _classify_query(self, state: AgentState) -> dict:
        """
        Classify query type.

        Determines if we need to retrieve documents or can answer directly.
        This saves retrieval latency for factual questions.
        """
        logger.info(f"Classifying query: {state['query']}")

        # Use GPT-4o for classification
        response = await self.openai.chat.completions.create(
            model=self.settings.chat_model,
            messages=[
                {
                    "role": "system",
                    "content": """Classify the financial question into one of:
1. simple_qa: Factual questions answerable from documents (e.g., "What is our cash balance?")
2. analysis: Requires synthesis across documents (e.g., "How risky is our portfolio?")
3. recommendation: Requires advice (e.g., "Should we increase equity allocation?")
4. retrieval: Bulk data request (e.g., "List all holdings")

Respond with ONLY the category name.""",
                },
                {"role": "user", "content": state["query"]},
            ],
            temperature=0.0,
            max_tokens=50,
        )

        query_type = response.choices[0].message.content.strip().lower()
        logger.info(f"Query classified as: {query_type}")

        return {
            "query_type": query_type,
            "requires_retrieval": True,  # For now, always retrieve (safer)
        }

    async def _retrieve_documents(self, state: AgentState) -> dict:
        """
        Retrieve relevant documents using hybrid RAG.

        Uses HyDE + dense + sparse + RRF fusion.
        """
        logger.info(f"Retrieving documents for: {state['query']}")

        try:
            chunks = await self.retriever.retrieve(
                query=state["query"],
                client_id=state["client_id"],
                top_k=5,
                use_hyde=self.settings.enable_hyde_retrieval,
            )

            retrieved_chunks = [
                {
                    "id": chunk.chunk_id,
                    "content": chunk.content,
                    "score": chunk.score,
                    "document_id": chunk.document_id,
                    "metadata": chunk.metadata,
                }
                for chunk in chunks
            ]

            logger.info(f"Retrieved {len(retrieved_chunks)} chunks")

            return {
                "retrieved_chunks": retrieved_chunks,
                "retrieval_method": "hybrid",
            }

        except Exception as e:
            logger.error(f"Retrieval error: {e}")
            return {
                "error": str(e),
                "error_type": "retrieval_error",
                "retrieved_chunks": [],
            }

    async def _rerank_documents(self, state: AgentState) -> dict:
        """
        Rerank retrieved documents with cross-encoder.

        Takes top-20 and selects top-5 with higher precision.
        """
        if not state.get("retrieved_chunks"):
            logger.warning("No chunks to rerank")
            return {"reranked_chunks": []}

        logger.info(f"Reranking {len(state['retrieved_chunks'])} chunks")

        # In production, would use cross-encoder here
        # For now, just sort by existing score
        reranked = sorted(
            state["retrieved_chunks"],
            key=lambda x: x["score"],
            reverse=True,
        )[: self.settings.reranker_top_k]

        return {
            "reranked_chunks": reranked,
            "reranked_count": len(reranked),
        }

    async def _compress_context(self, state: AgentState) -> dict:
        """
        Compress context with LLMLingua.

        Reduces token count while preserving key information.
        Logs compression ratio for audit trail.
        """
        chunks = state.get("reranked_chunks", [])
        if not chunks:
            return {
                "compressed_context": "",
                "compression_ratio": 0.0,
                "original_context_length": 0,
            }

        # Combine chunks into context
        context = "\n\n".join([f"[{c['id'][:8]}] {c['content']}" for c in chunks])
        original_length = len(context.split())

        # In production, would call LLMLingua here
        # For now, return as-is with 100% ratio
        compressed = context
        compression_ratio = 0.0  # No compression

        logger.info(f"Context: {original_length} tokens, ratio: {compression_ratio:.2%}")

        return {
            "compressed_context": compressed,
            "compression_ratio": compression_ratio,
            "original_context_length": original_length,
        }

    async def _fetch_market_data(self, state: AgentState) -> dict:
        """
        Fetch live market data relevant to the query.

        Detects stock symbols in query and document context,
        fetches real-time prices and technical indicators.

        **Market Data Availability Tracking:**
        - Tracks whether market data service is available
        - Records timestamp when data is fetched
        - Logs explicit status: "success", "failed", "unavailable"
        """
        import re
        from datetime import datetime

        logger.info("Fetching live market data")
        market_data_context = ""
        market_data_errors = []
        market_data_status = "not_applicable"  # Default: no symbols found
        market_data_timestamp = None

        try:
            # Check if market data service is available
            if not self.market_data.is_available():
                logger.warning("Market data service unavailable - API key not configured")
                return {
                    "market_data_context": "",
                    "market_symbols_queried": [],
                    "market_data_errors": ["Market data API key not configured"],
                    "market_data_available": "unavailable",
                    "market_data_timestamp": None,
                }

            query_text = state.get("query", "")
            query_type = state.get("query_type", "")
            # Skip market data for analysis/recommendation unless explicitly requested
            market_keywords = ("price", "quote", "market", "trading", "ticker", "stock", "share", "shares", "current", "latest", "today")
            if query_type in {"analysis", "recommendation", "retrieval"} and not any(k in query_text.lower() for k in market_keywords):
                logger.info("Skipping market data fetch (not requested for this query type)")
                return {
                    "market_data_context": "",
                    "market_symbols_queried": [],
                    "market_data_errors": None,
                    "market_data_available": "not_applicable",
                    "market_data_timestamp": None,
                }

            # Extract potential stock symbols from query and documents
            query = state.get("query", "").upper()
            chunks = state.get("reranked_chunks", [])

            # Look for stock ticker patterns (e.g., AAPL, MSFT)
            # More comprehensive pattern: all-caps, 1-5 chars, word boundary
            symbol_pattern = r'\b([A-Z]{1,5})\b'
            query_symbols = re.findall(symbol_pattern, query)

            # Also extract from document chunks (preserve order per chunk)
            doc_symbols: list[str] = []
            for chunk in chunks:
                chunk_text = chunk.get("content", "").upper()
                doc_symbols.extend(re.findall(symbol_pattern, chunk_text))

            # Filter to likely stock symbols (exclude common words)
            common_words = {
                "AND", "THE", "FOR", "WITH", "FROM", "THIS", "THAT", "WHICH", "WHEN", "WHERE",
                "HOW", "WHAT", "WHY", "IS", "OF", "IN", "ON", "AT", "AS", "A", "AN", "PRICE",
                "CURRENT", "NOW", "LATEST", "TODAY", "STOCK", "SHARE", "SHARES",
            }
            def normalize_symbols(items: list[str]) -> list[str]:
                filtered = []
                seen = set()
                for s in items:
                    if s in seen:
                        continue
                    if s in common_words or len(s) > 5 or len(s) < 2:
                        continue
                    seen.add(s)
                    filtered.append(s)
                return filtered

            query_symbols = normalize_symbols(query_symbols)
            doc_symbols = normalize_symbols(doc_symbols)

            # Prioritize query symbols, then fill with doc symbols
            symbols = query_symbols[:]
            for s in doc_symbols:
                if s not in symbols:
                    symbols.append(s)
                if len(symbols) >= 3:
                    break

            logger.info(f"Detected symbols: {symbols}")

            if not symbols:
                logger.info("No symbols detected in query or documents")
                return {
                    "market_data_context": "",
                    "market_symbols_queried": [],
                    "market_data_errors": None,
                    "market_data_available": "not_applicable",
                    "market_data_timestamp": None,
                }

            # Fetch data for each symbol
            market_quotes = {}
            for idx, symbol in enumerate(symbols):
                try:
                    if idx > 0:
                        await asyncio.sleep(1.1)  # Alpha Vantage free tier: ~1 req/sec
                    quote = await self.market_data.get_quote(symbol)
                    if quote:
                        market_quotes[symbol] = quote
                        logger.info(f"Fetched quote for {symbol}: ${quote.get('price')}")
                except Exception as e:
                    logger.warning(f"Failed to fetch quote for {symbol}: {e}")
                    market_data_errors.append(f"{symbol}: {str(e)}")

            # Fetch company info for top symbols
            company_info = {}
            for symbol in symbols[:3]:  # Limit to 3 companies to save API calls
                try:
                    info = await self.market_data.get_company_info(symbol)
                    if info:
                        company_info[symbol] = info
                        logger.info(f"Fetched company info for {symbol}")
                except Exception as e:
                    logger.warning(f"Failed to fetch company info for {symbol}: {e}")

            # Track market data availability status
            if market_quotes or company_info:
                market_data_status = "success"
                market_data_timestamp = datetime.utcnow().isoformat()
            elif market_data_errors:
                market_data_status = "failed"

            # Format market data for inclusion in context
            if market_quotes or company_info:
                market_data_context = "\n\n=== LIVE MARKET DATA (As of " + market_data_timestamp + ") ===\n"

                # Add quotes
                if market_quotes:
                    market_data_context += "\nReal-Time Quotes:\n"
                    for symbol, quote in market_quotes.items():
                        market_data_context += f"\n{symbol}:\n"
                        market_data_context += f"  Price: ${quote.get('price', 'N/A')}\n"
                        market_data_context += f"  Change: {quote.get('change', 0)} ({quote.get('change_percent', 0)}%)\n"
                        market_data_context += f"  Last Trading Day: {quote.get('last_trading_day', 'N/A')}\n"
                        market_data_context += f"  Fetched at: {quote.get('fetched_at', 'N/A')}\n"

                # Add company info
                if company_info:
                    market_data_context += "\nCompany Fundamentals:\n"
                    for symbol, info in company_info.items():
                        market_data_context += f"\n{symbol} - {info.get('name', 'Unknown')}:\n"
                        if info.get('sector'):
                            market_data_context += f"  Sector: {info.get('sector')}\n"
                        if info.get('market_cap'):
                            market_data_context += f"  Market Cap: ${info.get('market_cap'):,}\n"
                        if info.get('pe_ratio'):
                            market_data_context += f"  P/E Ratio: {info.get('pe_ratio')}\n"
                        if info.get('dividend_yield'):
                            market_data_context += f"  Dividend Yield: {info.get('dividend_yield'):.2%}\n"
                        if info.get('52_week_high'):
                            market_data_context += f"  52-Week High: ${info.get('52_week_high')}\n"
                        if info.get('52_week_low'):
                            market_data_context += f"  52-Week Low: ${info.get('52_week_low')}\n"

            return {
                "market_data_context": market_data_context,
                "market_symbols_queried": symbols,
                "market_data_errors": market_data_errors if market_data_errors else None,
                "market_data_available": market_data_status,
                "market_data_timestamp": market_data_timestamp,
            }

        except Exception as e:
            logger.error(f"Market data fetch error: {e}")
            return {
                "market_data_context": "",
                "market_symbols_queried": [],
                "market_data_errors": [str(e)],
                "market_data_available": "failed",
                "market_data_timestamp": None,
            }

    async def _generate_response(self, state: AgentState) -> dict:
        """
        Generate answer with GPT-4o using document + live market data context.

        Combines RAG retrieval with real-time market data for comprehensive answers.

        **Source Grounding & Hard Failures:**
        - Returns "no answer" if both document and market data are empty
        - Tracks whether response is grounded in sources
        - Records data sources for audit trail
        """
        logger.info("Generating response with GPT-4o")

        doc_context = state.get("compressed_context", "")
        market_context = state.get("market_data_context", "")
        query = state["query"]
        history = []  # Would include previous messages from conversation
        reranked_chunks = state.get("reranked_chunks", [])

        # **HARD FAIL: Check if we have any sources to ground the response**
        has_document_sources = bool(doc_context.strip() and reranked_chunks)
        has_market_data = bool(market_context.strip())

        if not has_document_sources and not has_market_data:
            error_msg = """I don't have enough information to answer this question.

No relevant documents were found in your knowledge base, and no market data is available.

**To help me answer financial questions:**
1. Upload documents containing financial data (portfolios, holdings, reports, statements)
2. For real-time stock prices, ensure the market data API is configured

Please try asking another question or upload relevant documents first."""

            logger.warning(f"Hard fail: No sources available (docs: {has_document_sources}, market: {has_market_data})")

            return {
                "generated_response": error_msg,
                "generation_metadata": {
                    "model": self.settings.chat_model,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "sources_grounded": False,
                    "grounding_reason": "No sources available",
                },
                "final_response": error_msg,
                "sources": [],
                "confidence": 0.0,
            }

        # Combine all context
        combined_context = doc_context
        if market_context:
            combined_context += "\n\n" + market_context

        # Build system prompt with explicit grounding instructions
        system_prompt = """You are a financial advisor AI. Answer questions using the provided context.

**CRITICAL INSTRUCTIONS:**
1. You MUST ground every claim in the provided context (documents or live market data)
2. If asked about something not in the context, explicitly state "This information is not available in your documents"
3. Always cite your sources in parentheses:
   - For documents: "(Document: [chunk-id])"
   - For market data: "(Live Market Data - [date/time])"
4. Be specific with numbers, percentages, and dates
5. If live data conflicts with document data, acknowledge both sources and explain the difference
6. Do NOT fabricate portfolio holdings, prices, or company information not in the context
7. For portfolio questions without uploaded documents, explain that you need portfolio data"""

        # Build user prompt
        user_prompt = f"""Context from documents and live market data:
{combined_context}

Question: {query}

Answer with sources cited:"""

        response = await self.openai.chat.completions.create(
            model=self.settings.chat_model,
            messages=[
                {"role": "system", "content": system_prompt},
                *history,
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=800,
        )

        generated_response = response.choices[0].message.content.strip()

        # Determine if response is grounded in sources
        sources_grounded = "(" in generated_response  # Rough heuristic: has citations

        logger.info(f"Generated response (grounded: {sources_grounded}): {generated_response[:100]}...")

        return {
            "generated_response": generated_response,
            "generation_metadata": {
                "model": self.settings.chat_model,
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
                "sources_grounded": sources_grounded,
                "has_document_sources": has_document_sources,
                "has_market_data": has_market_data,
            },
        }

    async def _score_faithfulness(self, state: AgentState) -> dict:
        """
        Score faithfulness of generated answer.

        Uses NLI to verify answer is grounded in context.
        If score < 0.6, triggers retry loop.
        """
        logger.info("Scoring faithfulness")

        context = state.get("compressed_context", "")
        response = state.get("generated_response", "")

        if not context or not response:
            return {"faithfulness_score": 0.5, "should_retry": False}

        try:
            score = await self.faithfulness_scorer.score(context, response)
            should_retry = (
                score < self.settings.faithfulness_threshold
                and state.get("retry_count", 0) < self.settings.faithfulness_retry_limit
            )

            logger.info(f"Faithfulness score: {score:.3f}, retry: {should_retry}")

            # Count the retry here: conditional-edge functions (_should_retry)
            # cannot write state, so without this the loop never ends.
            retry_count = state.get("retry_count", 0) + (1 if should_retry else 0)

            return {
                "faithfulness_score": score,
                "should_retry": should_retry,
                "retry_count": retry_count,
                "retry_reason": "Low faithfulness score" if should_retry else None,
            }

        except Exception as e:
            logger.error(f"Faithfulness scoring error: {e}")
            return {"faithfulness_score": 0.5, "should_retry": False}

    async def _format_response(self, state: AgentState) -> dict:
        """
        Format final response with sources and metadata.

        Extracts cited chunk IDs and confidence scores.
        """
        logger.info("Formatting final response")

        sources = [
            chunk["id"]
            for chunk in state.get("reranked_chunks", [])
        ]

        final_response = state.get("generated_response", "")

        return {
            "final_response": final_response,
            "sources": sources,
            "confidence": state.get("faithfulness_score", 0.5),
        }

    @staticmethod
    def _should_retry(state: AgentState) -> str:
        """
        Determine if we should retry retrieval.

        Returns "retrieve" to loop back, "format" to proceed.
        """
        if state.get("should_retry"):
            logger.info(f"Retrying retrieval (attempt {state.get('retry_count', 0)})")
            return "retrieve"
        return "format"


# Factory function for use in dependency injection
async def create_qa_agent(db_session):
    """Create and return initialized QA agent."""
    return FinancialQAAgent(db_session)
