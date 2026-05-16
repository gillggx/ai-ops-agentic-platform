"""tools.trace_replay — replay LLM decisions from build traces under
controlled variants.

Pair with BuildTracer (python_ai_sidecar/agent_builder/graph_build/trace.py).
Given a trace JSON, pick any captured LLM call and re-run it N times with
the original prompt vs one or more transformations (variants). Surfaces
whether a prompt change actually shifts LLM behaviour — empirical, not
theoretical.

See README.md for usage.
"""
