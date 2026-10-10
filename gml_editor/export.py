"""Export edited GML (v0.2).

The edit loop only ever *deletes* whole features, so export is: take the
original parsed tree, drop the elements of the features that are gone, and write
the rest back out unchanged. Because surviving feature elements are copied
verbatim, their schema, attributes, and CRS are preserved exactly.

Deleted features are identified by their stable ``order`` (document index),
mapped through the same :func:`~gml_editor.gml_loader.iter_feature_elements`
traversal used at load time, so the mapping cannot drift.
"""

from __future__ import annotations

import copy
import os
import xml.etree.ElementTree as ET
from typing import Iterable, Optional

from .gml_loader import _localname, iter_feature_elements
from .model import Scene


class ExportError(Exception):
    """Raised when export cannot proceed (no source tree, bad path, etc.)."""


def default_output_path(input_path: str) -> str:
    """``/dir/name.gml`` -> ``/dir/name_edited.gml``."""
    root, ext = os.path.splitext(input_path)
    return f"{root}_edited{ext or '.gml'}"


def _build_parent_map(root: ET.Element) -> dict:
    return {child: parent for parent in root.iter() for child in parent}


def export_gml(
    scene: Scene,
    surviving_features: Iterable,
    out_path: Optional[str] = None,
) -> str:
    """Write the surviving features to ``out_path`` as GML.

    Returns the path actually written. ``surviving_features`` is the live list
    of features that remain after editing. The input file is never overwritten.
    """
    if scene.tree_root is None:
        raise ExportError("Scene has no source XML tree to export from")

    out_path = out_path or default_output_path(scene.source_path)
    if os.path.abspath(out_path) == os.path.abspath(scene.source_path):
        raise ExportError(
            f"Refusing to overwrite the input file: {scene.source_path}"
        )

    surviving_orders = {f.order for f in surviving_features}

    # Work on a copy so the live scene/tree is untouched and re-exportable.
    root = copy.deepcopy(scene.tree_root)

    # Remove the elements of deleted features. The copy is traversed with the
    # same iterator as load, so the Nth yielded feature here has order == N.
    members_touched = []
    for order, (member, feature_elem) in enumerate(iter_feature_elements(root)):
        if order not in surviving_orders:
            member.remove(feature_elem)
            members_touched.append(member)

    # Drop any member wrapper that is now empty of feature elements.
    if members_touched:
        parent_map = _build_parent_map(root)
        for member in members_touched:
            if len(list(member)) == 0:
                parent = parent_map.get(member)
                if parent is not None:
                    parent.remove(member)

    # Restore original namespace prefixes on output.
    for prefix, uri in scene.nsmap.items():
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass  # reserved prefix (e.g. 'xml'); skip

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        raise ExportError(f"Output directory does not exist: {out_dir}")

    ET.ElementTree(root).write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path
