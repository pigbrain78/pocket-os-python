# Apple Sign-In — Testing Notes

## Environment
- `APPLE_AUDIENCES` in `/app/backend/.env` is set to `com.emergent.thinkingreplay.ras3v3,host.exp.Exponent`. Update if you register a different Services ID / bundle identifier in Apple Developer portal.
- Apple JWKS is fetched from `https://appleid.apple.com/auth/keys` and cached for 1h; rotated automatically on kid mismatch.

## Preview vs Real Device
- The Apple button renders **iOS only** and only after `AppleAuthentication.isAvailableAsync()` returns true. On Android and in the browser preview, only the email/password flow shows — this is expected.
- To actually see the button and complete the flow, the app must run either in Expo Go on an iPhone (audience `host.exp.Exponent`) or in a real iOS build with the bundle id above (Publish → Deploy → iOS build).

## Backend Verification (no device needed)
1. Confirm `/api/auth/apple` rejects an invalid token:
   `curl -s -X POST $BASE/api/auth/apple -H 'Content-Type: application/json' -d '{"identity_token":"garbage"}'` → expect HTTP 401.
2. Confirm `/api/auth/register` and `/api/auth/login` still work end-to-end (already covered by /app/backend/tests/backend_test.py).
3. Confirm `APPLE_AUDIENCES` is populated at boot (logs printed if missing when a real token arrives).

## Device Test (manual, iOS only)
1. In Expo Go on an iPhone signed into an Apple ID, open the app → tap the native "Sign in with Apple" button.
2. First sign-in returns `full_name` + `email` from Apple; the backend upserts a user keyed on `apple_sub` and issues a JWT.
3. Subsequent sign-ins return only `sub` (name/email are null) — the backend must **not** overwrite the stored name/email with null (already guarded).

## Linking to Existing Email Accounts
- If Apple provides a verified email that matches an existing password-based account, the two are linked automatically by writing `apple_sub` onto the existing user record. The next sign-in uses `apple_sub` directly.

## Common Failures
- **401 "Invalid Apple token: Invalid audience"** → the `aud` claim on the identity token doesn't appear in `APPLE_AUDIENCES`. Add it.
- **401 "Signing key not found in Apple JWKS"** → Apple rotated keys; our cache auto-refreshes on kid miss, but transient network errors could cause this. Retry.
- **Button never renders on iOS** → check `expo.ios.usesAppleSignIn` is `true` in `app.json` and the app was built with that flag (Expo Go picks it up automatically).
