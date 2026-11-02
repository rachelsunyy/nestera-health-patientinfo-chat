# Deploying the demo to Google Cloud Run

This guide puts the Hospital-At-Home demo on Cloud Run for a sponsor demo.
It serves one Streamlit app with two pages, `/patient` and `/clinician`.
Patient data lives in a Cloud Storage bucket.

None of the commands below were run while writing this guide.
Each block is marked `# NOT run here`.
Read each one before you run it.
Nothing here describes the current state of your project.
The steps tell you how to check it.

Run everything from [Google Cloud Shell](https://shell.cloud.google.com).
It already has `gcloud`, `git` and Python.
To use your laptop instead, install the Google Cloud CLI from https://cloud.google.com/sdk/docs/install and run `gcloud init`.

## Names used in this guide

These match `cloudbuild.yaml` and the README.
If you change one, change it in `cloudbuild.yaml` too.

```bash
# NOT run here
export PROJECT=nestera-health
export REGION=us-central1
export REPO=hah-agent                 # Artifact Registry repository
export SERVICE=hah-agent-ui           # Cloud Run service
export BUCKET=nestera-health-hah-agent
export RUNTIME_SA=hah-agent-run@$PROJECT.iam.gserviceaccount.com
gcloud config set project $PROJECT
```

Cloud Shell forgets these variables when the session ends.
Paste the block again in a new session.

## Before you start

Confirm you are in the right project and that billing is on.

```bash
# NOT run here
gcloud config get-value project
gcloud billing projects describe $PROJECT --format="value(billingEnabled)"   # expect True
```

Check who can already reach the project.
Project-level Owners and Cloud Run Invokers will be able to open the app.
Broad roles such as Editor usually can too.

```bash
# NOT run here
gcloud projects get-iam-policy $PROJECT \
  --flatten="bindings[].members" --format="table(bindings.role, bindings.members)"
```

Check that the Artifact Registry repository and the bucket exist.
An error saying "not found" means you create them in the next block.

```bash
# NOT run here
gcloud artifacts repositories describe $REPO --location=$REGION
gcloud storage buckets describe gs://$BUCKET
```

Create whichever one is missing.
The bucket blocks public access and uses one permission model for every object.

```bash
# NOT run here
gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION
gcloud storage buckets create gs://$BUCKET --location=$REGION \
  --uniform-bucket-level-access --public-access-prevention
```

## One-time setup

Turn on the four APIs the deploy uses.

```bash
# NOT run here
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com storage.googleapis.com
```

Create a service account for the app to run as.
Give it read and write access to objects in this one bucket and nothing else.
Do not run the app as the default compute service account, which usually has Editor on the whole project.

```bash
# NOT run here
gcloud iam service-accounts create hah-agent-run --display-name="HAH demo app (Cloud Run)"
gcloud storage buckets add-iam-policy-binding gs://$BUCKET \
  --member=serviceAccount:$RUNTIME_SA --role=roles/storage.objectAdmin
```

## Build

Cloud Build uploads the source, builds the image and pushes it to Artifact Registry.
`.gcloudignore` keeps `.env`, `.venv`, local patient data and tests out of the upload.
`.dockerignore` keeps the same files out of the image.
`tests/test_image_context.py` fails if either file stops excluding secrets or patient data, or starts excluding a file the app needs.
The image installs the exact versions in `requirements.lock`, so a rebuild next month gets the same packages.
Each image gets two tags: `latest` and the build id, which you can roll back to.

### Refreshing the lock

`requirements.txt` is the file you edit.
After changing it, or to pick up newer versions, regenerate the lock with Python 3.12, the image's version.

```bash
# NOT run here
python3.12 -m venv /tmp/lockvenv
/tmp/lockvenv/bin/pip install -r requirements.txt
/tmp/lockvenv/bin/pip freeze | sort -f
```

Replace the package lines in `requirements.lock` with that output and keep its two header lines.
On macOS the freeze leaves out `watchdog`, which Streamlit installs only on Linux, so keep the `watchdog` line too.
Then rebuild a clean venv from the lock alone, install pytest, and run the full test suite before you build.

```bash
# NOT run here
python3.12 -m venv /tmp/lockcheck
/tmp/lockcheck/bin/pip install --no-deps -r requirements.lock && /tmp/lockcheck/bin/pip check
/tmp/lockcheck/bin/pip install pytest && /tmp/lockcheck/bin/python -m pytest -q
```

```bash
# NOT run here
git clone https://github.com/rachelsunyy/nestera-health-patientinfo-chat.git
cd nestera-health-patientinfo-chat
gcloud builds submit --config cloudbuild.yaml .
```

If the push step fails with a permission error, the Cloud Build service account needs the Artifact Registry Writer role on the project.
Which account Cloud Build uses depends on how your project was set up.
The error message names it.

## Deploy

```bash
# NOT run here
gcloud run deploy $SERVICE \
  --image=$REGION-docker.pkg.dev/$PROJECT/$REPO/app:latest \
  --region=$REGION \
  --no-allow-unauthenticated \
  --service-account=$RUNTIME_SA \
  --min-instances=1 \
  --max-instances=1 \
  --session-affinity \
  --timeout=3600 \
  --memory=1Gi \
  --cpu=1 \
  --set-env-vars=GCS_BUCKET=$BUCKET
```

Why each flag is there:

- `--no-allow-unauthenticated`. The clinician page has no login. Anyone who can load the URL can read every patient and register new ones. With this flag only people you grant the invoker role can reach the app.
- `--service-account`. The app runs as the account from one-time setup, which can only touch this bucket.
- `--min-instances=1`. One instance stays warm, so the sponsor does not wait through a cold start.
- `--max-instances=1`. Each chat lives in the memory of one instance. With a single instance a check-in never lands on an instance that has not seen it. One instance is plenty for a demo.
- `--session-affinity`. Sends a browser back to the same instance. It matters if you raise the instance cap later.
- `--timeout=3600`. Streamlit keeps a websocket open for the whole visit. Cloud Run closes any request at the timeout, and 3600 seconds is the maximum.
- `--memory=1Gi` and `--cpu=1`. Enough for Streamlit and pandas with a handful of users. Raise memory if the logs show the instance was out of memory.
- `--set-env-vars=GCS_BUCKET=...`. The only setting the app needs. It switches storage from local files to the bucket.

Leave every AI setting unset.
AI assist stays off in the cloud demo.
The Anthropic API key must never be baked into the image or passed as a plain environment variable, because anyone who can view the service can read those.
If the team ever wants AI in the cloud, store the key in Secret Manager and mount it with `--set-secrets`.
The README's rules on AI and patient data still apply: synthetic data only, until a BAA is signed and confirmed.

### Letting people in

Grant the invoker role to each person who should open the app.

```bash
# NOT run here
gcloud run services add-iam-policy-binding $SERVICE --region=$REGION \
  --member=user:someone@example.com --role=roles/run.invoker
```

A browser does not send Google credentials on its own, so opening the `run.app` URL directly returns 403 even for invited people.
Open the app through the proxy instead.
It signs each request with your own Google login.

```bash
# NOT run here
gcloud run services proxy $SERVICE --region=$REGION --port=8082
```

On a laptop, open http://localhost:8082/patient and http://localhost:8082/clinician.
In Cloud Shell, click Web Preview, change the port to 8082, then add `/patient` or `/clinician` to the preview URL.
A Web Preview URL works only for the Cloud Shell user who opened it, so the presenter shares their screen.

### The public alternative

For a short demo that holds only synthetic patients, you can deploy with `--allow-unauthenticated` in place of `--no-allow-unauthenticated`.
The `run.app` URL then works in any browser.
The risk is that anyone who finds the URL can read and change every record, and can register patients.
Use it only with the seeded synthetic data, and delete the service or switch back right after the demo.

```bash
# NOT run here
gcloud run services update $SERVICE --region=$REGION --no-allow-unauthenticated
```

## Seed the demo patients

A new bucket is empty, and the app only auto-loads the sample patients when it uses local files.
The seed script writes the `demo_` scenario patients from DEMO.md, plus the three sample patients if they are missing.
`--reset` removes every `demo_` patient first.
The script never touches a patient whose id does not start with `demo_`.

```bash
# NOT run here
cd nestera-health-patientinfo-chat
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export GOOGLE_CLOUD_PROJECT=$PROJECT
TZ=UTC python scripts/seed_demo.py --gcs-bucket $BUCKET --reset
```

The script uses your own Google login.
If it reports missing credentials, run `gcloud auth application-default login` and try again.

The demo dates are relative to the day you seed.
Seed again on demo day, shortly before the demo.

`TZ=UTC` matters.
Cloud Run runs in UTC, and the app decides what "today" is from its own clock.
Seeding with the same clock keeps today's check-ins on today.
Check-in times on screen are UTC as well.

## Verify after deploy

Start the proxy from the section above, then check the health endpoint.

```bash
# NOT run here
curl -s http://localhost:8082/_stcore/health     # expect: ok
```

Then in the browser:

1. Open `/clinician`. The roster lists the six `demo_` patients and the three sample patients.
2. Open `/patient`, pick Grace Thompson and complete a check-in.
3. Open `/clinician` again. Grace Thompson shows a completed check-in for today.

Read the logs if anything fails.

```bash
# NOT run here
gcloud run services logs read $SERVICE --region=$REGION --limit=100
```

## Roll back

Every build has an image tagged with its build id.
Find the previous build and point the service at its image.

```bash
# NOT run here
gcloud builds list --limit=5 --format="table(id, createTime, status)"
gcloud run services update $SERVICE --region=$REGION \
  --image=$REGION-docker.pkg.dev/$PROJECT/$REPO/app:BUILD_ID_FROM_THE_LIST
```

You can also send all traffic to an earlier revision.
After this, new deploys get no traffic until you run `update-traffic --to-latest`.

```bash
# NOT run here
gcloud run revisions list --service=$SERVICE --region=$REGION
gcloud run services update-traffic $SERVICE --region=$REGION --to-revisions=REVISION_NAME=100
```

## Tear down

Delete the service when the demo is over.

```bash
# NOT run here
gcloud run services delete $SERVICE --region=$REGION
```

Deleting the bucket erases every patient record in it, and it cannot be undone.
Only do it if nothing in the bucket is needed.

```bash
# NOT run here
gcloud storage rm --recursive gs://$BUCKET
```

## Cost

This guide gives no prices.
Check the Google Cloud pricing pages or the pricing calculator for current figures.

- `--min-instances=1` keeps one instance running all the time, so it bills even when nobody uses the app. Set it back to 0 or delete the service after the demo.
- Each build bills Cloud Build time on the `E2_HIGHCPU_8` machine in `cloudbuild.yaml`.
- Every build adds an image to Artifact Registry, which bills for storage. Delete old images you no longer need for rollback.
- The bucket holds small JSON files.
