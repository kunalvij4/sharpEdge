# Stripe Checkout setup

The pricing buttons send new subscribers to Stripe Checkout. Gold, Gold Plus, Fantasy Package, Fantasy+ and Platinum are supported. Existing subscribers review a plan-change quote in the app. Upgrades charge the full new monthly price immediately and start a new billing month after payment succeeds, with no credit for unused previous-plan time. Downgrades preserve the current plan until renewal, when the lower plan and price begin. My account → Manage billing shows membership status, scheduled changes, billing details and invoices, and supports cancellation at the end of the paid term.

Stripe keys, prices and a Firebase billing service account must be configured before payments can open. Tests use disposable Stripe test-mode objects and an in-memory Firestore; they do not modify real user records.

## 1. Create test products and monthly prices

In your [Stripe test dashboard](https://dashboard.stripe.com/test/products), create these products with **USD recurring monthly** prices:

| Product | Monthly price | Server environment variable |
| --- | --- | --- |
| Gold | $14.99 | `STRIPE_PRICE_GOLD` |
| Gold Plus | $19.99 | `STRIPE_PRICE_PLUS` |
| Fantasy Package | $29.99 | `STRIPE_PRICE_FANTASY` |
| Fantasy+ | Set your monthly USD price in Stripe | `STRIPE_PRICE_FANTASY_PLUS` |
| Platinum | $99.99 | `STRIPE_PRICE_PLATINUM` |

Copy each **Price ID** (`price_...`), not its Product ID (`prod_...`). Match the values shown on the pricing page. Fantasy+ uses the monthly price you configure in Stripe; its upgrade button opens Checkout so the customer can review that price before paying. Its internal plan ID is `fantasyplus`, including in `users/<UID>.plan` after verified payment. In [API keys](https://dashboard.stripe.com/test/apikeys), get your test secret key (`sk_test_...`). The hosted redirect does not require a publishable key or Stripe.js.

Add the following to your ignored `frontend/.env`, using `.env.example` as the template. Also configure these server runtime variables on whichever host you deploy to:

```dotenv
APP_URL=http://localhost:4173
STRIPE_SECRET_KEY=sk_test_REPLACE_ME
STRIPE_WEBHOOK_SECRET=whsec_REPLACE_ME
STRIPE_PRICE_GOLD=price_REPLACE_ME
STRIPE_PRICE_PLUS=price_REPLACE_ME
STRIPE_PRICE_FANTASY=price_REPLACE_ME
STRIPE_PRICE_FANTASY_PLUS=price_REPLACE_ME
STRIPE_PRICE_PLATINUM=price_REPLACE_ME
FIREBASE_CLIENT_EMAIL=billing@YOUR_FIREBASE_PROJECT_ID.iam.gserviceaccount.com
FIREBASE_PRIVATE_KEY='-----BEGIN PRIVATE KEY-----\nREPLACE_ME\n-----END PRIVATE KEY-----\n'
```

Use an HTTPS `APP_URL` in production. Never put server keys in browser code or commit `.env` or the downloaded service account JSON. The `/api/auth/config` endpoint continues to return only public Firebase configuration.

## 2. Authorize billing writes to Firestore

Create a dedicated Google Cloud service account in your Firebase project and grant it the **Cloud Datastore User** role (`roles/datastore.user`) for the database. Create a JSON private key, then copy its `client_email` and `private_key` into the two `FIREBASE_*` variables above. The application accepts literal `\n` sequences or real newlines in the PEM key. Keep your existing Firebase web configuration and `FIREBASE_DATABASE_ID` settings.

This server identity is needed because browser security rules intentionally forbid membership changes. Billing updates only `users/<UID>.plan` and `expiresAt`; it preserves the signup date, journal and bankroll. Customer and subscription IDs are stored in `billingAccounts/<UID>`, which the existing default-deny Firestore rules keep inaccessible to browser clients. No rule relaxation is required.

The implementation uses the [Firestore REST API with service account authorization](https://firebase.google.com/docs/firestore/use-rest-api) and works in both local Node and Cloudflare Workers without additional npm packages. Service account IAM permissions bypass Firestore security rules; retain the private key only in trusted server configuration.

## 3. Configure the billing portal

The application creates and selects its own Stripe portal configuration for billing details, payment methods, invoice history and cancellation. Cancellation uses `at_period_end` with no proration. The portal displays the no-refund policy and links to the application's billing policy. The API key must allow portal configuration creation as well as portal sessions.

Plan changes are handled by the application's confirmation flow rather than the Dashboard's default portal configuration. This supports prices across separate Stripe products: an upgrade uses `billing_cycle_anchor[type]=now`, `proration_behavior=none` and `payment_behavior=pending_if_incomplete`, while a downgrade creates a two-phase subscription schedule. Only successful upgrade payment grants the higher plan. A failed or authentication-required payment leaves the existing paid access in place and exposes the invoice in Manage billing. Cancelling renewal also voids an unpaid upgrade and removes any scheduled downgrade.

The app recovers missing customer links by matching Stripe's server-controlled Firebase UID, project and database metadata. Matching email alone never grants billing access. Firestore continues to store the currently paid plan and expiration on `users/<UID>`; `billingAccounts/<UID>` also records cancellation and scheduled plan-change details. Opening Manage billing reconciles Stripe and Firestore and refreshes a stale browser membership.

## 4. Forward webhooks while developing

Install and authenticate the [Stripe CLI](https://docs.stripe.com/stripe-cli). On Windows PowerShell, use the `.cmd` launchers to avoid compatibility errors in PowerShell installer scripts or `npm.ps1`:

```powershell
npm.cmd install --global @stripe/cli@latest
stripe.cmd version
stripe.cmd login
```

Then forward events from one terminal. On Windows, use `stripe.cmd` in place of `stripe` in this command:

```sh
stripe listen --events checkout.session.completed,checkout.session.async_payment_succeeded,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,customer.subscription.pending_update_applied,customer.subscription.pending_update_expired,subscription_schedule.updated,subscription_schedule.released,subscription_schedule.completed,invoice.paid,invoice.payment_failed --forward-to localhost:4173/api/billing/webhook
```

Copy the printed `whsec_...` into `STRIPE_WEBHOOK_SECRET`. Restart the frontend after editing `.env`:

```sh
cd frontend
node --env-file=.env scripts/dev.mjs
```

In production, create a Stripe webhook destination at `https://YOUR_APP_HOST/api/billing/webhook`, subscribe to the same events, and use that destination's signing secret. The CLI secret and production destination secret are different. The application pins Stripe API requests to `2026-10-28.endive`; use that version for the webhook destination as well.

**Stripe must be able to POST to the webhook without an interactive hosting sign-in.** The existing Sites hosting audience is restricted and these code changes do not change it. Before production use, arrange a publicly reachable webhook endpoint on your deployment; if the host gates all paths, an independently public backend or an explicitly authorized hosting access change is required. A successful browser return also verifies the paid session on the server and activates access, but webhooks are required for renewals, cancellations and customers who close the tab.

## 5. Test the flow

1. Open `http://localhost:4173`, sign in with Google, and select a plan. Stripe should show the selected product and monthly price. A signed-out selection returns to the same plan after Google sign-in.
2. Complete test Checkout using Stripe's [test card details](https://docs.stripe.com/testing), such as `4242 4242 4242 4242`, a future expiry and any valid test CVC. Never use real card details in test mode.
3. Confirm the return message says the membership is active, the matching tools open, and `users/<UID>` has the correct plan and a Firestore Timestamp expiration. `billingAccounts/<UID>` should contain Stripe customer and subscription IDs.
4. Cancel Checkout before paying and confirm the user remains Guest. Check that a failed or missing configuration shows an error and lets the user retry.
5. Open My account → Manage billing. Confirm billing details, invoices and the no-refund policy are visible. An upgrade must show and charge the full new monthly price, reset the renewal date and grant higher access only after payment succeeds. A downgrade must show its future start date and preserve current access until renewal. Cancelling renewal must keep access until the current expiration and remove scheduled downgrades. Failed renewals do not extend the last verified paid period.
6. Check webhook deliveries in Stripe and test renewals with a Stripe test clock. Merely opening Checkout or changing a return URL never grants a membership.

Run `npm test` from `frontend` for automated checks. They mock Stripe/Firebase network calls, verify real HMAC/RSA signatures with test keys, and cover authentication, signed plan-change quotes, full-price upgrades, scheduled downgrades, cancellation, billing-link recovery, invoices and account ownership.

For an explicit Stripe integration check, run `npm run test:stripe`. It requires test keys and the configured test prices, creates a disposable test customer and subscription, verifies upgrades, schedules, cancellation and portal features against Stripe, and cleans up those objects. Firestore is simulated in memory, and live keys/prices are refused. It does not validate a real Google OAuth exchange or hosted webhook delivery.

When restoring Firestore into another database, reconcile billing records and update the subscriptions' server-controlled `database` metadata to the new ID before relying on webhooks. Metadata from a different Firebase project/database is intentionally ignored.

For production, create live prices and configure live keys, the live portal and a live webhook secret separately. Confirm the displayed amounts and your subscription terms before enabling live payments. Reference: [Stripe Checkout subscriptions](https://docs.stripe.com/payments/checkout/build-subscriptions), [webhook verification](https://docs.stripe.com/webhooks), and [billing portal flows](https://docs.stripe.com/customer-management/portal-deep-links).
