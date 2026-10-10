"""Editing state for v0.2: selection plus a multi-level undo/redo stack.

Kept separate from both the data model (pure geometry) and the viewer (drawing)
so the full edit loop — select, delete, undo, redo — can be driven and tested
without a GUI. The viewer calls these methods from mouse/key events; the tests
call them directly.

Delete granularity is always a whole :class:`~gml_editor.model.Feature`. The
undo stack records ``(feature, position)`` so a restore re-inserts the feature
at the exact index it occupied, returning the live list to its prior state.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .model import Feature, Scene


class EditSession:
    """Mutable editing state over a :class:`Scene`'s features.

    ``features`` is the live, visible list (a copy of the scene's, so the
    original load result is left intact). Deletions and restores mutate this
    list; the scene itself is only read.
    """

    def __init__(self, scene: Scene):
        self.scene = scene
        self.features: List[Feature] = list(scene.features)
        self.selected: Optional[Feature] = None
        self._undo: List[Tuple[Feature, int]] = []
        self._redo: List[Tuple[Feature, int]] = []

    # -- selection ---------------------------------------------------------

    def select(self, feature: Optional[Feature]) -> None:
        """Select a feature, or clear the selection when ``feature`` is None."""
        if feature is not None and feature not in self.features:
            return
        self.selected = feature

    def clear_selection(self) -> None:
        self.selected = None

    # -- deletion / undo / redo -------------------------------------------

    def delete_selected(self) -> Optional[Feature]:
        """Delete the current selection. Returns the deleted feature or None."""
        if self.selected is None:
            return None
        return self.delete(self.selected)

    def delete(self, feature: Feature) -> Optional[Feature]:
        """Delete ``feature`` from the live list, recording it for undo."""
        try:
            index = self.features.index(feature)
        except ValueError:
            return None
        self.features.pop(index)
        self._undo.append((feature, index))
        self._redo.clear()  # a new edit invalidates the redo history
        if self.selected is feature:
            self.selected = None
        return feature

    def undo(self) -> Optional[Feature]:
        """Restore the most recently deleted feature at its original position."""
        if not self._undo:
            return None
        feature, index = self._undo.pop()
        index = min(index, len(self.features))  # clamp defensively
        self.features.insert(index, feature)
        self._redo.append((feature, index))
        return feature

    def redo(self) -> Optional[Feature]:
        """Re-delete the feature most recently restored by :meth:`undo`."""
        if not self._redo:
            return None
        feature, _index = self._redo.pop()
        try:
            index = self.features.index(feature)
        except ValueError:
            return None
        self.features.pop(index)
        self._undo.append((feature, index))
        if self.selected is feature:
            self.selected = None
        return feature

    # -- queries -----------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def deleted_count(self) -> int:
        return len(self._undo)
