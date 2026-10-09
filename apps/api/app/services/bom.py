"""Bill-of-materials rules shared by the API and the CSV importer.

A BOM must be a tree (or DAG): if a component ends up containing its own parent, demand
explodes around the loop and planning fails for the whole workspace. Loops are rejected when
a line is written, not discovered at planning time.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BomLine

Graph = dict[uuid.UUID, set[uuid.UUID]]  # parent -> components


def load_graph(db: Session, org_id: uuid.UUID) -> Graph:
    g: Graph = defaultdict(set)
    rows = db.execute(
        select(BomLine.parent_product_id, BomLine.component_product_id).where(
            BomLine.org_id == org_id
        )
    )
    for parent, comp in rows:
        g[parent].add(comp)
    return g


def creates_cycle(graph: Graph, parent: uuid.UUID, component: uuid.UUID) -> bool:
    """True if adding parent -> component closes a loop (component already contains parent)."""
    if parent == component:
        return True
    stack, seen = [component], set()
    while stack:
        node = stack.pop()
        if node == parent:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(graph.get(node, ()))
    return False


def find_cycle(graph: Graph) -> list[uuid.UUID] | None:
    """One loop in the graph as a list of product ids, or None. Used as a guard at planning
    time for loops written before this check existed."""
    white, grey, black = 0, 1, 2
    color: dict[uuid.UUID, int] = defaultdict(int)
    path: list[uuid.UUID] = []

    def visit(n: uuid.UUID) -> list[uuid.UUID] | None:
        color[n] = grey
        path.append(n)
        for m in graph.get(n, ()):
            if color[m] == grey:
                return path[path.index(m) :] + [m]
            if color[m] == white:
                found = visit(m)
                if found:
                    return found
        path.pop()
        color[n] = black
        return None

    for node in list(graph):
        if color[node] == white:
            found = visit(node)
            if found:
                return found
    return None
