# Mobile Implementation Spec

## Purpose

This document turns the product brief into an implementation-facing spec for the first mobile release.

The goal is to define:

- the recommended technical approach
- the app architecture
- the screen-level behavior
- the sync and offline model
- the backend work needed before the mobile client can be considered correct

## Recommended Technical Direction

Recommended stack for V1:

- Flutter
- Dart
- one shared codebase for Android and iPhone

Reasoning:

- this is a mobile-first product, not a web-and-mobile shared UI project
- consistent Android and iPhone behavior matters more than code sharing with the current HTMX web app
- Flutter is a strong fit for a compact, performance-sensitive day view with predictable offline UI
- local storage, secure storage, and widget integration are straightforward enough for a narrow V1
- the project currently has no existing React or React Native client that would justify defaulting to that ecosystem

## Architecture Summary

### Client Layers

- presentation layer for screens, widgets, and shared components
- application layer for auth, sync orchestration, and task actions
- data layer for API client, secure auth storage, and local task cache

### Core Mobile Modules

- `connection`
- `auth`
- `tasks`
- `sync`
- `settings`
- `widget_bridge`

### State Boundaries

- connection state
- auth state
- sync state
- task cache state

The app should not treat "offline" and "empty" as the same state.

## Required App Capabilities

### Connection

The app must support:

- server hostname or IP
- port
- HTTP or HTTPS selection
- a derived base URL preview before login

Recommended stored connection shape:

```json
{
  "scheme": "http",
  "host": "192.168.1.12",
  "port": 8000
}
```

Derived base URL example:

```text
http://192.168.1.12:8000
```

### Authentication

The app must:

- log in with email and password
- store the returned token in secure storage
- avoid storing the raw password by default
- clear token and user-specific cache on logout

The app should be ready for either:

- a simple login-only token flow for V1
- a future access-token plus refresh-token flow

### Task Data

The mobile client should focus on tasks relevant to the logged-in user.

V1 views should be based on:

- today
- upcoming
- task detail

V1 writes should be limited to:

- update task status

## Screen Spec

### Connection / Login

Purpose:

- connect the app to a user-managed Homeflow server
- authenticate the user

Fields:

- hostname or IP
- port
- HTTP or HTTPS
- email
- password

Actions:

- sign in
- test connection

Required states:

- idle
- connecting
- invalid server input
- server unreachable
- auth failed
- login succeeded

Validation rules:

- host must not be empty
- port must be numeric and in valid range
- email must be valid
- password must not be empty

### Today

Purpose:

- open directly into the most useful daily view

Content:

- today's assigned tasks
- visible sync status
- last successful sync time

Behavior:

- actionable tasks first
- completed tasks visible in a lower-priority section or after active items
- pull to refresh
- tap into task detail
- fast status changes without leaving the screen where reasonable

### Upcoming

Purpose:

- show the next cached days in a clear rolling window

Content:

- grouped day sections
- empty-state messages
- stale-cache messaging where needed

Behavior:

- do not imply server-confirmed emptiness for uncached future days
- clearly show when a day is outside the available cache window

### Task Detail

Purpose:

- show the full task content and allow status changes safely

Content:

- title
- description
- status
- due date
- assignment date
- effort level
- recurrence summary if present
- sync state if task data is cached

Actions:

- set pending
- set in progress
- set completed

### Settings / Sync

Purpose:

- expose connection, cache, and sync behavior without clutter

Content:

- current server URL
- signed-in email
- offline task window
- auto-refresh on app open
- manual refresh
- last sync status
- clear cached data
- logout

## Data Model Expectations

### Remote Task Fields Needed By Mobile

- `id`
- `title`
- `description`
- `status`
- `due_date`
- `assignment_date`
- `assignee_id`
- `effort_level`
- `points_value`
- `updated_at`

Useful server-derived helpers:

- `is_overdue`
- `is_completed`
- `display_bucket`
- `sort_key`

### Local Cache Model

Minimum local record shape:

```json
{
  "server_base_url": "http://192.168.1.12:8000",
  "user_email": "user@example.com",
  "window_start": "2026-04-09",
  "window_end": "2026-04-17",
  "last_successful_sync_at": "2026-04-10T08:12:00Z",
  "last_sync_result": "success",
  "tasks": []
}
```

The exact storage schema can differ, but the data model must preserve those concepts.

## Sync Rules

The sync coordinator should:

- build the active cache window from settings
- request the full window from the server
- replace or merge cached task rows deterministically
- keep the previous cache on failed refresh
- expose sync state to both screens and widget code

The app should not:

- clear valid cache just because one refresh failed
- show stale data without a label
- fabricate empty future days

## Ordering Rules

The mobile app should define explicit task ordering so "today" feels stable and logical.

Recommended order:

1. overdue active tasks relevant to today
2. today's in-progress tasks
3. today's pending tasks
4. today's completed tasks

Within each bucket:

- earlier assignment date first when present
- then due date
- then most recently updated as a stable tie-breaker

The backend should ideally provide a stable sort order or enough fields for the client to reproduce it consistently.

## Backend Requirements Before Mobile UI Can Be Considered Correct

The mobile app should not be built around the current generic task routes alone.

Backend work needed first or in parallel:

- define mobile-oriented read endpoints for today and windowed upcoming tasks
- ensure returned tasks are scoped to the authenticated user's mobile views
- add a status-only update endpoint
- add `updated_at` to task responses if missing
- provide predictable error payloads

Important current gap:

- the existing `GET /api/v1/tasks` route is not a safe final contract for the mobile companion because its visibility and filtering do not cleanly represent "my assigned mobile tasks"

## Testing Expectations

Each implementation phase should include:

- backend API verification
- app-level state verification
- offline and retry verification
- regression checks for stale or missing-cache cases

Detailed phase gates are defined in `phased-plan.md`.
