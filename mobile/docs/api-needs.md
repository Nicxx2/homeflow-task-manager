# Mobile API Notes

## Current Backend Shape

The current backend exposes JSON routes under `/api/v1` and a top-level health endpoint at `/health`.

Current relevant routes already in the repo:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/register` when public registration is enabled
- `GET /api/v1/tasks`
- `GET /api/v1/tasks/{task_id}`
- `PUT /api/v1/tasks/{task_id}`
- `POST /api/v1/tasks/{task_id}/assign`
- `GET /health`

Notes:

- the mobile app currently uses sign-in with an existing account rather than an in-app registration flow
- public registration can be disabled by an admin, so mobile clients should not assume self-signup is available on every server

Current auth response:

- bearer token returned by `POST /api/v1/auth/login`

Current task payload already includes:

- `id`
- `title`
- `description`
- `due_date`
- `assignment_date`
- `assignee_id`
- `created_by_id`
- `effort_level`
- `points_value`
- `status`
- recurrence metadata

Current status values:

- `pending`
- `in_progress`
- `completed`

## Fit For Mobile Today

The current API is a usable starting point for mobile login and generic task fetches, but it is not yet shaped around the main mobile workflow.

Main gaps for the mobile companion:

- no dedicated "my tasks for today" endpoint
- no dedicated "my upcoming tasks for next X days" endpoint
- no lightweight status-only update route
- no token refresh route
- no mobile-focused sync envelope with server timestamp and filtered window metadata
- current task listing logic is not clearly aligned with "assigned to the logged-in user" day views

## Recommended Mobile-Oriented Endpoints

### Authentication

Required:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout` if server-side token invalidation is introduced

Optional:

- `POST /api/v1/auth/register` only if the product later exposes self-service signup in mobile

Recommended login response fields:

- `access_token`
- `token_type`
- `expires_at`
- `user`

Recommended user summary fields:

- `id`
- `email`
- `full_name`
- `is_admin`

### Server Reachability

Useful:

- `GET /health`
- optional `GET /api/v1/mobile/health`

Recommended mobile health payload:

- `status`
- `server_time`
- `api_version`
- `auth_required`

### Task Sync

Recommended:

- `GET /api/v1/mobile/tasks/today`
- `GET /api/v1/mobile/tasks/upcoming?days=7`
- `GET /api/v1/mobile/tasks/window?start=YYYY-MM-DD&end=YYYY-MM-DD`
- `GET /api/v1/mobile/tasks/{task_id}`

The `window` endpoint is the most flexible option for the app because it matches the offline cache design directly.

Recommended query rules:

- server returns only tasks relevant to the authenticated user
- completed items may still be returned, but flagged clearly and ordered after actionable items
- ordering should match the intended day workflow, not just raw due date sorting

### Status Update

Recommended:

- `PATCH /api/v1/mobile/tasks/{task_id}/status`

Suggested request body:

```json
{
  "status": "completed"
}
```

This is better for the mobile app than sending full task objects just to change one field.

## Recommended Task Payload For Mobile

Minimum useful fields:

- `id`
- `title`
- `description`
- `status`
- `due_date`
- `assignment_date`
- `assignee_id`
- `effort_level`
- `points_value`
- `is_overdue`
- `is_completed`
- `updated_at`

Helpful extras:

- `display_bucket` such as `overdue`, `today`, `upcoming`, `completed`
- `sort_key`
- `recurrence_summary`

## Recommended Sync Envelope

Instead of returning only a plain task array, the mobile endpoints would benefit from a sync envelope such as:

```json
{
  "server_time": "2026-04-10T08:12:00Z",
  "window_start": "2026-04-09",
  "window_end": "2026-04-17",
  "tasks": []
}
```

Why this helps:

- app can show a precise last successful sync time
- app can explain what date window is cached
- widget refreshes can reuse the same server data contract

## Error Handling Expectations

The mobile app should distinguish these cases cleanly:

- no internet or no network
- hostname or IP cannot be reached
- server reachable but login failed
- server reachable but token expired
- server responded with 4xx validation error
- server responded with 5xx error

Recommended error response fields:

- `detail`
- `code`
- `retryable`

## Backend Follow-Up

For the mobile companion, the preferred backend direction is to add dedicated mobile-oriented JSON routes rather than making the app interpret desktop web behavior or scrape HTML.
