"""In-memory generation jobs and their event streams."""

import asyncio
import logging
import uuid
from collections import OrderedDict
from typing import Any, AsyncIterator

import anthropic

from app.config import settings
from app.generation.llm import GenerationError, LLMClient
from app.generation.planner import build_specs, ensure_plan
from app.schemas import ConditionPlan, GenerateRequest, JobStatus, Sample, SampleSpec

logger = logging.getLogger(__name__)

MAX_STORED_JOBS = 50

# Errors that will fail every request in the job, so retrying is pointless.
FATAL_API_ERRORS = (
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.BadRequestError,
    anthropic.NotFoundError,
)


class Job:
    def __init__(self, request: GenerateRequest, llm: LLMClient):
        self.id = uuid.uuid4().hex[:12]
        self.request = request
        self.llm = llm
        self.status: str = "planning"
        self.error: str | None = None
        self.total = request.total_samples
        self.samples: dict[int, Sample] = {}
        self.failed: dict[int, str] = {}
        self.events: list[dict[str, Any]] = []
        self._changed = asyncio.Condition()
        self.task: asyncio.Task | None = None

    # --- state -------------------------------------------------------------------

    @property
    def finished(self) -> bool:
        return self.status in ("completed", "failed", "cancelled")

    def status_model(self) -> JobStatus:
        return JobStatus(
            job_id=self.id,
            status=self.status,  # type: ignore[arg-type]
            total=self.total,
            completed=len(self.samples),
            failed=len(self.failed),
            error=self.error,
        )

    def ordered_samples(self) -> list[Sample]:
        return [self.samples[i] for i in sorted(self.samples)]

    async def _emit(self, event: dict[str, Any]) -> None:
        async with self._changed:
            self.events.append(event)
            self._changed.notify_all()

    async def _emit_status(self) -> None:
        await self._emit({"type": "status", **self.status_model().model_dump()})

    async def events_from(self, start: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Yield all events from `start`, then new ones until the job finishes."""
        i = start
        while True:
            async with self._changed:
                await self._changed.wait_for(lambda: len(self.events) > i or self.finished)
                pending = self.events[i:]
                done = self.finished
            for event in pending:
                yield event
            i += len(pending)
            if done and i >= len(self.events):
                return

    # --- execution ---------------------------------------------------------------

    async def run(self) -> None:
        try:
            await self._emit_status()
            plans = await self._plan()
            specs = build_specs(self.request, plans)
            self.status = "running"
            await self._emit_status()

            semaphore = asyncio.Semaphore(settings.max_concurrency)
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
            await self._emit_status()
            await self._emit({"type": "done", "status": self.status, "error": self.error})

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
            for _ in range(settings.max_attempts_per_sample):
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
        self.samples[spec.index] = sample
        await self._emit({"type": "sample", "index": spec.index, "sample": sample.model_dump()})
        await self._emit_status()


def _describe(e: BaseException) -> str:
    if isinstance(e, anthropic.APIStatusError):
        return f"{type(e).__name__} ({e.status_code}): {e.message}"
    return f"{type(e).__name__}: {e}"


class JobStore:
    def __init__(self) -> None:
        self._jobs: OrderedDict[str, Job] = OrderedDict()

    def start(self, request: GenerateRequest, llm: LLMClient) -> Job:
        job = Job(request, llm)
        self._jobs[job.id] = job
        self._evict()
        job.task = asyncio.create_task(job.run())
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _evict(self) -> None:
        while len(self._jobs) > MAX_STORED_JOBS:
            oldest = next((j for j in self._jobs.values() if j.finished), None)
            if oldest is None:
                return
            del self._jobs[oldest.id]


jobs = JobStore()
