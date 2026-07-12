"""Parallel discrete-event simulation of a single model.

Conservative (YAWNS-style) sharding: the model is partitioned into logical
processes that advance in lockstep within a computed safe window, exchanging
timestamped messages over channels. Optimistic/Time Warp is permanently
rejected because generator frames cannot be snapshotted.
"""
