"""Generation jobs: run in-process, stream events live, and persist results to the database.

Users are charged only for delivered samples: when a job ends, every sample that was
not delivered (failed, cancelled, or interrupted) is credited back to the account.
"""

import asyncio
import logging
from collections import OrderedDict
from typing import Any, AsyncIterator

import anthropic
from sqlalchemy import select, update

from app import config
from app.db import JobRecord, SampleRecord, User, session_scope, utcnow
from app.generation.llm import GenerationError, LLMClient
from app.generation.planner import build_specs, ensure_plan
from app.schemas import ConditionPlan, GenerateRequest, JobStatus, Sample, SampleSpec

logger = logging.getLogger(__name__)

MAX_JOBS_IN_MEMORY = 50
ACTIVE_STATUSES = ("planning", "running")

# Errors that will fail every request in the job, so retrying is pointless.
FATAL_API_ERRORS = (
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.BadRequestError,
    anthropic.NotFoundError,
)


def _status_event(record: JobRecord) -> dict[str, Any]:
    return {
        "type": "status",
        **JobStatus(
            job_id=record.id,
            status=record.status,  # type: ignore[arg-type]
            total=record.total,
            completed=record.completed,
            failed=record.failed,
            error=record.error,
        ).model_dump(),
    }


async def _credit_undelivered(db, user_id: int, record: JobRecord) -> None:
    undelivered = record.total - record.completed
    if undelivered > 0:
        await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(sample_credits=User.sample_credits + undelivered)
        )


class Job:
    def __init__(self, job_id: str, user_id: int, request: GenerateRequest, llm: LLMClient):
        self.id = job_id
        self.user_id = user_id
        self.request = request
        self.llm = llm
        self.status: str = "planning"
        self.error: str | None = None
        self.total = request.total_samples
        self.completed = 0
        self.failed: dict[int, str] = {}
        self.events: list[dict[str, Any]] = []
        self._changed = asyncio.Condition()
        self._closed = False  # set once the final "done" event has been emitted
        self.task: asyncio.Task | None = None

    @property
    def finished(self) -> bool:
        return self.status not in ACTIVE_STATUSES

    def status_model(self) -> JobStatus:
        return JobStatus(
            job_id=self.id,
            status=self.status,  # type: ignore[arg-type]
            total=self.total,
            completed=self.completed,
            failed=len(self.failed),
            error=self.error,
        )

    async def _emit(self, event: dict[str, Any]) -> None:
        async with self._changed:
            self.events.append(event)
            if event["type"] == "done":
                self._closed = True
            self._changed.notify_all()

    async def _emit_status(self) -> None:
        await self._emit({"type": "status", **self.status_model().model_dump()})

    async def events_from(self, start: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Yield all events from `start`, then new ones until the job finishes."""
        i = start
        while True:
            async with self._changed:
                await self._changed.wait_for(lambda: len(self.events) > i or self._closed)
                pending = self.events[i:]
                done = self._closed
            for event in pending:
                yield event
            i += len(pending)
            if done and i >= len(self.events):
                return

    async def _save(self, **values: Any) -> None:
        async with session_scope() as db:
            await db.execute(update(JobRecord).where(JobRecord.id == self.id).values(**values))
            await db.commit()

    # --- execution ---------------------------------------------------------------

    async def run(self) -> None:
        try:
            await self._emit_status()
            plans = await self._plan()
            specs = build_specs(self.request, plans)
            self.status = "running"
            await self._save(status="running")
            await self._emit_status()

            semaphore = asyncio.Semaphore(config.settings.max_concurrency)
            async with asyncio.TaskGroup() as tg:
                for spec in specs:
                    tg.create_task(self._generate(spec, semaphore))

            self.status = "completed"
        except asyncio.CancelledError:
            self.status = "cancelled"
        except Exception as e:
            # TaskGroup wraps failures in an ExceptionGroup; report the first cause.
            while isinstance(e, ExceptionGroup):
                e = e.exceptions[0]
            if not isinstance(e, FATAL_API_ERRORS):
                logger.error("job %s failed", self.id, exc_info=e)
            self.status = "failed"
            self.error = _describe(e)
        finally:
            await self._finish()
            await self._emit_status()
            await self._emit({"type": "done", "status": self.status, "error": self.error})

    async def _finish(self) -> None:
        async with session_scope() as db:
            record = await db.get(JobRecord, self.id)
            record.status = self.status
            record.error = self.error
            record.completed = self.completed
            record.failed = len(self.failed)
            record.finished_at = utcnow()
            await _credit_undelivered(db, self.user_id, record)
            await db.commit()

    async def _plan(self) -> dict[str, ConditionPlan]:
        if self.request.negative_count == 0:
            empty = ConditionPlan(hard_negatives=["-"], easy_negatives=["-"])
            return {c: empty for c in self.request.conditions}

        async def plan_one(condition: str) -> tuple[str, ConditionPlan]:
            plan = await self.llm.plan_negatives(self.request.department, condition)
            return condition, ensure_plan(plan, condition)

        results = await asyncio.gather(*(plan_one(c) for c in self.request.conditions))
        return dict(results)

    async def _generate(self, spec: SampleSpec, semaphore: asyncio.Semaphore) -> None:
        last_error = "unknown error"
        async with semaphore:
            for _ in range(config.settings.max_attempts_per_sample):
                try:
                    record = await self.llm.generate_record(spec)
                    break
                except FATAL_API_ERRORS:
                    raise
                except (GenerationError, anthropic.APIError) as e:
                    last_error = _describe(e)
                    logger.warning("sample %d of job %s: %s", spec.index, self.id, last_error)
            else:
                self.failed[spec.index] = last_error
                await self._save(failed=len(self.failed))
                await self._emit({"type": "sample_error", "index": spec.index, "error": last_error})
                await self._emit_status()
                return

        sample = Sample(
            id=f"sample-{spec.index + 1:04d}",
            department=spec.department,
            target_condition=spec.target_condition,
            label=spec.label,
            negative_type=spec.negative_type,
            intended_diagnosis=spec.intended_diagnosis,
            record=record,
        )
        self.completed += 1
        async with session_scope() as db:
            db.add(SampleRecord(job_id=self.id, index=spec.index, data=sample.model_dump()))
            await db.execute(
                update(JobRecord)
                .where(JobRecord.id == self.id)
                .values(completed=JobRecord.completed + 1)
            )
            await db.commit()
        await self._emit({"type": "sample", "index": spec.index, "sample": sample.model_dump()})
        await self._emit_status()


def _describe(e: BaseException) -> str:
    if isinstance(e, anthropic.APIStatusError):
        return f"{type(e).__name__} ({e.status_code}): {e.message}"
    return f"{type(e).__name__}: {e}"


class JobStore:
    """Jobs currently running (or recently finished) in this process."""

    def __init__(self) -> None:
        self._jobs: OrderedDict[str, Job] = OrderedDict()

    def start(self, job_id: str, user_id: int, request: GenerateRequest, llm: LLMClient) -> Job:
        job = Job(job_id, user_id, request, llm)
        self._jobs[job.id] = job
        self._evict()
        job.task = asyncio.create_task(job.run())
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _evict(self) -> None:
        while len(self._jobs) > MAX_JOBS_IN_MEMORY:
            oldest = next((j for j in self._jobs.values() if j.finished), None)
            if oldest is None:
                return
            del self._jobs[oldest.id]


jobs = JobStore()


# --- database-backed reads ---------------------------------------------------------


async def get_job_record(job_id: str) -> JobRecord | None:
    async with session_scope() as db:
        return await db.get(JobRecord, job_id)


async def load_samples(job_id: str) -> list[Sample]:
    async with session_scope() as db:
        rows = await db.execute(
            select(SampleRecord).where(SampleRecord.job_id == job_id).order_by(SampleRecord.index)
        )
        return [Sample(**r.data) for r in rows.scalars()]


async def replay_events(job_id: str) -> list[dict[str, Any]]:
    """Events for a job that isn't running in this process (finished, or from before a restart)."""
    record = await get_job_record(job_id)
    if record is None:
        return []
    events = [_status_event(record)]
    async with session_scope() as db:
        rows = await db.execute(
            select(SampleRecord).where(SampleRecord.job_id == job_id).order_by(SampleRecord.index)
        )
        events += [{"type": "sample", "index": r.index, "sample": r.data} for r in rows.scalars()]
    events.append({"type": "done", "status": record.status, "error": record.error})
    return events


async def recover_interrupted_jobs() -> None:
    """At startup, close out jobs that were running when the process stopped."""
    async with session_scope() as db:
        stale = (
            await db.execute(select(JobRecord).where(JobRecord.status.in_(ACTIVE_STATUSES)))
        ).scalars().all()
        for record in stale:
            if jobs.get(record.id):
                continue
            record.status = "failed"
            record.error = "Interrupted by a server restart. Undelivered samples were credited to your account."
            record.finished_at = utcnow()
            await _credit_undelivered(db, record.user_id, record)
            logger.warning("job %s was interrupted; marked failed", record.id)
        await db.commit()
