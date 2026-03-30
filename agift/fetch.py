"""Stage 1: Fetch — pull full AGIFT hierarchy from TemaTres API."""

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.request import Request, urlopen
from urllib.error import URLError

from agift.common import AGIFT_TOP_TO_DCAT, TEMATRES_BASE


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
    """Fetch XML from TemaTres API with retry."""
    url = f"{TEMATRES_BASE}?task={task}"
    if arg:
        url += f"&arg={arg}"
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "AGIFT-Graph-Import/1.0"})
            with urlopen(req, timeout=120) as resp:
                data = resp.read().decode("utf-8")
                return ET.fromstring(data)
        except (URLError, TimeoutError, ET.ParseError) as e:
            if attempt == 2:
                raise
            wait = 5 * (attempt + 1)
            print(f"  Retry {attempt + 1} for {task} {arg}: {e}")
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


def fetch_full_hierarchy(include_alts: bool = True) -> list[AgiftTerm]:
    """Walk the full AGIFT hierarchy from TemaTres and return all terms.

    Args:
        include_alts: If True, fetch alt labels for each term (slower).

    Returns:
        List of AgiftTerm objects for the full 3-level hierarchy.
    """
    print("Fetching AGIFT top-level terms...")
    top_root = _fetch_xml("fetchTopTerms")
    top_terms = _parse_terms(top_root)
    print(f"  Found {len(top_terms)} top-level functions")
    if not include_alts:
        print("  (skipping alt labels)")

    all_terms: list[AgiftTerm] = []

    for top_id, top_label in top_terms:
        dcat = AGIFT_TOP_TO_DCAT.get(top_label.lower())
        if not dcat:
            print(f"  WARNING: No DCAT mapping for top-level '{top_label}', using GOVE")
            dcat = "GOVE"

        alt_labels = _fetch_alt_labels(top_id) if include_alts else []
        all_terms.append(AgiftTerm(
            term_id=top_id, label=top_label, parent_id=None,
            top_level_id=top_id, depth=1, dcat_theme=dcat,
            alt_labels=alt_labels,
        ))

        # Level 2
        l2_root = _fetch_xml("fetchDown", str(top_id))
        l2_terms = _parse_terms(l2_root)
        print(f"  {top_label} ({dcat}): {len(l2_terms)} L2 terms")

        for l2_id, l2_label in l2_terms:
            alt_labels = _fetch_alt_labels(l2_id) if include_alts else []
            all_terms.append(AgiftTerm(
                term_id=l2_id, label=l2_label, parent_id=top_id,
                top_level_id=top_id, depth=2, dcat_theme=dcat,
                alt_labels=alt_labels,
            ))

            # Level 3
            l3_root = _fetch_xml("fetchDown", str(l2_id))
            l3_terms = _parse_terms(l3_root)

            for l3_id, l3_label in l3_terms:
                alt_labels = _fetch_alt_labels(l3_id) if include_alts else []
                all_terms.append(AgiftTerm(
                    term_id=l3_id, label=l3_label, parent_id=l2_id,
                    top_level_id=top_id, depth=3, dcat_theme=dcat,
                    alt_labels=alt_labels,
                ))

        # Be polite to the API
        time.sleep(2)

    return all_terms
