# SautiPay

> **Bitcoin access through familiar phone interfaces — USSD first, voice calling as an advanced channel.**

SautiPay is a phone-based Bitcoin access project designed for people who may not have a smartphone, reliable mobile data, or experience with conventional wallet interfaces. The product direction prioritizes USSD, Lightning payments, and English/Hausa accessibility.

---

## The Problem

Many financial and Bitcoin services assume users have a smartphone, can install an app, have reliable mobile internet, and understand unfamiliar interfaces. These assumptions can exclude feature-phone users, people with limited connectivity, and first-time Bitcoin users.

SautiPay aims to make Bitcoin easier to access through familiar phone menus while treating authentication, key management, and payment verification as first-class requirements.

---

## The Solution

- **USSD-first access:** Familiar short-code menus without requiring mobile data on the user's handset for the core USSD session.
- **Lightning-focused payments:** Simple journeys for supported send/receive operations.
- **English and Hausa:** Language accessibility from the beginning.
- **Voice access:** Planned interactive phone-call menus for people who prefer spoken prompts or find text menus difficult.
- **Security-minded design:** Explicit transaction authorization, spending limits, idempotency, and clear payment states.
- **Shared backend:** USSD and voice should use the same application services, account model, wallet mapping, and transaction controls.

_SautiPay will not claim that fiat on/off-ramps, swaps, or other integrations are available until their providers, liquidity, settlement, compliance, and implementation have been verified._

---

## Target Users

- Feature-phone users and people with limited mobile data.
- First-time Bitcoin users who need a simpler interface.
- People who prefer English or Hausa prompts or any other language.
- Small merchants and community businesses exploring Lightning payments.
- Bitcoin communities interested in accessible phone-based services.

---

## Product Channels

### 1. USSD — Primary Channel

Users dial a provisioned short code and navigate a menu. The USSD provider sends session requests to SautiPay through server callbacks.

Potential menu options include balance, receive, send, recent transactions, language, and help. Only expose options whose backend flows are implemented and tested.

### 2. Voice Calls — Advanced Feature

The planned voice channel lets users call a service number and hear interactive voice response (IVR) prompts. The first version should use keypad tones (DTMF); speech recognition can be evaluated later.

The voice experience should:

- Offer English and Hausa prompts where supported by the chosen provider.
- Read menu options and transaction details aloud.
- Reuse the same backend services and controls as USSD.
- Require authentication and explicit confirmation before sensitive actions.
- Explain whether a transaction is pending, successful, failed, or still being reconciled.
- Handle call drops, timeouts, duplicate callbacks, and invalid input safely.

>

### 3. SMS — Notifications

SMS may be used for receipts and non-sensitive alerts. Do not accept PINs or treat SMS or caller ID alone as authorization for a Bitcoin transfer.

---

## Example User Journeys

### Onboarding

1. User starts through USSD or, when available, the voice number.
2. SautiPay explains the service and custody model.
3. User completes authentication and consent steps.
4. Backend creates an internal user ID and links it to a normalized phone number.
5. User receives confirmation and help instructions.

_A phone number is a contact/account identifier, not a database primary key. Account recovery must consider SIM swaps and recycled phone numbers._

### Send a Lightning Payment

1. User enters the destination and amount.
2. Backend validates the destination, fees, amount, limits, and payment request.
3. SautiPay reads or displays the recipient, amount, and fee.
4. User authenticates and explicitly confirms.
5. Payment service submits the request through the Lightning adapter.
6. Backend reconciles the result and reports it accurately.

_A timeout is not proof of failure or success. An uncertain payment must remain `PENDING` or `UNKNOWN` until reconciled; do not blindly retry._

### Receive a Lightning Payment

1. User chooses Receive.
2. Backend creates a supported payment request/address.
3. SautiPay explains amount and expiry when applicable.
4. Backend verifies payment status through the supported integration.
5. A receipt is issued only after the payment state is verified.

---

## Planned Voice-Call Flow

```text
Incoming call
    │
    ▼
Verify provider webhook
    │
    ▼
Select language (English / Hausa)
    │
    ▼
Identify account and authenticate (PIN via DTMF)
    │
    ▼
Read available menu
    │
    ▼
Choose a supported action
    │
    ▼
Validate amount, destination, fees, and limits
    │
    ▼
Read back transaction details
    │
    ▼
Explicit authenticated confirmation
    │
    ▼
Submit transaction and reconcile status
    │
    ▼
Read result aloud and dispatch receipt if appropriate
```

### Voice Implementation Approach

- Use a telephony provider supporting inbound calls, HTTPS webhooks, DTMF, and programmable call control.
- Put provider-specific behaviour behind a `VoiceProvider` adapter.
- Implement an explicit IVR state machine with validated transitions.
- Verify webhook signatures and use idempotency controls for repeated callbacks.
- Keep prompts short and provide help, cancel, and exit paths.
- Do not reveal sensitive account information before authentication.
- Never collect PINs in SMS, logs, analytics, or untrusted callback parameters.
- Do not let caller ID alone authorize a transfer.
- Reuse the shared payment, account, limits, and audit services rather than building a separate wallet for voice.

---

## Architecture

```text
Feature phone
  │               │
  │ USSD          │ Voice call (planned)
  ▼               ▼
USSD provider   Telephony / IVR provider
  │ HTTPS         │ HTTPS
  │ callback      │ webhook
  └───────┬───────┘
          ▼
    Channel adapters
          │
          ▼
   Authentication / sessions
          │
          ▼
   SautiPay application services
   ├── Account
   ├── Payments
   └── Notifications
          │
          ▼
   Bitcoin / Lightning adapter
          │
          ▼
   Lightning infrastructure
```

**Shared services:** PostgreSQL/SQLite, secret management, audit events, monitoring, webhook validation, idempotency, and reconciliation.

---

## Technology Stack

| Area                     | Initial Direction                                                                |
| :----------------------- | :------------------------------------------------------------------------------- |
| **Backend**              | Python, FastAPI                                                                  |
| **Validation**           | Pydantic                                                                         |
| **Database**             | SQLite (prototype) / PostgreSQL (production target)                              |
| **Lightning**            | LND through a dedicated adapter, subject to repository implementation            |
| **USSD**                 | Africa's Talking or another verified provider                                    |
| **Voice**                | IVR provider with inbound calls and DTMF, selected after coverage/pricing checks |
| **Testing**              | `pytest`, integration tests, provider mocks                                      |
| **Local infrastructure** | Python virtual environment / Docker Compose                                      |

_This is the intended stack, not proof every component is connected. Update it to match the code and dependencies in the repository._

---

---

## Implementation Status

_Keep this table honest and update it based on the actual repository:_

| Capability                                   | Status to use until verified                      |
| :------------------------------------------- | :------------------------------------------------ |
| **Product direction and user journeys**      | Defined                                           |
| **USSD provider integration**                | Implemented (sandbox tested)                      |
| **English and Hausa UX**                     | Implemented (bilingual menu)                      |
| **Voice IVR and phone-call access**          | Advanced feature planned                          |
| **Lightning send/receive**                   | Implemented (LND REST + test suite)               |
| **Payment reconciliation and receipts**      | Implemented (Hash-chained ledger)                 |
| **Transaction limits and replay protection** | Implemented (`security_engine.py`)                |
| **Production key management and recovery**   | Requires review before real funds                 |
| **On-chain BTC, swaps, NGN rails**           | Implemented atomic swap engine / NGN future scope |

_Only mark a feature "implemented" when the code exists and tests demonstrate it. Include environment details for demos (sandbox, testnet, regtest, or mainnet)._

---

## Local Development

The exact commands depend on the repository. For this project:

```bash
git clone https://github.com/Ugarba202/SautiPay-.git
cd SautiPay-
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

_Never commit `.env` or real credentials._

---

## Configuration

Document only environment variables used by the code. Likely categories include:

```ini
APP_ENV=development
DATABASE_URL=sautipay.db

# Add only when the corresponding integration exists:
# USSD_PROVIDER_API_KEY=
# USSD_SERVICE_CODE=*384#
# PUBLIC_BASE_URL=
# VOICE_PROVIDER_ACCOUNT_ID=
# VOICE_PROVIDER_AUTH_TOKEN=
# VOICE_PROVIDER_NUMBER=
```

_The variable names are illustrative placeholders; align them with the implementation and provider documentation._

---

## Testing Checklist

- [x] New and returning user flows.
- [x] English/Hausa menu selection and fallback.
- [x] Invalid input, expired sessions, and repeated callbacks.
- [x] Incorrect PIN, rate limiting, lockout, and recovery.
- [x] Invalid invoice, wrong recipient, fees, insufficient balance, and spending limits.
- [x] Duplicate webhooks and idempotent processing.
- [x] Pending/unknown payment status and reconciliation after timeout.
- [ ] Call drop/reconnect, DTMF validation, and safe IVR exits.
- [x] Provider signature validation and malformed webhook payloads.
- [x] Logs and error responses do not expose secrets.
- [x] Use a test network or provider sandbox for integration tests.

_A voice demo should prove inbound calling, language/menu navigation, authentication, and safe invalid-input handling. Demonstrate payments only in a test environment unless production controls have been reviewed._

---

## Deployment Considerations

- Deploy public endpoints behind HTTPS with a stable hostname.
- Configure provider callbacks and verify signatures.
- Keep credentials in protected deployment configuration or a secrets manager.
- Secure and back up database; test recovery.
- Monitor callback failures, payment reconciliation delays, database availability, and provider errors.
- Separate development, test, and production credentials.
- Confirm USSD code provisioning, voice number availability, local pricing, provider coverage, and applicable Nigerian regulatory obligations.

---

## Roadmap

### Phase 1 — Secure USSD Foundation

- Build and test USSD session/menu flows.
- Add English/Hausa copy.
- Implement supported Lightning flows.
- Add authorization, limits, idempotency, reconciliation, and receipts.

### Phase 2 — Voice Access

- Select a provider based on Nigerian coverage and price.
- Implement IVR state machine and DTMF.
- Add English/Hausa prompts.
- Reuse shared authentication and payment services.
- Test call drops, retries, invalid input, and uncertain payment status.

### Phase 3 — Broader Bitcoin Access

- Evaluate on-chain BTC support and recovery requirements.
- Research supported swap routes and their risks.
- Explore merchant settlement verification.
- Investigate fiat on/off-ramps only where providers, liquidity, settlement, and compliance are verified.

### Phase 4 — Reliability and Ecosystem

- Improve monitoring, backups, support, and incident response.
- Conduct security and usability reviews.
- Publish integration guides and invite open-source contributions.

---

## Contributing

Contributions are welcome in USSD flows, localization, provider adapters, webhook security, Lightning tests, payment reconciliation, IVR/DTMF handling, documentation, and deployment hardening.

Before submitting a pull request:

1. Describe the problem and change.
2. Add or update tests.
3. Document configuration changes.
4. Never include secrets, real user data, or wallet key material.
5. State which flows were tested and in what environment.

---

## License

Add a LICENSE file before publishing and choose a license that matches the project's goals. Do not imply that a license exists until it is present in the repository.

---

**SautiPay — Bitcoin access through familiar phone interfaces.**
