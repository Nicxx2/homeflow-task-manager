![Sponsored OSS](https://img.shields.io/badge/Sponsored-OSS-8a3af8?logo=github-sponsors&logoColor=white)

![Docker Pulls](https://img.shields.io/docker/pulls/nicxx2/homeflow-task-manager)

![License](https://img.shields.io/github/license/Nicxx2/homeflow-task-manager)


---
## 💖 Support This Project

If you found this helpful and want to support what I do, you can leave a tip here — thank you so much!

[![Support on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/nicxx2)

---
# homeflow-task-manager

Plan tasks without overload. Built-in workload limits, smart scheduling, recurring task handling, and personal customization keep plans realistic and easier to follow.

---

## What this is

A task manager for households and small teams.

It is designed to help people plan work realistically instead of just stacking tasks onto a list.

Version 2 expands the original workload-focused idea with smarter assignment, better recurring tasks, cleaner views, and personal UI customization for each user.

Version 2.1 keeps that same foundation and adds a mobile companion app plus a cleaner day-to-day workflow on the web app.

---

## Why this exists

Most task apps let you assign unlimited work to one day.

That can be difficult to keep up with in real life, so this app helps you stay balanced, plan realistically, and keep the app simple enough to use every day.

**Example:**

You assign 3 high-effort tasks to one day  
-> The app will not allow it  
-> It suggests the next available day automatically

If someone is away or has blocked days  
-> The app skips those dates  
-> It suggests the next valid day instead

---

## ✨What is new in v2.2

- Improved the task detail view with a cleaner, more minimal layout.
- Kept the task title and description visible first for faster reading.
- Moved extra task information into expandable sections to reduce clutter.
- Kept assignment controls visible for quicker task management.
- Added a safer delete flow with a themed confirmation popup.
- Limited task deletion to the task creator or admins only.
- Added clear delete guidance so users know who to contact for removal.
- Improved recurring task deletion options:
  - Delete just this occurrence.
  - Delete the whole recurring task.
- Preserved completed recurring history when removing future recurrence.
- Improved assignment date handling:
  - Defaults to today for first-time assignment.
  - Keeps the saved assignment date for already assigned tasks.
  - Supports due date and next available day shortcuts.
- Updated visible wording from `color` to `colour`.

---

## v2.1

- Mobile companion app for self-hosted Homeflow servers
- Android app included in this repo under `mobile/app`
- Mobile sign-in, today view, upcoming view, task status updates, offline cache, and sync status handling
- Mobile secure saved login so users stay signed in until logout
- Mobile theme mode with remembered preference
- Simpler dashboard focused on what matters most
- Interactive dashboard panels for `Unassigned` and `My active tasks`
- Cleaner Tasks page with one active category view instead of showing everything at once
- Better `Just mine` and `Everyone` workflow
- Better return flow after editing tasks so users go back to the task view they were already using
- Per-user task category button appearance controls

---

## v2

- Smarter assignment with automatic next-best-day suggestions
- User away periods and weekday availability preferences
- Cleaner recurring tasks with one active recurring task instead of cluttering the list with many future copies
- Recurring tasks can skip blocked dates or move within the same week, then return to the normal schedule
- Better overdue handling and task prioritization
- Cleaner dashboard with expandable sections and stronger focus on today's workload
- Task list grouped into clearer buckets such as overdue, upcoming, unassigned, in progress, and completed
- Personal appearance settings for each user
- Personal task highlighting and custom state colors without affecting other users

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
- User away periods and blocked weekdays
- Recurring task support with cleaner rollover logic
- Personal appearance and task highlighting
- Clean and simple UI
- Mobile companion app for Android

---

## Smart scheduling

Version 2 improves planning so the app can work with real-life availability.

It can now:

- avoid assigning work on days a user has blocked
- avoid away periods automatically
- suggest the next valid day with enough capacity
- prevent assignment to past dates
- allow controlled force-assign only when logically allowed

This keeps the schedule practical without removing flexibility.

---

## Recurring tasks

Recurring tasks are handled in a cleaner way in v2.

Instead of creating many future task copies and cluttering the task list, the app keeps one active recurring task visible.

When it is completed:

- that occurrence is recorded in history
- the recurring series continues
- the next active occurrence is prepared
- blocked dates can be skipped or moved based on the chosen rule
- future occurrences return to the normal recurring schedule

This keeps recurring tasks predictable without overwhelming the interface.

---

## Personal customization

Each user can personalize their own experience without affecting anyone else.

Users can customize:

- theme
- accent color
- overdue task color
- recurring task color
- unassigned task color
- in-progress task color
- density and surface style
- subtle decorative style
- personal highlight colors for specific tasks
- task category button colors on the Tasks page

These changes are personal only. One user's customization does not change how the app looks for other users.

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

## Mobile companion app

Version 2.1 includes a mobile companion app for users running their own Homeflow server.

The mobile app is not a shared cloud product. Each user connects it to their own self-hosted Homeflow backend.

Current mobile scope:

- secure sign-in to the user's own server
- today's tasks first
- upcoming assigned tasks
- task detail and fast status changes
- rolling offline cache window
- clear sync, stale-cache, and auth-required states
- Android support in this repo

The mobile project is included here:

- `mobile/app/`
- `mobile/docs/`

Typical Android development commands:

```bash
cd mobile/app
flutter pub get
flutter analyze
flutter test
flutter build apk --debug
```

---

## Docker Hub Repository

👉[https://hub.docker.com/r/nicxx2/homeflow-task-manager](https://hub.docker.com/r/nicxx2/homeflow-task-manager)

---

## How to run with Docker Compose

Use the following `docker-compose.yml`:

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

```text
http://localhost:8000
```

---

## Default admin login

On a fresh database, the default admin is:

- Email: admin@example.com
- Password: admin1234

---

## Recommended changes before real use

Update these values before production use:

- `INITIAL_ADMIN_EMAIL`
- `INITIAL_ADMIN_PASSWORD`
- `SECRET_KEY`

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
- Flutter Android/mobile companion app source in this repo

---

## Who this is for

- Personal task organisation
- Couples sharing responsibilities
- Small teams
- People who want realistic workload planning
- Developers who want a clean FastAPI project
- Self-hosters who want both web and mobile access

---

## Tech stack

- FastAPI
- PostgreSQL
- HTMX
- Tailwind CSS
- Ollama
- Docker Compose
- Flutter

---

## Summary

This is not just a task list.

It is a practical system to help you:

- avoid overload
- plan properly
- stay consistent day by day
- handle recurring responsibilities cleanly
- keep the app personal without making it cluttered
- use the same self-hosted system on the web and on Android
