from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping

Scalar = str | int | bool | None

@dataclass(frozen=True)
class ProjectedAction:
    """Non-semantic C1 runner shim for ReplayMark's immutable action value interface."""
    dimensions: tuple[tuple[str, Scalar], ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        normalized: list[tuple[str, Scalar]] = []
        for key, value in self.dimensions:
            if not isinstance(key, str) or not key.strip() or key != key.strip():
                raise ValueError("invalid action dimension")
            if key in seen:
                raise ValueError("duplicate action dimension")
            if isinstance(value, float) or not (value is None or isinstance(value, (str, int, bool))):
                raise TypeError("invalid action scalar")
            seen.add(key)
            normalized.append((key, value))
        if not normalized:
            raise ValueError("ProjectedAction requires at least one dimension")
        object.__setattr__(self, "dimensions", tuple(sorted(normalized)))

    @classmethod
    def from_mapping(cls, dimensions: Mapping[str, Scalar]) -> "ProjectedAction":
        return cls(tuple(dimensions.items()))

    def as_dict(self) -> dict[str, Scalar]:
        return dict(self.dimensions)
