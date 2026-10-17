# Private deployment from GitHub

This app needs a persistent Docker-capable Linux server, not GitHub Pages or a static hosting plan. The production configuration includes Caddy (HTTPS), frontend, API, worker, PostgreSQL and Redis. A hosting account, DNS name, and a GitHub repository must be selected before an actual deployment. Nothing is published by adding these files.

## GitHub

Create an empty **private** repository, for example `lecture-studio`. Upload the contents of this application folder as the repository root. Include source, Dockerfiles, `compose.production.yaml`, `.env.example`, tests and `.github/workflows/checks.yml`.

**Exclude** `.env`, any `.env.*` files except `.env.example`, API keys, recordings, databases, `node_modules`, `.next*`, and generated exports. The included `.gitignore` handles normal Git usage; uploading with the website requires selecting files carefully. Never publish your local `.env`.

The Checks workflow builds the frontend and runs backend authentication and actual demo-media tests on pushes and pull requests. It uses no API key and does not deploy automatically. Check the first GitHub Actions run after upload; the workflow has not run on GitHub until a repository is chosen.

## Configure your administrator locally (optional)

Your existing `compose.yaml` remains localhost-only and authentication stays off until explicitly configured. To enable login on your current local app, run this from the app folder:

```powershell
docker run --rm -it -v "${PWD}:/workspace" python:3.12-slim python /workspace/scripts/configure-admin.py /workspace/.env
docker compose up --build -d
```

Enter a username and a password of at least 12 characters at the terminal prompts. Password entry is hidden. The script stores a salted scrypt hash, never the plaintext password, and also generates a database secret for a future new production database. It preserves your other `.env` settings, including your OpenAI key. No password should be shared in chat.

Use http://localhost:3000 consistently (not a mixture of localhost and 127.0.0.1) because browser cookies are host-specific. Local login cookies are HttpOnly/SameSite=Lax and sent over localhost HTTP. Public cookies require HTTPS and are Secure/host-only. Rebuilding is necessary to get the new login UI into the running frontend.

## On your Linux hosting server

1. Install Docker Engine and Compose from official Docker instructions for that server's operating system. Use a server with enough CPU, memory and disk for FFmpeg and long recordings; measure with a short lecture before committing large jobs.
2. Point a DNS A record (and only a working AAAA record, if using IPv6) for your chosen hostname at the server. Allow inbound TCP 80 and 443. Retain your normal protected SSH access. Do not expose ports 3000, 8000, 5432 or 6379.
3. Clone the private repository using the hosting platform's GitHub integration or a read-only GitHub deploy key you configure yourself. Do not paste passwords/tokens into chat or into repository files.
4. From the cloned repository, prepare configuration:

```sh
cp .env.example .env
docker run --rm -it -v "$PWD:/workspace" python:3.12-slim python /workspace/scripts/configure-admin.py /workspace/.env
```

5. Edit `.env` on the server. Keep the generated administrator hash and database password. Set these non-secret/example fields and add your real OpenAI API key privately:

```dotenv
SITE_HOST=lectures.your-domain.example
OPENAI_API_KEY=your-key-entered-on-the-server
```

`SITE_HOST` must be a bare real DNS hostname without scheme, port or path. Do not copy the example domain literally. `compose.production.yaml` forces `AUTH_REQUIRED=true` and `PUBLIC_ORIGIN=https://<SITE_HOST>`; API startup fails if authentication lacks a valid password hash. Never override this to disable public authentication.

6. Start the **standalone production file**:

```sh
docker compose -f compose.production.yaml config --quiet
docker compose -f compose.production.yaml up --build -d
docker compose -f compose.production.yaml ps
docker compose -f compose.production.yaml logs --tail=100 proxy api worker
```

Do not combine `compose.yaml` and `compose.production.yaml`. Production exposes only Caddy on 80/443. Caddy obtains a public HTTPS certificate when DNS and network access are correct. The frontend calls `/api` on the same HTTPS origin, so cookies, screen recording and long uploads don't depend on cross-domain credential settings or a Next.js upload proxy.

7. Open `https://<your-hostname>` and sign in with the administrator password you chose. No self-registration or student accounts exist. Only the sign-in UI/static assets, session status and basic health are public; lecture metadata, uploads, processing, transcripts, audio/video, exports and API documentation require a valid session.

## Check before relying on hosting

- An incognito session must show the sign-in page. `GET /api/lectures` and an export URL must return 401 when signed out.
- Sign in, create a short lecture, and check recording/upload and range seeking on preview video. Run a real-key sample only after checking API billing.
- Logout must revoke the session; old protected URLs must stop working. Test a fresh browser session and a wrong password.
- Watch proxy logs for certificate problems. Actual HTTPS/domain, Docker networking, GitHub Actions and long-lecture load tests must be completed on the selected host; they cannot be established from a local code test.
- Back up **both** PostgreSQL and the media volume. PostgreSQL contains sessions as well as lecture metadata. Browser recording-recovery chunks remain in that browser until manually deleted, including after logout.

## Sessions and maintenance

Sessions expire after eight hours and are stored as opaque token hashes in PostgreSQL. Cookies are HttpOnly, SameSite=Lax, Secure on public HTTPS, and use the `__Host-` prefix. Mutating authenticated API requests require an allowed exact Origin plus a session-derived CSRF header. Five incorrect logins in one minute temporarily block login; the single-admin limit is shared across API processes. Logout deletes the session. Password/username hash changes revoke existing sessions after restarting services with the new configuration.

To change the administrator password, rerun the configuration script and restart API/worker. It generates a new hash even if the same password is entered, which also revokes existing sessions. Keep the existing `DB_PASSWORD` when updating a deployment: changing the environment does not change the password in an already initialized PostgreSQL volume. Database-password rotation requires a coordinated SQL change and service update.

To update code, pull the chosen branch and rerun `docker compose -f compose.production.yaml up --build -d`. Processing jobs should be allowed to finish or explicitly cancelled before a worker update; use the documented crash recovery procedure when necessary. `down` preserves volumes; `down -v` destroys stored data. This is a single-user deployment foundation, not a multi-tenant service or a completed independent security review.
