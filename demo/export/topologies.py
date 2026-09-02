"""Shared topology definitions for the demo: exported once by export_scenario.py
into static JSON, and reconstructed identically (same size + seed) by the
push-pull scoring backend at request time. Keep this the single source of
truth for both so they never drift apart.
"""

TOPOLOGIES = [
    dict(id="medium", label="Reef", network_size=12, seed=None),
    dict(id="large", label="Grand Reef", network_size=24, seed=1024),
]
