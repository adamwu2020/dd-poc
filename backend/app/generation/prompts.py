from app.schemas import SampleSpec

RECORD_SYSTEM_PROMPT = """\
You write fully synthetic hospital patient records that are used as labeled test \
cases for evaluating language models on clinical reasoning. The records must read \
like real clinical documentation written by a physician, but describe fictional \
patients: never use real names, dates of birth, addresses, or identifiers.

Write each record so that the clinical picture is internally consistent and \
medically plausible:
- The history, examination, and test results together support the assigned final \
diagnosis, the way they would in a real case.
- Include the investigations a clinician would actually order for this \
presentation, with realistic values, units, and reference ranges. Normal results \
are as important as abnormal ones.
- Include pertinent negatives in the history and review of systems.
- Do not name the final diagnosis anywhere outside the diagnosis section, so the \
record can be used as a test case once that section is removed. Clinical findings \
that point to it are expected.
- Vary writing style, level of detail, and comorbidities from case to case so \
records do not look templated."""

PLAN_SYSTEM_PROMPT = """\
You are an experienced clinician helping build an evaluation dataset of synthetic \
patient records."""

SUGGEST_SYSTEM_PROMPT = PLAN_SYSTEM_PROMPT


def record_prompt(spec: SampleSpec) -> str:
    if spec.label == "positive":
        role = (
            f"This is a POSITIVE case: the patient has {spec.target_condition}. "
            f"The final diagnosis must be {spec.intended_diagnosis}."
        )
    elif spec.negative_type == "hard":
        role = (
            f"This is a HARD NEGATIVE case for {spec.target_condition}: the patient "
            f"presents with symptoms that overlap with {spec.target_condition}, so it "
            f"is a reasonable differential, but the work-up shows the final diagnosis "
            f"is {spec.intended_diagnosis}. The record must not support a diagnosis of "
            f"{spec.target_condition}."
        )
    else:
        role = (
            f"This is an EASY NEGATIVE case for {spec.target_condition}: the patient "
            f"presents to {spec.department} with {spec.intended_diagnosis}, which is "
            f"clinically unrelated to {spec.target_condition}. The record must not "
            f"support a diagnosis of {spec.target_condition}."
        )

    return f"""\
Write one synthetic patient record.

Department: {spec.department}
{role}

Patient profile:
- Age: {spec.age}
- Sex: {spec.sex}
- Severity of the presenting illness: {spec.severity}
- Presentation: {spec.presentation}

Write all free-text fields in {spec.language}. Use "{spec.intended_diagnosis}" \
(or a more specific form of it) as diagnosis.final and list the differentials that \
were considered."""


def plan_prompt(department: str, condition: str) -> str:
    return f"""\
Department: {department}
Target condition: {condition}

We need negative examples for a classifier that answers "does this patient have \
{condition}?". List:
- hard_negatives: 6-10 diagnoses that present similarly to {condition} and are \
part of its differential diagnosis, but are a different condition.
- easy_negatives: 6-10 common diagnoses seen in {department} that are clinically \
unrelated to {condition}.

Use specific diagnosis names (not symptoms), and do not include {condition} itself \
or a subtype of it."""


def suggest_prompt(department: str) -> str:
    return f"""\
List 8-12 diseases and presenting symptoms that are commonly seen in the \
{department} department of a general hospital. Put diseases first, then 2-4 common \
presenting symptoms. Use standard clinical names in English."""
