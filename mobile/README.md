## Mobile Area

This directory holds the Homeflow mobile companion app and its supporting docs.

The mobile app is for users who run their own self-hosted Homeflow server. It is not a shared hosted backend.

Current structure:

- `app/` Flutter mobile app source
- `docs/` product, API, offline sync, widget, implementation, and delivery notes

Recommended reading order:

1. `docs/product-brief.md`
2. `docs/implementation-spec.md`
3. `app/README.md`

Current mobile scope:

- secure sign-in to the user's own server
- sign-in assumes an existing approved account on that server
- saved login and session restoration on app reopen
- today-first task workflow with active, overdue, and completed sections
- upcoming task view
- task detail, quick status changes, and online date adjustment
- backend capacity checks for assignment-date changes
- optional capacity extension when the signed-in user chooses to take on extra work
- rolling offline cache window
- offline status-change queueing, sync, and stale-cache messaging
- Android daily reminder notifications backed by cached tasks
- notification preference persistence across app restarts
- improved auth/status handling on refresh and app resume
- Android support included in this repo

To build the Android app locally, go to `app/` and follow the commands in `app/README.md`.
