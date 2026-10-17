# Railway trial: short clips only

This is a limited evaluation deployment, not a promise of ongoing free hosting. Official Railway pricing inspected 2026-10-18 lists a one-time $5 trial credit expiring after 30 days, with constrained RAM and storage. Check your own workspace's actual eligibility, credit and plan before deploying: https://railway.com/pricing. Do not enable a paid subscription or automatic top-ups if you only want the trial. AI API charges are separate.

## Architecture

The root `railway.toml` builds `deploy/railway/Dockerfile`. Its Node build stage exports the Next.js interface as static files; the runtime image contains Nginx, the FastAPI API and a separate supervised RQ worker process. These processes share one mounted media directory. PostgreSQL and Redis remain separate private Railway services. This uses three services instead of deploying the original six-service Compose configuration.

Do not deploy the API and worker as separate Railway services with separate `/data` volumes: they would not see the same media. Never use the local SQLite/thread-worker development path for this deployment. One app replica is required. This does not change normal local Docker Compose behavior.

## Before setup

- Connect the Railway integration to your Railway Free/Trial account, or use the Railway website and authorize your GitHub repository there.
- Confirm that the trial account permits the required services and network access. Trial verification/eligibility can restrict deployments; no bypass is implemented.
- Use only short test recordings. The image enforces **one lecture at a time, at most 120 seconds and 50 MB per upload**. Download everything you want to retain and delete that lecture before creating another. Frame holds, WAV intermediates and exports still consume additional storage; monitor the mounted volume and remaining trial credit.

## Dashboard configuration

1. Create a Railway project with a PostgreSQL service and Redis service. Keep these services private; do not generate public database or Redis endpoints. PostgreSQL should use its template's persistent volume. Redis is queue delivery; PostgreSQL remains the durable job source.
2. Add an application service from `hbhaq/lecturedubber`, branch `main`, with repository root `/`. The root `railway.toml` selects the trial Dockerfile. Build context must include frontend, backend and deploy directories.
3. Add a persistent volume mounted at `/data` to the application service. Check the permitted trial volume capacity; avoid increasing resources beyond the trial's allowance.
4. Set runtime variables using Railway references to your actual service names:

```dotenv
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
AUTH_REQUIRED=true
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=<your salted scrypt hash>
STORAGE_ROOT=/data
PORT=8080
MAX_LECTURES=1
MAX_UPLOAD_BYTES=52428800
MAX_LECTURE_SECONDS=120
```

The service names `Postgres`/`Redis` above are examples. Use the dashboard's reference picker rather than copying these names blindly. The PostgreSQL URL must use the **private** endpoint. `postgresql://` URLs are normalized to the installed psycopg driver by the app.

5. Generate the application service's Railway HTTPS domain, targeting port **8080**. Set `PUBLIC_ORIGIN` to that exact `https://...up.railway.app` origin, or let startup use `RAILWAY_PUBLIC_DOMAIN` if available. Do not use localhost. Restart/redeploy after the public domain is available. Startup intentionally fails if no public origin or valid administrator hash is configured.
6. Set `ADMIN_PASSWORD_HASH` privately in Railway. Generate it on your own computer with `scripts/configure-admin.py`; that script saves it in your ignored `.env`. Copy only the hash into Railway, never the plaintext password into GitHub/chat. You choose the sign-in password yourself. Public deployment cannot run without login.
7. Leave `OPENAI_API_KEY` unset for an offline demo evaluation. If you want live recognition/translation, enter your key privately in Railway Variables, with API billing enabled. This sends lecture audio/text to OpenAI and can incur API charges; trial hosting credits do not cover them.

## Deploy and verify

Deploy after database references, volume, administrator hash and domain are configured. Health path is `/api/health`; the public API and static UI share the same HTTPS origin. Open the generated URL and verify:

- Sign-in works; signed-out `/api/lectures` returns 401.
- A short demo recording can upload, run through review/approval, render, seek and download.
- The app rejects oversized or longer-than-two-minute inputs before paid transcription.
- Logout blocks private downloads, and data persists after an intentional app restart.
- A Live sample is checked separately only after you add the API key and accept API charges.

Do not enable serverless/app sleeping while an RQ job is running; background work is not necessarily visible as incoming HTTP activity. Do not scale the application above one replica. Redeploys can interrupt renders; completed speech remains cached. Use the documented job recovery procedure after confirming the old worker is stopped.

Trial expiry or exhausted credits can stop services. Download exports before the evaluation ends. A production lecture service needs a hosting/storage budget and a representative long-lecture test; the trial settings deliberately prevent 60–120 minute lectures.

## Verification limits

Backend limit/authentication tests pass locally. The Railway Docker image build and static frontend export completed on 2026-10-18; PostgreSQL and Redis show Online. Application startup refuses missing public-origin configuration as intended. Nginx routing, service references, mounted-volume persistence, public authentication and resource use still need runtime verification after the administrator settings are supplied. A successful image build is not a working public deployment.
