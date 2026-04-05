"""Stage 1: Fetch — pull full AGIFT hierarchy from TemaTres API."""

import random
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from urllib.request import Request, urlopen
from urllib.error import URLError

from agift.common import AGIFT_TOP_TO_DCAT, TEMATRES_BASE

# Concurrency for alt-label fetches
_ALT_LABEL_WORKERS = 10
_MAX_RETRIES = 5
_BASE_BACKOFF = 1.0  # seconds


@dataclass
class AgiftTerm:
    """A single AGIFT vocabulary term."""

    term_id: int
    label: str
    parent_id: int | None
    top_level_id: int | None
    depth: int
    dcat_theme: str
    alt_labels: list[str] = field(default_factory=list)


def _fetch_xml(task: str, arg: str = "") -> ET.Element:
    """Fetch XML from TemaTres API with exponential backoff and jitter."""
    url = f"{TEMATRES_BASE}?task={task}"
    if arg:
        url += f"&arg={arg}"
    for attempt in range(_MAX_RETRIES):
        try:
            req = Request(url, headers={"User-Agent": "AGIFT-Graph-Import/1.0"})
            with urlopen(req, timeout=120) as resp:
                data = resp.read().decode("utf-8")
                return ET.fromstring(data)
        except (URLError, TimeoutError, ET.ParseError) as e:
            if attempt == _MAX_RETRIES - 1:
                raise
            wait = _BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 1)
            print(f"  Retry {attempt + 1} for {task} {arg}: {e} (wait {wait:.1f}s)")
            time.sleep(wait)


def _parse_terms(root: ET.Element) -> list[tuple[int, str]]:
    """Extract (term_id, label) pairs from a TemaTres XML response."""
    results = []
    for term in root.findall(".//term"):
        tid_el = term.find("term_id")
        str_el = term.find("string")
        if tid_el is not None and str_el is not None and tid_el.text and str_el.text:
            results.append((int(tid_el.text), str_el.text.strip()))
    return results


def _fetch_alt_labels(term_id: int) -> list[str]:
    """Fetch non-preferred (alternative) labels for a term."""
    try:
        root = _fetch_xml("fetchAlt", str(term_id))
        return [label for _, label in _parse_terms(root)]
    except Exception:
        return []


def _fetch_alt_labels_batch(term_ids: list[int]) -> dict[int, list[str]]:
    """Fetch alt labels for many terms concurrently.

    Returns:
        Dict mapping term_id -> list of alt label strings.
    """
    results: dict[int, list[str]] = {}
    with ThreadPoolExecutor(max_workers=_ALT_LABEL_WORKERS) as pool:
        futures = {pool.submit(_fetch_alt_labels, tid): tid for tid in term_ids}
        for future in as_completed(futures):
            tid = futures[future]
            results[tid] = future.result()
    return results


def fetch_full_hierarchy(include_alts: bool = True) -> list[AgiftTerm]:
    """Walk the full AGIFT hierarchy from TemaTres and return all terms.

    Args:
        include_alts: If True, fetch alt labels for each term concurrently.

    Returns:
        List of AgiftTerm objects for the full 3-level hierarchy.
    """
    print("Fetching AGIFT top-level terms...")
    top_root = _fetch_xml("fetchTopTerms")
    top_terms = _parse_terms(top_root)
    print(f"  Found {len(top_terms)} top-level functions")
    if not include_alts:
        print("  (skipping alt labels)")

    # First pass: walk the hierarchy to collect all terms (structure only)
    all_terms: list[AgiftTerm] = []

    for top_id, top_label in top_terms:
        dcat = AGIFT_TOP_TO_DCAT.get(top_label.lower())
        if not dcat:
            print(f"  WARNING: No DCAT mapping for top-level '{top_label}', using GOVE")
            dcat = "GOVE"

        all_terms.append(
            AgiftTerm(
                term_id=top_id,
                label=top_label,
                parent_id=None,
                top_level_id=top_id,
                depth=1,
                dcat_theme=dcat,
            )
        )

        # Level 2
        l2_root = _fetch_xml("fetchDown", str(top_id))
        l2_terms = _parse_terms(l2_root)
        print(f"  {top_label} ({dcat}): {len(l2_terms)} L2 terms")

        for l2_id, l2_label in l2_terms:
            all_terms.append(
                AgiftTerm(
                    term_id=l2_id,
                    label=l2_label,
                    parent_id=top_id,
                    top_level_id=top_id,
                    depth=2,
                    dcat_theme=dcat,
                )
            )

            # Level 3
            l3_root = _fetch_xml("fetchDown", str(l2_id))
            l3_terms = _parse_terms(l3_root)

            for l3_id, l3_label in l3_terms:
                all_terms.append(
                    AgiftTerm(
                        term_id=l3_id,
                        label=l3_label,
                        parent_id=l2_id,
                        top_level_id=top_id,
                        depth=3,
                        dcat_theme=dcat,
                    )
                )

        # Small courtesy pause between top-level groups
        time.sleep(0.2)

    # Second pass: fetch alt labels concurrently
    if include_alts:
        term_ids = [t.term_id for t in all_terms]
        print(f"\nFetching alt labels for {len(term_ids)} terms "
              f"({_ALT_LABEL_WORKERS} concurrent workers)...")
        alt_map = _fetch_alt_labels_batch(term_ids)
        for term in all_terms:
            term.alt_labels = alt_map.get(term.term_id, [])
        total_alts = sum(len(v) for v in alt_map.values())
        print(f"  Fetched {total_alts} alt labels")

    return all_terms
