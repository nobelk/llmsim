"""Object-queue ``Store``.

Models a buffer of discrete items that producers put and consumers get, with
optional filtering, blocking each side when the store is empty or full.

``Store`` is FIFO; ``PriorityStore`` retrieves the smallest item first;
``FilterStore`` retrieves the first item matching a caller-supplied predicate.
"""

import heapq
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, NamedTuple, TypeVar

from llmsim.resources import base

if TYPE_CHECKING:
    from llmsim.core.sim import Sim

T = TypeVar("T")


class StorePut(base.Put):
    """A request to put *item* into a store, granted once there is a free slot."""

    __slots__ = ("item",)

    def __init__(self, store: "Store[Any]", item: Any) -> None:
        """Request to put *item* into *store*."""
        #: The item to store.
        self.item = item
        super().__init__(store)


class StoreGet(base.Get[T]):
    """A request to get an item from a store, granted once one is available."""

    __slots__ = ()


class FilterStoreGet(StoreGet[T]):
    """A store get restricted to items for which *filter* returns ``True``."""

    __slots__ = ("filter",)

    def __init__(
        self, store: "FilterStore[T]", filter: Callable[[T], bool] = lambda _item: True
    ) -> None:
        """Request the first item in *store* matching *filter*."""
        #: The predicate an item must satisfy to be returned.
        self.filter = filter
        super().__init__(store)


class Store(base.BaseResource[StorePut, StoreGet[T]], Generic[T]):
    """A buffer of up to *capacity* items, put and retrieved in FIFO order."""

    __slots__ = ("items",)

    def __init__(self, sim: "Sim", capacity: float = float("inf")) -> None:
        """Create a store holding up to *capacity* items.

        Raises:
            ValueError: if *capacity* is not positive.
        """
        super().__init__(sim, capacity)
        #: The items currently held, oldest first.
        self.items: list[T] = []

    def put(self, item: T) -> StorePut:
        """Request to put *item* into the store."""
        return StorePut(self, item)

    def get(self) -> StoreGet[T]:
        """Request to get the next item from the store."""
        return StoreGet(self)

    def _do_put(self, event: StorePut) -> bool | None:
        """Accept the item if there is room."""
        if len(self.items) < self._capacity:
            self.items.append(event.item)
            event.succeed()
        return None

    def _do_get(self, event: StoreGet[T]) -> bool | None:
        """Hand over the oldest item if one is available."""
        if self.items:
            event.succeed(self.items.pop(0))
        return None


class PriorityItem(NamedTuple):
    """Pairs an orderable *priority* with an arbitrary, possibly-unorderable *item*.

    Comparisons consider only *priority*, so unorderable items can be stored in
    a :class:`PriorityStore` by wrapping them.
    """

    priority: Any
    item: Any

    def __lt__(self, other: object) -> bool:
        """Order solely by priority."""
        if not isinstance(other, PriorityItem):
            return NotImplemented
        return bool(self.priority < other.priority)


class PriorityStore(Store[T]):
    """A store that retrieves its smallest item first.

    All items must be orderable (implement ``__lt__``); wrap unorderable items
    in :class:`PriorityItem`.
    """

    __slots__ = ()

    def _do_put(self, event: StorePut) -> bool | None:
        """Insert the item into the priority heap if there is room."""
        if len(self.items) < self._capacity:
            heapq.heappush(self.items, event.item)
            event.succeed()
        return None

    def _do_get(self, event: StoreGet[T]) -> bool | None:
        """Hand over the smallest item if one is available."""
        if self.items:
            event.succeed(heapq.heappop(self.items))  # type: ignore[type-var]
        return None


class FilterStore(Store[T]):
    """A store whose gets can be restricted to items matching a predicate.

    Because a get may skip non-matching items, gets are not necessarily served
    in the order they were issued: a later get with a satisfiable filter can be
    granted ahead of an earlier one still waiting for its item.
    """

    __slots__ = ()

    def get(
        self, filter: Callable[[T], bool] = lambda _item: True
    ) -> FilterStoreGet[T]:
        """Request the first item matching *filter*."""
        return FilterStoreGet(self, filter)

    def _do_get(self, event: StoreGet[T]) -> bool | None:
        """Hand over the first item matching the get's filter, if any.

        Returns ``True`` regardless so the trigger loop keeps scanning later
        gets -- a blocked filtered get must not stall gets behind it.
        """
        assert isinstance(event, FilterStoreGet)
        for index, item in enumerate(self.items):
            if event.filter(item):
                del self.items[index]  # index in hand -- no second scan by value
                event.succeed(item)
                break
        return True
