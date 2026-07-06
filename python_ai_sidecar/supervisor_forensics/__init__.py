"""Supervisor trace forensics (W3) — offline, PROPOSE-ONLY.

Reads /tmp/builder-traces/*.json, aggregates failure / loop-stuck signals
per block, deep-dives the top hotspots with a bounded number of LLM calls,
and queues DOC_REVISE / PROMOTE / ISSUE / CFG proposals for human review in
/supervisor. Never mutates agent_knowledge / block docs directly.
"""
