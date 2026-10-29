import pytest
from demo import run_demo

def test_full_demo_headless_flow():
    # Runs the full 8-beat stage script
    run_demo(mock_lightning=True)

