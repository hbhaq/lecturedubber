# Lecture Studio

A local, single-user lecture dubbing application. Next.js/React/TypeScript/Tailwind frontend, FastAPI API, PostgreSQL metadata, Redis/RQ background worker, local volume storage, FFmpeg rendering. Record or upload → short sample → transcription and translation → human review → approval → narration → synchronized preview → exports.

Optional single-administrator login and an HTTPS Docker deployment are now included. See [GitHub and hosting setup](docs/DEPLOYMENT.md). The local configuration remains unchanged until you explicitly enable authentication; production requires it.

## Start with Docker (recommended)

Install Docker Desktop with Linux containers and Docker Compose v2. Allow at least 4 CPU cores, 8 GB RAM, and ample disk space. Video intermediates can use several times the source size. FFmpeg, ffprobe, eSpeak NG, Python and Node are installed by the Dockerfiles.

From this directory:

```powershell
Copy-Item .env.example .env
# Optional: edit .env and set OPENAI_API_KEY for live processing.
docker compose up --build -d
```

Open http://localhost:3000 in desktop Chrome or Edge. API docs: http://localhost:8000/docs. Both published ports bind to **127.0.0.1**. PostgreSQL and Redis have no published ports. No login is implemented: keep this on localhost.

```powershell
docker compose logs -f worker
docker compose down
```

`down` preserves named volumes. Do not use `down -v` unless you intend to erase the entire local database, queue, and media collection. Delete individual lectures in the app to delete their source, intermediates, cached requests, audio, and exports. Browser recovery chunks live separately in IndexedDB; delete them in the recorder.

## First lecture

1. Create a lecture with title, course, topic, glossary and optional context. Choose **Demo** or **Live** explicitly.
2. Upload an MP4/WebM/MOV/MKV/M4V, or select Record screen. Start recording opens separate screen-sharing and microphone permission dialogs. A screen audio track is never assumed to include a microphone. This version deliberately excludes system/tab audio.
3. Stop the recorder or end screen sharing. Use the saved recording; download a backup. Recording chunks are written every three seconds to browser IndexedDB. Pause/resume is available when supported. Keep the tab open and ensure free browser storage. Chunk recovery is best effort, not a guarantee against browser crashes or quota exhaustion.
4. Run the first 30-second sample. Inspect the original and English text before clicking **Sample checked · Process full lecture**. Live mode sends audio and text to OpenAI and incurs charges.
5. Review the timestamped script beside the original video. Each segment has a seek control, original transcript, editable English and review flags. Save every edit. Acknowledge flagged passages after listening.
6. Choose a voice and save pronunciation instructions, such as `secp256k1: say “seck P two fifty-six K one”`. Settings changes require renewed approval. Use the explicit short voice preview button if desired (a paid API call in live mode).
7. Approve the current script in Review script. Generate narration and a synchronized video from Voice. No lecture narration is generated before approval. Edits revoke approval and make preview/exports unavailable; unchanged narration stays cached.
8. Watch Preview & export. Inspect flagged holds, especially handwriting/demonstrations. Accept long holds explicitly, choose optional burned captions, then create final exports.
9. Download `lecture.mp4`, SRT, VTT, complete transcript (Markdown/text), notes (Markdown/PDF), and the JSON timing map. Notes are an optional derivative, distinct from the complete translated narration.

## Demo versus live

**Demo** is explicitly labeled throughout the interface and exports. It uses a fixed Urdu–English modular inverse example regardless of the uploaded audio, a fixed English translation, and eSpeak NG speech. Demo notes quote the reviewed demo script. It exercises the actual review, approval, media render, timing, export and download code, with no external AI calls. It does **not** demonstrate recognition/translation accuracy. All demo voice selections use the same basic offline voice.

**Live** requires only a backend `OPENAI_API_KEY`. The UI disables live mode if the key is absent. Default adapters:

| Stage | Default | Why / boundary |
|---|---|---|
| Transcription | `whisper-1` | Verbose segment timestamps required by the current alignment adapter. Automatic language detection; technical glossary prompt. Code-switch accuracy must be checked on the short sample. |
| Translation and notes | `gpt-4.1-mini` | Responses structured output parsed and validated with Pydantic. `store=False`. Replaceable independently of speech. |
| English narration | `gpt-4o-mini-tts` | Supported standard voices, pronunciation instructions, WAV output. Input is limited to 4000 characters per reviewed segment (below the documented 4096 maximum). |

Read [provider verification and privacy](docs/PROVIDERS.md) before using sensitive content. Model availability is account dependent; the app does not claim a live test without credentials. No price estimate is displayed because no current pricing schedule has been configured and verified. API-returned usage is persisted per job; TTS input characters are measured locally because the streaming speech response does not provide token usage. Usage is not a billing ledger.

## Synchronization

See [the alignment design](docs/ALIGNMENT.md). Every source interval is covered, including silence/gaps. Audio is measured with ffprobe; speech can be accelerated at most 1.12× with FFmpeg `atempo` (pitch preserving). Shorter speech is padded with silence; longer speech extends the corresponding video interval by holding its last frame. Interval durations are quantized to 30 fps. Source order/resolution are retained (odd dimensions rounded down one pixel for H.264 compatibility). Output is H.264/yuv420p + AAC in MP4 at 30 fps.

The stored source→final map drives subtitles and notes timestamps. A separate preview must exist before export. Holds exceeding 2 seconds or 25% of an interval are flagged. The strategy is unsuitable for some continuous drawing or tightly timed demonstrations: review and revise narration manually. Subtitle cues are proportionally spaced within each final spoken segment; **word-level forced alignment is not implemented**.

## Reliability and recovery

PostgreSQL is the durable job source. Redis is queue delivery and a per-lecture worker lock. The API uses a row lock to prevent simultaneous mutations/starts per lecture; it blocks editing while work runs. One worker is configured by default. Jobs have bounded provider retry/backoff, attempts, stage, progress, error, cancellation and measured usage. Transient provider failures retry four times. Other failures surface with stage and a retry action. Files are processed on disk; audio is extracted as 300-second mono 16 kHz WAV chunks (~9.6 MB/request, below the documented 25 MB upload limit). No full video is loaded into application memory. Browser recovery downloads do assemble a Blob and may be expensive for very long recordings.

Cancel is cooperative between provider requests or FFmpeg intervals; it cannot interrupt an already accepted provider call or refund it. Retry reuses completed transcription/translation/audio/notes caches and rendered interval files. A crash after a provider accepted a request but before its result was saved can still cause a duplicate charge; the provider APIs do not supply transactional billing with our database.

After a worker/host crash, stop all workers before explicitly reconciling durable queued/running jobs:

```powershell
docker compose stop worker
docker compose run --rm worker python -m app.worker --recover
docker compose up -d worker
```

This requeues interrupted jobs. Do not run recovery while workers are processing. The Redis lecture lock prevents overlapping duplicate delivery. An abruptly killed worker may leave a lock for up to eight hours; after confirming all workers are stopped, inspect/delete only the specific `lecture:<id>` lock with Redis CLI, or wait for expiry. Queue enqueue failures are saved as failed jobs and can be retried after Redis is restored.

Cache keys include model, mode, input, glossary/context, voice and pronunciation where relevant. Script edits invalidate only the changed segment's audio plus whole-lecture alignment/exports/notes; other speech remains reusable. Voice settings affect all narration. Sources are immutable after upload; create a new lecture for replacement source media. Old export files remain versioned on disk but only current exports are downloadable; deleting the lecture removes all versions.

## Native development (alternative)

Python 3.12+, Node 22+, FFmpeg/ffprobe (H.264, AAC and libass), eSpeak NG, and optionally PostgreSQL/Redis. For convenient single-process development only, SQLite and an in-process background thread are supported:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -c constraints.txt
$env:LOCAL_WORKER='1'
$env:DATABASE_URL='sqlite:///./lecture.db'
$env:STORAGE_ROOT='./data'
# Optional: $env:OPENAI_API_KEY='...'
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Use http://localhost:3000. The browser calls http://localhost:8000 directly for streaming uploads/media; it does not proxy multi-gigabyte files through Next.js. Set `NEXT_PUBLIC_API_URL` at frontend build time to change the local API address. On Windows, native demo speech tries `System.Speech` if eSpeak NG is absent; installing eSpeak NG is recommended. `ESPEAK`, `FFMPEG`, and `FFPROBE` can specify executable paths. If ffprobe is absent in native development only, metadata falls back to FFmpeg diagnostics; install ffprobe for reliable metadata. SQLite/local threads are for development and are not the PostgreSQL/Redis reliability path.

## Tests

```powershell
docker compose run --rm api python -m pytest tests -q
docker compose run --rm frontend npm run typecheck
```

Or `python -m pytest tests -q` from backend with dependencies and FFmpeg/eSpeak installed. The media test creates a short fixture and runs actual demo speech, FFmpeg rendering, export downloads, injected render failure/retry and edit invalidation. Provider adapters are demo fixtures; this is **not live AI verification**. Read [validation results](docs/VALIDATION.md) for the checks actually executed during implementation.

## Boundaries and next steps

Single-administrator authentication, session revocation and CSRF protection are available for private hosting; no multi-user registration, cloning, live captions, YouTube integration, or automatic vision/OCR is included. Use the separate production configuration with HTTPS for hosting. It enforces authentication and a 20 GB proxy request limit. Add appropriate storage quotas, backups and monitoring for your actual server. Do not expose API/database/queue ports publicly.

Optional vision extension: extract user-selected source frames into a separate asset namespace, send only explicitly selected frames through a replaceable vision/OCR adapter, store candidate equations/diagrams linked to segment IDs, and require human verification before merging them into reviewed scripts or notes. Current notes only know what was spoken/reviewed.

Database tables are created on initial startup. Future schema changes need migrations before upgrading existing data; no production migration framework is included. Native development dependencies and Docker images require internet access on first install/build.
