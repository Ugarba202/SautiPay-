#!/usr/bin/env python3
"""
demo.py — SautiPay 3-Minute Stage Demo Script (Headless Runner)

Runs the exact 3-minute stage flow without human input:
1. Problem Beat: Fake alert / screenshot scam context.
2. USSD Payment Request: Merchant requests ₦2,000 via USSD session (*384#).
3. Lightning Settlement: Node confirms payment -> Settle -> Mint Receipt -> Send SMS.
4. Cryptographic Proof: Verify receipt hash chain passes.
5. Tamper Demonstration: Modify receipt in database -> Verify fails!
6. Security Attack 1: Replay attack with consumed nonce -> Blocked!
7. Security Attack 2: Over-limit transaction (₦15,000) -> Blocked!
8. Value Mode Toggle: Switch merchant between lock_ngn and keep_sats.
"""
import sys
import os
import argparse
import time
import hashlib
import uuid

# Add sautipay to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "sautipay")))

from app.models import init_db, db_session
from app.ledger import Ledger
from app.settlement import settle
from app.ussd_handler import ussd_handler
from app.demo_mode import DemoSimulator
from app.lightning_service import LightningService
from scripts.seed_demo import seed, DEMO_MERCHANT_ID, DEMO_PHONE, DEMO_PIN

class MockLightningForDemo(LightningService):
    def __init__(self):
        super().__init__()
        self.preimage_store = {}

    def create_invoice(self, amount_msat: int, memo: str = "", expiry_seconds: int = 600):
        preimage = hashlib.sha256(str(time.time()).encode("utf-8")).hexdigest()
        payment_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
        self.preimage_store[payment_hash] = preimage
        return payment_hash, f"lnbc_testnet_invoice_{payment_hash[:16]}"

    def lookup_invoice(self, payment_hash_hex: str):
        preimage = self.preimage_store.get(payment_hash_hex, "00" * 32)
        return "SETTLED", preimage

def print_beat(beat_num: int, title: str, text: str):
    print(f"\n=======================================================")
    print(f"🎬 BEAT {beat_num}: {title.upper()}")
    print(f"=======================================================")
    print(f"{text}\n")
    time.sleep(1)

def run_demo(mock_lightning: bool = True):
    print("=" * 60)
    print("   SAUTIPAY — 3-MINUTE HACKATHON STAGE DEMO RUNNER")
    print("   'Verify the payment, not the screenshot.'")
    print("=" * 60)

    # Initialize and seed
    init_db()
    seed()
    ledger = Ledger()

    # Look up the actual merchant ID from the phone
    with db_session() as conn:
        m_row = conn.execute("SELECT id FROM merchants WHERE phone = ?", (DEMO_PHONE,)).fetchone()
        actual_merchant_id = m_row["id"] if m_row else DEMO_MERCHANT_ID

    # Ensure rate oracle has a fallback/override for smooth headless demo
    from app.config import settings
    if not settings.RATE_OVERRIDE_NGN:
        settings.RATE_OVERRIDE_NGN = 1.847

    demo_lnd = MockLightningForDemo()
    if mock_lightning:
        ussd_handler.lnd = demo_lnd

    # BEAT 1: PROBLEM FRAMING
    print_beat(
        1,
        "The Problem — Fake Alerts in Nigerian Markets",
        "A fabric seller in Kaduna Central Market has a basic phone. Scammers show fake screenshots\n"
        "or forged bank alert SMS. Today's Lightning solutions offer wallets (Machankura), but\n"
        "merchant settlement is 'not yet available'. SautiPay builds the merchant trust layer."
    )

    # BEAT 2: USSD PAYMENT REQUEST
    print_beat(
        2,
        "Merchant Requests ₦2,000 via USSD (*384#)",
        "Merchant dials *384# on feature phone, enters ₦2000, enters PIN 1234."
    )
    sess_id = f"demo_sess_{int(time.time())}"
    # Turn 1: Main menu
    r1 = ussd_handler.handle(sess_id, DEMO_PHONE, "")
    print(f"[PHONE SCREEN]:\n{r1}\n")
    # Turn 2: Select 1 (Request Payment)
    r2 = ussd_handler.handle(sess_id, DEMO_PHONE, "1")
    print(f"[PHONE SCREEN]:\n{r2}\n")
    # Turn 3: Enter 2000 NGN
    r3 = ussd_handler.handle(sess_id, DEMO_PHONE, "1*2000")
    print(f"[PHONE SCREEN]:\n{r3}\n")
    # Turn 4: Enter PIN 1234
    r4 = ussd_handler.handle(sess_id, DEMO_PHONE, "1*2000*1234")
    print(f"[PHONE SCREEN]:\n{r4}\n")

    # Fetch the newly created invoice from DB
    with db_session() as conn:
        inv = dict(conn.execute("SELECT * FROM invoices ORDER BY created_at DESC LIMIT 1").fetchone())

    print(f"✓ Invoice Stamped & Created in Database: {inv['id']}")
    print(f"  Amount: ₦{inv['amount_ngn']} ({inv['amount_msat'] // 1000} sats at {inv['sats_per_ngn']} sats/NGN)")
    print(f"  Payment Hash: {inv['payment_hash']}")

    # BEAT 3: LIGHTNING SETTLEMENT & SMS
    print_beat(
        3,
        "Lightning Settlement Verification & Immutable Mint",
        "Customer pays from any Lightning wallet. Node confirms settlement.\n"
        "INV-1: Both SHA256(preimage) matches AND LND confirms SETTLED.\n"
        "Only then does a receipt mint into the ledger, and only then does SMS fire."
    )
    # Generate preimage
    demo_lnd = MockLightningForDemo()
    if mock_lightning:
        # Preimage matching payment hash
        preimage = hashlib.sha256(f"secret_preimage_{inv['id']}".encode()).hexdigest()
        # Patch payment hash in DB for mock testing
        real_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
        with db_session() as conn:
            conn.execute("UPDATE invoices SET payment_hash = ? WHERE id = ?", (real_hash, inv["id"]))
        demo_lnd.preimage_store[real_hash] = preimage
        payment = settle(inv["id"], preimage, lnd_client=demo_lnd)
    else:
        # Real node execution
        from app.lightning_service import lightning_service
        state, preimage = lightning_service.lookup_invoice(inv["payment_hash"])
        if state != "SETTLED" or not preimage:
            print(f"[WARN] Live node reports invoice state: {state}. Please pay {inv['payment_request']}.")
            return
        payment = settle(inv["id"], preimage)

    print(f"✓ SETTLEMENT CONFIRMED BY NODE! Payment ID: {payment['id']}")
    print(f"✓ Minted Canonical Receipt Hash: {payment['receipt_hash']}")

    # BEAT 4: CRYPTOGRAPHIC RECEIPT CHAIN AUDIT
    print_beat(
        4,
        "Audit Ledger Integrity",
        "Auditing merchant hash chain against genesis..."
    )
    is_valid = ledger.verify_chain(actual_merchant_id)
    print(f"✓ Ledger Cryptographic Verification: {'VALID & UNTAMPERED' if is_valid else 'FAILED'}")
    assert is_valid is True

    # BEAT 5: LIVE TAMPER DEMONSTRATION
    print_beat(
        5,
        "Tamper Demonstration — Rogue DB Edit Detected",
        "Attempting to alter the receipt amount in SQLite without node proof."
    )
    tampered, msg = DemoSimulator.tamper_latest_receipt(actual_merchant_id, new_amount_ngn=99999)
    print(f"Action: {msg}")
    is_valid_after_tamper = ledger.verify_chain(actual_merchant_id)
    print(f"Ledger Verification After Tampering: {'VALID' if is_valid_after_tamper else 'TAMPER DETECTED (REJECTED)'}")
    assert is_valid_after_tamper is False
    # Restore receipt for subsequent tests
    with db_session() as conn:
        conn.execute("UPDATE receipts SET amount_ngn = 2000 WHERE merchant_id = ?", (actual_merchant_id,))
    print("✓ Receipt restored to original state.")

    # BEAT 6: SECURITY ATTACK 1 — REPLAY ATTACK BLOCKED
    print_beat(
        6,
        "Security Engine — Replay Attack Blocked",
        "An attacker captures an old authorization nonce and attempts to replay it."
    )
    from app.security_engine import security_engine
    test_intent = security_engine.create_intent(actual_merchant_id, 2000)
    security_engine.consume_intent(test_intent["nonce"], actual_merchant_id, DEMO_PIN)
    # Second consume must fail!
    blocked, replay_msg = DemoSimulator.simulate_replay_attack(actual_merchant_id, test_intent["nonce"])
    print(f"✓ Result: {replay_msg}")
    assert blocked is True

    # BEAT 7: SECURITY ATTACK 2 — OVER-LIMIT BLOCKED
    print_beat(
        7,
        "Security Engine — Over-Limit Transaction Blocked",
        "A merchant or malicious caller attempts a ₦15,000 transaction (Cap is ₦10,000)."
    )
    blocked_limit, limit_msg = DemoSimulator.simulate_over_limit_attack(actual_merchant_id, excessive_amount=15000)
    print(f"✓ Result: {limit_msg}")
    assert blocked_limit is True

    # BEAT 8: SETTLEMENT MODE TOGGLE
    print_beat(
        8,
        "Merchant Value Mode — lock_ngn vs keep_sats",
        "Merchant dials USSD and switches mode from lock_ngn to keep_sats."
    )
    mode_sess = f"mode_sess_{int(time.time())}"
    ussd_handler.handle(mode_sess, DEMO_PHONE, "")
    ussd_handler.handle(mode_sess, DEMO_PHONE, "3")
    mode_resp = ussd_handler.handle(mode_sess, DEMO_PHONE, "3*1") # 1 = keep_sats
    print(f"[PHONE SCREEN]:\n{mode_resp}\n")

    # BEAT 9: BTC SWAP (LIGHTNING <-> ON-CHAIN)
    print_beat(
        9,
        "Multi-Rail Bitcoin Mobility — Lightning ↔ On-Chain BTC Swap",
        "Merchant swaps 20,000 sats from Lightning to their on-chain savings address via atomic HTLC."
    )
    from app.swap_service import swap_service
    onchain_dest = "tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx"
    swap = swap_service.create_swap(actual_merchant_id, "ln_to_btc", 20000, onchain_dest)
    print(f"✓ Atomic Swap Created: ID={swap['swap_id'][:8]}...")
    print(f"  Direction: Lightning → On-Chain BTC")
    print(f"  Fee: {swap['fee_sats']} sats (0.5%), Net Output: {swap['net_sats']} sats")
    print(f"  Lock Contract: Timeout at block {swap['timeout_block']}, Preimage Hash: {swap['payment_hash'][:12]}...")
    
    # Reveal preimage & claim swap
    settled_swap = swap_service.execute_and_claim_swap(swap["swap_id"])
    print(f"✓ SWAP ATOMICALLY SETTLED & CLAIMED!")
    print(f"✓ Swap Receipt Chained to Ledger: {settled_swap['receipt_hash'][:16]}...\n")

    print("\n" + "=" * 60)
    print("🎉 DEMO COMPLETE: All 8 beats executed flawlessly!")
    print("   Open http://localhost:8000 on laptop to view the live Control Room.")
    print("   Open http://localhost:8000/m on mobile for the fallback phone view.")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run SautiPay Headless Demo")
    parser.add_argument("--real-lightning", action="store_true", help="Run against real LND node instead of mock")
    args = parser.parse_args()

    run_demo(mock_lightning=not args.real_lightning)
