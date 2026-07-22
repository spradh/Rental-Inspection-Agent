# Deploy the BI Analyst Agent to Cloud Run

A step-by-step runbook to take the **full agent** to production on GCP. The FastAPI service
(`project/api/main.py`) runs on **Cloud Run** (serverless containers — no cluster to manage)
and talks to **cloud backends only**:

```
                ┌──────────── Cloud Run ────────────┐
 client ──HTTPS▶│  bi-agent service (autoscaled)     │── BigQuery   (warehouse, keyless SA)
   (auto TLS)   │    uvicorn project.api.main         │── Qdrant     (vector store / retrieval)
                │    runs as bi-agent@…gserviceaccount │── Redis      (agent memory)
                │                                     │── LangSmith  (tracing)
                └────────────────────────────────────┘── OpenRouter (LLM, Secret Manager)
```

BigQuery is reached by the service's **runtime service account** (no key files); every other
backend is an external managed service reached over the network with a URL + key from **Secret
Manager**. `GET /health` probes all four and returns **503 unless every one is online** — so a
deploy that's missing an env key is held out of rotation instead of half-working.

Why Cloud Run (vs. Kubernetes/GKE): no cluster, nodes, `kubectl`, or YAML; you deploy with
**one command**, get an **HTTPS URL + autoscaling (incl. scale-to-zero)**, and pay ~nothing when
idle. Same image, same backends — far less operational surface.

> **Cost:** Cloud Run scales to zero (idle ≈ $0); BigQuery charges per byte scanned (the agent
> caps scans at ~2 GB/query). The deployable image is the repo-root [`Dockerfile`](../../Dockerfile)
> — it ships the retrieval stack (sentence-transformers → torch), so it's multi-GB by design.
> Run [Cleanup](#8-cleanup) after a class demo.

---

## 0. Prerequisites
- `gcloud` installed; a GCP project with **billing enabled**. (No Docker or `kubectl` — Cloud
  Build builds the image in the cloud.)
- Authenticated: `gcloud auth login` and `gcloud auth application-default login`.
- A Qdrant cluster, a Redis instance, a LangSmith key, and an OpenRouter key (the cohort's
  managed services — same URLs/keys as your `.env`).
- Run everything **from the repo root**.

## 1. Set variables & enable APIs
```shell
export PROJECT_ID="your-gcp-project"          # ← your project id
export REGION="us-central1"
export SA="bi-agent@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com bigquery.googleapis.com secretmanager.googleapis.com
```

## 2. Load the warehouse into BigQuery (one-time)
```shell
export BIGQUERY_PROJECT="$PROJECT_ID"
python -m data.generate                        # produces data/local/csv/*.csv
python -m data.load_bigquery --dataset loomco  # creates the dataset + loads 8 tables
```

## 3. Ingest the knowledge base into Qdrant (one-time)
Retrieval reads from **Qdrant**, so index the KB once (embeds the corpus, then upserts). Needs
`QDRANT_URL` + `QDRANT_API_KEY` in your local `.env`:
```shell
python -c "from project.retrieval import ingest; print(ingest(), 'chunks indexed')"
```

## 4. Create the runtime service account (keyless BigQuery)
The Cloud Run service *runs as* this identity, so it reads BigQuery with **no key file** — the
"identity, not secrets" idea, minus the GKE Workload Identity ceremony.
```shell
gcloud iam service-accounts create bi-agent
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" --role="roles/bigquery.dataViewer"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" --role="roles/bigquery.jobUser"
```
> Qdrant, Redis, and LangSmith are **not** GCP resources — they're reached by URL + key, not
> IAM. Only BigQuery uses the service-account identity.

## 5. Put the keys in Secret Manager
Every secret (the URLs with embedded passwords too) lives in Secret Manager and is mounted as
an env var at runtime — never in the image, the source, or the deploy command. Read the values
**straight from your `.env`** (run from the repo root) so nothing lands in your shell history.
```shell
getv(){ grep "^$1=" .env | head -1 | cut -d= -f2- | tr -d '"'; }        # pull one value from .env
# create the secret if it's new, else add a new version — safe to rerun. `printf '%s' "$(...)"`
# is load-bearing: it strips the trailing newline, or the key becomes an illegal HTTP header and
# services fail at runtime.
put(){ printf '%s' "$(getv "$2")" | gcloud secrets create "$1" --data-file=- 2>/dev/null \
       || printf '%s' "$(getv "$2")" | gcloud secrets versions add "$1" --data-file=-; }
put openrouter-key OPENROUTER_API_KEY
put qdrant-key     QDRANT_API_KEY
put redis-url      REDIS_URL
put langsmith-key  LANGSMITH_API_KEY
for s in openrouter-key qdrant-key redis-url langsmith-key; do
  gcloud secrets add-iam-policy-binding "$s" \
    --member="serviceAccount:${SA}" --role="roles/secretmanager.secretAccessor"
done
```
> Redeploys just reference `…:latest`, so you only touch this once — and rerunning it is safe
> (existing secrets get a new version rather than erroring).

## 6. Deploy
One command: Cloud Build builds the repo-root `Dockerfile`, pushes it to Artifact Registry, and
Cloud Run rolls it out behind an HTTPS URL. `QDRANT_URL` isn't secret (the key is); the three
`*_MODEL` vars point the agent at OpenRouter (it defaults to Anthropic) so one key runs it all.
```shell
QDRANT_URL="$(grep '^QDRANT_URL=' .env | cut -d= -f2- | tr -d '"')"   # your real cluster URL (not a placeholder)
gcloud run deploy bi-agent \
  --source . \
  --region "$REGION" \
  --service-account "$SA" \
  --set-env-vars "BIGQUERY_PROJECT=${PROJECT_ID},BIGQUERY_DATASET=loomco,QDRANT_URL=${QDRANT_URL},LANGSMITH_TRACING=true,SUPERVISOR_MODEL=openrouter:qwen/qwen3-30b-a3b-instruct-2507,SPECIALIST_MODEL=openrouter:qwen/qwen3-30b-a3b-instruct-2507,SYNTH_MODEL=openrouter:qwen/qwen3-30b-a3b-instruct-2507" \
  --update-secrets "OPENROUTER_API_KEY=openrouter-key:latest,QDRANT_API_KEY=qdrant-key:latest,REDIS_URL=redis-url:latest,LANGSMITH_API_KEY=langsmith-key:latest" \
  --memory 4Gi --cpu 2 --timeout 600 \
  --allow-unauthenticated
```
> `--memory 4Gi --cpu 2` fits the embedding + reranker models; `--timeout 600` covers the slow
> **first** request, which downloads those models (cold start). Drop `--allow-unauthenticated`
> to require IAM auth instead of a public URL.

## 7. Test it
```shell
# `status.url` returns the deprecated legacy URL; build the deterministic one the deploy prints:
URL="https://bi-agent-$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)').${REGION}.run.app"

# /health is 200 only when BigQuery + Qdrant + Redis + LangSmith are ALL online:
curl "${URL}/health"
curl -X POST "${URL}/chat" -H 'content-type: application/json' \
  -d '{"question":"What was net revenue in March 2026?"}'   # -> AnalystAnswer JSON
```
(First `/chat` is slow — the instance loads the embedding + rerank models on first use.)

## 8. Cleanup
`services delete` stops compute billing but **leaves the built images** — every `--source .`
deploy pushes one to the `cloud-run-source-deploy` Artifact Registry repo (a few full-agent
deploys is ~GBs of storage that keeps billing). Remove them too:
```shell
gcloud run services delete bi-agent --region "$REGION"                            # the service
gcloud artifacts repositories delete cloud-run-source-deploy --location "$REGION" # the images (the big leftover)
gcloud storage rm -r "gs://run-sources-${PROJECT_ID}-${REGION}"                   # the source tarballs
# optional: gcloud secrets delete openrouter-key qdrant-key redis-url langsmith-key
# optional (⚠️ the cohort's later lessons reuse loomco — drop it only if you're done for good):
#           bq rm -r -d "${PROJECT_ID}:loomco"
```

## CI/CD (optional — needs your own GitHub repo)
`project/deploy/ci.yml` is two jobs. The **`quality`** job (lint + tests + Session-07 evals)
is the valuable part and runs on every PR — run it locally with `make ci`, no GitHub required.
The **`deploy`** job (auto-deploy to Cloud Run on merge to `main`) only fires if you push this
repo to *your own* GitHub repo and set its secrets — see the header of `ci.yml`. For coursework,
the manual `gcloud run deploy` above is all you need.

---

## Troubleshooting
| Symptom | Likely cause / fix |
|---------|--------------------|
| Deploy fails at build | Run from the **repo root** (the build context); confirm `uv.lock` is committed (`--frozen` needs it). |
| `/health` returns 503 | One backend is down or unconfigured — the JSON body names which (`bigquery`/`qdrant`/`redis`/`langsmith` not `online`), or no provider key is set. Fix that env/secret and redeploy. |
| `/health` shows `qdrant` offline though it's reachable | You skipped §3 — the collection is empty until you `ingest()`. |
| BigQuery `403 / permission denied` | The runtime SA lacks BigQuery roles, or you didn't pass `--service-account` — recheck §4 + §6. |
| First `/chat` times out | Cold-start model download — that's why `--timeout 600`; retry, or set `--min-instances 1`. |
| `Container failed to start … PORT` | The app must listen on `$PORT`; the root `Dockerfile` already does (`--port ${PORT:-8080}`). Don't hardcode a port. |
