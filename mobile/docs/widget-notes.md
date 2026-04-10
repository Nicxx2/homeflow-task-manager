# Widget Notes

## V1 Widget Scope

Keep the widget simple and read-first.

Recommended V1 behavior:

- show today's tasks
- show a count or top few items
- show sync state or last refresh time
- open the app when tapped

## Why Keep It Simple

The widget is useful when it gives fast visibility with low failure risk.

Keeping status changes inside the app for V1 avoids:

- auth edge cases inside the widget
- confusing partial failures
- stale action states
- platform-specific complexity for Android and iPhone widget interactions

## V1 Display Priorities

- today's outstanding task count
- next one to three task titles
- cached or sync state indicator
- tap target into the Today screen

## Data Source

The widget should read from the app's local cache rather than depending on a live server call for every display.

That means:

- widget can still show useful information when offline
- widget state matches the app's cached/stale messaging
- server failures do not blank the widget unnecessarily

Current app-side implementation:

- export a single "today widget snapshot" from the Flutter app after initialize, refresh, status change, cache clear, and logout
- keep the widget snapshot read-only and derived from the same cache/session state the app already trusts
- include signed-out, no-cache, ready, stale, auth-required, empty, and error states in the exported payload

Current platform limitation:

- actual Android/iPhone widget host code should be added only after the Flutter `android/` and `ios/` folders are generated in the repo
- until those platform folders exist, the stable part to implement safely is the shared widget data contract rather than guessed native project files

## Refresh Expectations

Widget refresh should:

- use the latest successful app cache when available
- attempt a refresh only within platform constraints
- show last refresh or stale state when live sync is not possible

## V1 Non-Goals

- mark complete from widget
- quick inline status actions
- deep task interactions
- editing task details
- admin actions

## Later Enhancement Ideas

- mark complete from widget
- quick start in-progress
- configurable widget size modes
- separate widgets for today and upcoming
- richer overdue indicators
