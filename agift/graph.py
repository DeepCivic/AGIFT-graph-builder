"""Stage 2: Graph — upsert AGIFT terms and structural edges into Neo4j."""

from agift.fetch import AgiftTerm


def ensure_schema(driver) -> None:
    """Create Neo4j constraints and indexes.

    Args:
        driver: Neo4j driver.
    """
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT term_id_unique IF NOT EXISTS "
            "FOR (t:Term) REQUIRE t.term_id IS UNIQUE"
        )
        session.run(
            "CREATE INDEX term_dcat IF NOT EXISTS "
            "FOR (t:Term) ON (t.dcat_theme)"
        )
        session.run(
            "CREATE INDEX term_depth IF NOT EXISTS "
            "FOR (t:Term) ON (t.depth)"
        )
    print("Neo4j schema ensured.")


def upsert_graph(driver, terms: list[AgiftTerm]) -> dict:
    """Upsert AGIFT terms as Neo4j nodes with PARENT_OF edges.

    Uses MERGE to avoid duplicates. Detects changed labels to flag
    terms that need re-embedding.

    Args:
        driver: Neo4j driver.
        terms: List of AgiftTerm objects.

    Returns:
        Dict with created, updated, unchanged counts and
        changed_ids list of term_ids that need re-embedding.
    """
    # Sort so parents come before children
    terms_sorted = sorted(terms, key=lambda t: t.depth)

    stats = {"created": 0, "updated": 0, "unchanged": 0, "changed_ids": []}

    with driver.session() as session:
        for t in terms_sorted:
            result = session.run(
                """
                MERGE (t:Term {term_id: $term_id})
                ON CREATE SET
                    t.label = $label,
                    t.label_norm = $label_norm,
                    t.depth = $depth,
                    t.dcat_theme = $dcat_theme,
                    t.top_level_id = $top_level_id,
                    t.alt_labels = $alt_labels,
                    t.created_at = datetime(),
                    t._changed = true
                ON MATCH SET
                    t._changed = (t.label <> $label OR t.alt_labels <> $alt_labels),
                    t.label = $label,
                    t.label_norm = $label_norm,
                    t.depth = $depth,
                    t.dcat_theme = $dcat_theme,
                    t.top_level_id = $top_level_id,
                    t.alt_labels = $alt_labels
                RETURN t._changed AS changed, t.embedding IS NULL AS no_embed
                """,
                term_id=t.term_id,
                label=t.label,
                label_norm=t.label.lower().strip(),
                depth=t.depth,
                dcat_theme=t.dcat_theme,
                top_level_id=t.top_level_id,
                alt_labels=t.alt_labels,
            )
            record = result.single()
            if record["changed"] or record["no_embed"]:
                stats["changed_ids"].append(t.term_id)
                if record["no_embed"]:
                    stats["created"] += 1
                else:
                    stats["updated"] += 1
            else:
                stats["unchanged"] += 1

            # Create PARENT_OF edge
            if t.parent_id is not None:
                session.run(
                    """
                    MATCH (parent:Term {term_id: $parent_id})
                    MATCH (child:Term {term_id: $child_id})
                    MERGE (parent)-[:PARENT_OF]->(child)
                    """,
                    parent_id=t.parent_id,
                    child_id=t.term_id,
                )

    # Clean up _changed flag
    with driver.session() as session:
        session.run("MATCH (t:Term) REMOVE t._changed")

    return stats
