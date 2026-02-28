"""
Reports Router - Generate and retrieve financial reports

Endpoints for creating, managing, and downloading financial reports.
Reports are generated asynchronously by the ReportWriterAgent.
"""

import logging
from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.dependencies import get_db, verify_client_ownership
from app.models.report import Report
from app.models.client import Client
from app.agents.report_writer_agent import create_report_agent
from app.services.retriever import HybridRetriever
from app.auth import get_current_advisor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


class ReportResponse:
    """Schema for report response."""
    id: str
    client_id: str
    report_type: str
    title: str
    status: str
    created_at: str


@router.post("/{client_id}/generate")
async def generate_report(
    client_id: str,
    report_type: str,  # portfolio_summary, risk_assessment, client_email
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
    current_advisor: dict = Depends(get_current_advisor),  # JWT auth check
):
    """
    Generate a new financial report for a client.

    **Multi-tenancy & Authentication:**
    - Requires valid JWT token from current advisor
    - Verifies advisor owns the client before allowing report generation
    - Only grounded reports (from actual client documents)

    **Async Generation:**
    - Report generation can be long-running (30-60 seconds)
    - Return immediately with report ID
    - Client polls /reports/{report_id}/status to check progress
    - Or use WebSocket for real-time updates

    Args:
        client_id: Client UUID
        report_type: Type of report (portfolio_summary, risk_assessment, client_email)
        background_tasks: FastAPI background task handler
        client: Verified client (dependency - ownership checked)
        current_advisor: Authenticated advisor (JWT token validated)

    Returns:
        {report_id, status: "generating", estimated_time_sec: 45}
    """
    logger.info(
        f"Generating {report_type} report for client {client_id} "
        f"by advisor {current_advisor['advisor_email']} (verified)"
    )

    # Client ownership already verified by verify_client_ownership dependency

    # Create report record with draft status
    report = Report(
        client_id=UUID(client_id),
        report_type=report_type,
        title=f"{report_type.replace('_', ' ').title()}",
        status="generating",
        generation_metadata={
            "started_at": str(__import__("datetime").datetime.utcnow()),
        },
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    # Schedule async generation
    background_tasks.add_task(
        _generate_report_background,
        report_id=str(report.id),
        client_id=client_id,
        report_type=report_type,
        db_session=db,
    )

    logger.info(f"Report {report.id} scheduled for generation")

    return {
        "report_id": str(report.id),
        "status": "generating",
        "estimated_time_sec": 45,
        "message": "Report generation started. Check status for progress.",
    }


async def _generate_report_background(
    report_id: str,
    client_id: str,
    report_type: str,
    db_session: AsyncSession,
):
    """
    Background task: Generate report asynchronously.

    **Why background tasks?**
    - Report generation can take 30-60 seconds
    - Don't want to block HTTP request
    - Can update database as we progress
    - Client can poll for status updates

    **Alternative:** Use Celery or ARQ for more robust task queue.
    """
    logger.info(f"Starting background report generation for {report_id}")

    try:
        # Fetch report
        report = await db_session.get(Report, UUID(report_id))
        if not report:
            logger.error(f"Report {report_id} not found")
            return

        # Create agent
        retriever = HybridRetriever(db_session)
        agent = await create_report_agent(db_session, retriever)

        # Initial state
        from app.agents.state import ReportGenerationState

        state: ReportGenerationState = {
            "client_id": client_id,
            "report_type": report_type,
            "client_data": {"name": f"Client {client_id[:8]}"},
            "total_iterations": 0,
            "total_tokens": 0,
        }

        # Run agent (streams progress)
        result = await agent.invoke(state)

        # Update report with final content
        report.content = result.get("final_report", "")
        report.content_html = result.get("html_output", "")
        report.status = "final"
        report.finalized_at = __import__("datetime").datetime.utcnow()
        report.generation_metadata = {
            "iterations": result.get("total_iterations", 1),
            "total_tokens": result.get("total_tokens", 0),
            "sources": result.get("report_sources", {}),
        }

        await db_session.commit()
        logger.info(f"Report {report_id} generation complete")

    except Exception as e:
        logger.error(f"Error generating report {report_id}: {e}", exc_info=True)

        # Update report with error status
        report = await db_session.get(Report, UUID(report_id))
        if report:
            report.status = "failed"
            report.error_message = str(e)
            await db_session.commit()


@router.get("/{client_id}")
async def list_reports(
    client_id: str,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
    current_advisor: dict = Depends(get_current_advisor),  # JWT auth
) -> List[dict]:
    """
    List all reports for a client.

    **Multi-tenancy & Authentication:**
    - Requires valid JWT token
    - Verifies advisor owns the client

    Args:
        client_id: Client UUID
        client: Verified client (dependency)
        current_advisor: Authenticated advisor (JWT token validated)

    Returns:
        List of reports with metadata
    """
    stmt = select(Report).where(Report.client_id == UUID(client_id))
    result = await db.execute(stmt)
    reports = result.scalars().all()

    return [
        {
            "id": str(r.id),
            "report_type": r.report_type,
            "title": r.title,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "finalized_at": r.finalized_at.isoformat() if r.finalized_at else None,
        }
        for r in reports
    ]


@router.get("/{client_id}/{report_id}")
async def get_report(
    client_id: str,
    report_id: str,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
    current_advisor: dict = Depends(get_current_advisor),  # JWT auth
):
    """
    Get full report content and status.

    **Multi-tenancy & Authentication:**
    - Requires valid JWT token
    - Verifies advisor owns the client

    Args:
        client_id: Client UUID
        report_id: Report UUID
        client: Verified client (dependency)
        current_advisor: Authenticated advisor (JWT token validated)

    Returns:
        Full report with content and HTML
    """
    report = await db.get(Report, UUID(report_id))
    if not report or str(report.client_id) != client_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    return {
        "id": str(report.id),
        "report_type": report.report_type,
        "title": report.title,
        "content": report.content,
        "content_html": report.content_html,
        "status": report.status,
        "created_at": report.created_at.isoformat(),
        "finalized_at": report.finalized_at.isoformat() if report.finalized_at else None,
        "metadata": report.generation_metadata,
    }


@router.get("/{client_id}/{report_id}/status")
async def get_report_status(
    client_id: str,
    report_id: str,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
    current_advisor: dict = Depends(get_current_advisor),  # JWT auth
):
    """
    Poll report generation status.

    **Multi-tenancy & Authentication:**
    - Requires valid JWT token
    - Verifies advisor owns the client

    **Why polling?**
    - Simple HTTP GET, no WebSocket needed
    - Browser polls every 1-2 seconds
    - When status changes to "final", show content

    **Better:** WebSocket for real-time updates (future)
    """
    report = await db.get(Report, UUID(report_id))
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    return {
        "report_id": str(report.id),
        "status": report.status,
        "is_complete": report.status == "final",
        "created_at": report.created_at.isoformat(),
        "metadata": report.generation_metadata,
    }


@router.post("/{client_id}/{report_id}/download")
async def download_report_pdf(
    client_id: str,
    report_id: str,
    db: AsyncSession = Depends(get_db),
    client: Client = Depends(verify_client_ownership),  # Multi-tenancy check
    current_advisor: dict = Depends(get_current_advisor),  # JWT auth
):
    """
    Download report as PDF.

    **Multi-tenancy & Authentication:**
    - Requires valid JWT token
    - Verifies advisor owns the client

    **Uses WeasyPrint to convert HTML → PDF**

    In production:
    ```python
    from weasyprint import HTML, CSS
    html_content = report.content_html
    HTML(string=html_content).write_pdf(f'report_{report_id}.pdf')
    ```

    Then return FileResponse with PDF bytes.
    """
    report = await db.get(Report, UUID(report_id))
    if not report or str(report.client_id) != client_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found",
        )

    if report.status != "final":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Report is not yet complete",
        )

    # In production, generate PDF here with WeasyPrint
    # For now, return placeholder
    return {
        "message": "PDF generation would happen here",
        "report_id": str(report.id),
        "note": "WeasyPrint integration in next phase",
    }
