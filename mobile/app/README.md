## Homeflow Mobile App

This directory now contains the Flutter app implementation for the Homeflow mobile companion through Phase 5.

Included in this phase:

- Flutter package manifest and lint config
- app bootstrap and route shell
- connection, auth, sync, and cache architecture
- local and secure storage abstractions
- V1 screens for login, today, upcoming, task detail, and settings
- offline/stale/auth-required sync messaging
- exported read-only widget snapshot state derived from the cached Today view

Current limitation:

- native platform folders are not generated in this workspace because `flutter create` was not run here
- the widget's shared data contract is implemented in Flutter, but the actual Android/iPhone widget host code still depends on generating the native platform projects first

When you are ready to turn this into a runnable Flutter project with Android and iPhone platform folders, run:

```bash
flutter create --platforms=android,ios .
```

Then keep the generated native folders and preserve the existing `lib/` code from this repo.
