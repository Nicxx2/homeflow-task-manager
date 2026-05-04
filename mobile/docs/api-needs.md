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
- `GET /api/v1/mobile/tasks/today`
- `GET /api/v1/mobile/tasks/window?start=YYYY-MM-DD&end=YYYY-MM-DD`
- `GET /api/v1/mobile/tasks/{task_id}`
- `PATCH /api/v1/mobile/tasks/{task_id}/status`
- `GET /api/v1/mobile/tasks/{task_id}/schedule/check?assignment_date=YYYY-MM-DD`
- `GET /api/v1/mobile/tasks/{task_id}/schedule/next-available?start_date=YYYY-MM-DD`
- `PATCH /api/v1/mobile/tasks/{task_id}/schedule`
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

The dedicated mobile routes are the preferred contract for the companion app. They keep the mobile client scoped to the signed-in user's day views instead of relying on generic task routes or web behavior.

Remaining gaps to consider later:

- no token refresh route
- no server-side token invalidation/logout route
- no public mobile registration flow, by design for now

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
- completed items should belong to the assignment date, not reappear later because the due date arrives
- tasks assigned today with a past due date should remain in Today and expose an overdue indicator

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

### Schedule Update

Current:

- `GET /api/v1/mobile/tasks/{task_id}/schedule/check?assignment_date=YYYY-MM-DD`
- `GET /api/v1/mobile/tasks/{task_id}/schedule/next-available?start_date=YYYY-MM-DD`
- `PATCH /api/v1/mobile/tasks/{task_id}/schedule`

Suggested schedule update body:

```json
{
  "due_date": "2026-05-04",
  "assignment_date": "2026-05-04",
  "extend_capacity": false
}
```

Rules:

- due date can be today, future, or past
- assignment date can only be today or future
- assignment date changes must be validated by the backend
- capacity extension must be explicit and only applies to the signed-in user's selected assignment day

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
