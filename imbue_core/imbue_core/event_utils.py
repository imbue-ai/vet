import time
from threading import Event
from threading import Lock

from pydantic import PrivateAttr

from imbue_core.errors import ExpectedError
from imbue_core.pydantic_serialization import MutableModel


class ShutdownEvent(MutableModel):
    """
    Encapsulate two different shutdown subevents:
        - A shutdown event that came from above (e.g. in response to a Ctrl+C signal); we're only listening to it.
        - A shutdown event initiated by the "owner" of this event.

    From the perspective of threads and processes, they don't care where the shutdown event came from.
    But we need to distinguish between them - we may want to only trigger a shutdown for a particular part of the codebase

    This is effectively a tree of shutdown events where each node can be triggered by its parent or by itself.
    (This concept is closely related to Sculptor's ConcurrencyGroups which span the whole codebase in a tree structure.)

    """

    _parent: "ShutdownEvent | None" = PrivateAttr()
    # This would typically be a threading.Event, but we allow ShutdownEvent as well for consistency in some interfaces.
    _own: "Event | ShutdownEvent" = PrivateAttr(default_factory=Event)
    # Optionally, the shutdown event can also be set through an external event.
    _external: "ReadOnlyEvent | None" = PrivateAttr(default=None)
    # Used to prevent multiple busy-wait loops from being unnecessarly active at the same time.
    _wait_lock: Lock = PrivateAttr(default_factory=Lock)

    def is_set(self) -> bool:
        return (
            self._own.is_set()
            or (self._external is not None and self._external.is_set())
            or (self._parent is not None and self._parent.is_set())
        )

    def set(self) -> None:
        self._own.set()

    def wait(self, timeout: float | None = None) -> bool:
        start = time.monotonic()
        # Don't busy-wait if another thread is already doing so for us.
        acquired = self._wait_lock.acquire(timeout=timeout if timeout is not None else -1)
        if not acquired:
            return False
        try:
            while timeout is None or time.monotonic() - start < timeout:
                if self.is_set():
                    return True
                time.sleep(0.01)
            return False
        finally:
            self._wait_lock.release()

    @classmethod
    def from_parent(cls, parent: "ShutdownEvent", external: "ReadOnlyEvent | None" = None) -> "ShutdownEvent":
        """
        Inject your own Event if you need to integrate with existing code that already has an Event.

        """
        shutdown_event = cls()
        shutdown_event._parent = parent
        if external is not None:
            shutdown_event._external = external
        return shutdown_event

    @classmethod
    def build_root(cls) -> "ShutdownEvent":
        shutdown_event = cls()
        shutdown_event._parent = None
        return shutdown_event


class CompoundEvent:
    """Has the read-only interface of an Event, but is set if any child event is set."""

    def __init__(self, events: list["ReadOnlyEvent"]) -> None:
        assert len(events) >= 1
        self.events = events

    def is_set(self) -> bool:
        return any([event.is_set() for event in self.events])

    def wait(self, timeout: float | None = None) -> bool:
        start = time.monotonic()
        while timeout is None or time.monotonic() - start < timeout:
            if self.is_set():
                return True
            time.sleep(0.01)
        return False


class CancelledByEventError(ExpectedError):
    """A generic cancellation error to signal event-triggered cancellations."""


# Define some convenience type aliases.
MutableEvent = Event | ShutdownEvent
ReadOnlyEvent = Event | ShutdownEvent | CompoundEvent
