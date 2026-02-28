"""
Clients Router - Manage financial advisor clients

CRUD operations for clients and basic portfolio management.
"""

import logging
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.dependencies import get_db, verify_client_ownership
from app.auth import get_current_advisor
from app.models.client import Client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clients", tags=["clients"])


# Request/Response schemas
class ClientCreate(BaseModel):
    """Schema for creating a client."""
    name: str
    email: Optional[str] = None
    risk_profile: str = "moderate"  # low, moderate, high, aggressive
    portfolio_value: Optional[float] = None


class ClientUpdate(BaseModel):
    """Schema for updating a client."""
    name: Optional[str] = None
    email: Optional[str] = None
    risk_profile: Optional[str] = None
    portfolio_value: Optional[float] = None


class ClientResponse(BaseModel):
    """Schema for client response."""
    id: str
    name: str
    email: Optional[str]
    risk_profile: str
    portfolio_value: Optional[float]
    created_at: str


@router.post("")
async def create_client(
    client_data: ClientCreate,
    db: AsyncSession = Depends(get_db),
    current_advisor: dict = Depends(get_current_advisor),
) -> ClientResponse:
    """
    Create a new client.

    Args:
        client_data: Client information

    Returns:
        Created client with ID
    """
    logger.info(f"Creating client: {client_data.name}")

    client = Client(
        advisor_id=UUID(current_advisor["advisor_id"]),
        name=client_data.name,
        email=client_data.email,
        risk_profile=client_data.risk_profile,
        portfolio_value=client_data.portfolio_value,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)

    logger.info(f"Client {client.id} created")

    return ClientResponse(
        id=str(client.id),
        name=client.name,
        email=client.email,
        risk_profile=client.risk_profile,
        portfolio_value=client.portfolio_value,
        created_at=client.created_at.isoformat(),
    )


@router.get("")
async def list_clients(
    db: AsyncSession = Depends(get_db),
    current_advisor: dict = Depends(get_current_advisor),
) -> List[ClientResponse]:
    """
    List all clients for current advisor.

    In production, would filter by current_advisor from JWT token.
    """
    stmt = select(Client).where(Client.advisor_id == UUID(current_advisor["advisor_id"]))
    result = await db.execute(stmt)
    clients = result.scalars().all()

    return [
        ClientResponse(
            id=str(c.id),
            name=c.name,
            email=c.email,
            risk_profile=c.risk_profile,
            portfolio_value=c.portfolio_value,
            created_at=c.created_at.isoformat(),
        )
        for c in clients
    ]


@router.get("/{client_id}")
async def get_client(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),
) -> ClientResponse:
    """Get a specific client (ownership enforced)."""

    return ClientResponse(
        id=str(client.id),
        name=client.name,
        email=client.email,
        risk_profile=client.risk_profile,
        portfolio_value=client.portfolio_value,
        created_at=client.created_at.isoformat(),
    )


@router.put("/{client_id}")
async def update_client(
    client_id: str,
    client_data: ClientUpdate,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),
) -> ClientResponse:
    """Update a client."""

    # Update fields
    if client_data.name:
        client.name = client_data.name
    if client_data.email:
        client.email = client_data.email
    if client_data.risk_profile:
        client.risk_profile = client_data.risk_profile
    if client_data.portfolio_value:
        client.portfolio_value = client_data.portfolio_value

    await db.commit()
    await db.refresh(client)

    return ClientResponse(
        id=str(client.id),
        name=client.name,
        email=client.email,
        risk_profile=client.risk_profile,
        portfolio_value=client.portfolio_value,
        created_at=client.created_at.isoformat(),
    )


@router.delete("/{client_id}")
async def delete_client(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),
):
    """Delete a client (cascades to documents, conversations, reports)."""

    await db.delete(client)
    await db.commit()

    logger.info(f"Deleted client {client_id}")

    return {"message": "Client deleted successfully"}
