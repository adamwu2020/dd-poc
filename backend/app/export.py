"""Serialize samples to JSONL / JSON / CSV.

`part` selects what to export:
- full:    the complete sample, including diagnosis and plan
- inputs:  the record with diagnosis and plan removed (what the model under test sees)
- answers: id, label, and ground-truth diagnosis only
"""

import csv
import io
import json
from typing import Literal

from app.schemas import Sample

ExportFormat = Literal["jsonl", "json", "csv"]
ExportPart = Literal["full", "inputs", "answers"]

MEDIA_TYPES = {
    "jsonl": "application/x-ndjson",
    "json": "application/json",
    "csv": "text/csv",
}


def _row(sample: Sample, part: ExportPart) -> dict:
    if part == "answers":
        return {
            "id": sample.id,
            "target_condition": sample.target_condition,
            "label": sample.label,
            "negative_type": sample.negative_type,
            "final_diagnosis": sample.record.diagnosis.final,
            "differentials": sample.record.diagnosis.differentials,
        }
    data = sample.model_dump()
    if part == "inputs":
        data = {
            "id": sample.id,
            "department": sample.department,
            "target_condition": sample.target_condition,
            "record": sample.record.model_dump(exclude={"diagnosis", "plan"}),
        }
    return data


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{name}."))
        elif isinstance(value, list):
            if value and isinstance(value[0], dict):
                flat[name] = json.dumps(value, ensure_ascii=False)
            else:
                flat[name] = "; ".join(str(v) for v in value)
        else:
            flat[name] = "" if value is None else str(value)
    return flat


def export_samples(samples: list[Sample], fmt: ExportFormat, part: ExportPart) -> str:
    rows = [_row(s, part) for s in samples]
    if fmt == "jsonl":
        return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    if fmt == "json":
        return json.dumps(rows, ensure_ascii=False, indent=2)

    flat_rows = [_flatten(r) for r in rows]
    fieldnames = list(dict.fromkeys(k for r in flat_rows for k in r))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(flat_rows)
    return buf.getvalue()
