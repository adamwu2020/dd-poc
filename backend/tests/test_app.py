import asyncio
import json
from collections import Counter
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from app.export import export_samples
from app.generation.llm import AnthropicLLM, GenerationError, MockLLM, get_llm
from app.generation.planner import build_specs, ensure_plan
from app.main import app
from app.schemas import ConditionPlan, GenerateRequest, Sample

PLAN = ConditionPlan(hard_negatives=["Pericarditis", "Aortic dissection"], easy_negatives=["Gout"])


def make_request(**kwargs) -> GenerateRequest:
    data = {
        "department": "Cardiology",
        "conditions": ["Acute myocardial infarction"],
        "positive_count": 6,
        "negative_count": 9,
        "options": {"seed": 1},
    }
    data.update(kwargs)
    return GenerateRequest(**data)


# --- planner -----------------------------------------------------------------------


def test_build_specs_matches_requested_counts():
    req = make_request(conditions=["Acute myocardial infarction", "Heart failure"])
    specs = build_specs(req, {c: PLAN for c in req.conditions})

    assert len(specs) == 30
    assert [s.index for s in specs] == list(range(30))
    for condition in req.conditions:
        labels = Counter(s.label for s in specs if s.target_condition == condition)
        assert labels == {"positive": 6, "negative": 9}


def test_build_specs_negative_strategies():
    mixed = build_specs(make_request(), {"Acute myocardial infarction": PLAN})
    negs = [s for s in mixed if s.label == "negative"]
    assert Counter(s.negative_type for s in negs) == {"hard": 6, "easy": 3}
    for s in negs:
        expected = PLAN.hard_negatives if s.negative_type == "hard" else PLAN.easy_negatives
        assert s.intended_diagnosis in expected

    hard = build_specs(
        make_request(options={"negative_strategy": "hard"}), {"Acute myocardial infarction": PLAN}
    )
    assert {s.negative_type for s in hard if s.label == "negative"} == {"hard"}


def test_build_specs_respects_profile_options_and_seed():
    req = make_request(options={"seed": 7, "age_min": 30, "age_max": 40, "sex": "female", "severity": "severe"})
    specs = build_specs(req, {"Acute myocardial infarction": PLAN})
    assert all(30 <= s.age <= 40 and s.sex == "female" and s.severity == "severe" for s in specs)
    assert specs == build_specs(req, {"Acute myocardial infarction": PLAN})


def test_ensure_plan_removes_target_and_fills_empty_lists():
    plan = ensure_plan(
        ConditionPlan(hard_negatives=["Migraine", " migraine ", "Cluster headache"], easy_negatives=[]),
        "Migraine",
    )
    assert plan.hard_negatives == ["Cluster headache"]
    assert plan.easy_negatives == ["Cluster headache"]


def test_request_validation():
    with pytest.raises(ValueError):
        make_request(positive_count=0, negative_count=0)
    with pytest.raises(ValueError):
        make_request(conditions=["  "])
    with pytest.raises(ValueError):
        make_request(options={"age_min": 60, "age_max": 20})


# --- LLM client --------------------------------------------------------------------


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def fake_client(**kwargs):
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(**kwargs)))


def test_anthropic_llm_sends_schema_and_fallbacks():
    plan = ConditionPlan(hard_negatives=["A"], easy_negatives=["B"])
    client = fake_client(response=SimpleNamespace(stop_reason="end_turn", parsed_output=plan))
    result = asyncio.run(AnthropicLLM(client).plan_negatives("Cardiology", "Heart failure"))

    assert result == plan
    call = client.beta.messages.calls[0]
    assert call["output_format"] is ConditionPlan
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]


@pytest.mark.parametrize(
    "stop_reason,parsed", [("refusal", None), ("max_tokens", None), ("end_turn", None)]
)
def test_anthropic_llm_raises_on_unusable_response(stop_reason, parsed):
    client = fake_client(response=SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed))
    with pytest.raises(GenerationError):
        asyncio.run(AnthropicLLM(client).plan_negatives("Cardiology", "Heart failure"))


# --- API ---------------------------------------------------------------------------


@pytest.fixture
def client():
    app.dependency_overrides[get_llm] = lambda: MockLLM(delay=0)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def read_stream(client: TestClient, job_id: str) -> list[dict]:
    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/stream") as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_conditions_for_seeded_and_unknown_departments(client):
    r = client.get("/api/departments/cardiology/conditions")
    assert r.json()["source"] == "seed"
    assert "Heart failure" in r.json()["conditions"]

    r = client.get("/api/departments/Dermatology/conditions")
    assert r.json()["source"] == "llm"
    assert r.json()["conditions"]


def test_generate_stream_and_export(client):
    r = client.post(
        "/api/generate",
        json={"department": "Cardiology", "conditions": ["Heart failure"], "positive_count": 3, "negative_count": 2},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    events = read_stream(client, job_id)
    assert events[-1] == {"type": "done", "status": "completed", "error": None}
    samples = [e["sample"] for e in events if e["type"] == "sample"]
    assert Counter(s["label"] for s in samples) == {"positive": 3, "negative": 2}

    inputs = client.get(f"/api/jobs/{job_id}/export", params={"format": "jsonl", "part": "inputs"})
    rows = [json.loads(line) for line in inputs.text.splitlines()]
    assert len(rows) == 5
    assert all("diagnosis" not in row["record"] and "plan" not in row["record"] for row in rows)

    csv_answers = client.get(f"/api/jobs/{job_id}/export", params={"format": "csv", "part": "answers"})
    assert csv_answers.text.splitlines()[0].startswith("id,target_condition,label")


def test_generate_enforces_sample_limit(client):
    def post(positive, negative):
        return client.post(
            "/api/generate",
            json={"department": "Cardiology", "conditions": ["A", "B"], "positive_count": positive, "negative_count": negative},
        )

    assert post(5, 5).status_code == 202  # 2 conditions x 10 = 20, at the limit
    r = post(6, 5)  # 22 samples
    assert r.status_code == 422
    assert "limit is 20" in r.json()["detail"]


def test_fatal_api_error_fails_job(client):
    class BrokenLLM(MockLLM):
        async def generate_record(self, spec):
            request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.AuthenticationError(
                "invalid x-api-key", response=httpx.Response(401, request=request), body=None
            )

    app.dependency_overrides[get_llm] = lambda: BrokenLLM(delay=0)
    r = client.post(
        "/api/generate",
        json={"department": "Cardiology", "conditions": ["Heart failure"], "positive_count": 2, "negative_count": 0},
    )
    events = read_stream(client, r.json()["job_id"])
    assert events[-1]["status"] == "failed"
    assert "AuthenticationError" in events[-1]["error"]


def test_transient_errors_are_reported_per_sample(client):
    class FlakyLLM(MockLLM):
        async def generate_record(self, spec):
            if spec.index == 0:
                raise GenerationError("model declined the request")
            return await super().generate_record(spec)

    app.dependency_overrides[get_llm] = lambda: FlakyLLM(delay=0)
    r = client.post(
        "/api/generate",
        json={"department": "Cardiology", "conditions": ["Heart failure"], "positive_count": 3, "negative_count": 0},
    )
    job_id = r.json()["job_id"]
    events = read_stream(client, job_id)
    assert events[-1]["status"] == "completed"
    assert [e["index"] for e in events if e["type"] == "sample_error"] == [0]
    assert client.get(f"/api/jobs/{job_id}").json()["failed"] == 1


def test_export_csv_flattens_nested_fields():
    spec = build_specs(make_request(positive_count=1, negative_count=0), {"Acute myocardial infarction": PLAN})[0]
    record = asyncio.run(MockLLM(delay=0).generate_record(spec))
    sample = Sample(
        id="sample-0001", department="Cardiology", target_condition=spec.target_condition,
        label="positive", negative_type=None, intended_diagnosis=spec.intended_diagnosis, record=record,
    )
    header = export_samples([sample], "csv", "full").splitlines()[0]
    assert "record.physical_exam.vitals.heart_rate" in header
    assert "record.test_results" in header


def test_app_password_protects_everything_but_health(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "settings", config.Settings(app_password="s3cret"))
    assert client.get("/api/health").status_code == 200
    r = client.get("/api/departments")
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic")
    assert client.get("/api/departments", auth=("anyone", "wrong")).status_code == 401
    assert client.get("/api/departments", auth=("anyone", "s3cret")).status_code == 200
