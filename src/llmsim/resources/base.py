"""Common base for resource types.

Factors out the shared request/release queue mechanics (put/get event
bookkeeping, FIFO/priority ordering) reused by ``Resource``, ``Container``,
and ``Store``.

The single machine here -- one ``put_queue``, one ``get_queue``, and the
``_trigger_put``/``_trigger_get`` retry chain -- is the one code path every
concrete resource shares (DRY). A concrete resource only supplies ``_do_put``
and ``_do_get``: whether a queued request can be satisfied now, and the side
effect of satisfying it.
"""

from types import TracebackType
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from llmsim.core.events import Event

if TYPE_CHECKING:
    from llmsim.core.sim import Sim

T = TypeVar("T")
PutType = TypeVar("PutType", bound="Put")
GetType = TypeVar("GetType", bound="Get[Any]")


class Put(Event[None]):
    """A request to put something into a resource, granted when there is room.

    Usable as a context manager so an aborted request (for example one whose
    process is interrupted while waiting) is cancelled -- removed from the
    resource's queue -- on ``with`` exit::

        with resource.put(item) as request:
            yield request
    """

    __slots__ = ("resource", "proc")

    def __init__(self, resource: "BaseResource[Any, Any]") -> None:
        """Enqueue this put on *resource* and try to satisfy it at once."""
        sim = resource._sim
        super().__init__(sim)
        self.resource = resource
        #: The process that issued this request (used for preemption), or None.
        self.proc = sim._active_process
        resource.put_queue.append(self)
        # When this put is finally granted, a get may become possible. The
        # callbacks list was just created by Event.__init__ above.
        self.callbacks.append(resource._trigger_get)  # type: ignore[union-attr]
        resource._trigger_put(None)

    def __enter__(self) -> "Put":
        """Return the request itself for use in a ``with`` block."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Cancel the request on block exit."""
        self.cancel()

    def cancel(self) -> None:
        """Abort the request if it has not yet been granted.

        Removing an ungranted put from the queue is the stale-waiter cleanup
        that keeps an interrupted or abandoned waiter from later being served.
        """
        if not self.triggered:
            self.resource.put_queue.remove(self)


class Get(Event[T]):
    """A request to get something from a resource, granted when one is available.

    Usable as a context manager, mirroring :class:`Put`::

        with resource.get() as request:
            item = yield request
    """

    __slots__ = ("resource", "proc")

    def __init__(self, resource: "BaseResource[Any, Any]") -> None:
        """Enqueue this get on *resource* and try to satisfy it at once."""
        sim = resource._sim
        super().__init__(sim)
        self.resource = resource
        self.proc = sim._active_process
        resource.get_queue.append(self)
        # When this get is finally granted, a put may become possible. The
        # callbacks list was just created by Event.__init__ above.
        self.callbacks.append(resource._trigger_put)  # type: ignore[union-attr]
        resource._trigger_get(None)

    def __enter__(self) -> "Get[T]":
        """Return the request itself for use in a ``with`` block."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Cancel the request on block exit."""
        self.cancel()

    def cancel(self) -> None:
        """Abort the request if it has not yet been granted (stale-waiter cleanup)."""
        if not self.triggered:
            self.resource.get_queue.remove(self)


class BaseResource(Generic[PutType, GetType]):
    """Abstract shared resource with pending put and get queues.

    Subclasses set :attr:`PutQueue`/:attr:`GetQueue` (the queue disciplines) and
    implement :meth:`_do_put`/:meth:`_do_get`. Each of those returns a truthy
    value to let the trigger loop keep serving further waiters, or a falsy value
    to stop (for example a single-slot resource stops after one grant).
    """

    __slots__ = ("_sim", "_capacity", "put_queue", "get_queue")

    #: Queue discipline for pending puts. A plain ``list`` gives FIFO order.
    PutQueue: type[list[Any]] = list
    #: Queue discipline for pending gets.
    GetQueue: type[list[Any]] = list

    def __init__(self, sim: "Sim", capacity: float) -> None:
        """Create an empty resource bound to *sim* with the given *capacity*.

        Raises:
            ValueError: if *capacity* is not positive.
        """
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self._sim = sim
        self._capacity = capacity
        self.put_queue: list[PutType] = self.PutQueue()
        self.get_queue: list[GetType] = self.GetQueue()

    @property
    def capacity(self) -> float:
        """The resource's maximum capacity."""
        return self._capacity

    def _do_put(self, event: PutType) -> bool | None:
        """Try to satisfy put *event*; subclasses implement the discipline."""
        raise NotImplementedError(self)

    def _trigger_put(self, _get_event: Event[Any] | None) -> None:
        """Serve pending puts while :meth:`_do_put` keeps making progress."""
        queue = self.put_queue  # same object throughout; hoist off self
        index = 0
        while index < len(queue):
            put_event = queue[index]
            proceed = self._do_put(put_event)
            if not put_event.triggered:
                index += 1
            elif queue.pop(index) is not put_event:
                raise RuntimeError("put queue invariant violated")
            if not proceed:
                break

    def _do_get(self, event: GetType) -> bool | None:
        """Try to satisfy get *event*; subclasses implement the discipline."""
        raise NotImplementedError(self)

    def _trigger_get(self, _put_event: Event[Any] | None) -> None:
        """Serve pending gets while :meth:`_do_get` keeps making progress."""
        queue = self.get_queue  # same object throughout; hoist off self
        index = 0
        while index < len(queue):
            get_event = queue[index]
            proceed = self._do_get(get_event)
            if not get_event.triggered:
                index += 1
            elif queue.pop(index) is not get_event:
                raise RuntimeError("get queue invariant violated")
            if not proceed:
                break
