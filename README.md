# Simple Task Management MVP

A clean, production-minded task planner for households and small teams.

It helps users:
- create tasks with realistic effort levels (`low`, `medium`, `high`)
- assign tasks later as a separate step
- prevent daily overload using point-based capacity rules
- use local AI for effort suggestions, with safe fallback when AI is unavailable

## Key Features

- **Clear task lifecycle**: create first, assign later
- **AI-first effort analysis**: tries Ollama before save
- **Manual override**: always available before saving
- **Workload protection**: assignment checks daily point capacity
- **Date suggestion**: proposes next available date when over capacity
- **Admin controls**: effort points, user capacities, AI provider/model/timeout
- **Session and UX polish**: auth-protected pages, inactivity timeout, theme preference

## Tech Stack

- Backend: `FastAPI`, `SQLAlchemy`, `Alembic`, `PostgreSQL`
- Frontend: `Jinja2`, `HTMX`, `TailwindCSS`
- Auth: JWT (HTTP-only cookie for web + bearer support for API)
- AI: `OllamaProvider` + `RulesFallbackProvider`
- Infra: `Docker`, `Docker Compose`

## Docker-First Quick Start (Recommended)

1. Create your env file from template:
   - Windows PowerShell: `Copy-Item .env.example .env`
   - macOS/Linux: `cp .env.example .env`
2. Start the app:
   - `docker compose up -d --build`
3. Open:
   - [http://localhost:8000](http://localhost:8000)
4. Log in with defaults (or your env overrides):
   - Email: `admin@example.com`
   - Password: `admin1234`

## First-Run Behavior (Ollama Model Download)

On first startup, Docker Compose will:
- start PostgreSQL, Ollama, and backend containers
- run DB migrations automatically
- trigger a one-time helper container to pull `qwen2.5:1.5b`
- store model files in persistent Docker volume `ollama_data`

Important:
- first startup can take longer while the model downloads
- the app is still usable immediately during download
- task creation stays functional because rules fallback remains active
- once model download completes and Ollama is healthy, AI suggestions use Ollama automatically

## AI and Privacy

- The default AI path is local (`ollama` container).
- Task text stays on your machine/server in normal local Docker usage.
- No paid external AI service is required for this MVP.
- If Ollama is slow/unavailable, rules fallback keeps task creation reliable.

## Basic Usage Flow

1. **Login**
   - open `/login` and sign in with admin credentials
2. **Create task**
   - enter title + description + due date
   - app runs AI effort analysis first
   - choose suggested level or manually override
   - save unassigned task
3. **Assign task**
   - open task detail and select assignee + assignment date
   - app validates projected points against that user capacity
4. **Workload validation**
   - if within capacity: assignment succeeds
   - if over capacity: assignment blocked and next available date suggested
5. **Admin settings**
   - update effort points and user capacities
   - manage AI provider/model/timeout/fallback
   - review model health and recent AI errors

## Core Product Rules Enforced

- Task creation and assignment are separate actions.
- Task save requires a valid effort level.
- AI is attempted first during task creation.
- Manual override is available before save.
- Capacity is checked only during assignment/reassignment.
- Workload calculations use `assignment_date` (not due date).
- Completed tasks assigned for a day still count for that day.

## Project Structure

```text
backend/
  app/
    api/
    models/
    schemas/
    services/
    ai/
      providers/
      services/
      registry/
      prompts/
      schemas/
      utils/
    core/
    db/
    templates/
  alembic/
    versions/
Dockerfile
docker-compose.yml
alembic.ini
.env.example
requirements.txt
tests/
```

## Environment Configuration

Use `.env.example` as your baseline. Most users only need to change:
- `SECRET_KEY`
- `INITIAL_ADMIN_EMAIL`
- `INITIAL_ADMIN_PASSWORD`

Default Docker setup already points backend to internal services:
- Postgres via `db`
- Ollama via `http://ollama:11434`

## Local Development (Optional, without Docker)

1. Create Python 3.12 virtual environment
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Copy env template to `.env`
4. Ensure PostgreSQL is running and `DATABASE_URL` is correct
5. Apply migrations:
   - `alembic upgrade head`
6. Start app:
   - `uvicorn backend.app.main:app --reload`

## Tests

- Run all tests:
  - `pytest`

## Docker Sharing / Publication Notes

This repository is prepared for easy sharing:
- Docker-first startup path is documented and stable
- local AI model is auto-pulled on first run
- fallback behavior keeps app usable during AI warm-up
- persistent volumes are defined for DB and Ollama data
- `.dockerignore` is included to keep build context clean
