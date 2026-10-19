"""Tunable limits for RFP response generation (Milestone 9, Part 2)."""

# Hard cap of generate -> evaluate attempts per department section.
MAX_ITERATIONS = 3

# Readability gate (Flesch-Kincaid grade level). Business text, so not too strict.
READABILITY_MAX_GRADE = 12.0
# py-readability-metrics refuses texts shorter than 100 words.
MIN_WORDS_FOR_READABILITY = 100

# LLM resilience: departments run in parallel, so rate limits / transient errors happen.
LLM_ATTEMPTS = 4
LLM_RETRY_BASE_DELAY = 2.0  # seconds; doubles on every retry (2, 4, 8)
