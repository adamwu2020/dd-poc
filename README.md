# Synthetic Patient Data Generator for LLM Evaluation

A web app that generates realistic, **fully synthetic** patient records for evaluating LLMs on clinical reasoning tasks (e.g. "Does this patient have condition X?").

For a chosen hospital department and one or more target conditions, the app produces a labeled dataset of:

- **Positive samples**: patients whose record supports the target diagnosis.
- **Negative samples**: patients with overlapping or similar presentations whose final diagnosis is something else (hard negatives), or who have no relevant pathology.

Each sample is structured like a standard hospital clinical note, so it can be fed directly into an LLM evaluation pipeline.

> ⚠️ **All generated data is synthetic.** It contains no real patient information (PHI) and must not be used for clinical decision-making.

---

## User Journey

### 0. Sign in

Users register with an email and password. Every new account gets **1 positive and 1 negative sample free**. After that, each sample costs **$0.50**, paid by card through Stripe Checkout before generation starts.

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

### 3. Review and pay

The review page shows what will be generated and what it costs: the number of samples × $0.50, minus free samples and account credits. If anything is due, the user pays on a Stripe page. Otherwise generation starts right away.

Users are charged only for delivered samples. Samples that fail, or that weren't generated because a job was cancelled or interrupted, become **credits** on the account and are used before any payment on the next job.

### 4. Generate

Once paid, the app:

1. Builds a generation plan (which samples are positive/negative and, for negatives, which alternative diagnosis to use).
2. Generates the samples, showing progress as they come in.
3. Shows the results in a table with a detail view for each record.
4. Lets the user export the dataset as **JSONL**, **JSON**, or **CSV**.

Past datasets are listed under **My datasets** and can be reopened and downloaded later.

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
│  - Sign in, pay     │      │  - accounts, orders       │ ───▶ Stripe Checkout
└─────────────────────┘      └─────────────┬─────────────┘
                                           ▼
                                   Postgres (Supabase)
```

How a job runs:

1. **Plan negatives.** For each selected condition, the model lists *hard negatives* (diagnoses on its differential) and *easy negatives* (unrelated diagnoses common in the department).
2. **Build sample specs.** Every sample is assigned a label, an intended final diagnosis, and a patient profile (age, sex, severity, typical/atypical presentation) before any record is written. This fixes the dataset's composition and keeps samples varied. With a seed, this step is reproducible.
3. **Generate records.** Records are generated in parallel (`MAX_CONCURRENCY`), one call per sample, using structured outputs so each response matches the `PatientRecord` schema. Failed samples are retried up to `MAX_ATTEMPTS_PER_SAMPLE` times. Errors that would affect every call (bad API key, invalid request) stop the job.
4. **Stream results.** Each finished sample is sent to the browser over Server-Sent Events.

Generation uses `claude-opus-5` by default with server-side refusal fallback (`fallbacks: "default"`) enabled, so a declined request is retried on Anthropic's recommended fallback model.

Accounts, orders, jobs, and samples are stored in the database (Postgres in production, SQLite locally). Jobs run inside the web process. If the process restarts mid-job, the job is marked failed at startup and its undelivered samples are credited back.

### Accounts and payments

- **Sign-in:** passwords are hashed with scrypt. Sessions are random tokens stored in the database (hashed) and sent as an `HttpOnly`, `SameSite=Lax` cookie that is `Secure` over HTTPS. Login is limited to 10 failed attempts per email per 15 minutes.
- **Orders:** creating an order reserves the user's free samples and credits. If money is due, the user is sent to Stripe Checkout. The job starts when Stripe confirms payment, through the `checkout.session.completed` webhook or a check when the user returns, whichever comes first. Starting a job is idempotent, so a payment never starts two jobs.
- **Expiry:** Checkout sessions expire after 35 minutes. Unpaid orders are then released and their reserved free samples and credits returned. This happens through the `checkout.session.expired` webhook, or the next time the user loads the app.

### API

| Method   | Endpoint                                   | Description                                           |
|----------|--------------------------------------------|-------------------------------------------------------|
| `GET`    | `/api/health`                              | Mode, model, sample limit (public)                    |
| `POST`   | `/api/auth/register`                       | Create an account and sign in                         |
| `POST`   | `/api/auth/login`                          | Sign in                                               |
| `POST`   | `/api/auth/logout`                         | Sign out                                              |
| `GET`    | `/api/auth/me`                             | Current account: free samples left, credits           |
| `GET`    | `/api/departments`                         | Seeded departments (public)                           |
| `GET`    | `/api/departments/{department}/conditions` | Common diseases/symptoms (seed list, else LLM)        |
| `POST`   | `/api/orders/quote`                        | Price breakdown for a request                         |
| `POST`   | `/api/orders`                              | Create an order; returns a `checkout_url`, or a `job_id` if nothing is due |
| `GET`    | `/api/orders/{order_id}`                   | Order status (settles it with Stripe if paid)         |
| `POST`   | `/api/orders/{order_id}/cancel`            | Cancel an unpaid order and release its reservation    |
| `POST`   | `/api/stripe/webhook`                      | Stripe webhook (signature-verified)                   |
| `GET`    | `/api/jobs`                                | The user's datasets                                   |
| `GET`    | `/api/jobs/{job_id}`                       | Job status                                            |
| `DELETE` | `/api/jobs/{job_id}`                       | Cancel a running job                                  |
| `GET`    | `/api/jobs/{job_id}/stream`                | SSE: `status`, `sample`, `sample_error`, `done` events |
| `GET`    | `/api/jobs/{job_id}/samples`               | All samples generated so far                          |
| `GET`    | `/api/jobs/{job_id}/export`                | Download: `format=jsonl\|json\|csv`, `part=full\|inputs\|answers` |

All endpoints except those marked public require a signed-in user, and users can only see their own orders and jobs.

`POST /api/orders` request body:

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

Locally, data is stored in `backend/dev.db` (SQLite).

To try the whole flow without any keys, start the backend with `GENERATION_MODE=mock PAYMENT_MODE=mock`. Records are placeholders, and payments use a fake checkout page instead of Stripe.

To test real payments locally, use Stripe **test mode** keys (`sk_test_…`) and the [Stripe CLI](https://docs.stripe.com/stripe-cli) to forward webhooks:

```bash
stripe listen --forward-to localhost:8000/api/stripe/webhook   # prints a whsec_… secret
STRIPE_SECRET_KEY=sk_test_... STRIPE_WEBHOOK_SECRET=whsec_... uvicorn app.main:app --reload --port 8000
```

Pay with the test card `4242 4242 4242 4242`, any future expiry date, and any CVC.

### Tests

```bash
cd backend
.venv/bin/python -m pytest
```

The tests use SQLite, the mock generator, and a fake Stripe gateway. They never call Claude or Stripe. To run them against Postgres, set `TEST_DATABASE_URL=postgresql://…`. This drops and recreates the tables, so use a throwaway database.

### Configuration

| Variable                  | Description                                          | Default          |
|---------------------------|------------------------------------------------------|------------------|
| `ANTHROPIC_API_KEY`       | API key for generation                               | —                |
| `GENERATION_MODE`         | `anthropic`, or `mock` for placeholder records       | `anthropic`      |
| `GENERATION_MODEL`        | Model used to generate records                       | `claude-opus-5`  |
| `GENERATION_EFFORT`       | Effort level: `low`, `medium`, `high`, `xhigh`, `max` | `medium`         |
| `MAX_CONCURRENCY`         | Parallel generation requests                         | `5`              |
| `MAX_SAMPLES_PER_JOB`     | Upper limit on samples per job (all conditions)      | `20`             |
| `MAX_ATTEMPTS_PER_SAMPLE` | Attempts per sample before it is reported as failed  | `3`              |
| `DATABASE_URL`            | Postgres connection string (e.g. from Supabase)      | SQLite `backend/dev.db` |
| `STRIPE_SECRET_KEY`       | Stripe secret key (`sk_live_…` or `sk_test_…`)       | —                |
| `STRIPE_WEBHOOK_SECRET`   | Signing secret of the Stripe webhook endpoint (`whsec_…`) | —           |
| `PAYMENT_MODE`            | `stripe`, or `mock` for a fake checkout page (development only) | `stripe` |
| `PRICE_PER_SAMPLE_CENTS`  | Price per sample in US cents                         | `50`             |
| `FREE_POSITIVE_SAMPLES`   | Free positive samples for each new account           | `1`              |
| `FREE_NEGATIVE_SAMPLES`   | Free negative samples for each new account           | `1`              |
| `PUBLIC_URL`              | Base URL for Stripe redirects                        | Render's `RENDER_EXTERNAL_URL`, else the request host |
| `SESSION_DAYS`            | How long a sign-in lasts                             | `30`             |
| `STATIC_DIR`              | Built frontend served at `/`                         | `frontend/dist`  |

---

## Deploy to Render

`render.yaml` defines one web service. It builds the frontend, installs the backend, and serves both from FastAPI. Three outside services are needed:

### 1. Database (Supabase)

1. Create a project at [supabase.com](https://supabase.com).
2. Click **Connect** and copy the **Session pooler** connection string (`postgresql://postgres.<ref>:[PASSWORD]@aws-0-<region>.pooler.supabase.com:5432/postgres`), and put in your database password. Use the session pooler, not the direct connection: Supabase's direct connection is IPv6-only, and Render can't reach IPv6 addresses.
3. This is `DATABASE_URL`. The app creates its tables on first start.

### 2. Payments (Stripe)

1. In the [Stripe dashboard](https://dashboard.stripe.com), copy the secret key from **Developers → API keys**. This is `STRIPE_SECRET_KEY`. Start with test mode (`sk_test_…`) and switch to live once everything works.
2. Under **Developers → Webhooks**, add an endpoint:
   - URL: `https://<your-app>.onrender.com/api/stripe/webhook`
   - Events: `checkout.session.completed`, `checkout.session.expired`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`
3. Copy the endpoint's signing secret (`whsec_…`). This is `STRIPE_WEBHOOK_SECRET`.

### 3. Render

Use **New → Blueprint** with this repository, or set these environment variables on an existing web service:

| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `DATABASE_URL` | Supabase session pooler URL |
| `STRIPE_SECRET_KEY` | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `PYTHON_VERSION` | `3.12.11` |
| `NODE_VERSION` | `22` |

Notes:
- The free plan sleeps after 15 minutes without traffic, so the first request afterwards takes about a minute. A job interrupted this way is marked failed and its undelivered samples are credited back.
- Pushes to `main` redeploy automatically.

---

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app
│   │   ├── config.py          # Environment settings
│   │   ├── schemas.py         # Patient record + API models
│   │   ├── db.py              # Database models (users, sessions, orders, jobs, samples)
│   │   ├── auth.py            # Registration, sign-in, sessions
│   │   ├── billing.py         # Pricing, orders, Stripe Checkout and webhook
│   │   ├── jobs.py            # Job runner, retries, event stream, credits
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
│       └── components/        # AuthPage, DepartmentStep, ConditionStep, OrderReview,
│                              # MockCheckout, ResultsView, RecordDetail, MyDatasets
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
- [x] Accounts, free samples, and paid generation (Stripe)
- [x] Persist jobs and results
- [ ] Email verification and password reset
- [ ] Run jobs in a background worker so they survive web restarts
- [ ] Duplicate and near-duplicate detection across samples
- [ ] Optional clinician review / approval of samples
- [ ] Saved generation presets and dataset versioning

---

## Limitations & Disclaimer

- Records are generated by an LLM. They may contain clinical inaccuracies or implausible combinations. Have a clinician review the data before using it for high-stakes evaluation.
- Generated data reflects the biases of the generating model. Check demographic and presentation diversity.
- This tool is for **research and evaluation only**. It is not a medical device and does not provide medical advice.
