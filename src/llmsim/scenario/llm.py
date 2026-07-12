"""LLM adapter (design time only).

Wraps the optional ``anthropic`` extra to translate natural-language scenario
descriptions into the typed schema. Invoked only while authoring; never on any
code path once a simulation is running.
"""
