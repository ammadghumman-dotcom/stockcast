"""BOM utilities: multi-level explosion of finished-goods demand into component demand."""

from __future__ import annotations

import uuid

import numpy as np

Bom = dict[uuid.UUID, list[tuple[uuid.UUID, float]]]  # parent -> [(component, qty_per_unit)]


def explode_demand(
    bom: Bom, demand: dict[uuid.UUID, np.ndarray], *, max_depth: int = 10
) -> dict[uuid.UUID, np.ndarray]:
    """Return derived daily demand per component (summed over all parents, all levels).

    `demand` holds the independent demand of finished goods; components that are themselves
    made from sub-components propagate their derived demand downward.
    """
    derived: dict[uuid.UUID, np.ndarray] = {}
    frontier = dict(demand)
    for _ in range(max_depth):
        nxt: dict[uuid.UUID, np.ndarray] = {}
        for parent, d in frontier.items():
            for comp, per in bom.get(parent, []):
                add = d * per
                derived[comp] = add if comp not in derived else derived[comp] + add
                if comp in bom:
                    nxt[comp] = add if comp not in nxt else nxt[comp] + add
        if not nxt:
            break
        frontier = nxt
    return derived


def made_in_house(bom: Bom, product_id: uuid.UUID) -> bool:
    return bool(bom.get(product_id))
