"""Limited-capacity ``Resource``.

Models a pool of interchangeable servers: processes request a slot, hold it for
some service time, and release it, with waiters queued until capacity frees.

``Resource`` grants in FIFO order; ``PriorityResource`` grants by request
priority; ``PreemptiveResource`` lets a higher-priority request bump a lower one
by interrupting the holder.
"""

import bisect
from operator import attrgetter
from types import TracebackType
from typing import TYPE_CHECKING, Any

from llmsim.resources import base

if TYPE_CHECKING:
    from llmsim.core.sim import Sim

# Sort key of a queued priority request, hoisted out of the insert loop so no
# per-append lambda is allocated.
_request_key = attrgetter("key")


class Preempted:
    """The cause of a preemption :class:`~llmsim.core.errors.Interrupt`."""

    __slots__ = ("by", "usage_since", "resource")

    def __init__(
        self, by: Any, usage_since: float | None, resource: "Resource"
    ) -> None:
        """Record who preempted, since when the slot was held, and which resource."""
        #: The process whose request preempted the holder.
        self.by = by
        #: The time the preempted process acquired the slot.
        self.usage_since = usage_since
        #: The resource whose slot was lost.
        self.resource = resource


class Request(base.Put):
    """Request a usage slot; triggered once one is granted.

    Auto-releases the slot on ``with`` exit (except on ``GeneratorExit``, whose
    cleanup would otherwise create unclaimable reference cycles).
    """

    __slots__ = ("usage_since",)

    def __init__(self, resource: "Resource") -> None:
        """Create a request against *resource*."""
        #: The time the request was granted, or ``None`` while pending.
        self.usage_since: float | None = None
        super().__init__(resource)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Cancel a pending request and release a granted one on block exit."""
        super().__exit__(exc_type, exc_value, traceback)
        if exc_type is not GeneratorExit:
            assert isinstance(self.resource, Resource)
            self.resource.release(self)


class Release(base.Get[None]):
    """Release a slot previously granted by a :class:`Request`.

    Triggered immediately; releasing always succeeds whether or not the request
    currently holds a slot.
    """

    __slots__ = ("request",)

    def __init__(self, resource: "Resource", request: Request) -> None:
        """Create a release of *request* against *resource*."""
        #: The request whose slot is being released.
        self.request = request
        super().__init__(resource)


class PriorityRequest(Request):
    """A :class:`Request` carrying a priority (and preemption flag).

    A smaller *priority* number means higher priority. Ties break by request
    time, then by preemption flag (preempting requests sort ahead).
    """

    __slots__ = ("priority", "preempt", "time", "key")

    def __init__(
        self, resource: "Resource", priority: int = 0, preempt: bool = True
    ) -> None:
        """Create a prioritized request against *resource*."""
        #: Requested priority (lower is more important).
        self.priority = priority
        #: Whether this request may preempt a lower-priority holder.
        self.preempt = preempt
        #: The time the request was made.
        self.time = resource._sim.now
        #: Sort key: (priority, time, not preempt) -- all "smaller is first".
        self.key = (priority, self.time, not preempt)
        super().__init__(resource)


class SortedQueue(list[Any]):
    """A put queue that keeps :class:`PriorityRequest`s ordered by their key."""

    __slots__ = ("maxlen",)

    def __init__(self, maxlen: int | None = None) -> None:
        """Create an empty queue with an optional length bound."""
        super().__init__()
        self.maxlen = maxlen

    def append(self, item: Any) -> None:
        """Insert *item* in key order (stable for equal keys).

        Raises:
            RuntimeError: if the queue is already at ``maxlen``.
        """
        if self.maxlen is not None and len(self) >= self.maxlen:
            raise RuntimeError("cannot append request: queue is full")
        # Insert at the key-sorted position instead of re-sorting the whole
        # queue: O(n) shift rather than O(n log n), and no per-call lambda.
        # ``insort`` inserts after equal keys, matching the stable order a full
        # sort would give.
        bisect.insort(self, item, key=_request_key)


class Resource(base.BaseResource[Request, Release]):
    """A pool of *capacity* interchangeable slots requested and released by processes.

    Requests beyond capacity queue in FIFO order and are granted as slots free.
    """

    __slots__ = ("users", "queue")

    def __init__(self, sim: "Sim", capacity: int = 1) -> None:
        """Create a resource with *capacity* slots.

        Raises:
            ValueError: if *capacity* is not positive.
        """
        super().__init__(sim, capacity)
        #: Requests currently holding a slot.
        self.users: list[Request] = []
        #: Alias of :attr:`~llmsim.resources.base.BaseResource.put_queue`.
        self.queue = self.put_queue

    @property
    def count(self) -> int:
        """The number of slots currently in use."""
        return len(self.users)

    def request(self) -> Request:
        """Request a usage slot."""
        return Request(self)

    def release(self, request: Request) -> Release:
        """Release the slot held by *request*."""
        return Release(self, request)

    def _do_put(self, event: Request) -> bool | None:
        """Grant *event* a slot if capacity allows."""
        if len(self.users) < self._capacity:
            self.users.append(event)
            event.usage_since = self._sim.now
            event.succeed()
        return None

    def _do_get(self, event: Release) -> bool | None:
        """Free the released request's slot, always succeeding."""
        try:
            self.users.remove(event.request)
        except ValueError:
            pass
        event.succeed()
        return None


class PriorityResource(Resource):
    """A :class:`Resource` that grants queued requests by ascending priority."""

    __slots__ = ()

    PutQueue: type[list[Any]] = SortedQueue
    GetQueue: type[list[Any]] = list

    def request(self, priority: int = 0, preempt: bool = True) -> PriorityRequest:
        """Request a usage slot at the given *priority*."""
        return PriorityRequest(self, priority, preempt)


class PreemptiveResource(PriorityResource):
    """A :class:`PriorityResource` whose holders can be preempted.

    A request that cannot be granted may bump the lowest-priority current holder
    -- if that holder ranks below the request -- by removing it and interrupting
    its process with a :class:`Preempted` cause.
    """

    __slots__ = ()

    def _do_put(self, event: Request) -> bool | None:
        """Preempt a lower-priority holder if needed, then grant if possible."""
        assert isinstance(event, PriorityRequest)
        if len(self.users) >= self._capacity and event.preempt:
            # The lowest-priority holder is the one with the largest key.
            preempted = max(self.users, key=_request_key)
            assert isinstance(preempted, PriorityRequest)
            if preempted.key > event.key:
                self.users.remove(preempted)
                assert preempted.proc is not None
                preempted.proc.interrupt(
                    Preempted(
                        by=event.proc,
                        usage_since=preempted.usage_since,
                        resource=self,
                    )
                )
        return super()._do_put(event)
