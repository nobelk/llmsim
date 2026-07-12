"""The conservative synchronization barrier.

Computes the global safe window (YAWNS: lower-bound time stamp plus lookahead)
each round so every shard may process its due events without risk of receiving
an earlier-timestamped message.
"""
