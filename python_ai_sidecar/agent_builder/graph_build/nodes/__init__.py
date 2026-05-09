"""Graph nodes — each is a pure async function with signature
    (state) → state_update_dict.

LLM nodes call get_llm_client(); pure nodes never do.
"""
