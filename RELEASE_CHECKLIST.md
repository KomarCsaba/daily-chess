# Release Readiness Checklist

## Reliability
- [x] Live move feedback (last move, captures, sounds, animations)
- [x] Reconnect banner in game UI
- [ ] Add reconnect recovery test plan (manual + automated)
- [ ] Add backend tests for move route success/failure paths

## Security
- [x] Session cookie defaults (`HttpOnly`, `SameSite=Lax`, optional `Secure`)
- [x] Basic response hardening headers
- [x] Move input format validation
- [x] Add CSRF protection for all POST form endpoints
- [x] Add rate-limiting for auth and move endpoints

## Data and Migrations
- [x] Introduce Flask-Migrate / Alembic migrations
- [x] Convert runtime schema patching to versioned migrations
- [ ] Add DB backup/restore notes

## Quality
- [ ] Add tests for timeout handling and draw offers
- [ ] Add tests for `last_move_uci` and move flags payload
- [ ] Browser QA matrix (Chrome, Firefox, Safari, mobile)

## Ops
- [ ] Production env template (`.env.example`)
- [ ] Dependency pinning policy and update cadence
- [ ] Health check and structured logging conventions
