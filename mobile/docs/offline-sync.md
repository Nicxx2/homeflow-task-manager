# Offline Sync Plan

## Goal

Keep the app useful when the Homeflow server cannot be reached, without turning V1 into a heavy offline-first system.

The mobile app should cache a practical rolling window of relevant task data for the logged-in user and display that cache honestly when live refresh is not possible.

## Cache Window

Default recommendation:

- yesterday
- today
- the next 7 to 14 days

Recommended user setting:

- `Offline task window`

Suggested options:

- 3 days
- 7 days
- 14 days
- 30 days

## Cache Rules

- cache only days that actually contain relevant task data
- do not pre-cache empty distant future windows indefinitely
- keep a rolling window instead of trying to cache years of data
- replace or update cached records on successful refresh
- preserve the previous cache if a later sync attempt fails

## Refresh Behavior

When server is reachable:

- authenticate using the stored token
- sync any pending offline status changes first when possible
- refresh the whole selected cache window
- update local storage
- update last successful sync time
- update last sync status to success

When server is unreachable:

- keep showing cached task data
- do not clear the current local cache
- mark the current view as cached or stale
- record the failed sync attempt and reason if known

When auth fails:

- keep cached data visible if available
- show that re-authentication is required
- do not pretend the data is current

## Stale Data Rules

The UI should always make it clear whether the data is current or cached from a previous sync.

Recommended state labels:

- fresh
- cached
- stale
- auth required
- server error

Practical rule of thumb:

- if the current view comes from local storage because refresh failed, show it as cached
- if the last sync is older than the normal app-open refresh expectation, show it as stale

## Empty Future Days

If the user opens a day outside the cached window or a day that has never been synced successfully, the app should not imply the server confirmed there are no tasks.

Use an explicit message instead:

- no cached tasks available for this day yet

This is important because "no tasks" and "no cached data" are different states.

## Local Storage Expectations

Minimum local data to store:

- auth token in secure storage
- server connection settings
- cached task records for the selected window
- pending status changes that were made while offline
- last successful sync timestamp
- last sync result
- the configured offline cache window

Task cache should be keyed by:

- account
- server base URL
- date window

This avoids cross-contaminating data if the user changes server settings or logs into a different server.

## Offline Write Scope

Status changes can be queued while offline because they are small, user-owned actions that can be retried safely when the server is reachable again.

Schedule and capacity changes should stay online-only:

- due date edits need the latest server task state
- assignment date edits need backend date validation
- capacity checks and capacity extension need live server confirmation
- failed schedule saves should leave the cached task unchanged and show a clear error

## Messaging Examples

- Showing cached tasks from your last sync.
- Can't reach your Homeflow server right now.
- Last synced today at 08:12.
- No cached tasks available for tomorrow yet.
- You appear to be away from your server or local network.

## Sync Triggers For V1

- app open
- pull to refresh
- manual refresh from Settings
- widget refresh when supported by platform limits
- returning online after pending status changes exist

Auto-refresh should be conservative in V1. Reliability and clarity matter more than aggressive background sync behavior.
