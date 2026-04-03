"""Stage 2: Graph — upsert AGIFT terms and structural edges."""

from agift.backend import GraphBackend
from agift.fetch import AgiftTerm


def ensure_schema(backend: GraphBackend) -> None:
    """Create backend constraints and indexes.

    Args:
        backend: Graph backend instance.
    """
    backend.ensure_schema()


def upsert_graph(backend: GraphBackend, terms: list[AgiftTerm]) -> dict:
    """Upsert AGIFT terms as nodes with PARENT_OF edges.

    Uses merge semantics to avoid duplicates. Detects changed labels
    to flag terms that need re-embedding.

    Args:
        backend: Graph backend instance.
        terms: List of AgiftTerm objects.

    Returns:
        Dict with created, updated, unchanged counts and
        changed_ids list of term_ids that need re-embedding.
    """
    # Sort so parents come before children
    terms_sorted = sorted(terms, key=lambda t: t.depth)

    stats = {"created": 0, "updated": 0, "unchanged": 0, "changed_ids": []}

    for t in terms_sorted:
        changed, no_embed = backend.upsert_term(
            term_id=t.term_id,
            label=t.label,
            label_norm=t.label.lower().strip(),
            depth=t.depth,
            dcat_theme=t.dcat_theme,
            top_level_id=t.top_level_id,
            alt_labels=t.alt_labels,
        )
        if changed or no_embed:
            stats["changed_ids"].append(t.term_id)
            if no_embed:
                stats["created"] += 1
            else:
                stats["updated"] += 1
        else:
            stats["unchanged"] += 1

        # Create PARENT_OF edge
        if t.parent_id is not None:
            backend.create_parent_edge(t.parent_id, t.term_id)

    backend.cleanup_changed_flags()
    return stats
