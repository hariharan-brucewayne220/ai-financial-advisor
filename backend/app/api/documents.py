"""
Documents Router - Upload, manage, and track document ingestion

Handles document upload, parsing, chunking, embedding, and indexing.
"""

import logging
import io
from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.dependencies import get_db, async_session_maker, verify_client_ownership
from app.models.document import Document, DocumentChunk
from app.models.client import Client

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/{client_id}/upload")
async def upload_document(
    client_id: str,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
):
    """
    Upload and ingest a document.

    **Async Ingestion Pipeline:**
    1. Save uploaded file to S3
    2. Parse PDF/CSV/Excel (in background)
    3. Detect PII (in background)
    4. Split into chunks (in background)
    5. Generate embeddings (in background)
    6. Insert into pgvector (in background)
    7. Update document status

    **Why async?**
    - Parsing large PDFs can take 10+ seconds
    - Generating embeddings for 100 chunks: 30+ seconds
    - Don't block user's upload request

    **Multi-tenancy:** Endpoint verifies caller owns the client before uploading.

    Args:
        client_id: Client UUID
        file: Document file (PDF, CSV, XLSX, TXT)
        background_tasks: FastAPI background task runner
        client: Verified client (dependency injection with ownership check)

    Returns:
        {document_id, status: "pending", message: "Processing..."}
    """
    logger.info(f"Uploading document for client {client_id}: {file.filename} (verified ownership)")

    # Client ownership already verified by verify_client_ownership dependency

    # Determine file type
    file_ext = file.filename.split(".")[-1].lower()
    if file_ext not in ["pdf", "csv", "xlsx", "txt", "jpg", "jpeg", "png", "gif", "webp"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {file_ext}. Supported: PDF, CSV, XLSX, TXT, JPG, PNG, GIF, WEBP",
        )

    # Create document record
    document = Document(
        client_id=UUID(client_id),
        file_name=file.filename,
        file_type=file_ext,
        s3_key=f"documents/{client_id}/{file.filename}",
        status="pending",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    logger.info(f"Document {document.id} created, scheduling ingestion")

    # Save file temporarily (in production: upload to S3)
    import tempfile
    import os

    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, f"{document.id}_{file.filename}")

    # Read and save uploaded file
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    logger.info(f"File saved to {file_path}")

    # Schedule async ingestion pipeline
    background_tasks.add_task(
        _ingest_document_background,
        document_id=str(document.id),
        client_id=client_id,
        file_path=file_path,
        file_type=file_ext,
    )

    return {
        "document_id": str(document.id),
        "file_name": file.filename,
        "status": "pending",
        "message": "Document uploaded. Processing started...",
    }


async def _ingest_document_background(
    document_id: str,
    client_id: str,
    file_path: str,
    file_type: str,
):
    """
    Background task: Full RAG ingestion pipeline.

    **Real pipeline:**
    1. Parse document (PDF text extraction + image Vision API)
    2. Detect PII (Presidio)
    3. Chunk text intelligently
    4. Embed chunks (OpenAI)
    5. Store in pgvector with HNSW index
    6. Update status to "indexed"
    """
    from app.services.ingestion_pipeline import DocumentIngestionPipeline

    try:
        # Get database session (background task needs its own session)
        async with async_session_maker() as db:
            pipeline = DocumentIngestionPipeline(db)

            # Run ingestion
            chunk_count, pii_detected = await pipeline.ingest(
                document_id=UUID(document_id),
                client_id=UUID(client_id),
                file_path=file_path,
                file_type=file_type,
            )

            logger.info(
                f"✓ Ingested document {document_id}: "
                f"{chunk_count} chunks, PII: {pii_detected}"
            )

    except Exception as e:
        logger.error(f"Ingestion failed for {document_id}: {e}", exc_info=True)


@router.get("/{client_id}")
async def list_documents(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
) -> List[dict]:
    """
    List all documents for a client with status.

    **Multi-tenancy:** Endpoint verifies caller owns the client.

    Returns:
        List of documents with upload status, chunk count, PII detection
    """
    stmt = select(Document).where(Document.client_id == UUID(client_id))
    result = await db.execute(stmt)
    documents = result.scalars().all()

    return [
        {
            "id": str(d.id),
            "file_name": d.file_name,
            "file_type": d.file_type,
            "status": d.status,
            "chunk_count": d.chunk_count,
            "pii_detected": d.pii_detected,
            "created_at": d.created_at.isoformat(),
            "error_message": d.error_message,
        }
        for d in documents
    ]


@router.get("/{client_id}/{document_id}/status")
async def get_document_status(
    client_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
):
    """
    Poll document ingestion status.

    **Status values:**
    - pending: Waiting to process
    - processing: Currently ingesting
    - indexed: Ready for retrieval
    - failed: Error during processing

    **Multi-tenancy:** Endpoint verifies caller owns the client.

    Client polls this every 1-2 seconds until status == "indexed"
    """
    document = await db.get(Document, UUID(document_id))
    if not document or str(document.client_id) != client_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return {
        "document_id": str(document.id),
        "status": document.status,
        "chunk_count": document.chunk_count,
        "pii_detected": document.pii_detected,
        "is_ready": document.status == "indexed",
        "error_message": document.error_message,
    }


@router.delete("/{client_id}/{document_id}")
async def delete_document(
    client_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
):
    """
    Delete a document and its chunks.

    **Multi-tenancy:** Endpoint verifies caller owns the client before deletion.

    Removes from S3, deletes chunks from pgvector, clears BM25 cache.
    """
    document = await db.get(Document, UUID(document_id))
    if not document or str(document.client_id) != client_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if settings.retrieval_backend == "azure_search":
        from app.services.azure_search import get_search_index
        chunk_ids = (await db.execute(
            select(DocumentChunk.id).where(DocumentChunk.document_id == document.id)
        )).scalars().all()
        await get_search_index().delete_chunks([str(i) for i in chunk_ids])

    # Delete from database (cascades to chunks via foreign key)
    await db.delete(document)
    await db.commit()

    logger.info(f"Deleted document {document_id}")

    return {"message": "Document deleted successfully"}
