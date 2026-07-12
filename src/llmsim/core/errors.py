"""The engine's exception hierarchy.

Defines the base error type and the specific exceptions the core raises
(interrupts, stopped simulations, misuse of the event API) so callers can
catch engine faults distinctly from domain faults.
"""
