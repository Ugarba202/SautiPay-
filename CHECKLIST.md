# Demo-Day Checklist — SautiPay

**DevFest Kaduna Build-a-thon (Btrust Track) · 29 October 2026**

- [ ] **Voltage (or Polar) testnet node:** synced, 2+ channels with outbound, ≥5k testnet sats.
- [ ] `scripts/node_smoke.py` settles a real invoice (paste output into `demo_runs.log`).
- [ ] **Africa's Talking sandbox session:** registered; USSD code live; SMS sends working (or fallback phone confirmed).
- [ ] `RATE_OVERRIDE_NGN` set 30 min before demo (e.g. `1.847`); dashboard shows override badge.
- [ ] **Seed merchant:** PIN `1234`, mode `lock_ngn`, daily limit `50,000` (`python scripts/seed_demo.py`).
- [ ] **Dashboard open:** `http://localhost:8000` on judge-facing laptop.
- [ ] **Fallback phone view:** `http://localhost:8000/m` open on merchant phone on desk.
- [ ] `demo.py` executed 5× consecutively, clean (`demo_runs.log` verified).
- [ ] **Backup:** screen recording of one full clean run (recorded at rehearsal #5).
- [ ] **Presentation slides:**
  - The One Rule: Settlement verification required before notification.
  - Machankura menu screenshot showing merchant payment "not yet available".
  - 52% fake-alert fraud stat in Nigerian informal trade.
- [ ] **Honesty check:** Testnet-only honesty, "sender needs a Lightning wallet" honesty stated up-front.

