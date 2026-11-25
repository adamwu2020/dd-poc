"""Turns a generation request into a list of per-sample specifications.

Each spec fixes the label, intended diagnosis, and patient profile up front so that
samples are diverse and the dataset composition matches what the user asked for.
"""

import itertools
import random

from app.schemas import ConditionPlan, GenerateRequest, NegativeType, SampleSpec

SEVERITIES = ("mild", "moderate", "severe")
# Share of positive samples given an atypical presentation.
ATYPICAL_RATE = 0.25


def _negative_types(strategy: str, count: int) -> list[NegativeType]:
    if strategy == "hard":
        return ["hard"] * count
    if strategy == "easy":
        return ["easy"] * count
    # mixed: roughly two hard negatives for every easy one
    return ["easy" if i % 3 == 2 else "hard" for i in range(count)]


def build_specs(
    request: GenerateRequest, plans: dict[str, ConditionPlan]
) -> list[SampleSpec]:
    opts = request.options
    rng = random.Random(opts.seed)
    specs: list[SampleSpec] = []

    def profile() -> dict:
        sex = opts.sex if opts.sex != "mixed" else rng.choice(["male", "female"])
        severity = opts.severity if opts.severity != "mixed" else rng.choice(SEVERITIES)
        return {
            "age": rng.randint(opts.age_min, opts.age_max),
            "sex": sex,
            "severity": severity,
            "language": opts.language,
        }

    for condition in request.conditions:
        plan = plans[condition]
        hard = itertools.cycle(rng.sample(plan.hard_negatives, len(plan.hard_negatives)))
        easy = itertools.cycle(rng.sample(plan.easy_negatives, len(plan.easy_negatives)))
        base = {"department": request.department, "target_condition": condition}

        for _ in range(request.positive_count):
            specs.append(
                SampleSpec(
                    index=0,
                    label="positive",
                    intended_diagnosis=condition,
                    presentation="atypical" if rng.random() < ATYPICAL_RATE else "typical",
                    **base,
                    **profile(),
                )
            )
        for neg_type in _negative_types(opts.negative_strategy, request.negative_count):
            specs.append(
                SampleSpec(
                    index=0,
                    label="negative",
                    negative_type=neg_type,
                    intended_diagnosis=next(hard if neg_type == "hard" else easy),
                    presentation="typical",
                    **base,
                    **profile(),
                )
            )

    # Shuffle so labels are interleaved in the output, then number in final order.
    rng.shuffle(specs)
    for i, spec in enumerate(specs):
        spec.index = i
    return specs


def ensure_plan(plan: ConditionPlan, condition: str) -> ConditionPlan:
    """Drop the target condition from its own negatives; never return empty lists."""
    target = condition.strip().lower()

    def clean(items: list[str]) -> list[str]:
        return [d for d in dict.fromkeys(i.strip() for i in items) if d and d.lower() != target]

    hard = clean(plan.hard_negatives)
    easy = clean(plan.easy_negatives)
    return ConditionPlan(
        hard_negatives=hard or easy or [f"Condition other than {condition}"],
        easy_negatives=easy or hard or [f"Condition other than {condition}"],
    )
