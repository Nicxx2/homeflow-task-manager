## Homeflow Mobile App

This directory contains the Flutter mobile companion app for Homeflow.

Current implementation includes:

- connection and login flow for self-hosted Homeflow servers
- secure session storage and saved login support
- today, upcoming, task detail, and settings screens
- local cache and offline sync handling
- Android widget snapshot support
- Android project files in `android/`

## What You Need

To build the Android app locally, you need:

- Flutter SDK
- Android SDK / Android Studio
- a running Homeflow backend from this repo or another compatible Homeflow server

## Build And Test Locally

From this directory run:

```bash
flutter pub get
flutter analyze
flutter test
flutter build apk --debug
```

The debug APK output is:

```text
build/app/outputs/flutter-apk/app-debug.apk
```

## Running Against Homeflow

The mobile app is designed to connect to the Homeflow backend from this repository.

Typical workflow:

1. start the backend with Docker Compose from the repo root
2. find the server machine's local IP address
3. install the APK on an Android device
4. in the app, enter the server host, port, email, and password

If you are testing from a phone on the same local network, use the computer's LAN IP, not `localhost`.

## iPhone / iOS Note

Android support is already included here.

If you later want to complete iPhone support, that still needs the usual Flutter iOS setup on macOS with Xcode.
