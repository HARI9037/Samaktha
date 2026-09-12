"""Docling is quarantined from the core pilot after Windows DLL faults.

Keep the adapter source for engineering work. Re-enablement requires isolated
process validation; merely installing its package must not activate it.
"""


def docling_enabled() -> bool:
    return False
