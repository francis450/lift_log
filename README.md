# Lift Log (Frappe app)

Backend for the Lift Log Android app: DocTypes, whitelisted API and seed data. Frappe v15, needs only the
Frappe framework. Specs live in the handoff folder (`docs/01`–`07`).

## Install

```bash
bench get-app <repo-url>
bench --site <site> install-app lift_log
bench --site <site> execute lift_log.setup.seed.run   # 1 program, 32 exercises, 44 foods; idempotent
```

Then give each person the **Lift Log User** role (desk: User > Roles). Sign-in refuses accounts without it.
Set the Anthropic key later in **LL Settings** (needed from milestone M5).

## Tests

```bash
bench --site <site> set-config allow_tests true
bench --site <site> run-tests --app lift_log
```

## API

All methods are `/api/method/lift_log.api.<module>.<fn>`, documented in `docs/04-api-contract.md`.
Calls after sign-in send `Authorization: token <api_key>:<api_secret>`.

Behaviour the contract leaves open, as built:

- **Optional numbers** (`kg`, `height_cm`, `waist_cm`, `sleep`, ...) come back as `null` when blank.
  Frappe stores numeric columns as `NOT NULL DEFAULT 0`, so 0 and blank are the same value.
- **Times** are ISO 8601 UTC with milliseconds (`2026-10-06T15:02:00.000Z`); any offset is accepted on input.
- **`profile.get`** before setup returns the defaults with `"exists": false` (nothing is saved).
- **`today.get`** also returns `targets_note` so Today can show the one-time note.
- **`sessions.save`** computes `week` from the date and the active program. Set rows with no `amount` are dropped.
- **`sessions.history`** items also carry `week` and `routine_key`, so the app can ignore deload-week history.
- **`checkins.get`** returns `{week, checkin, previous_weight_kg, last_measured: {waist, forearm}, due: {waist, forearm}}`
  for the check-in screen's prefill and "Due this week" labels.
- **`progress.summary`** also returns `week` and `protein_target_g` (for the dashed target line), and each lift
  has a short `label`. Planned sessions count scheduled training days before today, plus today once trained.
- **`ai.*`** answer HTTP 501 until M5/M7.
- A stale write (`client_updated_at` older than the stored one) gets HTTP 409 with `{"stored": ...}`.
  An equal timestamp is treated as a retry and overwrites with the same content.

Baseline logging (Nov 2026):

- **`daily.get` / `daily.save` / `daily.recent`**: one LL Daily Log per user per day with morning weight, sleep hours,
  steps and pain (0-10, blank = not logged). `save` keeps fields that are left out and clears fields sent as `""`, so
  weight and steps can be saved at different times. `get` and `today.get` return a 7-day weight trend (`trend.py`):
  the average needs 4 weigh-ins in the 7 days, and the weekly change compares two consecutive 7-day averages.
- **Sets** take `rir` (reps in reserve, 0-4, blank = not rated) and `warmup`. The old `effort` stays for sets logged
  before; the rule reads it as easy 3, right 1, hard 0.
- **Food days** take `complete`; left out, the stored flag stays. The weekly review averages only complete days once
  any day in the week is marked complete. Entries take `grams`, custom foods `grams_per_portion`.
- **Check-ins** take `hips_cm`.
- **Exercises**: type `assisted` logs the machine's help in kg (less is progress). Patch `v1_1.equipment_steps` sets
  barbell steps to 5 kg (smallest plate 2.5 kg) and the assisted pull-up step to 0 until it's measured.

