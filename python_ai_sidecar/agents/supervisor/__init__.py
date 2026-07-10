"""Supervisor — knowledge/rule curation proposals (public API).

Implementation: python_ai_sidecar/supervisor_curation/. Proposals ALWAYS land
in the human review queue (/supervisor GUI); no agent approves anything.
"""
from python_ai_sidecar.supervisor_curation import proposer  # noqa: F401

__all__ = ["proposer"]
