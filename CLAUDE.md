# CLAUDE.md: Lift Log

Lift Log is a personal gym and food log for Android. Specs live in `docs/`; screen designs in `design/screens/`. When the spec and the designs disagree, the spec wins and you say so.

## Stack

**Mobile (`lift-log-mobile`)**
- Expo SDK (latest stable), managed workflow, TypeScript strict.
- Navigation: `expo-router` with a bottom tab layout (Today, Train, Food, Progress).
- Server state: TanStack Query. Local state: Zustand.
- Local storage: `expo-sqlite` for the offline log and sync queue; `expo-secure-store` for the API token.
- Camera and photos: `expo-image-picker` (camera + library), resize to max 1568 px long edge with `expo-image-manipulator` before upload.
- Notifications: `expo-notifications` (local, scheduled on device).
- Fonts: Barlow Condensed (600, 700), IBM Plex Sans (400, 500, 600), IBM Plex Mono (500) via `@expo-google-fonts/*`.
- Builds: EAS Build, `preview` profile produces an APK.

**Backend (`lift_log` Frappe app)**
- Frappe v15 app installed on an ERPNext site. Python 3.11.
- All mobile endpoints are whitelisted methods in `lift_log/api/*.py`, called as `/api/method/lift_log.api.<module>.<fn>`.
- Claude calls use the official `anthropic` Python SDK from the server only.

## Rules

- Never put the Anthropic API key, or any secret, in the mobile app or in git. It is read from `LL Settings` (a Password field) on the server.
- Every write endpoint is an idempotent upsert keyed by `(user, date)` or a client-generated id, so retries and offline sync never duplicate data.
- Every record belongs to one user. Server code filters by `frappe.session.user` and never trusts a user id sent by the client.
- Units: kg, cm, kcal, grams. Dates as `YYYY-MM-DD` in the user's time zone (default `Africa/Nairobi`). Store times in UTC.
- The progression rule (docs/01, "Add-weight rule") lives in one pure function on the mobile side, with unit tests covering every branch. The server does not duplicate it.
- Tap targets at least 44 x 44. Text contrast at least 4.5:1. Every icon-only button has an accessibility label.
- No emoji in the UI. Icons: `lucide-react-native`, stroke 2.

## Commands

Mobile:
- `npx expo start` to run, `npx expo run:android` for a dev build on a device.
- `npm test` (Jest + React Native Testing Library), `npm run lint`, `npm run typecheck`.
- `eas build -p android --profile preview` for an installable APK.

Backend (from the bench folder):
- `bench get-app <repo-url>` then `bench --site <site> install-app lift_log`.
- `bench --site <site> migrate` after DocType changes.
- `bench --site <site> run-tests --app lift_log`.
- `bench --site <site> execute lift_log.setup.seed.run` to load `data/*.json`.

## Working style

- Build one milestone from `docs/07-build-plan.md` at a time. Finish with its acceptance checks and a short list of what the user should test on the phone.
- Ask before deleting or rewriting any existing DocType, data, or file you did not create in this session.
- Keep the UI copy as written in the specs and designs; it was chosen deliberately.
