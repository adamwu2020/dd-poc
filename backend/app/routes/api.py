import json

import anthropic
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from app.config import settings
from app.data.departments import DEPARTMENT_CONDITIONS, find_department
from app.export import MEDIA_TYPES, ExportFormat, ExportPart, export_samples
from app.generation.llm import GenerationError, LLMClient, get_llm
from app.jobs import Job, jobs
from app.schemas import GenerateRequest, JobStatus

router = APIRouter(prefix="/api")


def _get_job(job_id: str) -> Job:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "mode": settings.generation_mode,
        "model": settings.generation_model,
        "max_samples_per_job": settings.max_samples_per_job,
    }


@router.get("/departments")
async def list_departments() -> list[str]:
    return list(DEPARTMENT_CONDITIONS)


@router.get("/departments/{department}/conditions")
async def list_conditions(department: str, llm: LLMClient = Depends(get_llm)) -> dict:
    seeded = find_department(department)
    if seeded:
        return {"department": seeded, "source": "seed", "conditions": DEPARTMENT_CONDITIONS[seeded]}
    try:
        conditions = await llm.suggest_conditions(department.strip())
    except (GenerationError, anthropic.APIError) as e:
        raise HTTPException(status_code=502, detail=f"could not suggest conditions: {e}") from e
    return {"department": department.strip(), "source": "llm", "conditions": conditions}


@router.post("/generate", status_code=202)
async def generate(request: GenerateRequest, llm: LLMClient = Depends(get_llm)) -> JobStatus:
    if request.total_samples > settings.max_samples_per_job:
        raise HTTPException(
            status_code=422,
            detail=(
                f"this request would generate {request.total_samples} samples; "
                f"the limit is {settings.max_samples_per_job} per job"
            ),
        )
    job = jobs.start(request, llm)
    return job.status_model()


@router.get("/jobs/{job_id}")
async def job_status(job_id: str) -> JobStatus:
    return _get_job(job_id).status_model()


@router.delete("/jobs/{job_id}")
async def cancel_job(job_id: str) -> JobStatus:
    job = _get_job(job_id)
    if job.task and not job.finished:
        job.task.cancel()
    return job.status_model()


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str) -> StreamingResponse:
    """Server-Sent Events: replays every event so far, then streams new ones."""
    job = _get_job(job_id)

    async def event_source():
        async for event in job.events_from(0):
            yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}/samples")
async def job_samples(job_id: str) -> list[dict]:
    return [s.model_dump() for s in _get_job(job_id).ordered_samples()]


@router.get("/jobs/{job_id}/export")
async def export_job(
    job_id: str,
    format: ExportFormat = Query("jsonl"),
    part: ExportPart = Query("full"),
) -> Response:
    job = _get_job(job_id)
    body = export_samples(job.ordered_samples(), format, part)
    filename = f"patients-{job.id}-{part}.{format}"
    return Response(
        content=body,
        media_type=MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
