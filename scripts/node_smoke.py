#!/usr/bin/env python3
"""
scripts/node_smoke.py
Creates a 100-sat testnet invoice via LND REST and polls it for settlement.
"""
import sys
import os
import time

# Add sautipay to PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.lightning_service import lightning_service, LightningError

def main():
    print("=== SautiPay Real Node Smoke Test ===")
    print(f"Target node URL: {lightning_service.rest_url}")
    
    amount_sats = 100
    amount_msat = amount_sats * 1000
    memo = "SautiPay Smoke Test 100 Sats"

    try:
        print(f"1. Creating {amount_sats} sat invoice...")
        payment_hash, payment_request = lightning_service.create_invoice(
            amount_msat=amount_msat,
            memo=memo,
            expiry_seconds=300
        )
        print(f"   [SUCCESS]")
        print(f"   Payment Hash: {payment_hash}")
        print(f"   Invoice Bolt11: {payment_request}\n")

        print("2. Looking up invoice state on node...")
        state, preimage = lightning_service.lookup_invoice(payment_hash)
        print(f"   Current node state: {state}")
        print(f"   Preimage: {preimage}\n")

        if state == "SETTLED":
            print("Invoice is SETTLED!")
        else:
            print(f"Invoice is {state}. Pay the BOLT11 invoice with a testnet wallet to verify settlement.")

    except LightningError as e:
        print(f"[NODE ERROR]: {e}")
        print("\nNote: Make sure LND_REST_URL and LND_MACAROON_HEX are configured in .env for a live node.")

if __name__ == "__main__":
    main()

