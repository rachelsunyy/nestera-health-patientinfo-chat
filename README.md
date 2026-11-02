# Hospital-At-Home Patient Check-In Agent

A conversational check-in chatbot for Hospital-At-Home programs. Patients complete a daily check-in by answering personalized questions through a chatbot interface. Their responses are automatically summarized into a structured clinical note for the care team.

## How It Works

**Patient side**
The patient opens `/patient`, picks their name, and the chatbot immediately starts asking 8–10 questions personalized to their conditions, medications, and monitoring parameters. No AI model is called — questions are built directly from the patient's medical record. The patient types answers in plain language and presses Enter after each one.

**Doctor / Nurse side**
As soon as the patient finishes, a clinical note is automatically generated from their exact responses. The doctor opens `/clinician`, clicks **Open** on the patient's row in the roster, and sees a structured note with all Q&A pairs, any flagged concerns (missed medications, worsening symptoms, etc.), and a recommended action: Routine review / Schedule visit / Escalate.

## Features

- Personalized questions built from each patient's conditions, medications, and monitoring parameters
- Doctor-specified questions added per patient per day (shown first in the check-in)
- Clinical summary derived entirely from patient responses — no hallucinations, no fabrication
- Automatic flagging of concerning answers: keyword matching with negation ("no falls" is not flagged) plus numeric checks on reported vitals (SpO2, temperature, blood pressure, blood glucose, breathing rate)
- Trend tracking across check-ins: each check-in is compared with earlier ones and labelled Improving / Stable / Worsening, with reasons
- Clinician dashboard with a today's-check-ins overview, status chips and recommended action per patient
- Register new patients by uploading a JSON file
- All data stored persistently in Google Cloud Storage

## Running the Demo

### Prerequisites
- Access to the `nestera-health` Google Cloud project
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installed

### Deploy to Cloud Run

[DEPLOY.md](DEPLOY.md) has the full steps: checking the project, one-time setup, build, deploy flags, seeding the bucket, verifying, rollback and teardown. The short version, after that setup:

```bash
# Build the image (tagged latest and with the build id)
gcloud builds submit --project=nestera-health --config cloudbuild.yaml .

# Deploy, private by default (see DEPLOY.md for every flag)
gcloud run deploy hah-agent-ui \
  --image us-central1-docker.pkg.dev/nestera-health/hah-agent/app:latest \
  --region us-central1 \
  --project=nestera-health \
  --no-allow-unauthenticated \
  --service-account=hah-agent-run@nestera-health.iam.gserviceaccount.com \
  --min-instances=1 --max-instances=1 --session-affinity --timeout=3600 \
  --memory=1Gi --cpu=1 \
  --set-env-vars GCS_BUCKET=nestera-health-hah-agent

# Seed the bucket with the demo patients (repeat on demo day)
TZ=UTC python scripts/seed_demo.py --gcs-bucket nestera-health-hah-agent --reset
```

The image installs the pinned versions in `requirements.lock`, not the ranges in `requirements.txt`. After editing `requirements.txt`, regenerate the lock and re-run the tests against it, as described in DEPLOY.md under "Refreshing the lock".

### Access the app

The service is private. The clinician page has no login, so only people granted `roles/run.invoker` can reach it, and they do so through the proxy.

```bash
gcloud run services proxy hah-agent-ui \
  --region us-central1 \
  --project=nestera-health \
  --port=8082
```

Then open http://localhost:8082/patient and http://localhost:8082/clinician. In Cloud Shell, use Web Preview on port 8082 and add `/patient` or `/clinician` to the preview URL. Opening the `run.app` URL directly in a browser returns 403. DEPLOY.md explains how to grant access and when a public URL is acceptable.

### Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Then open http://localhost:8501. The landing page offers two experiences, each at its own URL:

- http://localhost:8501/patient is the patient check-in. It shows only what a patient sees. Add `?patient=<id>` to skip the name picker, as in `/patient?patient=patient_001`.
- http://localhost:8501/clinician is the clinician dashboard: today's roster, then each patient's summary, trends and added questions. `?patient=<id>` opens that patient directly.

No environment variables are required for local development: the app stores data as JSON files in `patient_data/` (git-ignored) and loads the sample patients in `sample_data/` automatically. To use Google Cloud Storage instead, set `GCS_BUCKET`.

Each patient's folder (or `patients/<patient_id>/` in the bucket) holds `record.json`, `doctor_questions/<date>.json`, and one file per check-in in `checkins/` and `summaries/`, named by check-in id (date and time, such as `2026-11-01T17-30-05.123456.json`). Files from older versions named by date alone (`2026-10-29.json`) still load, with the date as their id.

**Sponsor demo.** `DEMO.md` is a 10 to 12 minute walkthrough script with the exact answers to type, safety talking points and known limits.
`python scripts/seed_demo.py --reset` loads its synthetic `demo_` patients through the real check-in and summary code; it never touches other patients.

Other entry points (all use the same agents and database layer):

```bash
python cli.py list-patients                      # terminal version of the check-in
python cli.py checkin --patient patient_001
python cli.py summary --patient patient_001        # today's latest check-in; --checkin <id> for another
uvicorn app:app --reload --port 8080             # REST API (see docstring in app.py)
```

### Run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Patient Record Format

Register a new patient by uploading a JSON file under **Register a new patient**, below the roster on `/clinician`. A file whose `patient_id` is already registered replaces that record only after you click **Replace the existing record**. Check-ins and notes are kept. A file that does not match the format below is rejected with one line per problem, such as `Missing required field: date_of_birth`.

```json
{
  "patient_id": "patient_001",
  "name": "Margaret Chen",
  "date_of_birth": "1948-03-15",
  "care_team_contact": "(312) 555-0199 — UChicago Medicine HAH Program",
  "admission_date": "2026-09-28",
  "primary_diagnosis": "Community-acquired pneumonia",
  "conditions": [
    { "name": "Community-acquired pneumonia", "icd_code": "J18.9" },
    { "name": "Type 2 diabetes mellitus", "icd_code": "E11.9" },
    { "name": "Hypertension", "icd_code": "I10" }
  ],
  "medications": [
    { "name": "Amoxicillin-clavulanate", "dose": "875/125mg", "frequency": "twice daily" },
    { "name": "Metformin", "dose": "500mg", "frequency": "twice daily with meals" }
  ],
  "monitoring_parameters": ["oxygen saturation (SpO2)", "temperature", "blood pressure"],
  "known_allergies": [],
  "notes": "Optional free-text notes for the care team."
}
```

**Required fields:** `patient_id`, `name`, `date_of_birth`, `care_team_contact`, `admission_date`, `primary_diagnosis`

The chatbot generates more specific questions when `conditions`, `medications`, and `monitoring_parameters` are provided. Recognized conditions include: pneumonia, diabetes, hypertension, heart failure, COPD, stroke, and kidney/renal disease.

## How concerns are flagged

`agents/summary_agent.py` and `agents/vitals.py` scan each answer and set the recommended action to the most severe finding:

- **Keywords** (e.g. "chest pain", "fell", "didn't take", "short of breath"). Matching is by whole word, and a phrase is ignored when negated nearby ("no falls", "not short of breath").
- **Vital-sign numbers**, read from the answers to the SpO2, temperature, blood pressure, blood sugar and breathing-rate questions. Example defaults: SpO2 below 90% escalates and below 92% schedules a visit; BP at or above 180/120 escalates and at or above 160/100 schedules a visit.

> The thresholds in `agents/vitals.py` are general-purpose **demo values**. They must be reviewed by the clinical team before any real use and ideally made patient-specific (for example, a COPD patient's normal SpO2 is lower).

## Trend tracking across check-ins

`agents/trends.py` (no AI, no extra data collected) compares the latest check-in with up to four earlier ones (two check-ins on the same day count separately) and labels the patient **Worsening**, **Improving**, **Stable**, or **Not enough data** (fewer than two check-ins). Each label comes with reasons the clinician can verify against the raw answers.

- **Vital readings** (SpO2, temperature, systolic BP, blood sugar, breathing rate) are compared with the earlier readings: moving further outside a normal band, or a slow drift the wrong way inside it (for example SpO2 98 → 97 → 95), counts as worsening; moving back toward normal counts as improving.
- **Symptom reports**: answers saying "worse" (negation-aware: "not worse" doesn't count; "not better" does) on two of the last three check-ins, or more worse reports than last time.
- **Recommended action** rising above anything seen earlier in the window.

A worsening trend adds a flagged item and raises a *Routine review* check-in to *Schedule visit*; it never lowers an action. The result appears in the clinical note, on the dashboard's **Trends** tab (with charts), and at `GET /trend/{patient_id}`.

> The normal bands and margins at the top of `agents/trends.py` are prototype values and need clinical review, like the thresholds in `agents/vitals.py`. Only readings the patient actually reports are used, so a skipped measurement produces no trend for that vital.

## External datasets (Synthea and NoteChat)

Both are synthetic, so no PHI is involved. Raw downloads go in `external_data/`, which is git-ignored. See each tool's docstring for the full details.

**Synthea patients** (`data/synthea_import.py`, Apache-2.0). Maps Synthea's SNOMED conditions onto the ones the question builder knows, builds patient records (active medications, allergies, implied monitoring parameters) and can register them in the app.

```bash
curl -L -o synthea.zip https://synthetichealth.github.io/synthea-sample-data/downloads/latest/synthea_sample_data_csv_latest.zip
unzip synthea.zip -d external_data/synthea
python -m data.synthea_import --src external_data/synthea                      # report: conditions and question coverage
python -m data.synthea_import --src external_data/synthea --register           # add the patients to the app
python -m data.synthea_import --src external_data/synthea --vitals-out evals/synthea_vitals.jsonl   # labeled vital-sign check-ins
```

The ~100-patient sample is small for our purpose: 29 patients have a usable condition, none of them alive with heart failure or stroke, and asthma, sepsis and heart attack have no question templates in the app (reported as a coverage gap). For a bigger, more relevant cohort, run Synthea itself (needs Java) with module filters and point `--src` at its `output/csv` folder.

**NoteChat patient speech** (`data/notechat_import.py`, Wang et al., 2024). 10,000 synthetic doctor-patient dialogues with **no urgency labels**, so they can't be scored automatically. The tool audits how often the rules fire on realistic patient speech (`--audit`), writes a blind sample for the team or a clinician to label (`--sheet`), and turns the labeled rows into eval cases for `evals/run_eval.py` (`--labels`). The dialogues are visit conversations about past events, not daily home check-ins, and the dataset card states no licence (it derives from case reports under a non-commercial licence), so keep it out of the repository and ask Nestera before any product use.

## Optional AI assist (Anthropic Claude)

Off by default. The deterministic rules above always run first and set a floor: **AI can raise a recommended action or add notes, but never lower it**, and its output is shown to clinicians only, never to patients. If AI is off, misconfigured, errors, or refuses, the check-in still gets its normal rules-based summary.

Models are stratified by how much reasoning each job needs (override with env vars, see `.env.example`):

| Tier | Job | Runs | Default model | Effort |
|---|---|---|---|---|
| Triage | Rate each free-text answer none / minor / moderate / urgent | every check-in | `claude-haiku-5-5` | low |
| Summary | Short, grounded overview for the clinician | every check-in | `claude-sonnet-5-5` | medium |
| Review | Second look and rationale | only when the action is *Escalate* or AI raised it | `claude-opus-5-5` | high |

Enable it by setting `AI_ASSIST_ENABLED=true`, an explicit `AI_DATA_MODE` (`synthetic` for demo patients; `phi` for real data, which also requires `AI_BAA_CONFIRMED=true`), and credentials: `ANTHROPIC_API_KEY`, or `AI_PROVIDER=vertex` with `GCP_PROJECT` and `GCP_REGION` to use Claude through Google Cloud. With no `AI_DATA_MODE` set, AI stays off. Code is in `agents/llm_assist.py`; tests use a fake client, so no key is needed to run them.

Data handling built into every model call:
- Only condition names and the question/answer text are sent, never the patient's name, date of birth, contact details or ID.
- Text is scrubbed first (`agents/deid.py`): phone numbers, emails, dates, addresses, ID numbers, titles like "Dr. X", and the patient's own name are replaced with tags. Clinical values (BP, SpO2, glucose, temperature) are kept. This is a best-effort safety net, not a guarantee: names the app doesn't know about can slip through, so use a managed de-identification service (e.g. Google Sensitive Data Protection) before real patient data.
- Every call is recorded in `patient_data/ai_audit.jsonl` (`agents/ai_audit.py`): time, tier, model, provider, data mode, latency, token counts and outcome (ok, refused, error), plus a one-way hash of the patient. Request and response content is never logged.

### Measuring model quality

```bash
python evals/run_eval.py                    # rules only: free, no key needed
python evals/run_eval.py --ai               # also run the AI tiers (spends API credit)
python evals/run_eval.py --ai --triage-model claude-sonnet-5-5   # compare another triage model
```

`evals/dataset.jsonl` holds 37 synthetic check-ins with expected actions, including informal phrasings the keyword rules miss and prompt-injection attempts. The report counts **under-triage** (recommending less than needed) separately from over-triage, because missing a sick patient is the costlier error. **The labels were written without clinician input and the cases were designed to include the rules' known gaps, so the numbers are a development aid, not clinical evidence.** Have clinicians review and extend the dataset before relying on it.

**Larger set.** `evals/dataset_v2.jsonl` holds 394 synthetic check-ins: the original 37 (unchanged) plus 357 more across 17 categories, each with a `category`, a `source` (`original`, `template` or `authored`) and a `split` (`dev` or `test`, fixed by a hash of the id).

```bash
python evals/run_eval.py --dataset evals/dataset_v2.jsonl                 # whole set, with a per-category table
python evals/run_eval.py --dataset evals/dataset_v2.jsonl --split test    # held-out cases only
python evals/build_dataset.py                                             # regenerate the file (deterministic)
```

- **What is generated and what is written by hand.** Routine check-ins and the numeric vital-sign sweeps (SpO2, temperature, blood pressure, blood sugar including mmol/L, breathing rate, values on both sides of every threshold) come from templates. The informal, typo and shorthand phrasings, benign sentences that contain trigger words ("I fell asleep", "zero shortness of breath"), contradictory and rambling answers, prompt-injection attempts, and the multi-finding check-ins use hand-written phrasings in `evals/case_bank.py`.
- **How labels were chosen.** Each expected action follows the clinical meaning of the case, using the policy at the top of `evals/case_bank.py`, never the output of the rules or a model. The numeric labels use a separate copy of the documented thresholds, so a mismatch with `agents/vitals.py` would show up as a failure. A test checks the committed file is exactly what the generator produces.
- **Reading the numbers.** Read the per-category table, not just the overall exact match, because the overall figure depends on how many easy numeric cases the set contains. Tune prompts or rules on `dev` only and report `test`.
- **Limits.** All labels are still synthetic and not clinician-reviewed, and the phrasings come from the authors, not from real patients. More cases make the estimate steadier, but they do not make it clinical evidence.



### Conversational check-in (patient-facing, optional)

Set `AI_CONVERSATION_ENABLED=true` (on top of the AI settings above) and the patient chat becomes an adaptive conversation (`agents/conversation_agent.py`). Each patient still has a **coverage checklist**, the topics a clinician needs answered, built from their record (conditions, readings, medications, safety, plus any doctor-added questions). The checklist is fixed. How the conversation gets through it is not: one model call per reply (`claude-sonnet-5-5` at low effort by default) lets it

- **choose the order**: e.g. ask for the oxygen reading right after the patient mentions trouble breathing
- **word each question to flow from what the patient just said**
- **ask short follow-up questions** when an answer reveals something worth a closer look (a symptom getting worse, something new, an incomplete answer), capped at 2 per topic and 6 per check-in
- **skip a topic the patient has already answered**, but only when it quotes their exact words and the code verifies the quote (a reading must include the number)
- ask one clarifying question when an answer is too vague, redirect medical questions to the care team, and record a concerning symptom mentioned out of order

What the model can never change, because it is plain code:

- **A check-in only ends when every checklist topic is covered**, or when an emergency ends it.
- **Recorded answers are the patient's own words**, never a model paraphrase. Each question/answer is tagged with its topic, so numeric checks (SpO2, BP, glucose...) still apply when a question was reworded. Doctor-written questions are always asked exactly as written.
- **Emergency and medical-advice responses are fixed text.** The same rules used for triage run *before* the model on every reply; if they (or the model) flag an emergency, the patient sees a fixed message to contact the care team and call 911 if in danger, and the check-in ends and is saved with an emergency marker that always escalates.
- **The patient is told up front** that they are talking to an automated assistant, not a person or a medical professional.

Anything the model writes for the patient is checked first: one question only, on the topic, short, no advice or reassurance wording, no numbers the patient didn't say. If a check fails, or the model errors or refuses, that turn uses the standard question and a scripted acknowledgment. Replies are untrusted text: instructions inside a reply cannot skip topics or end the check-in. The model sees the scrubbed conversation so far (question/answer pairs), the current reply, and the remaining topics, not the patient's name or other identifiers.

Measure it with `python evals/run_conversation_eval.py` (synthetic cases): **emergencies missed** first, then false alarms, whether it asks follow-ups when warranted and stays quiet on routine answers, and how often its wording is rejected by the safety checks. Treat this as a prototype until clinicians have reviewed the cases, the emergency rules, and what follow-up questions are appropriate.

### AI assist and patient data

There is no "HIPAA-approved model". What matters is the **agreement and service**, not the model:

- Anthropic offers a Business Associate Agreement (BAA) for its first-party API, but it must be signed by the organization that will operate the system (for this project, the sponsor, not individual students) and the API organization must be set up as HIPAA-ready. Only the Messages API features Anthropic lists as eligible are covered (for example prompt caching and structured outputs); the Batch API, Files API, Code Execution and Web Fetch are not.
- Anthropic's BAA does not extend to Claude accessed through a third-party cloud (Amazon Bedrock, Google Vertex AI). There, the cloud provider's own BAA and written confirmation that the specific Claude model and region are in scope are required.
- Zero data retention and HIPAA configuration can't be combined on one API organization, and some newer models require 30-day retention.
- **Until all of this is confirmed in writing, use only synthetic data** (the sample patients in `sample_data/` are synthetic) and keep `AI_ASSIST_ENABLED` off.
- A BAA with the model provider is not enough on its own: the app also needs authentication, audit logging and encryption appropriate for PHI. Have the sponsor's compliance/legal team review before any real use.

## Project Structure

```
.
├── streamlit_app.py          # Web interface entry point: routes /, /patient and /clinician
├── views/
│   ├── landing.py            # / : choose the patient or the clinician experience
│   ├── patient.py            # /patient : name picker, then the check-in chat
│   ├── clinician.py          # /clinician : roster, then one patient's summary, trends and questions
│   └── shared.py             # Database connection and patient names shared by the pages
├── ui_theme.py               # Branding, CSS and small HTML components for the UI
├── .streamlit/config.toml    # Streamlit theme
├── agents/
│   ├── patient_agent.py      # Builds personalized questions, runs the check-in
│   ├── llm_assist.py         # Optional Claude triage / overview / review / conversation tiers
│   ├── conversation_agent.py # Optional conversational check-in (fixed questions, model-assisted dialogue)
│   ├── markers.py            # Fixed labels for emergency / volunteered entries
│   ├── deid.py               # Scrubs identifiers before text goes to a model
│   ├── ai_audit.py           # Audit log of model calls (no content)
│   ├── summary_agent.py      # Flags concerns and generates the clinical note
│   └── vitals.py             # Numeric vital-sign thresholds
├── database/
│   └── patient_db.py         # Mock (local JSON) and GCS backends
├── data/
│   ├── models.py             # Pydantic models (PatientRecord, DailyCheckIn, etc.)
│   ├── synthea_import.py     # Synthea patient importer
│   └── notechat_import.py    # NoteChat dialogue audit and labeling tool
├── sample_data/              # Demo patient JSON files
├── scripts/
│   └── seed_demo.py          # Seeds synthetic demo_ patients for DEMO.md
├── tests/                    # pytest suite
├── evals/                    # Labeled synthetic check-ins + triage evaluation runner
├── DEMO.md                   # Sponsor demo script
├── app.py                    # FastAPI REST API (alternative to the Streamlit UI)
├── cli.py                    # Terminal check-in (uses the same database layer as the app)
├── guardrails/safety.py      # Advice-wording check used by the conversational check-in
├── config.py                 # Paths and settings
├── Dockerfile                # Container definition for Cloud Run
├── cloudbuild.yaml           # Google Cloud Build configuration
├── requirements.txt          # Runtime dependencies (edit this one)
├── requirements.lock         # Exact versions the image installs, generated from requirements.txt
└── requirements-dev.txt      # Adds pytest
```

## Infrastructure

| Component | Service |
|---|---|
| Web app | Google Cloud Run |
| Container image | Google Artifact Registry |
| Patient data | Google Cloud Storage |
| Build pipeline | Google Cloud Build |

## Important Notes

- **By default no AI model is used.** The patient check-in is always deterministic. Clinician summaries can optionally be enhanced with Claude (see above).
- **No real patient data should be committed to this repository.** The `patient_data/` directory and `.env` files are excluded via `.gitignore`.
- The app has no authentication by default. Enable Google IAM or add a password layer before using with real patient data.
- A patient can check in more than once a day. Every check-in and its summary is kept; the dashboard shows the latest of today's check-ins and how many there were.
