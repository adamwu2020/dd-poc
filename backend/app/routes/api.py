import json

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.auth import current_user
from app.data.departments import DEPARTMENT_CONDITIONS, find_department
from app.db import JobRecord, User, get_session
from app.export import MEDIA_TYPES, ExportFormat, ExportPart, export_samples
from app.generation.llm import GenerationError, LLMClient, get_llm
from app.jobs import jobs, load_samples, replay_events
from app.schemas import JobStatus

router = APIRouter(prefix="/api")


async def _own_job(job_id: str, user: User, db: AsyncSession) -> JobRecord:
    record = await db.get(JobRecord, job_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(status_code=404, detail="job not found")
    return record


def _status(record: JobRecord) -> JobStatus:
    live = jobs.get(record.id)
    if live:
        return live.status_model()
    return JobStatus(
        job_id=record.id,
        status=record.status,  # type: ignore[arg-type]
        total=record.total,
        completed=record.completed,
        failed=record.failed,
        error=record.error,
    )


@router.get("/health")
async def health() -> dict:
    s = config.settings
    return {
        "status": "ok",
        "mode": s.generation_mode,
        "model": s.generation_model,
        "max_samples_per_job": s.max_samples_per_job,
        "payment_mode": s.payment_mode,
    }


@router.get("/departments")
async def list_departments() -> list[str]:
    return list(DEPARTMENT_CONDITIONS)


@router.get("/departments/{department}/conditions")
async def list_conditions(
    department: str, llm: LLMClient = Depends(get_llm), _: User = Depends(current_user)
) -> dict:
    seeded = find_department(department)
    if seeded:
        return {"department": seeded, "source": "seed", "conditions": DEPARTMENT_CONDITIONS[seeded]}
    try:
        conditions = await llm.suggest_conditions(department.strip())
    except (GenerationError, anthropic.APIError) as e:
        raise HTTPException(status_code=502, detail=f"could not suggest conditions: {e}") from e
    return {"department": department.strip(), "source": "llm", "conditions": conditions}


class JobSummary(BaseModel):
    job_id: str
    status: str
    department: str
    conditions: list[str]
    total: int
    completed: int
    failed: int
    created_at: str


@router.get("/jobs")
async def list_jobs(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> list[JobSummary]:
    rows = await db.execute(
        select(JobRecord).where(JobRecord.user_id == user.id).order_by(JobRecord.created_at.desc()).limit(50)
    )
    summaries = []
    for r in rows.scalars():
        s = _status(r)
        summaries.append(
            JobSummary(
                job_id=r.id,
                status=s.status,
                department=r.request["department"],
                conditions=r.request["conditions"],
                total=s.total,
                completed=s.completed,
                failed=s.failed,
                created_at=r.created_at.isoformat() + "Z",
            )
        )
    return summaries


@router.get("/jobs/{job_id}")
async def job_status(
    job_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> JobStatus:
    return _status(await _own_job(job_id, user, db))


@router.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> JobStatus:
    record = await _own_job(job_id, user, db)
    job = jobs.get(job_id)
    if job and job.task and not job.finished:
        job.task.cancel()
    return _status(record)


@router.get("/jobs/{job_id}/stream")
async def stream_job(
    job_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    """Server-Sent Events: replays every event so far, then streams new ones."""
    await _own_job(job_id, user, db)
    job = jobs.get(job_id)

    async def event_source():
        events = job.events_from(0) if job else _iterate(await replay_events(job_id))
        async for event in events:
            yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _iterate(items):
    for item in items:
        yield item


@router.get("/jobs/{job_id}/samples")
async def job_samples(
    job_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_session)
) -> list[dict]:
    await _own_job(job_id, user, db)
    return [s.model_dump() for s in await load_samples(job_id)]


@router.get("/jobs/{job_id}/export")
async def export_job(
    job_id: str,
    format: ExportFormat = Query("jsonl"),
    part: ExportPart = Query("full"),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    await _own_job(job_id, user, db)
    body = export_samples(await load_samples(job_id), format, part)
    filename = f"patients-{job_id}-{part}.{format}"
    return Response(
        content=body,
        media_type=MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
