"""LLM backends: the Claude API, and a mock for development without an API key."""

import asyncio
import random
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from app.config import settings
from app.data.departments import DEPARTMENT_CONDITIONS, find_department
from app.generation import prompts
from app.schemas import (
    ConditionPlan,
    ConditionSuggestions,
    Demographics,
    Diagnosis,
    PatientRecord,
    PhysicalExam,
    SampleSpec,
    TestResult,
    Vitals,
)

T = TypeVar("T", bound=BaseModel)


class GenerationError(Exception):
    """A single LLM call produced no usable output (refusal, truncation, bad JSON)."""


class LLMClient(Protocol):
    async def generate_record(self, spec: SampleSpec) -> PatientRecord: ...
    async def plan_negatives(self, department: str, condition: str) -> ConditionPlan: ...
    async def suggest_conditions(self, department: str) -> list[str]: ...


class AnthropicLLM:
    def __init__(self, client: anthropic.AsyncAnthropic | None = None):
        self._client = client or anthropic.AsyncAnthropic()

    async def _parse(self, system: str, user: str, output_format: type[T]) -> T:
        response = await self._client.beta.messages.parse(
            model=settings.generation_model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=output_format,
            output_config={"effort": settings.generation_effort},
            # If the model declines, retry server-side on Anthropic's recommended fallback.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise GenerationError("model declined the request")
        if response.stop_reason == "max_tokens":
            raise GenerationError("response was truncated (max_tokens)")
        if response.parsed_output is None:
            raise GenerationError("response did not match the expected schema")
        return response.parsed_output

    async def generate_record(self, spec: SampleSpec) -> PatientRecord:
        return await self._parse(
            prompts.RECORD_SYSTEM_PROMPT, prompts.record_prompt(spec), PatientRecord
        )

    async def plan_negatives(self, department: str, condition: str) -> ConditionPlan:
        return await self._parse(
            prompts.PLAN_SYSTEM_PROMPT,
            prompts.plan_prompt(department, condition),
            ConditionPlan,
        )

    async def suggest_conditions(self, department: str) -> list[str]:
        result = await self._parse(
            prompts.SUGGEST_SYSTEM_PROMPT,
            prompts.suggest_prompt(department),
            ConditionSuggestions,
        )
        return result.conditions


class MockLLM:
    """Returns template records instantly. Useful for UI work and tests."""

    def __init__(self, delay: float = 0.05):
        self._delay = delay

    async def generate_record(self, spec: SampleSpec) -> PatientRecord:
        await asyncio.sleep(self._delay)
        rng = random.Random(spec.index)
        abnormal = spec.label == "positive"
        return PatientRecord(
            demographics=Demographics(age=spec.age, sex=spec.sex),
            chief_complaint=f"[mock] Presenting complaint suggestive of {spec.intended_diagnosis}.",
            history_of_present_illness=(
                f"[mock] {spec.age}-year-old {spec.sex} with a {spec.severity}, "
                f"{spec.presentation} presentation over the past {rng.randint(1, 14)} days."
            ),
            past_medical_history=rng.sample(
                ["Hypertension", "Type 2 diabetes mellitus", "Hyperlipidemia", "Asthma", "None"], 2
            ),
            medications=["[mock] Medication A 10 mg daily"],
            allergies=["No known drug allergies"],
            family_history="[mock] Non-contributory.",
            social_history="[mock] Non-smoker, occasional alcohol.",
            review_of_systems="[mock] Otherwise negative.",
            physical_exam=PhysicalExam(
                vitals=Vitals(
                    blood_pressure=f"{rng.randint(105, 160)}/{rng.randint(60, 95)} mmHg",
                    heart_rate=rng.randint(60, 115),
                    respiratory_rate=rng.randint(12, 24),
                    temperature_c=round(rng.uniform(36.4, 38.6), 1),
                    spo2=rng.randint(90, 99),
                ),
                findings="[mock] Examination findings.",
            ),
            test_results=[
                TestResult(
                    name="C-reactive protein",
                    category="lab",
                    result=str(rng.randint(40, 120) if abnormal else rng.randint(1, 4)),
                    unit="mg/L",
                    reference_range="<5",
                    flag="high" if abnormal else "normal",
                )
            ],
            diagnosis=Diagnosis(
                final=spec.intended_diagnosis,
                differentials=[spec.target_condition] if spec.label == "negative" else [],
            ),
            plan="[mock] Management plan.",
        )

    async def plan_negatives(self, department: str, condition: str) -> ConditionPlan:
        dept = find_department(department)
        others = [c for c in DEPARTMENT_CONDITIONS.get(dept or "", []) if c != condition]
        return ConditionPlan(
            hard_negatives=others[:4] or [f"Condition mimicking {condition}"],
            easy_negatives=others[4:] or ["Unrelated condition"],
        )

    async def suggest_conditions(self, department: str) -> list[str]:
        return [f"{department} condition {i}" for i in range(1, 6)]


def get_llm() -> LLMClient:
    if settings.generation_mode == "mock":
        return MockLLM()
    return AnthropicLLM()
