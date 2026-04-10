# Homeflow Mobile Companion Product Brief

## Goal

Build a simple Android and iPhone companion app for the self-hosted Homeflow task manager.

The app is for users who run the Docker server on their own system. It is not a shared cloud service. Each user connects the app to their own Homeflow server.

## Product Principle

Keep the mobile app practical, reliable, and logical:

- today first
- fast status updates
- clear sync state
- useful offline behavior
- no unnecessary complexity in V1

## Primary Purpose

- show today's tasks clearly
- refresh from the user's own server when reachable
- update task status quickly from the phone
- optionally expose a simple home screen widget for quick visibility

## Secondary Purpose

- remain useful when the server cannot be reached
- show cached data with clear stale or offline messaging
- keep setup practical and simple for self-hosted users

## Target Users

- people already running the Homeflow Docker server
- users connecting to a local network host, VPN host, Tailscale address, or other self-managed endpoint
- users who want a fast mobile day view rather than full desktop administration

## Core User Flow

1. User installs the mobile app.
2. User enters server hostname or IP, port, and login credentials.
3. App signs in against the user's own Homeflow server.
4. App stores session information securely on-device.
5. App fetches tasks relevant to the logged-in user.
6. App opens to today's tasks first.
7. User updates task status quickly from the phone.
8. If the server later becomes unreachable, the app still shows previously cached task data and explains the sync state clearly.

## V1 Scope

### Screens

- Connection / Login
- Today
- Upcoming
- Task Detail
- Settings / Sync

### V1 Features

- connect to a self-hosted Homeflow server
- support secure sign-in
- fetch tasks relevant to the logged-in user
- show today's tasks first
- show the next upcoming days
- update task status
- cache a practical rolling window of task data locally
- show last sync time and last sync result
- show clear offline and server-unreachable states
- optionally provide a simple read-first home screen widget

### V1 Non-Goals

- full admin features
- task creation
- task editing beyond status changes
- advanced scheduling management
- reporting or analytics views
- complex widget actions

## Platform Plan

Initial targets:

- Android
- iPhone

Planned distribution path:

- early Android testing via APK or internal testing
- early iPhone testing via TestFlight
- later release via Google Play and Apple App Store

## Settings For V1

- server hostname or IP
- port
- HTTP or HTTPS preference if needed
- account email
- logout
- offline cache window
- manual refresh
- optional auto-refresh on app open

Helpful extras:

- current server URL summary
- current account email
- last sync status
- clear cached data

## Security Expectations

- store tokens in platform secure storage
- avoid storing the raw password unless there is no reasonable alternative
- clear auth state fully on logout
- support HTTPS cleanly for externally exposed servers
- allow local network server URLs, while making it clear that reachability depends on network access unless the user uses VPN or similar

## Success Criteria For V1

- the user can connect to their own server without needing the desktop web UI open
- today's assigned tasks are visible quickly
- status changes are fast and reliable
- the app remains useful when temporarily offline
- sync failures are explained clearly instead of silently failing
