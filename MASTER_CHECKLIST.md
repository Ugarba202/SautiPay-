# 🏆 SautiPay Master Execution Checklist (Hackathon Winning Path)

**Target:** Flawless live demonstration, zero stage crashes, and 100% judge confidence.

---

## Phase 1: Core Engine & Data Integrity (ALREADY VERIFIED)
- [x] SQLite WAL mode & foreign key constraints active (`sautipay.db`).
- [x] Cryptographic Hash-Chained Receipt Ledger (`app/ledger.py`, `app/receipt_chain.py`).
- [x] LND REST Client & Preimage Settlement Verifier (`app/settlement.py`).
- [x] scrypt PIN security, nonces, and decline-by-default engine (`app/security_engine.py`).
- [x] CoinGecko Rate Oracle with 60s cache and manual override (`app/rate_oracle.py`).
- [x] Atomic BTC Swaps between Lightning and On-Chain BTC (`app/swap_service.py`).
- [x] 37 pytest tests passing 100% green.

---

## Phase 2: Complete Phone Channels & Advanced Features (TO LOCK IN NOW)

### A. USSD Menu Expansion (`app/ussd_handler.py`)
- [ ] **First-Time User Registration Flow:**
  - Auto-detect unregistered phone numbers.
  - Language selection: `1. English`, `2. Hausa`.
  - Set secret 4-digit PIN.
  - Confirm account creation without needing web access.
- [ ] **Menu Options:**
  - `1. Balance & Tarihi` (receipt count + sats/NGN value).
  - `2. Nemi Biya (Request Payment / Invoice)`.
  - `3. Tura Kudi (Send to Phone Number)` (Instant internal phone-to-phone transfer).
  - `4. Musanya (Swap to On-Chain BTC)` (Atomic swap to cold storage).
  - `5. Zabi Moda (Mode: keep_sats vs lock_ngn)`.
  - `6. Yare / Language (Switch English <-> Hausa)`.

### B. SMS Command Parser & Watch-Only Queries (`app/sms_handler.py`)
- [ ] **Watch-Only Balance (No PIN required):**
  - Text `balance` or `kudi` → receive immediate SMS with balance & latest receipt.
- [ ] **Send Command with Call-Back Safety:**
  - Text `send 2000 to 08012345678` → SautiPay creates intent and triggers voice call-back for PIN confirmation.
- [ ] **Help & Menu:**
  - Text `help` or `madad` → list accepted commands.

### C. Voice Call / IVR Engine (`app/voice_handler.py`)
- [ ] Inbound call webhook (`POST /voice`) compatible with Africa's Talking / Twilio.
- [ ] Spoken prompts in clear English and Hausa.
- [ ] DTMF keypad PIN collection and authorization.
- [ ] Call-back endpoint (`POST /voice/callback`) for authorizing outbound sends.

### D. Enhanced Web Admin Control Room (`app/dashboard.py`)
- [ ] **Swaps Monitor Tab:** View active, claimed, and refunded atomic swaps.
- [ ] **Live Phone Simulator on Web:** A clickable virtual keypad directly on the Admin Dashboard so judges can see USSD/SMS work without needing telecom signals.
- [ ] **One-Click Attack Demos:**
  - *Button: "Simulate Replay Attack"* → visually shows rejection.
  - *Button: "Simulate Rogue DB Tamper"* → turns chain indicator red.
  - *Button: "Simulate Over-Limit Spend"* → visually shows decline.

---

## Phase 3: External Live API Integration (When You Provide Keys)
- [ ] **LND Node:** Paste `LND_REST_URL` and `LND_MACAROON_HEX` into `.env`.
- [ ] **Africa's Talking:** Paste `AT_USERNAME=sandbox` and `AT_API_KEY` into `.env`.
- [ ] **Live Node Smoke Test:** Execute `python scripts/node_smoke.py`.
- [ ] **Live USSD Webhook:** Connect ngrok public URL to Africa's Talking sandbox.

---

## Phase 4: Stage Demo Rehearsals
- [ ] Execute `python sautipay/demo.py` 5 consecutive times clean.
- [ ] Verify judge screen on `http://localhost:8000`.
- [ ] Verify merchant desk fallback on `http://localhost:8000/m`.
- [ ] Record 1 backup screen capture of a clean run.

