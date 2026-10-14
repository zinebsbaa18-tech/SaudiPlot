"""Approved architectural case ingestion (M6A): IFC -> reviewable design case.

Nothing here generates designs. A case ingested by this package stops at
``requires_review`` and can never be consumed as a template unless it passes
the objective eligibility policy and a human reviewer supplies explicit,
fingerprint-bound approval metadata.
"""
