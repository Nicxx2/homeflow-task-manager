# homeflow-task-manager

Plan tasks without overload. Built-in workload limits keep your plans realistic.

---

## What this is

A task manager for households and small teams.

It is designed to help people plan work realistically instead of just stacking tasks onto a list.

---

## Why this exists

Most task apps let you assign unlimited work to one day.

That can be difficult to keep up with in real life, so this app helps you stay balanced.

It is designed to help you plan more realistically.


**Example:**

You assign 3 high-effort tasks to one day<br>
→ The app will not allow it<br>
→ It suggests the next available day automatically

---

## Key features

- Create tasks first, assign later  
- Effort-based planning system  
- Daily workload protection  
- Automatic next-available-day suggestions when a day is overloaded  
- Automatic effort suggestions using local AI  
- Safe fallback rules when AI is unavailable  
- Account registration with admin approval  
- Admin controls for users, visibility, capacity, and AI settings  
- Quick status updates from task lists and day view  
- Built-in app assistant for task and workload queries  
- Clean and simple UI  

---

## AI

- Runs locally with Ollama  
- No external AI API required  
- Works offline after setup  
- Automatically falls back to rules if AI is unavailable  
- Includes an in-app assistant for task and workload help  

---

## Built-in assistant

The app includes a small built-in AI chat for app-specific help.

**Examples:**

- List low tasks  
- Show tasks due today  
- Show unassigned tasks due today  
- Show tasks assigned to me today  
- Who has the most capacity left?  
- Add me to a low task available  

The assistant is bounded to app-related actions only and uses explicit confirmation for self-assignment actions.

---

## Docker image

Docker Hub image:

`nicxx2/homeflow-task-manager:latest`

---

## How to run with Docker Compose

Use the following docker-compose.yml:

```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: stm-db
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-task_mgmt}
      POSTGRES_USER: ${POSTGRES_USER:-task_user}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-task_pass}
    ports:
      - "${POSTGRES_EXPOSE_PORT:-5432}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-task_user} -d ${POSTGRES_DB:-task_mgmt}"]
      interval: 5s
      timeout: 5s
      retries: 10

  ollama:
    image: ollama/ollama:latest
    container_name: stm-ollama
    volumes:
      - ollama_data:/root/.ollama
    healthcheck:
      test: ["CMD-SHELL", "ollama list > /dev/null 2>&1 || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 30

  ollama-init:
    image: curlimages/curl:8.10.1
    container_name: stm-ollama-init
    depends_on:
      ollama:
        condition: service_healthy
    entrypoint: ["/bin/sh", "-ec"]
    command: >
      "echo 'Waiting for Ollama API...' &&
       until curl -fsS http://ollama:11434/api/tags > /dev/null; do sleep 2; done &&
       echo 'Pulling model: ${OLLAMA_DEFAULT_MODEL:-qwen2.5:1.5b}' &&
       curl -fsS -X POST http://ollama:11434/api/pull -H 'Content-Type: application/json' -d '{\"name\":\"${OLLAMA_DEFAULT_MODEL:-qwen2.5:1.5b}\",\"stream\":false}' > /dev/null &&
       echo 'Model ready: ${OLLAMA_DEFAULT_MODEL:-qwen2.5:1.5b}'"
    restart: "no"

  backend:
    image: nicxx2/homeflow-task-manager:latest
    container_name: stm-backend
    environment:
      APP_NAME: ${APP_NAME:-Simple Task Management}
      APP_ENV: ${APP_ENV:-development}
      SECRET_KEY: ${SECRET_KEY:-change-me-in-production}
      ACCESS_TOKEN_EXPIRE_MINUTES: ${ACCESS_TOKEN_EXPIRE_MINUTES:-60}
      JWT_ALGORITHM: ${JWT_ALGORITHM:-HS256}
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-task_user}:${POSTGRES_PASSWORD:-task_pass}@db:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-task_mgmt}
      OLLAMA_BASE_URL: ${OLLAMA_BASE_URL:-http://ollama:11434}
      OLLAMA_DEFAULT_MODEL: ${OLLAMA_DEFAULT_MODEL:-qwen2.5:1.5b}
      AI_DEFAULT_TIMEOUT_SECONDS: ${AI_DEFAULT_TIMEOUT_SECONDS:-8}
      SESSION_IDLE_TIMEOUT_MINUTES: ${SESSION_IDLE_TIMEOUT_MINUTES:-15}
      INITIAL_ADMIN_EMAIL: ${INITIAL_ADMIN_EMAIL:-admin@example.com}
      INITIAL_ADMIN_PASSWORD: ${INITIAL_ADMIN_PASSWORD:-admin1234}
    ports:
      - "${APP_PORT:-8000}:8000"
    depends_on:
      db:
        condition: service_healthy
    command: >
      sh -c "alembic upgrade head &&
             uvicorn backend.app.main:app --host 0.0.0.0 --port 8000"

volumes:
  postgres_data:
  ollama_data:
```

Then run:

```bash
docker compose up -d
```

Open:

http://localhost:8000

---

## Default admin login

On a fresh database, the default admin is:

- Email: admin@example.com  
- Password: admin1234  

---

## Recommended changes to docker-compose file before real use

Update these values before production use:

- INITIAL_ADMIN_EMAIL  
- INITIAL_ADMIN_PASSWORD  
- SECRET_KEY  

---

## First startup

On first run:

- Database is created automatically  
- Migrations are applied automatically  
- The default admin account is created automatically  
- Ollama starts and downloads the configured model  
- The app is usable while AI finishes getting ready  
- AI features will use fallback rules until the model is ready  

---

## What is included

- PostgreSQL database  
- FastAPI backend and web UI  
- Ollama for local AI  
- Automatic model download  
- Persistent storage for app data and models  

---

## Who this is for

- Personal task organisation  
- Couples sharing responsibilities  
- Small teams  
- People who want realistic workload planning  
- Developers who want a clean FastAPI project  

---

## Tech stack

- FastAPI  
- PostgreSQL  
- HTMX  
- Tailwind CSS  
- Ollama  
- Docker Compose  

---

## Version

v1 (MVP)

Focused on:

- clear task flow  
- realistic workload management  
- simple and reliable behaviour  

---

## Summary

This is not just a task list.

It is a practical system to help you:

- avoid overload  
- plan properly  
- stay consistent day by day  
