# EBAphone

Responsive phone storefront for Ghana. It supports SKU-specific deposits,
full payment, multi-store pickup, delivery, store-level stock visibility,
customer profiles, and an authenticated support inbox.

## Run locally

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:4173` (or `http://<LAN-IP>:4173` from another device). API documentation is at
`http://localhost:8000/docs`.

Operations console:

```bash
cd admin-frontend
npm install
npm run dev -- --port 4174
```

Open `http://localhost:4174` (or `http://<LAN-IP>:4174` from another device) with a staff account. The console covers orders,
multi-store inventory, products, stores, staff access, customers, support
conversations, payments, fulfilment and reports. Global administrators can
edit organisation data; store-scoped staff see only their permitted stores and
related customer activity.

The backend uses MySQL 8 and creates the `ebaphone` database tables and seed
catalog on first startup. Override `DATABASE_URL` for another environment.
Customer sign-in uses the supplied SMS-service flow: Ghana numbers are
normalised to `+233XXXXXXXXX`, verification codes are six digits, valid for
five minutes, single-use, rate-limited and subject to a 60-second resend
cooldown. Development-only test numbers use a deterministic code that is
never enabled when `APP_ENV=production`. For real delivery set
`SMS_PROVIDER_URL` (plus its token/from values) in the environment; without it,
local development reports simulated delivery and never sends a real message.
Set `SMS_EXPOSE_TEST_CODE=false` in production. OTP challenges are persisted in
the `sms_challenges` table with
an HMAC digest (never the clear code), so verification survives a worker
restart and is shared by multiple workers. Production must set a strong,
random `OTP_HASH_SECRET`.

Store pickup orders also receive a random handover code. Staff must enter that
code before completing a pickup order; shipping orders continue to require a
tracking number before completion.

Delivery is currently a full-payment service for the covered Accra, Tema and
Kumasi routes. The API records the resolved delivery zone on each order,
rejects addresses shorter than 10 or longer than 500 characters, and refuses
uncovered city names instead of allowing an order that the local team cannot
route. Delivery timing is confirmed after address and stock review; shipping
fees are not currently added at checkout.

New orders use an optional `X-Idempotency-Key` header to safely retry a
checkout request without creating duplicate orders. A request may contain a
quantity from 1 to 99; the order total, deposit, balance and inventory hold
are all calculated for that quantity. With
`RESERVE_STOCK_ON_ORDER_CREATE=true` (the production default), the requested
quantity is held atomically at order creation and released by the reservation
sweeper if payment is abandoned. Set it to `false` only for legacy
environments that intentionally reserve at payment time.
Hubtel payment is integrated through `/items/initiate`, the
`payNotify` callback, transaction status lookup, and refund request. Configure
the Hubtel values through environment variables; never commit the API key.
The callback URL must be publicly reachable over HTTPS in production.

For automated local tests, the backend keeps the non-production
`/api/orders/{order_id}/simulate-payment` endpoint. It is not rendered in the
storefront and should never be enabled or relied on for real transactions.

Customer sign-in uses the SMS verification flow and `/api/auth/me` stores the
customer name, email and default delivery address. `/api/support/messages`
persists customer conversations; staff can read, reply to, resolve and reopen
them from the operations console. Existing databases are upgraded at startup
with additive migrations for customer fields, payment/order fields, inventory
safeguards and support tables; no existing business rows are deleted.

## Support AI assistant

The Support tab can use an OpenAI-compatible Chat Completions API. It is
disabled until configured. After starting the API and console, sign in as a
global administrator and open **AI assistant** in the operations console. Set
the Base URL (OpenAI: `https://api.openai.com/v1`), model (`gpt-4o-mini`), API
key and assistant guidance, test the connection, then enable and save it. The
API key is encrypted in the database and is never sent back to the browser.
Set `LLM_CONFIG_ENCRYPTION_KEY` to a strong secret in the backend environment;
if omitted, the encryption key is derived from `JWT_SECRET`, so rotating that
secret requires entering the provider API key again.

The assistant only receives active product/store data, FAQ context and a short
redacted conversation history. It cannot access an order or customer account
record, execute purchases, refunds or account changes, or answer outside the
configured FAQ/product/store scope. Provider failures fall back to the human
support inbox. The console controls input and reply limits, history length,
temperature, per-user cooldown and daily user/global request caps. The initial
limits are 3 seconds per-user cooldown, 20 requests/customer/day and 1,000
requests globally/day. Assistant configuration and secret management routes
are restricted to global administrators.

Before production startup, set a strong `JWT_SECRET` and `OTP_HASH_SECRET`,
an HTTPS `SMS_PROVIDER_URL`, `SMS_EXPOSE_TEST_CODE=false`, a real
`HUBTEL_WEBHOOK_SECRET`, non-default admin credentials, and an explicit
`CORS_ORIGINS` list. Use `backend/.venv/bin/pytest -q` for the isolated API
suite and `npm run build` in both frontend projects before deployment.
