# Synthetic Patient Data Generator for LLM Evaluation

A web app that generates realistic, **fully synthetic** patient records for evaluating LLMs on clinical reasoning tasks (e.g. "Does this patient have condition X?").

For a chosen hospital department and one or more target conditions, the app produces a labeled dataset of:

- **Positive samples**: patients whose record supports the target diagnosis.
- **Negative samples**: patients with overlapping or similar presentations whose final diagnosis is something else (hard negatives), or who have no relevant pathology.

Each sample is structured like a standard hospital clinical note, so it can be fed directly into an LLM evaluation pipeline.

> ⚠️ **All generated data is synthetic.** It contains no real patient information (PHI) and must not be used for clinical decision-making.

---

## User Journey

### 1. Choose a hospital department

The user enters or selects a department (e.g. *Cardiology*, *Emergency*, *Pediatrics*, *Neurology*, *Gastroenterology*).

The app returns a list of **common diseases and presenting symptoms** for that department, for example:

| Department  | Example diseases / symptoms                                                                        |
|-------------|----------------------------------------------------------------------------------------------------|
| Cardiology  | Acute myocardial infarction, Heart failure, Atrial fibrillation, Chest pain, Palpitations          |
| Neurology   | Ischemic stroke, Migraine, Epilepsy, Parkinson's disease, Headache, Dizziness                      |
| Respiratory | Community-acquired pneumonia, COPD exacerbation, Asthma, Pulmonary embolism, Shortness of breath   |

### 2. Select targets and sample counts

The user:

- Selects **one or more** diseases or symptoms from the list (custom entries are allowed).
- Sets the **number of positive samples** to generate.
- Sets the **number of negative samples** to generate.

Optional advanced settings:

| Setting              | Description                                                                        | Default        |
|----------------------|------------------------------------------------------------------------------------|----------------|
| Negative strategy    | `hard` (similar presentation, different diagnosis), `easy` (unrelated), or `mixed` | `mixed`        |
| Age range / sex mix  | Demographic distribution                                                           | Realistic mix  |
| Severity             | Mild / moderate / severe / mixed                                                   | `mixed`        |
| Language             | Output language of the records                                                     | English        |
| Random seed          | For reproducible generation                                                        | none           |

### 3. Generate

The user clicks **Generate**. The app:

1. Builds a generation plan (which samples are positive/negative and, for negatives, which alternative diagnosis to use).
2. Generates the samples, showing progress as they come in.
3. Shows the results in a table with a detail view for each record.
4. Lets the user export the dataset as **JSONL**, **JSON**, or **CSV**.

---

## Sample Format

Each sample follows a common hospital admission/consultation note structure:

| Section                              | Content                                                                         |
|--------------------------------------|---------------------------------------------------------------------------------|
| **Patient Demographics**             | Synthetic ID, age, sex                                                          |
| **Chief Complaint**                  | Main reason for the visit, in the patient's words                               |
| **History of Present Illness (HPI)** | Onset, duration, character, severity, aggravating/relieving factors             |
| **Past Medical History**             | Chronic conditions, prior surgeries, hospitalizations                           |
| **Medications & Allergies**          | Current medications, known allergies                                            |
| **Family & Social History**          | Relevant family conditions, smoking, alcohol, occupation                        |
| **Review of Systems**                | Positive and pertinent negative symptoms                                        |
| **Physical Examination**             | Vital signs and examination findings                                            |
| **Investigations / Test Results**    | Labs (with values and reference ranges), imaging, ECG, other relevant tests     |
| **Assessment / Diagnosis**           | Final diagnosis and differential diagnoses                                      |
| **Plan**                             | Treatment and follow-up (optional)                                              |

### Example output (JSONL record)

```json
{
  "id": "sample-0001",
  "department": "Cardiology",
  "target_condition": "Acute myocardial infarction",
  "label": "positive",
  "negative_type": null,
  "intended_diagnosis": "Acute myocardial infarction",
  "record": {
    "demographics": { "age": 62, "sex": "male" },
    "chief_complaint": "Crushing chest pain for the past 2 hours.",
    "history_of_present_illness": "...",
    "past_medical_history": ["Hypertension", "Type 2 diabetes mellitus"],
    "medications": ["Metformin 1000 mg BID", "Lisinopril 10 mg daily"],
    "allergies": ["No known drug allergies"],
    "family_history": "...",
    "social_history": "...",
    "review_of_systems": "...",
    "physical_exam": {
      "vitals": { "blood_pressure": "150/95 mmHg", "heart_rate": 104, "respiratory_rate": 20, "temperature_c": 36.9, "spo2": 95 },
      "findings": "..."
    },
    "test_results": [
      { "name": "Troponin I (high-sensitivity)", "category": "lab", "result": "2.4", "unit": "ng/mL", "reference_range": "<0.04", "flag": "high" },
      { "name": "12-lead ECG", "category": "ecg", "result": "ST elevation in leads II, III, aVF", "unit": "", "reference_range": "", "flag": "abnormal" }
    ],
    "diagnosis": {
      "final": "Acute inferior ST-elevation myocardial infarction",
      "differentials": ["Unstable angina", "Aortic dissection"]
    },
    "plan": "..."
  }
}
```

A negative sample for the same target has the same structure, with `"label": "negative"`, `"negative_type": "hard"` (or `"easy"`), and a different final diagnosis (e.g. *Acute pericarditis*, *GERD*).

### Using the data for evaluation

Show the model under test the record without its `diagnosis` and `plan` sections, then compare its answer to `label` / `diagnosis.final`. The export has three options:

| Export        | Contents                                                              |
|---------------|-----------------------------------------------------------------------|
| Full records  | Complete samples, including diagnosis and plan                        |
| Inputs only   | Records with `diagnosis` and `plan` removed — what the model sees    |
| Answers only  | `id`, `label`, `negative_type`, final diagnosis, differentials        |

The prompts tell the model not to name the final diagnosis outside the diagnosis section, so the "inputs only" records don't give the answer away.

---

## Architecture

```
┌─────────────────────┐      ┌───────────────────────────┐      ┌──────────────┐
│  Frontend (React)   │ ───▶ │  Backend API (FastAPI)    │ ───▶ │  Claude API  │
│  - Department input │      │  - condition lookup       │      │  (structured │
│  - Condition picker │ ◀─── │  - generation jobs        │ ◀─── │   outputs)   │
│  - Counts & options │ SSE  │  - schema validation      │      └──────────────┘
│  - Results & export │      │  - export                 │
└─────────────────────┘      └───────────────────────────┘
```

How a job runs:

1. **Plan negatives.** For each selected condition, the model lists *hard negatives* (diagnoses on its differential) and *easy negatives* (unrelated diagnoses common in the department).
2. **Build sample specs.** Every sample is assigned a label, an intended final diagnosis, and a patient profile (age, sex, severity, typical/atypical presentation) before any record is written. This fixes the dataset's composition and keeps samples varied. With a seed, this step is reproducible.
3. **Generate records.** Records are generated in parallel (`MAX_CONCURRENCY`), one call per sample, using structured outputs so each response matches the `PatientRecord` schema. Failed samples are retried up to `MAX_ATTEMPTS_PER_SAMPLE` times. Errors that would affect every call (bad API key, invalid request) stop the job.
4. **Stream results.** Each finished sample is sent to the browser over Server-Sent Events.

Generation uses `claude-opus-5` by default with server-side refusal fallback (`fallbacks: "default"`) enabled, so a declined request is retried on Anthropic's recommended fallback model.

Jobs are kept in memory (the 50 most recent). Restarting the backend clears them.

### API

| Method   | Endpoint                                   | Description                                           |
|----------|--------------------------------------------|-------------------------------------------------------|
| `GET`    | `/api/health`                              | Mode, model, and sample limit                         |
| `GET`    | `/api/departments`                         | Seeded departments                                    |
| `GET`    | `/api/departments/{department}/conditions` | Common diseases/symptoms (seed list, else LLM)        |
| `POST`   | `/api/generate`                            | Start a generation job; returns its status and `job_id` |
| `GET`    | `/api/jobs/{job_id}`                       | Job status                                            |
| `DELETE` | `/api/jobs/{job_id}`                       | Cancel a running job                                  |
| `GET`    | `/api/jobs/{job_id}/stream`                | SSE: `status`, `sample`, `sample_error`, `done` events |
| `GET`    | `/api/jobs/{job_id}/samples`               | All samples generated so far                          |
| `GET`    | `/api/jobs/{job_id}/export`                | Download: `format=jsonl\|json\|csv`, `part=full\|inputs\|answers` |

`POST /api/generate` request body:

```json
{
  "department": "Cardiology",
  "conditions": ["Acute myocardial infarction", "Heart failure"],
  "positive_count": 20,
  "negative_count": 20,
  "options": {
    "negative_strategy": "mixed",
    "severity": "mixed",
    "age_min": 18,
    "age_max": 85,
    "sex": "mixed",
    "language": "English",
    "seed": 42
  }
}
```

When several conditions are selected, the counts apply **per condition**. With `mixed`, about two thirds of negatives are hard negatives.

---

## Getting Started

### Prerequisites

- Node.js 20+
- Python 3.11+
- An Anthropic API key (not needed in mock mode)

### Run

```bash
# Backend (terminal 1)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your-key
uvicorn app.main:app --reload --port 8000

# Frontend (terminal 2)
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173. The Vite dev server forwards `/api` to the backend on port 8000.

To try the app without an API key, start the backend with `GENERATION_MODE=mock`. It returns placeholder records instantly.

### Tests

```bash
cd backend
.venv/bin/python -m pytest
```

The tests use the mock backend and never call the Claude API.

### Configuration

| Variable                  | Description                                          | Default          |
|---------------------------|------------------------------------------------------|------------------|
| `ANTHROPIC_API_KEY`       | API key for generation                               | —                |
| `GENERATION_MODE`         | `anthropic`, or `mock` for placeholder records       | `anthropic`      |
| `GENERATION_MODEL`        | Model used to generate records                       | `claude-opus-5`  |
| `GENERATION_EFFORT`       | Effort level: `low`, `medium`, `high`, `xhigh`, `max` | `medium`         |
| `MAX_CONCURRENCY`         | Parallel generation requests                         | `5`              |
| `MAX_SAMPLES_PER_JOB`     | Upper limit on samples per job                       | `500`            |
| `MAX_ATTEMPTS_PER_SAMPLE` | Attempts per sample before it is reported as failed  | `3`              |

---

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app
│   │   ├── config.py          # Environment settings
│   │   ├── schemas.py         # Patient record + API models
│   │   ├── jobs.py            # In-memory jobs, retries, event stream
│   │   ├── export.py          # JSONL / JSON / CSV export
│   │   ├── routes/api.py      # API endpoints
│   │   ├── generation/
│   │   │   ├── llm.py         # Claude client and mock client
│   │   │   ├── planner.py     # Sample specs (labels, diagnoses, profiles)
│   │   │   └── prompts.py     # Prompt text
│   │   └── data/departments.py  # Seed department → condition lists
│   └── tests/
├── frontend/
│   └── src/
│       ├── App.tsx
│       ├── api.ts
│       ├── types.ts
│       └── components/        # DepartmentStep, ConditionStep, ResultsView, RecordDetail
└── README.md
```

---

## Roadmap

- [x] Department → conditions lookup (seed list + LLM suggestions)
- [x] Condition multi-select with positive/negative counts
- [x] Streaming generation with progress
- [x] Schema validation and retries
- [x] Export (JSONL / JSON / CSV, with diagnosis redaction)
- [x] Hard-negative strategy using differential diagnoses
- [ ] Persist jobs (currently in memory only)
- [ ] Duplicate and near-duplicate detection across samples
- [ ] Optional clinician review / approval of samples
- [ ] Saved generation presets and dataset versioning

---

## Limitations & Disclaimer

- Records are generated by an LLM. They may contain clinical inaccuracies or implausible combinations. Have a clinician review the data before using it for high-stakes evaluation.
- Generated data reflects the biases of the generating model. Check demographic and presentation diversity.
- This tool is for **research and evaluation only**. It is not a medical device and does not provide medical advice.
