# Plan: Login rate-limiting milestone (commit + push)

- [x] Add per-IP login attempt tracking with lockout window — Login rate-limiting implemented — per-IP tracking, lockout, 429 with Retry-After
- [ ] Enforce rate limit on /api/login; return 429 with Retry-After
- [x] Add rate-limit tests (burst denied, lockout, reset after window) — Rate-limit tests pass — burst locks out with 429+Retry-After, success resets, lockout expires
- [x] Run all suites green — Running the full auth suite and confirming no regressions before the commit — All unit/API suites green — auth 18, engines 25, replay 11, control-room 20, features 11
- [~] Commit and push to origin — All suites green (99 tests). Committing the rate-limiting milestone and pushing to origin
