# SautiPay — Master Product Requirements Document (PRD v2.0)

**Project:** SautiPay  
**Theme:** "The OPay for Bitcoin in Africa" — A Phone-First Bitcoin Wallet Engine  
**Event:** DevFest Kaduna Build-a-thon (Btrust Track) · October 2026  
**Status:** LOCKED FOR BUILD

---

## 1. Executive Summary & Value Proposition

SautiPay is a phone-first Bitcoin and Lightning wallet engine designed for African informal trade. It allows anyone with an ordinary feature phone (no smartphone, no internet, no mobile app) to send, receive, swap, and manage Bitcoin using familiar phone channels: **USSD (`*384#`)**, **SMS**, and **Voice Phone Calls (IVR)**.

### The Problem It Solves:
1. **Digital Exclusion:** 100M+ Africans are shut out of Bitcoin because existing wallets require smartphones, app stores, and reliable data connections.
2. **Fake Alert & Screenshot Scams:** Nigerian market merchants frequently suffer losses from forged bank alert SMS and fake transfer screenshots.
3. **The Missing Merchant Rail:** Existing services like Machankura enable personal send/receive, but merchant settlement verification is explicitly marked *"not yet available"*.

### The SautiPay Solution:
* **Your Phone Number is Your Account:** Familiar, zero-friction access.
* **Settlement Verification Core:** A payment is marked `PAID` / `SETTLED` **only** when our Lightning node confirms the preimage match.
* **Hash-Chained Receipt Ledger:** Every settlement mints an immutable, tamper-evident cryptographic receipt.
* **Multi-Channel Parity:** USSD, SMS, Voice Calls, and Web Admin all talk to one unified backend engine.
* **DialSats Security:** Sensitive spends trigger an automatic **voice call-back** to collect the user's PIN via keypad tones (DTMF), ensuring PINs never travel over plain SMS.
* **Bilingual Native:** Full Hausa and English prompts.

---

## 2. System Architecture & Channels

```
                                ┌────────────────────────────────────────┐
                                │             SAUTIPAY CORE              │
                                │         Backend Wallet Engine          │
                                └────────────────────────────────────────┘
                                                    │
                ┌───────────────────┬───────────────┴───────────────┬───────────────────┐
                ▼                   ▼                               ▼                   ▼
        [1. USSD (*384#)]     [2. SMS Parser]               [3. Voice / IVR]      [4. Web Admin]
        Africa's Talking      Plain-text & watch-only       Inbound calls &       Control Room,
        interactive menus     balance queries               call-back for PIN     live chain audit,
        (Hausa/English)       (No PIN in SMS)               confirmation          invoices & swaps
```

---

## 3. Product Features & User Stories

### A. Phone-First Onboarding & Identity
* **Auto-Registration:** First dial to `*384#` or first SMS prompt initiates language selection (Hausa/English) and 4-digit PIN setup.
* **Phone Identifier:** Accounts are identified by normalized phone numbers (`+234...`).
* **Human-Readable Lightning Address:** Every user is allocated `<phone>@sautipay.ng`.

### B. Wallet Operations
* **Balance & History:** Checked via USSD option 1, voice call, or texting `balance` / `kudi` via SMS (watch-only, zero PIN risk).
* **Receive (Lightning):** Generates BOLT11 invoices or receives directly via Lightning Address.
* **Send (Phone-to-Phone & External):** Instant off-chain transfer between SautiPay phone numbers, or outbound Lightning payment via invoice.
* **BTC Swaps (Multi-Rail):** Atomic HTLC swaps between Lightning BTC and on-chain cold storage.
* **Value Mode:** Merchant choice between stacking Bitcoin (`keep_sats`) or locking fiat value (`lock_ngn`).

### C. The Anti-Fraud Settlement Trust Layer
* **INV-1:** Settlement proof strictly requires `SHA256(preimage) == invoice.payment_hash` **and** node status `SETTLED`.
* **INV-2:** Idempotent operations prevent duplicate settlements or duplicate SMS alerts.
* **INV-6:** Zero code path exists to send "PAYMENT RECEIVED" except verified node settlement.
* **Cryptographic Ledger:** Append-only receipt chain verified from Genesis. Tampering with any historical database row breaks chain validity immediately.

### D. Advanced Security (The DialSats Gem)
* **Call-Back for PIN:** High-value sends initiated by SMS trigger an automated call to the user. The user hears the transaction details and types their PIN on their keypad.
* **Brute-Force Lock:** 3 incorrect PIN attempts locks the account.
* **Spending Caps:** Per-transaction limit (₦10,000 default) and rolling 24-hour daily volume cap (₦50,000 default).

### E. Web Admin Control Room
* Real-time oversight dashboard at `http://localhost:8000`:
  * Node & Rate Oracle health telemetry.
  * Live interactive Hash-Chained Receipt block visualization.
  * Recent invoices & settlement state feed.
  * Merchant registry, balances, and security lock statuses.
  * Live swap status monitor.
  * Desktop phone fallback terminal at `/m`.

