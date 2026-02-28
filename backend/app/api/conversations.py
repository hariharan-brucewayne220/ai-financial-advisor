"""
Conversations Router - SSE Streaming Endpoint

**Why SSE (Server-Sent Events)?**
- One-way stream from server to client (perfect for agent steps)
- Native browser support via EventSource API
- Simpler than WebSockets for unidirectional data
- Auto-reconnect on disconnect

**Event Sequence:**
1. step:classify → User query classified
2. step:retrieve → Documents retrieved
3. step:rerank → Results reranked
4. step:compress → Context compressed
5. step:generate → Answer being generated...
6. token:<text> → Answer tokens as they arrive
7. step:score → Faithfulness being scored
8. sources:<json> → Cited chunk IDs
9. faithfulness:<score> → Faithfulness score
10. done → Agent finished

This lets UI show live progress without polling.
"""

import json
import asyncio
import logging
from typing import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi import Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_client_ownership
from app.schemas import ConversationCreate, ConversationResponse, MessageCreate
from app.models.conversation import Conversation, Message
from app.models.client import Client
from app.agents.state import AgentState
from app.agents.financial_qa_agent import create_qa_agent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("/{client_id}/conversations", response_model=ConversationResponse)
async def create_conversation(
    client_id: str,
    conv_data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
):
    """
    Create a new conversation for a client.

    **Multi-tenancy:** Endpoint verifies caller owns the client before creating conversation.

    Args:
        client_id: Client UUID
        conv_data: Conversation creation data
        client: Verified client (dependency injection with ownership check)

    Returns:
        Created conversation
    """
    logger.info(f"Creating conversation for client {client_id} (verified ownership)")

    # Client ownership already verified by verify_client_ownership dependency

    # Create conversation
    conversation = Conversation(
        client_id=UUID(client_id),
        title=conv_data.title or "New Conversation",
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)

    logger.info(f"Created conversation {conversation.id}")

    # Return without accessing lazy relationships
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[]  # Avoid loading lazy relationship
    )


@router.post("/{client_id}/conversations/{conv_id}/messages")
async def stream_message(
    client_id: str,
    conv_id: str,
    message_data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
):
    """
    Stream agent response to user message via SSE.

    **Multi-tenancy:** Endpoint verifies caller owns the client before streaming response.

    **SSE Format:**
    Each event is: event: <event_type>\\ndata: <json_data>\\n\\n

    **Example Response:**
    ```
    event: step
    data: {"step": "classify", "state": {...}}

    event: step
    data: {"step": "retrieve", "state": {...}}

    event: token
    data: {"token": "The"}

    event: token
    data: {"token": " portfolio"}

    event: done
    data: {"response": "The portfolio contains...", "sources": [...]}
    ```

    Client-side:
    ```javascript
    const eventSource = new EventSource('/api/conversations/client_id/messages?query=...');
    eventSource.addEventListener('step', (e) => {
        const {step, state} = JSON.parse(e.data);
        console.log(`Agent step: ${step}`);
    });
    eventSource.addEventListener('token', (e) => {
        const {token} = JSON.parse(e.data);
        responseDiv.textContent += token;
    });
    ```
    """
    logger.info(f"Streaming message for conv {conv_id}, query: {message_data.content}")

    # Verify conversation exists
    conversation = await db.get(Conversation, UUID(conv_id))
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    # Save user message
    user_msg = Message(
        conversation_id=UUID(conv_id),
        role="user",
        content=message_data.content,
    )
    db.add(user_msg)
    await db.commit()

    # Stream agent response
    return StreamingResponse(
        generate_stream(message_data.content, client_id, conv_id, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/{client_id}/conversations/{conv_id}/messages")
async def stream_message_get(
    client_id: str,
    conv_id: str,
    query: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
):
    """
    Stream agent response via SSE (GET for EventSource compatibility).
    Mirrors POST endpoint but takes `query` from the URL.

    **Multi-tenancy:** Endpoint verifies caller owns the client before streaming response.
    """
    logger.info(f"Streaming message (GET) for conv {conv_id}, query: {query}")

    conversation = await db.get(Conversation, UUID(conv_id))
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    user_msg = Message(
        conversation_id=UUID(conv_id),
        role="user",
        content=query,
    )
    db.add(user_msg)
    await db.commit()

    return StreamingResponse(
        generate_stream(query, client_id, conv_id, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


async def generate_stream(
    query: str,
    client_id: str,
    conv_id: str,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """
    Generator that streams SSE events for agent execution.

    Each yield is a complete SSE event that gets sent to client.

    **SSE Event Format:**
    event: <type>\\ndata: <json>\\n\\n

    The double newline tells client an event is complete.
    """
    try:
        # Create QA agent
        agent = await create_qa_agent(db)

        # Initialize agent state
        initial_state: AgentState = {
            "query": query,
            "client_id": client_id,
            "user_id": "current_user",  # TODO: get from auth
            "retry_count": 0,
        }

        final_state: AgentState | None = None

        # Stream agent execution step by step
        async for step_output in agent.stream(initial_state):
            step_name = step_output["step"]
            state = step_output["state"]
            final_state = state

            logger.info(f"Agent step: {step_name}")

            # Emit step event
            yield format_sse_event("step", {"step": step_name})

            # Emit token events during generation
            if step_name == "generate" and state.get("generated_response"):
                response_text = state["generated_response"]
                # Stream response tokens (simplified - just split by words)
                for token in response_text.split():
                    yield format_sse_event("token", {"token": token + " "})
                    await asyncio.sleep(0.01)  # Slight delay for UX

        # Emit final state with sources and score
        if final_state is None:
            final_state = initial_state

        yield format_sse_event("sources", {"sources": final_state.get("sources", [])})
        yield format_sse_event(
            "faithfulness",
            {"score": final_state.get("confidence", 0.5)},
        )

        # Save assistant message to database with full audit trail
        import json
        from datetime import datetime

        # Build comprehensive audit trail
        audit_trail = {
            "documents": {
                "retrieved_count": len(final_state.get("sources", [])),
                "chunk_ids": final_state.get("sources", []),
                "retrieval_method": final_state.get("retrieval_method", "unknown"),
            },
            "market_data": {
                "symbols_queried": final_state.get("market_symbols_queried", []),
                "availability": final_state.get("market_data_available", "not_applicable"),
                "timestamp": final_state.get("market_data_timestamp"),
                "errors": final_state.get("market_data_errors"),
            },
            "generation": {
                "sources_grounded": final_state.get("generation_metadata", {}).get("sources_grounded", False),
                "has_document_sources": final_state.get("generation_metadata", {}).get("has_document_sources", False),
                "has_market_data": final_state.get("generation_metadata", {}).get("has_market_data", False),
            },
            "quality": {
                "faithfulness_score": float(final_state.get("confidence", 0.5)),
                "compression_ratio": final_state.get("compression_ratio"),
            },
        }

        assistant_msg = Message(
            conversation_id=UUID(conv_id),
            role="assistant",
            content=final_state.get("final_response", ""),
            retrieved_chunk_ids=final_state.get("sources", []),
            faithfulness_score=float(final_state.get("confidence", 0.5)),
            # Audit trail fields
            retrieved_at=datetime.utcnow(),
            market_data_symbols=final_state.get("market_symbols_queried", []),
            market_data_available=final_state.get("market_data_available", "not_applicable"),
            data_sources_json=json.dumps(audit_trail),
        )
        db.add(assistant_msg)
        await db.commit()

        # Emit done event
        yield format_sse_event("done", {"status": "complete"})

    except Exception as e:
        logger.error(f"Error streaming message: {e}", exc_info=True)
        yield format_sse_event("error", {"error": str(e)})


def format_sse_event(event_type: str, data: dict) -> str:
    """
    Format a single SSE event.

    SSE format: "event: <type>\\ndata: <json>\\n\\n"

    Args:
        event_type: Type of event (step, token, sources, done, error)
        data: Data to send as JSON

    Returns:
        Formatted SSE event string
    """
    event_line = f"event: {event_type}\n"
    data_line = f"data: {json.dumps(data)}\n"
    return event_line + data_line + "\n"


@router.get("/{client_id}/conversations/{conv_id}")
async def get_conversation(
    client_id: str,
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
) -> ConversationResponse:
    """Get conversation with all messages.

    **Multi-tenancy:** Endpoint verifies caller owns the client.
    """
    conversation = await db.get(Conversation, UUID(conv_id))
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    # Return without accessing lazy relationships
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[]  # Messages loaded separately if needed
    )


@router.get("/{client_id}/conversations")
async def list_conversations(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
) -> list[ConversationResponse]:
    """List all conversations for a client.

    **Multi-tenancy:** Endpoint verifies caller owns the client.
    """
    # Query conversations (don't load relationships to avoid async issues)
    from sqlalchemy import select

    stmt = select(Conversation).where(Conversation.client_id == UUID(client_id))
    result = await db.execute(stmt)
    conversations = result.scalars().all()

    # Convert to response without accessing lazy relationships
    return [
        ConversationResponse(
            id=c.id,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
            messages=[]  # Avoid loading lazy relationship
        )
        for c in conversations
    ]
