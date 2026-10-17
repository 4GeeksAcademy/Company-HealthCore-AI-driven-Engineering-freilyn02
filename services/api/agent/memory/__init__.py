"""Agent memory (MEM-092): explicit store, single pending proposal, audit log, consolidation.

Nothing in this package writes to the company RAG (`*_knowledge`) collections.
Memory lives in its own Redis database (`agent_memory:` key prefix).
"""
