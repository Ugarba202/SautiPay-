# SautiPay

A Bitcoin Lightning wallet you operate from any phone call, SMS, or USSD dial. No app, no internet, no smartphone. Your phone number is your account; a keypad, text commands, and a voice menu are the interface.

Built for **DevFest Kaduna Build-a-thon (Btrust Track)**, October 2026.

---

## The idea

Hundreds of millions of people in Africa have a phone that does calls and SMS and nothing else. They are shut out of every Bitcoin wallet, because every wallet assumes a smartphone, an app store, and a reliable data connection.

At the same time, informal market merchants in Nigeria lose millions to **fake bank alert SMS and doctored transfer screenshots**.

**SautiPay puts a real Lightning wallet behind a phone number with cryptographic settlement verification:**

* **Call, dial, or text from any handset.** Your phone number is your account.
* **A 4-digit PIN**, hashed with `scrypt` and enforced by a decline-by-default security engine.
* **Receive to a human-readable Lightning address** tied to your number (`<phone>@sautipay.ng`).
* **Send by SMS in plain language or Hausa;** the backend calls you back to confirm with your PIN, so the PIN never travels in a message.
* **Dial USSD `*384#`** for instant interactive menus in English or Hausa.
* **Merchant Settlement Verification:** The notification service has **zero code path** that sends "PAYMENT RECEIVED" except an authoritative settlement event from our Lightning node (`SHA256(preimage) == invoice.payment_hash` and node confirmation).
* **Hash-Chained Receipt Ledger:** Every settlement mints an immutable, tamper-evident block into an append-only receipt chain verified from Genesis. If anyone tampers with a database row, the audit chain immediately flags it as compromised.
* **Multi-Rail Bitcoin Mobility:** Atomic swaps between Lightning BTC and on-chain cold storage.
* **Dual Value Modes:** Merchants choose between stacking Bitcoin (`keep_sats`) or locking fiat value at the stamped rate (`lock_ngn`).

---

## Status

Working end to end: USSD session engine (`*384#`), watch-only balance and receipts by SMS, sends with PIN confirmation, LND testnet settlement, tamper-evident receipt chaining, and multi-rail atomic swaps. The pieces:

1. **PIN-based security & limits:**
   * 4-digit PIN → `hashlib.scrypt` with a cryptographically secure random salt.
   * Brute-force protection: 3 wrong PIN attempts locks the account.
   * Spending limits: a per-send maximum (₦10,000 default) and a rolling 24-hour cap per user (₦50,000 default), checked before an intent is created and again at execution.
2. **The Lightning settlement engine:**
   * Connected to LND REST API.
   * **INV-1:** `settle()` succeeds iff `SHA256(preimage).hex() == invoice.payment_hash` **and** the node reports the invoice `SETTLED`.
   * **INV-2 Idempotency:** Duplicate settle calls or duplicate webhooks return the existing payment; no duplicate ledger entries or duplicate SMS alerts are ever generated.
3. **The Voice & Call-Back layer:**
   * Every prompt localized in **English and Hausa**.
   * State-changing SMS sends trigger a call-back where you hear the amount and recipient, enter your PIN on the keypad (DTMF), and only then is the payment made. The PIN never travels over plain SMS.
4. **The SMS command layer:**
   * A strict, table-driven regex parser turns text into actions (`balance`, `history`, `send <amount> to <phone>`, `address`).
   * Watch-only balance queries answer live from the ledger without needing a PIN.
5. **The Cryptographic Receipt Chain:**
   * Canonical hash: `SHA256(merchant_id | seq | invoice_id | amount_ngn | sats_per_ngn | value_mode | value_locked_ngn | prev_receipt_hash)`.
   * Continuous verification: recomputes all hashes from Genesis (`0000...`) and verifies gapless sequences.
6. **Multi-Rail BTC Swaps:**
   * Atomic HTLC swaps between Lightning BTC and on-chain Bitcoin.
   * State machine: `CREATED → PENDING → SUCCESS` or `REFUNDED` upon block timeout.
7. **Rate Oracle:**
   * Live CoinGecko BTC/NGN feed with 60-second caching.
   * Manual override `RATE_OVERRIDE_NGN` to guarantee 100% demo resilience if wifi lags.

---

## SMS Commands

| Text | What happens |
| :--- | :--- |
| `balance` · `kudi` · `bal` | Answered by SMS live from a watch-only read of the ledger (no PIN needed). |
| `history` · `tarihi` | Last verified receipt reference and amount sent by SMS. |
| `send 2000 to 08012345678` | Call-back initiated: backend rings your phone, reads the details, you confirm with your PIN. |
| `aika 2000 zuwa 08012345678` | Same, in Hausa. |
| `address` · `karba` | Returns your Lightning address (`<phone>@sautipay.ng`). |
| `help` · `madad` · `menu` | Command list by SMS. |

*A PIN in an SMS message is never accepted.*

---

## USSD Menu Tree (`*384#`)

```text
Dial *384#
├── Unregistered Phone
│   └── Choose Language: 1. English  2. Hausa
│       └── Enter 4-digit PIN → Account Created!
│
└── Registered Phone
    ├── 1. Balance & History (Enter PIN → Returns Sats, NGN, and Receipt count)
    ├── 2. Request Payment (Enter NGN → Enter PIN → Creates Lightning Invoice)
    ├── 3. Send to Phone (Enter recipient phone → Enter NGN → Enter PIN → Instant P2P transfer)
    ├── 4. Swap to On-Chain BTC (Enter sats → Enter on-chain address → Atomic swap)
    ├── 5. Settlement Mode (1. keep_sats  2. lock_ngn)
    └── 6. Switch Language (English ↔ Hausa toggle)
```

---

## Run

Requires Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 1. Seed Demo Merchant
```bash
python3 scripts/seed_demo.py
```
*Seeds merchant: `Phone: +2348012345678`, `PIN: 1234`, `Mode: lock_ngn`, `Daily Limit: ₦50,000`.*

### 2. Run the Full 9-Beat Automated Stage Demo
```bash
python3 demo.py
```
Runs the headless end-to-end stage script without human input:
1. **Problem beat:** Fake-alert scam context in Nigerian markets.
2. **USSD Request:** Merchant requests ₦2,000 via `*384#`.
3. **Settlement:** LND node confirms preimage $\rightarrow$ receipt minted $\rightarrow$ SMS dispatches.
4. **Ledger Audit:** Cryptographic verification from Genesis confirmed.
5. **Tamper Demo:** Modifying a database record immediately breaks the chain and triggers `TAMPER DETECTED`.
6. **Security Attack 1:** Replaying a consumed nonce is blocked fail-closed.
7. **Security Attack 2:** Over-limit spend (₦15,000) is blocked before wallet execution.
8. **Value Mode:** Switch between `lock_ngn` and `keep_sats`.
9. **Multi-Rail Swap:** Atomic HTLC swap moving 20,000 sats from Lightning to on-chain cold storage.

### 3. Run Test Suite
```bash
pytest tests
```
*37 unit and integration tests passing 100% green.*

---

## On a Real Phone (Live Telephony)

Point your Africa's Talking or Twilio webhooks at your public URL (e.g. via ngrok):

```bash
ngrok http 8000
```

1. **USSD Webhook:** Point USSD callback to `https://<public-url>/ussd` (POST).
2. **SMS Webhook:** Point incoming SMS callback to `https://<public-url>/sms` (POST).
3. **LND Settlement Hook:** Point LND webhook to `https://<public-url>/webhook/lnd` (POST).

Start the server:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open in browser:
* **Control Room:** `http://localhost:8000/` (Live node status, block visualization, invoices)
* **Receipt Chain Audit:** `http://localhost:8000/receipts/` (Cryptographic verification table)
* **Merchant Desk Phone View:** `http://localhost:8000/m` (Full-screen green `SETTLED` banner for fallback phone on desk)

---

## Production Checklist

* `PUBLIC_URL` is the HTTPS URL Africa's Talking / Twilio reaches.
* `LND_REST_URL` points to synced Voltage Cloud or Polar testnet node.
* `LND_MACAROON_HEX` uses least-privilege `invoice.macaroon`.
* `AT_USERNAME=sandbox` and `AT_API_KEY` configured in `.env`.
* `RATE_OVERRIDE_NGN` set (e.g. `1.847`) to guarantee 100% demo resilience regardless of external API outages.
* Database runs in SQLite WAL mode with foreign keys enforced.

---

## 30-Second Answers for Judges

* **"Isn't this Machankura?"**
  > "Machankura proved USSD Bitcoin and we respect their work, but their wallet stops at personal transfers — their menu literally marks merchant payments as 'not yet available'. SautiPay is the trust and settlement layer: our node independently verifies settlement and gives the merchant a hash-chained receipt a scammer cannot fake."

* **"How do you know it settled?"**
  > "Two independent proofs: `SHA256(preimage)` must match the invoice's payment hash, and our LND node must confirm the invoice is `SETTLED`. Only then is a receipt minted and only then does the SMS fire. There is no other code path in `app/settlement.py`."

* **"What about volatility?"**
  > "The merchant picks: keep sats, or lock naira — in `lock_ngn` mode, the receipt records the exact value at the stamped rate. Sats are the rail; the unit of account is the merchant's choice."

* **"Is the SMS fakeable?"**
  > "The SMS is just a notification. The receipt it references verifies cryptographically against the hash chain on our ledger. Anyone can forge a bank alert SMS; no one can fake a receipt that validates against prior hashes."

* **"Who controls the Bitcoin keys?"**
  > "SautiPay operates a secure backend wallet engine (server-side signing) protected by memory-hard `scrypt` PIN hashing, strict spending limits, and an auditable ledger. For high-value spends, SautiPay calls the user back so the PIN is entered over audio tones (DTMF), never plaintext SMS."

---

## Honesty Lines (Non-Negotiables)

1. **Testnet / Sandbox Only:** Built and verified for testnet/regtest; no mainnet funds used.
2. **Naira Lock Commitment:** Value in `lock_ngn` mode is an internal ledger commitment redeemable via future agent desks — real fiat conversion is on the roadmap.
3. **Wallet Requirement:** The buyer needs a standard Lightning-capable wallet; SautiPay is the merchant receiving leg.
4. **Telecom Sandbox:** Africa's Talking sandbox is used for demo USSD and SMS.
5. **Prior Art:** We build upon the work of Machankura, LNpesa, DialSats, and BOLT11/LND.
