# Mobile Phased Plan

## Delivery Strategy

Build the mobile companion in controlled phases.

Each phase must have:

- clear scope
- dependencies listed up front
- exit criteria
- verification checks

The goal is to avoid a common failure mode where screens exist before the API contract, offline model, and error states are actually reliable.

## Phase 0: Decision And Contract Baseline

### Objective

Lock the technical direction and remove ambiguity before coding the app.

### Deliverables

- approve Flutter as the V1 mobile stack
- approve the mobile data contract and screen scope
- confirm the offline cache window defaults
- confirm widget is read-only in V1

### Dependencies

- current mobile docs reviewed
- backend owner agrees on mobile-oriented endpoints

### Risks To Resolve

- uncertainty over whether the mobile app should use current generic task endpoints
- uncertainty over whether token refresh is required for V1
- uncertainty over how "today" ordering is defined

### Exit Criteria

- the implementation spec is accepted as the build baseline
- the mobile API contract is agreed in principle
- no open disagreement remains about V1 scope

### Verification Checklist

- is the chosen app stack explicit
- is the API approach explicit
- is offline behavior explicit
- are non-goals explicit

## Phase 1: Backend Mobile Contract

### Objective

Create a backend contract that is safe for the mobile client to depend on.

### Deliverables

- mobile-oriented task read endpoints
- status-only task update endpoint
- predictable error payloads
- task payload includes fields required for mobile ordering and sync
- health or lightweight reachability behavior confirmed

### Recommended API Scope

- `POST /api/v1/auth/login`
- `GET /health`
- `GET /api/v1/mobile/tasks/today`
- `GET /api/v1/mobile/tasks/window?start=YYYY-MM-DD&end=YYYY-MM-DD`
- `GET /api/v1/mobile/tasks/{task_id}`
- `PATCH /api/v1/mobile/tasks/{task_id}/status`

### Dependencies

- phase 0 contract approval

### Risks

- returning created tasks instead of assigned tasks
- inconsistent recurrence behavior across day views
- missing `updated_at` or missing sort fields
- errors that are not specific enough for the mobile app to message correctly

### Exit Criteria

- mobile client can fetch and update tasks without using web-specific behavior
- authenticated task responses reflect the intended logged-in user scope
- server errors can be mapped to user-visible app states

### Verification Checklist

- test login success and invalid credentials
- test inactive, pending-approval, and expired-session cases if applicable
- test task window filtering for the logged-in user
- test today ordering
- test status update success and invalid transition handling
- test unreachable-server and server-error behaviors separately

## Phase 2: Mobile App Skeleton

### Objective

Create the application shell and core infrastructure before feature polish.

### Deliverables

- Flutter project bootstrap in `mobile/app/`
- environment-independent API client
- secure token storage
- local cache layer
- sync coordinator
- routing and top-level app state

### Dependencies

- phase 1 backend contract stable enough for development

### Risks

- coupling UI directly to raw network calls
- mixing secure auth storage with general cached task storage
- lacking a single source of truth for sync state

### Exit Criteria

- app can store server settings
- app can log in
- app can persist token securely
- app can fetch and cache task window data
- app can reopen into a coherent signed-in or signed-out state

### Verification Checklist

- cold launch without configuration
- sign-in and app restart
- logout clears token and account-specific cache
- network success updates cache
- network failure preserves cache

## Phase 3: V1 Screens

### Objective

Build the user-facing screens on top of the stable app shell.

### Deliverables

- Connection / Login screen
- Today screen
- Upcoming screen
- Task Detail screen
- Settings / Sync screen

### Dependencies

- phase 2 core infrastructure complete

### Risks

- confusing sync state labels
- completed tasks crowding active tasks
- task detail showing stale data without disclosure

### Exit Criteria

- each V1 screen is navigable and functional
- today view is fast and clear
- upcoming reflects the configured cache window
- status changes work from app screens

### Verification Checklist

- first-run sign-in flow
- invalid server address flow
- today view with active and completed tasks
- upcoming view with cached and uncached days
- task detail status change round-trip
- settings change updates sync behavior correctly

## Phase 4: Offline Reliability

### Objective

Harden the app so offline and partial-failure cases are correct rather than merely tolerated.

### Deliverables

- stale-cache labeling
- per-state empty messaging
- retry behavior
- re-auth required handling
- local cache boundary handling for future days

### Dependencies

- phase 3 screens complete

### Risks

- "no data" and "no cache" being conflated
- failed refresh wiping valid state
- auth failures shown as generic network failures

### Exit Criteria

- app behaves honestly when the server cannot be reached
- app behaves honestly when cached data exists but is stale
- uncached future days are explained correctly

### Verification Checklist

- no network
- server DNS or IP unreachable
- server online but auth rejected
- server online but 500 error
- stale cache older than expected
- future day outside cache window

## Phase 5: Widget V1

### Objective

Add a simple read-only home screen widget that mirrors the app's cached day view.

### Deliverables

- Android widget
- iPhone widget if feasible within the same release train
- shared widget data source from local cache
- widget tap-through into Today screen

### Dependencies

- phase 4 offline model stable

### Risks

- widget showing stale data without context
- widget depending on live network refresh to remain useful
- platform-specific widget differences expanding scope

### Exit Criteria

- widget displays today's top items or count
- widget reflects last refresh or stale state
- tapping widget opens the app consistently

### Verification Checklist

- widget after fresh sync
- widget while offline
- widget after logout
- widget after cache clear
- widget with zero tasks for today

## Phase 6: Internal Test Release

### Objective

Prepare the app for controlled external testing.

### Deliverables

- signed Android test build
- iPhone TestFlight build
- brief tester setup instructions
- issue list for connection, auth, sync, and offline failures

### Dependencies

- phase 5 complete or intentionally deferred if widget slips

### Risks

- testers not understanding self-hosted connection requirements
- LAN-only users failing to connect when away from home
- HTTPS certificate or local-network edge cases surfacing late

### Exit Criteria

- at least one successful Android install from a tester flow
- at least one successful iPhone install from a tester flow
- tester setup instructions are clear enough to connect without developer intervention for common cases

### Verification Checklist

- first-run setup on a clean device
- login against local server
- login against VPN or Tailscale endpoint if available
- offline launch after successful sync
- status update from device to server and back

## Cross-Phase Gap Checks

These checks should be repeated at the end of every phase:

- does the current work still match the V1 scope
- did any new dependency get introduced without being written down
- are offline and error states still explicit
- are auth and cache boundaries still correct
- are there any platform-specific assumptions that only hold on Android or only on iPhone

## Recommended Build Order

1. finish phase 0 approval
2. build phase 1 backend contract
3. build phase 2 mobile shell
4. build phase 3 screens
5. harden phase 4 offline behavior
6. add phase 5 widget
7. release through phase 6 internal testing

This order keeps the project honest. The widget and polish only happen after the app has a correct sync and offline core.
