"""Every durable owned store must have an explicit finite candidate budget."""
import json
from pathlib import Path


def test_all_durable_store_budgets_are_explicit_and_finite():
    limits = json.loads((Path(__file__).resolve().parents[2] / 'deploy/stack/bundle.json').read_text())['limits']
    for role in ('server', 'bridge', 'mongo', 'fence'):
        value = limits[role]['stateBytes']
        assert type(value) is int and 32 * 1024**2 <= value <= 4 * 1024**3
