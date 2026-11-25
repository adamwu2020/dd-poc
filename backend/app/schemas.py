"""Pydantic models for API payloads and generated patient records.

`PatientRecord` doubles as the structured-output schema sent to the LLM, so keep
it to plain types (no numeric bounds or regex patterns).
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Label = Literal["positive", "negative"]
NegativeType = Literal["hard", "easy"]
NegativeStrategy = Literal["hard", "easy", "mixed"]
Severity = Literal["mild", "moderate", "severe"]
SeverityOption = Literal["mild", "moderate", "severe", "mixed"]


# --- Patient record (LLM output) -------------------------------------------------


class Demographics(BaseModel):
    age: int
    sex: Literal["male", "female"]


class Vitals(BaseModel):
    blood_pressure: str = Field(description="e.g. '128/82 mmHg'")
    heart_rate: int = Field(description="beats per minute")
    respiratory_rate: int = Field(description="breaths per minute")
    temperature_c: float
    spo2: int = Field(description="oxygen saturation, percent")


class PhysicalExam(BaseModel):
    vitals: Vitals
    findings: str


class TestResult(BaseModel):
    name: str
    category: Literal["lab", "imaging", "ecg", "microbiology", "pathology", "other"]
    result: str = Field(description="Value or narrative finding")
    unit: str = Field(description="Empty string if not applicable")
    reference_range: str = Field(description="Empty string if not applicable")
    flag: Literal["high", "low", "normal", "abnormal", "n/a"]


class Diagnosis(BaseModel):
    final: str
    differentials: list[str]


class PatientRecord(BaseModel):
    demographics: Demographics
    chief_complaint: str
    history_of_present_illness: str
    past_medical_history: list[str]
    medications: list[str]
    allergies: list[str]
    family_history: str
    social_history: str
    review_of_systems: str
    physical_exam: PhysicalExam
    test_results: list[TestResult]
    diagnosis: Diagnosis
    plan: str


class ConditionPlan(BaseModel):
    """Alternative diagnoses used for negative samples of one target condition."""

    hard_negatives: list[str] = Field(
        description="Diagnoses whose presentation overlaps with the target condition"
    )
    easy_negatives: list[str] = Field(
        description="Common diagnoses in the department unrelated to the target condition"
    )


class ConditionSuggestions(BaseModel):
    conditions: list[str]


# --- Samples ---------------------------------------------------------------------


class SampleSpec(BaseModel):
    """What one sample should look like, decided before calling the LLM."""

    index: int
    department: str
    target_condition: str
    label: Label
    negative_type: NegativeType | None = None
    intended_diagnosis: str
    age: int
    sex: Literal["male", "female"]
    severity: Severity
    presentation: Literal["typical", "atypical"]
    language: str = "English"


class Sample(BaseModel):
    id: str
    department: str
    target_condition: str
    label: Label
    negative_type: NegativeType | None
    intended_diagnosis: str
    record: PatientRecord


# --- API payloads ----------------------------------------------------------------


class GenerationOptions(BaseModel):
    negative_strategy: NegativeStrategy = "mixed"
    severity: SeverityOption = "mixed"
    age_min: int = Field(default=18, ge=0, le=110)
    age_max: int = Field(default=85, ge=0, le=110)
    sex: Literal["mixed", "male", "female"] = "mixed"
    language: str = "English"
    seed: int | None = None

    @model_validator(mode="after")
    def _check_age_range(self) -> "GenerationOptions":
        if self.age_min > self.age_max:
            raise ValueError("age_min must be <= age_max")
        return self


class GenerateRequest(BaseModel):
    department: str = Field(min_length=1, max_length=100)
    conditions: list[str] = Field(min_length=1, max_length=20)
    positive_count: int = Field(ge=0, le=500)
    negative_count: int = Field(ge=0, le=500)
    options: GenerationOptions = GenerationOptions()

    @field_validator("conditions")
    @classmethod
    def _clean_conditions(cls, v: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(c.strip() for c in v if c.strip()))
        if not cleaned:
            raise ValueError("at least one condition is required")
        return cleaned

    @model_validator(mode="after")
    def _check_counts(self) -> "GenerateRequest":
        if self.positive_count + self.negative_count == 0:
            raise ValueError("positive_count + negative_count must be at least 1")
        return self

    @property
    def total_samples(self) -> int:
        return (self.positive_count + self.negative_count) * len(self.conditions)


class JobStatus(BaseModel):
    job_id: str
    status: Literal["planning", "running", "completed", "failed", "cancelled"]
    total: int
    completed: int
    failed: int
    error: str | None = None
