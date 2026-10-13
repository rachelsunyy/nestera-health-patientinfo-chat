# Hospital-At-Home Patient Check-In Agent

A conversational check-in chatbot for Hospital-At-Home programs. Patients complete a daily check-in by answering personalized questions through a chatbot interface. Their responses are automatically summarized into a structured clinical note for the care team.

## How It Works

**Patient side**
The patient opens the app, selects their name, and the chatbot immediately starts asking 8–10 questions personalized to their conditions, medications, and monitoring parameters. No AI model is called — questions are built directly from the patient's medical record. The patient types answers in plain language and presses Enter after each one.

**Doctor / Nurse side**
As soon as the patient finishes, a clinical note is automatically generated from their exact responses. The doctor opens the dashboard, selects the patient, and sees a structured note with all Q&A pairs, any flagged concerns (missed medications, worsening symptoms, etc.), and a recommended action: Routine review / Schedule visit / Escalate.

## Features

- Personalized questions built from each patient's conditions, medications, and monitoring parameters
- Doctor-specified questions added per patient per day (shown first in the check-in)
- Clinical summary derived entirely from patient responses — no hallucinations, no fabrication
- Automatic flagging of concerning answers: keyword matching with negation ("no falls" is not flagged) plus numeric checks on reported vitals (SpO2, temperature, blood pressure, blood glucose, breathing rate)
- Clinician dashboard with a today's-check-ins overview, status chips and recommended action per patient
- Register new patients by uploading a JSON file
- All data stored persistently in Google Cloud Storage

## Running the Demo

### Prerequisites
- Access to the `nestera-health` Google Cloud project
- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installed

### Deploy to Cloud Run

```bash
# Build the Docker image
gcloud builds submit --project=nestera-health

# Deploy
gcloud run deploy hah-agent-ui \
  --image us-central1-docker.pkg.dev/nestera-health/hah-agent/app:latest \
  --region us-central1 \
  --project=nestera-health \
  --set-env-vars GCS_BUCKET=nestera-health-hah-agent
```

### Access the app

```bash
gcloud run services proxy hah-agent-ui \
  --region us-central1 \
  --project=nestera-health \
  --port=8082
```

Then open Web Preview on port 8082 in Cloud Shell, or visit the service URL directly if public access has been enabled.

### Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Then open http://localhost:8501. No environment variables are required for local development: the app stores data as JSON files in `patient_data/` (git-ignored) and loads the sample patients in `sample_data/` automatically. To use Google Cloud Storage instead, set `GCS_BUCKET`.

Other entry points (all use the same agents and database layer):

```bash
python cli.py list-patients                      # terminal version of the check-in
python cli.py checkin --patient patient_001
python cli.py summary --patient patient_001
uvicorn app:app --reload --port 8080             # REST API (see docstring in app.py)
```

### Run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Patient Record Format

Register a new patient by uploading a JSON file in the Doctor / Nurse → Register Patient tab.

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

## Project Structure

```
.
├── streamlit_app.py          # Main web interface (patient + clinician views)
├── ui_theme.py               # Branding, CSS and small HTML components for the UI
├── .streamlit/config.toml    # Streamlit theme
├── agents/
│   ├── patient_agent.py      # Builds personalized questions, runs the check-in
│   ├── summary_agent.py      # Flags concerns and generates the clinical note
│   └── vitals.py             # Numeric vital-sign thresholds
├── database/
│   └── patient_db.py         # Mock (local JSON), GCS and Firestore backends
├── data/
│   ├── models.py             # Pydantic models (PatientRecord, DailyCheckIn, etc.)
│   └── store.py              # Legacy JSON store, used only by main.py
├── sample_data/              # Demo patient JSON files
├── tests/                    # pytest suite
├── app.py                    # FastAPI REST API (alternative to the Streamlit UI)
├── cli.py                    # Terminal check-in (uses the same database layer as the app)
├── main.py                   # Older CLI built on data/store.py
├── models/, guardrails/      # LLM clients and advice filter from an earlier design (not used by the current flow)
├── config.py                 # Paths and settings
├── Dockerfile                # Container definition for Cloud Run
├── cloudbuild.yaml           # Google Cloud Build configuration
├── requirements.txt          # Runtime dependencies
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

- **No AI model is used** for the patient check-in or summary generation. Everything runs deterministically from the patient's record and their typed responses. `models/` (Gemini, MedGemma) and `guardrails/` are left over from an earlier LLM-based design and are not called by the current flow.
- **No real patient data should be committed to this repository.** The `patient_data/` directory and `.env` files are excluded via `.gitignore`.
- The app has no authentication by default. Enable Google IAM or add a password layer before using with real patient data.
- Only one check-in per patient per day is stored; completing a second one replaces the first.
