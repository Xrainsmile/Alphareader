"""Reports API — sync endpoint for upload script + list/detail for frontend.

Endpoints:
  POST   /api/v1/reports/sync   — Upsert a report (from Node.js sync script)
  DELETE /api/v1/reports/{id}   — Delete a report (requires token)
  GET    /api/v1/reports/       — List all reports (sorted by date desc)
  GET    /api/v1/reports/{id}   — Get single report by id
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.report import Report

logger = logging.getLogger("alphareader.reports")

router = APIRouter(prefix="/reports", tags=["reports"])


# ── Schemas ──

class ReportSyncRequest(BaseModel):
    sync_id: str
    title: str
    date: str = ""
    cover: str = ""
    summary: str = ""
    content: str


class ReportSyncResponse(BaseModel):
    code: int = 0
    action: str
    msg: str
    id: int | None = None


class ReportListItem(BaseModel):
    id: int
    sync_id: str
    title: str
    date: str
    cover: str
    summary: str

    class Config:
        from_attributes = True


class ReportDetail(BaseModel):
    id: int
    sync_id: str
    title: str
    date: str
    cover: str
    summary: str
    content: str

    class Config:
        from_attributes = True


# ── Auth helper ──

import hmac

SYNC_TOKEN = settings.REPORT_SYNC_TOKEN


def verify_sync_token(authorization: str = Header("")):
    """Simple Bearer token check for the sync endpoint."""
    if not SYNC_TOKEN:
        raise HTTPException(status_code=503, detail="REPORT_SYNC_TOKEN 未配置")
    token = authorization.replace("Bearer ", "").strip()
    if not token or not hmac.compare_digest(token.encode(), SYNC_TOKEN.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return token


# ── Endpoints ──

@router.post("/sync", response_model=ReportSyncResponse)
async def sync_report(
    payload: ReportSyncRequest,
    _token: str = Depends(verify_sync_token),
    db: AsyncSession = Depends(get_db),
):
    """Upsert a report — used by the Node.js sync script."""
    stmt = select(Report).where(Report.sync_id == payload.sync_id)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.title = payload.title
        existing.date = payload.date
        existing.cover = payload.cover
        existing.summary = payload.summary
        existing.content = payload.content
        await db.commit()
        logger.info("Report updated: %s", payload.title)
        return ReportSyncResponse(action="updated", msg=f"已更新: {payload.title}", id=existing.id)
    else:
        report = Report(
            sync_id=payload.sync_id,
            title=payload.title,
            date=payload.date,
            cover=payload.cover,
            summary=payload.summary,
            content=payload.content,
        )
        db.add(report)
        await db.commit()
        await db.refresh(report)
        logger.info("Report created: %s", payload.title)
        return ReportSyncResponse(action="created", msg=f"已创建: {payload.title}", id=report.id)


@router.delete("/{report_id}")
async def delete_report(
    report_id: int,
    _token: str = Depends(verify_sync_token),
    db: AsyncSession = Depends(get_db),
):
    """Delete a report by id (requires Bearer token)."""
    stmt = select(Report).where(Report.id == report_id)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    title = report.title
    await db.delete(report)
    await db.commit()
    logger.info("Report deleted: %s (id=%d)", title, report_id)
    return {"code": 0, "msg": f"已删除: {title}"}


@router.get("/", response_model=list[ReportListItem])
async def list_reports(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List reports sorted by date descending (for frontend list page)."""
    stmt = (
        select(Report)
        .order_by(Report.date.desc(), Report.id.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    reports = result.scalars().all()
    return [
        ReportListItem(
            id=r.id,
            sync_id=r.sync_id,
            title=r.title,
            date=r.date,
            cover=r.cover or "",
            summary=r.summary or "",
        )
        for r in reports
    ]


@router.get("/{report_id}", response_model=ReportDetail)
async def get_report(
    report_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a single report by id (for frontend detail page)."""
    stmt = select(Report).where(Report.id == report_id)
    result = await db.execute(stmt)
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return ReportDetail(
        id=report.id,
        sync_id=report.sync_id,
        title=report.title,
        date=report.date,
        cover=report.cover or "",
        summary=report.summary or "",
        content=report.content,
    )
