# Google sign-in and Firebase account storage

The application requires Google sign-in for `/ev`, `/arbitrage`, `/parlay`, `/analysis` and the account/feed APIs. All user data is stored in managed **Cloud Firestore** in Google Cloud. The home page, pricing and policies stay public at the application level. The existing Sites audience restriction remains in place independently.

Keep Firebase and Layerbase configuration in your ignored local `.env`. Tracked examples contain placeholders only. Analytics is not enabled.

## Create and configure the Firebase project

1. Open [the SharpEdge Firebase project](https://console.firebase.google.com/). Google Analytics is not used by this app.
2. Under Project settings → Your apps, use the existing registered Web app matching the supplied app ID. Firebase Hosting is not required; the existing Worker serves the app.
3. Under Build → Authentication, complete **Get started** if shown. Then under Sign-in method, enable **Google** and choose the project support email.
4. Under Authentication → Settings → Authorized domains, add `YOUR_APP_HOSTNAME`, your eventual custom domain, and `localhost` for local development. Keep the project's default Firebase authentication domain.
5. Create a **Cloud Firestore Standard edition database** in Native mode, using the `(default)` database ID. Choose a suitable region. Start with production rules, then publish the exact contents of [firestore.rules](firestore.rules) in the Rules editor. Do not use test mode.
6. From the Web app configuration, set these environment variables both locally in `.env` and in the hosted Site runtime settings:

   | Runtime variable | Firebase web configuration field |
   | --- | --- |
   | `FIREBASE_API_KEY` | `apiKey` |
   | `FIREBASE_AUTH_DOMAIN` | `authDomain` |
   | `FIREBASE_PROJECT_ID` | `projectId` |
   | `FIREBASE_APP_ID` | `appId` |

   Set `FIREBASE_DATABASE_ID=(default)` as well. It selects the same Cloud Firestore database for the browser SDK and Worker membership lookups, and can be changed to a restored database ID. The configuration endpoint exposes these public identifiers and the database ID. Keep Layerbase credentials server-side. No service-account private key or separate Google OAuth client secret is needed in this application.

   The API key must allow the Identity Toolkit API and the Worker request to `accounts:lookup`. A browser-referrer-only key restriction will block server verification; use API restrictions compatible with both the Firebase browser SDK and Worker. Keep Firebase Security Rules enabled: the web API key is not a database access boundary.

You can instead deploy the rules with an authenticated Firebase CLI:

```sh
firebase deploy --only firestore:rules --project YOUR_FIREBASE_PROJECT_ID
```

The Firebase plugin can perform project configuration once enabled and connected to the Google account that owns the project. Supplying the web configuration does not enable Google sign-in, publish rules or configure recovery automatically.

## First-time sign-up

After Google authenticates the user, the app creates `users/<Firebase UID>` in a Firestore transaction **before** the server checks the account's plan or starts the application session. The initial document includes:

| Field | Initial value / Firestore type |
| --- | --- |
| `signupDate` | Server Timestamp; preserved on later sign-ins |
| `plan` | String `guest` |
| `expiresAt` | Null; Guest has no paid access |
| `betHistory` | Empty Array |
| `bankroll` | Number `1000` |
| `savedEntry` | Null |
| `displayName`, `email`, `photoURL`, `provider` | Google profile details; provider is `google.com` |
| `lastSignInAt` | Server Timestamp |

Once the profile is saved and the verified session is established, new users are sent to `/#pricing`. A Google account created during an earlier failed attempt is still treated as new if its Firestore profile is missing. Returning members keep their plan, expiration, signup date and journal, and can return to the tool they requested. Returning Guests normally go to pricing; a direct journal return path remains available.

Choosing a plan stores `requestedPlan` and `planRequestedAt` on the same user document and confirms the selection. This is a preference until billing/administrative activation is connected: it does not change `plan`, grant paid access or charge a card.

**Publish the updated `firestore.rules` before testing this flow.** The earlier profile rules do not allow these new fields and will reject profile creation. Restart the development server after source changes because it builds its assets at startup. If Google succeeds but profile storage fails, the app reports that step specifically, and the browser console records the stage and Firebase error code without logging tokens or profile data. `permission-denied` usually requires checking the deployed rules and selected database; a session-stage error instead concerns the application's server request.

## Session troubleshooting

The session endpoint returns a stable `code` alongside its user-facing error. The client keeps the server's explanation instead of replacing every failure with a generic message. If an expired cached token is rejected, Firebase is asked for a fresh token and the session request is retried once. The request timeout allows both server verification and the account read to complete.

The server allows up to 60 seconds of difference for a newly issued token's `iat`/`auth_time` compared with its local clock. Google still verifies the signature and token; token expiration and membership expiration have no grace period. A production server should synchronize its clock normally.

In local development, `http://localhost:4173/api/auth/diagnostics` shows the last 20 failed session requests with only time, HTTP status and error code. It accepts loopback requests only, stores nothing on disk, and is not part of the hosted Worker. No authorization headers, ID tokens, emails or user documents are recorded.

| Code | What to check |
| --- | --- |
| `SESSION_ORIGIN_MISMATCH` | Use the same hostname and port throughout sign-in. The local server preserves the browser's Host header. |
| `AUTH_PROJECT_MISMATCH` | The browser and server must use the same Firebase project. Reload after changing configuration. |
| `AUTH_TOKEN_EXPIRED`, `AUTH_INVALID_ID_TOKEN` | The client refreshes once automatically; if it still fails, sign in again. |
| `AUTH_TOKEN_NOT_YET_VALID` | Synchronize the server clock with internet time. |
| `AUTH_PROVIDER_UNREACHABLE` | The Node/Worker process needs outbound HTTPS access to Firebase Authentication. |
| `AUTH_PROVIDER_REJECTED` | Check Identity Toolkit API availability and API key restrictions for server requests. |
| `AUTH_PROFILE_READ_DENIED` | Publish the current rules for the selected database; the signed-in user must be able to read `users/<UID>`. |
| `AUTH_PROFILE_UNREACHABLE` | The server needs outbound HTTPS access to Cloud Firestore. |
| `AUTH_SESSION_REVOKED` | Complete Google sign-in again after session revocation. |

## Cloud Firestore recovery

Recovery is configured on the managed database in Google Cloud, independently of the app deployment and `firebase.json`. The application uses the cloud service; it does not use a local database or connect to emulators.

In Google Cloud Console → Firestore → Databases, select the production database and configure:

- **Point-in-time recovery (PITR):** enable it under Disaster Recovery. PITR retains document versions for up to seven days. It requires billing and has storage charges; history builds from the time it is enabled. See [Firebase PITR setup](https://firebase.google.com/docs/firestore/use-pitr).
- **Scheduled backups:** use daily backups with a 14-day retention period to start. Retention can be extended up to 14 weeks to suit your recovery requirements. See [backup schedules and restore](https://firebase.google.com/docs/firestore/backups).
- **Delete protection:** enable database delete protection in the database settings to prevent accidental database deletion. This complements backups and PITR; it does not prevent individual document edits.

These cloud settings have not been applied or verified by the local code. `firebase deploy --only firestore:rules` deploys access rules, not a backup schedule or PITR configuration.

Backups restore into a **new database**. To recover without changing application code:

1. Restore the backup, or clone a PITR snapshot, into a new database in the same Firebase project. Keep writes paused during validation and the switch so updates are not split across the old and restored databases.
2. Set `firestore.database` in `firebase.json` to the restored ID and deploy `firestore.rules` to that database. Verify its rules, IAM permissions, recovery settings and any indexes before directing user traffic to it. Keep the existing database until recovery is validated.
3. Set `FIREBASE_DATABASE_ID` to the restored ID in both the local and production runtime settings, restart/redeploy the Worker, and reload browser clients. Both the client data SDK and server membership lookups then use the restored database.
4. Test with two accounts and verify profiles, settings, journals, saved entries and memberships. Reconcile any membership changes made after the recovery timestamp before resuming paid access. Expiration timestamps remain absolute: restoring an expired membership does not renew it.

Firestore backups cover Firestore records. Firebase Authentication users and OAuth provider configuration belong to the Firebase project separately; retain that project and its user UIDs when restoring a database.

## Memberships

Google sign-in creates a Guest profile automatically. Guests have a journal and account settings; market tools keep their membership restrictions. The pricing selector records a preference and cannot grant access or charge a card.

After the first Google sign-in, locate `users/<UID>` in Firestore and update its membership fields through the console or a trusted billing backend:

```json
{
  "plan": "platinum",
  "expiresAt": "2026-12-01T05:00:00Z"
}
```

Supported plans are `gold`, `plus`, `fantasy`, `fantasyplus`, and `platinum`. The JSON above illustrates the value: enter `expiresAt` as a **Firestore Timestamp** in the console, not a string. The example expires at midnight at the start of December 1, 2026 in America/New_York (05:00 UTC).

`expiresAt` is required. Access is granted only while it is strictly later than the server's current time. Missing, malformed, incorrectly typed and expired timestamps receive no market data. There is no `active` flag. Renew a membership by moving its expiration forward; revoke it immediately by setting the timestamp to now or an earlier instant. Existing records must be given an expiration date; an old `active: true` value alone grants no access and can be removed.

Only the console or a trusted billing backend may change `plan` and `expiresAt`; browser clients can update their own profile details, journal and plan preference. The server reads membership fields from `users/<UID>` and rechecks expiration on each protected request. The account panel displays the local expiration date and time, and the browser clears market data when the membership expires. Expiration does not sign the user out or delete their journal/settings. Refresh after an administrative renewal to update the account display.

The Worker filters data by membership before returning it. Gold receives pre-match sportsbook EV; Gold Plus also receives arbitrage; Fantasy receives fantasy pre-match EV; Fantasy+ receives all pre-match EV for its all-app builder; Platinum receives every feed including live EV. The client cannot unlock omitted records by editing browser storage.

## Stored data

- `users/<UID>` is the single account record: profile details, `signupDate`, `plan`, `expiresAt`, `betHistory`, `bankroll`, `savedEntry`, and update times. `betHistory` is an Array of bet objects, not a JSON string. The journal holds up to 500 bets. The account panel displays the saved entry across devices.
- Each bet retains its identifier, selection, book, entry odds, stake and manually entered closing odds so Analysis can calculate closing-line value.
- Older `users/<UID>/app/state` journals are copied into the user document once, when `betHistory` is absent. The source is kept for recovery and becomes read-only. Existing user-document history is never overwritten by this migration.
- Legacy `memberships/<UID>` records are no longer used for access. If any were created, an administrator must copy their approved `plan` and `expiresAt` into the corresponding user document. The browser cannot perform this entitlement migration.

The rules deny access to other users' records and deny unspecified collections. State is loaded before writes are enabled; failed saves show an error. Existing anonymous demo data is not automatically copied into an account, since ownership cannot be established on a shared browser. Sign-out clears the displayed account, market data and journal, the Firebase browser session, and the HttpOnly cookie. Signing out does not delete stored cloud records.

Firebase Authentication uses browser session persistence. A short-lived Firebase ID token is synchronized to a Secure, HttpOnly, SameSite=Lax cookie for full-page navigation. Session mutations require an exact same-origin Origin header. The Worker delegates signature verification to Firebase's `accounts:lookup` endpoint on protected requests, checks project/issuer/provider/expiry and account revocation, and reads the current membership. Authentication and membership outages deny access. API fetches use a refreshed Firebase bearer token. Session refreshes are serialized with sign-out to avoid restoring a cookie after logout.

## Local development and verification

```sh
# Copy .env.example to .env and fill in the values above.
node --env-file=.env scripts/dev.mjs
npm test
```

Open `http://localhost:4173`. Modern browsers treat localhost as a secure context for Secure cookies; use HTTPS when accessing a development server by another hostname. Production must use HTTPS.

The Node test suite checks Guest profile creation before the session request, pricing redirects, plan preferences, repeat sign-in and history preservation, legacy history migration, setup failure recovery, anonymous access, token rejection, expiration boundaries, restored databases, user switching and the parlay feed. Firebase services are mocked in these tests; they do not validate a real OAuth exchange or deploy/execute Firestore rules.

After configuring the project, verify with two real Google accounts:

1. A signed-out protected page redirects to sign-in, and `/api/feeds` returns 401.
2. Google sign-in creates `users/<UID>` with a signup timestamp, Guest plan, null paid expiration and empty bet history, then sends the user to pricing. Choosing a plan stores the request while keeping Guest access. The account can save its bankroll and journal; a Guest cannot retrieve market data.
3. Grant a membership with a future Firestore Timestamp and confirm the matching tools load; editing a browser plan value does not change access. Set its expiration to now and verify market data is denied while the journal stays available. Renew with a future timestamp and refresh to restore access.
4. Sign out, then sign in as the second account. The first account's profile, bankroll, journal and saved entry must be inaccessible, including direct Firestore reads and writes.
5. Confirm users can create only a Guest profile, cannot upgrade `plan`, cannot change `expiresAt` or `signupDate`, and cannot add role fields. A plan preference must not activate market access.
6. Disable the account or revoke sessions in Firebase and verify subsequent protected requests fail. Confirm signed-out browser Back navigation does not retain private content.

The Firebase SDK is pinned to the documented CDN release `13.1.0`. Reference: [Google sign-in](https://firebase.google.com/docs/auth/web/google-signin), [Auth REST account verification](https://firebase.google.com/docs/reference/rest/auth#section-get-account-info), [Firestore authentication](https://firebase.google.com/docs/firestore/use-rest-api), [Firestore rules](https://firebase.google.com/docs/firestore/security/rules-conditions).
