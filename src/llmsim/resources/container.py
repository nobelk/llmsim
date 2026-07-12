"""Bulk-quantity ``Container``.

Models a shared level of some homogeneous quantity (fuel, inventory, energy)
that processes add to and draw from, blocking when the level cannot satisfy a
request.
"""

from typing import TYPE_CHECKING

from llmsim.resources import base

if TYPE_CHECKING:
    from llmsim.core.sim import Sim


def _positive_amount(amount: float) -> float:
    """Return *amount*, or raise if it is not strictly positive."""
    if amount <= 0:
        raise ValueError(f"amount(={amount}) must be > 0")
    return amount


class ContainerPut(base.Put):
    """A request to add *amount* of matter, granted once there is room."""

    __slots__ = ("amount",)

    def __init__(self, container: "Container", amount: float) -> None:
        """Request to put *amount* into *container*.

        Raises:
            ValueError: if *amount* is not positive.
        """
        #: The quantity to add.
        self.amount = _positive_amount(amount)
        super().__init__(container)


class ContainerGet(base.Get[None]):
    """A request to draw *amount* of matter, granted once enough is available."""

    __slots__ = ("amount",)

    def __init__(self, container: "Container", amount: float) -> None:
        """Request to get *amount* from *container*.

        Raises:
            ValueError: if *amount* is not positive.
        """
        #: The quantity to draw.
        self.amount = _positive_amount(amount)
        super().__init__(container)


class Container(base.BaseResource[ContainerPut, ContainerGet]):
    """A shared level of homogeneous matter between ``0`` and *capacity*.

    Puts block while there is not enough free space; gets block while there is
    not enough matter. Both wake as the level changes.
    """

    __slots__ = ("_level",)

    def __init__(
        self, sim: "Sim", capacity: float = float("inf"), init: float = 0
    ) -> None:
        """Create a container holding *init* of *capacity* matter.

        Raises:
            ValueError: if *capacity* is not positive, *init* is negative, or
                *init* exceeds *capacity*.
        """
        super().__init__(sim, capacity)  # validates capacity > 0
        if init < 0:
            raise ValueError("init must be >= 0")
        if init > capacity:
            raise ValueError("init must be <= capacity")
        self._level = init

    @property
    def level(self) -> float:
        """The current amount of matter in the container."""
        return self._level

    def put(self, amount: float) -> ContainerPut:
        """Request to add *amount* of matter."""
        return ContainerPut(self, amount)

    def get(self, amount: float) -> ContainerGet:
        """Request to draw *amount* of matter."""
        return ContainerGet(self, amount)

    def _do_put(self, event: ContainerPut) -> bool | None:
        """Add the requested amount if it fits, and keep serving if it did."""
        if self._capacity - self._level >= event.amount:
            self._level += event.amount
            event.succeed()
            return True
        return None

    def _do_get(self, event: ContainerGet) -> bool | None:
        """Draw the requested amount if available, and keep serving if it was."""
        if self._level >= event.amount:
            self._level -= event.amount
            event.succeed()
            return True
        return None
