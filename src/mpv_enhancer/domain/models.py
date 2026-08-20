"""Ordered queue models with stable, path-independent identity."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class QueueItem:
    """A media queue entry whose UUID remains stable when its order changes."""

    item_id: UUID
    source_path: Path
    display_title: str

    def __post_init__(self) -> None:
        source = Path(self.source_path)
        title = self.display_title.strip()
        if not source.name or source.name in {".", ".."}:
            raise ValueError("A queue item requires a file name.")
        if not title:
            raise ValueError("A queue item requires a display title.")
        object.__setattr__(self, "source_path", source)
        object.__setattr__(self, "display_title", title)

    @classmethod
    def create(
        cls,
        source_path: str | Path,
        *,
        display_title: str | None = None,
        item_id: UUID | None = None,
    ) -> "QueueItem":
        """Create an item without reading or resolving the machine-local path."""
        source = Path(source_path)
        title = source.stem if display_title is None else display_title.strip()
        return cls(
            item_id=item_id if item_id is not None else uuid4(),
            source_path=source,
            display_title=title,
        )


class Playlist:
    """An ordered collection that allows duplicate paths but not duplicate UUIDs."""

    def __init__(self, items: Iterable[QueueItem] = ()) -> None:
        self._items = list(items)
        self._require_unique_identities()

    @property
    def items(self) -> tuple[QueueItem, ...]:
        """Return an immutable view of the current queue order."""
        return tuple(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[QueueItem]:
        return iter(self._items)

    def item_at(self, index: int) -> QueueItem:
        """Return the item at a zero-based queue position."""
        self._require_item_index(index)
        return self._items[index]

    def index_of(self, item_id: UUID) -> int:
        """Return the position of an identity, independent of its source path."""
        for index, item in enumerate(self._items):
            if item.item_id == item_id:
                return index
        raise KeyError(f"Queue item UUID {item_id} was not found.")

    def append(self, item: QueueItem) -> None:
        """Append a new identity to the end of the queue."""
        self.insert(len(self._items), item)

    def insert(self, index: int, item: QueueItem) -> None:
        """Insert an item at a zero-based position without copying it."""
        if not 0 <= index <= len(self._items):
            raise IndexError("Playlist insertion index is out of range.")
        self._require_new_identity(item.item_id)
        self._items.insert(index, item)

    def move(self, source_index: int, destination_index: int) -> None:
        """Move an existing item to its final zero-based position."""
        self._require_item_index(source_index)
        self._require_item_index(destination_index)
        if source_index == destination_index:
            return
        item = self._items.pop(source_index)
        self._items.insert(destination_index, item)

    def remove(self, item_id: UUID) -> QueueItem:
        """Remove and return one exact UUID, even when paths are duplicated."""
        return self._items.pop(self.index_of(item_id))

    def _require_unique_identities(self) -> None:
        identities = {item.item_id for item in self._items}
        if len(identities) != len(self._items):
            raise ValueError("Playlist items must have unique UUID identities.")

    def _require_new_identity(self, item_id: UUID) -> None:
        if any(item.item_id == item_id for item in self._items):
            raise ValueError("Playlist items must have unique UUID identities.")

    def _require_item_index(self, index: int) -> None:
        if not 0 <= index < len(self._items):
            raise IndexError("Playlist item index is out of range.")
