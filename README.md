# Study

A single-user, online retrieval-practice app for PDF, Markdown, and text course material. Upload files or generate AI-written study notes from a description of what you need to learn. Generated notes are labeled and should be checked against reliable sources. Files and proficiency are stored on the host; embeddings are computed locally with FastEmbed. The configured language model creates subtopics and source-cited questions. Failed questions return until answered correctly; proficiency is an exponentially weighted self-assessment, not a spaced-repetition schedule.

## Run

Copy `.env.example` to `.env`, choose a random `SESSION_SECRET` and set an Argon2id `PASSWORD_HASH`. For example, using a Python environment with `argon2-cffi` installed:

```sh
python -c 'from argon2 import PasswordHasher; import getpass; print(PasswordHasher().hash(getpass.getpass()))'
```

Put the hash in single quotes in `.env` so Compose preserves the `$` characters. Run `docker compose up -d --build`. The web container listens only on `127.0.0.1:8788`; configure a TLS reverse proxy or Cloudflare Tunnel to reach it. Cookies require HTTPS. To use Ollama, start the `local` Compose profile and pull the configured model separately. GPU access is not configured by default; the local Ollama profile has not been validated for Jetson acceleration.

For OpenAI, explicitly set `LLM_PROVIDER=openai`, `CLOUD_ENABLED=true`, `OPENAI_API_KEY` and `LLM_MODEL`. Source excerpts, summaries and descriptions for generated notes are sent to the configured provider when indexing or generating content. Keep `.env` private and out of version control. Reindex all topics after changing embedding models. The first indexing job downloads the embedding model to the persistent model volume.

The Jetson installation uses Pigeo's existing OpenAI key and model. The app itself binds only to loopback, with HTTPS provided by the remotely managed Cloudflare tunnel. The backend runs as one process and is not publicly exposed.

## Operations

`docker compose logs -f` shows service logs; `GET /health` checks basic liveness. Restarting the backend discards active sessions but keeps committed progress. Interrupted indexing jobs are requeued at startup. To change the password, generate a new Argon2id hash, replace `PASSWORD_HASH` in `.env`, and recreate the backend with `docker compose up -d --force-recreate backend`. Changing `SESSION_SECRET` also invalidates existing sessions.

To make a consistent backup, stop the backend first so uploads and SQLite cannot change while copying the volume. The web app will be unavailable during the backup:

```sh
docker compose stop backend
docker run --rm -v studyapp_app_data:/data:ro -v "$PWD":/backup alpine:3.21 tar czf /backup/study-data.tar.gz -C /data .
docker compose start backend
```

Keep the archive and `.env` securely, separately from the host. To restore into a **new, empty** data volume, stop the backend and extract the archive into that volume, then start it. Restoring over existing data replaces that data; make a fresh backup first. Embedding model files are re-downloadable and are not included. Volume names depend on the Compose project name; inspect `docker volume ls` if it differs from `studyapp_app_data`.

## Development and checks

```sh
cd frontend && npm ci && npm run build
cd ..
PYTHONPATH=backend pytest backend/tests
```

The integration test uses a simulated provider and embeddings. Real provider and device behaviour should also be checked with representative course material; extraction quality, generated questions and math may be imperfect. Scanned PDFs require OCR and are rejected. The current version does not render arbitrary HTML from generated cards; Markdown, tables, math and Mermaid are supported. Images must use authenticated local file URLs. The interface uses a light theme. The project currently initializes its SQLite schema at startup rather than providing Alembic migrations; back up the data before upgrading. Jetson GPU inference, full hardware benchmarking, iOS installation, and disaster recovery have not been validated.
