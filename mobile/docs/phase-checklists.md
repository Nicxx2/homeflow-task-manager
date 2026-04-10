# Phase Checklists

## How To Use This

Before closing any implementation phase, run through the matching checklist and confirm there are no known gaps.

If any item fails, the phase should remain open until the issue is fixed or explicitly deferred.

## Phase 1: Backend Contract

- mobile endpoints return JSON only
- endpoint behavior is scoped to the authenticated user correctly
- today and window queries return stable ordering
- task payload includes status, dates, assignee, and update timestamp
- status update route does not require full task replacement
- auth failures and validation failures are distinguishable

## Phase 2: App Skeleton

- server settings persist correctly
- token is in secure storage, not plain local storage
- logout clears auth and user-specific cache
- sync coordinator has one clear source of truth
- failed refresh does not wipe valid cache

## Phase 3: Screens

- login screen handles bad host, bad port, bad auth, and success
- today screen prioritizes active tasks
- upcoming screen distinguishes uncached future days from empty days
- task detail reflects the same status and sync state as list screens
- settings screen exposes the actual cache window and last sync state

## Phase 4: Offline Reliability

- no network and bad server address are not shown as the same state unless intentionally collapsed
- stale cached data is labeled
- auth required state is labeled
- server error state is labeled
- user can still read previously synced tasks when refresh fails

## Phase 5: Widget

- widget reads from local cache
- widget does not require the app to be open
- widget shows a stale or refreshed state
- widget opens into the correct app destination
- widget handles zero tasks and logged-out state cleanly

## Phase 6: Internal Release

- Android test build installs cleanly
- iPhone TestFlight build installs cleanly
- tester instructions explain self-hosted connection expectations
- at least one tester validated sync, offline read, and status update
