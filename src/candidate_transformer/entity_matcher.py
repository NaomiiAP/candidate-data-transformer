"""
Entity matching for candidate record deduplication.

Groups CandidateRecord instances that refer to the same person using
a union-find (disjoint set) data structure. Matching is performed across
multiple identity signals: email, phone, normalized name, LinkedIn URL,
and GitHub URL.
"""

from __future__ import annotations

import logging
from typing import Optional

from candidate_transformer.models import CandidateRecord
from candidate_transformer.normalizers import (
    normalize_email,
    normalize_name,
    normalize_phone,
    normalize_url,
)

logger = logging.getLogger(__name__)


class UnionFind:
    """Disjoint-set (union-find) data structure with path compression and union by rank.

    Provides near-constant-time operations for grouping elements.
    Used to cluster candidate records that share identity signals.
    """

    def __init__(self, n: int) -> None:
        """Initialize union-find with n elements.

        Args:
            n: Number of elements (0-indexed).
        """
        self._parent: list[int] = list(range(n))
        self._rank: list[int] = [0] * n
        self._size: int = n

    def find(self, x: int) -> int:
        """Find the root representative of element x with path compression.

        Args:
            x: Element index.

        Returns:
            Root representative index.

        Raises:
            IndexError: If x is out of range.
        """
        if x < 0 or x >= self._size:
            raise IndexError(f"Element {x} out of range [0, {self._size})")

        # Path compression: make every node on the path point to the root
        root = x
        while self._parent[root] != root:
            root = self._parent[root]

        while self._parent[x] != root:
            next_parent = self._parent[x]
            self._parent[x] = root
            x = next_parent

        return root

    def union(self, x: int, y: int) -> bool:
        """Merge the sets containing elements x and y.

        Uses union by rank to keep the tree balanced.

        Args:
            x: First element index.
            y: Second element index.

        Returns:
            True if the sets were merged (they were different),
            False if they were already in the same set.
        """
        root_x = self.find(x)
        root_y = self.find(y)

        if root_x == root_y:
            return False

        # Union by rank
        if self._rank[root_x] < self._rank[root_y]:
            self._parent[root_x] = root_y
        elif self._rank[root_x] > self._rank[root_y]:
            self._parent[root_y] = root_x
        else:
            self._parent[root_y] = root_x
            self._rank[root_x] += 1

        return True

    def groups(self) -> dict[int, list[int]]:
        """Return all groups as a mapping from root -> list of member indices.

        Returns:
            Dictionary mapping root representative to list of all
            element indices in that group.
        """
        result: dict[int, list[int]] = {}
        for i in range(self._size):
            root = self.find(i)
            if root not in result:
                result[root] = []
            result[root].append(i)
        return result


def _extract_identity_signals(
    record: CandidateRecord,
) -> dict[str, set[str]]:
    """Extract all normalized identity signals from a single CandidateRecord.

    Args:
        record: A candidate record to extract signals from.

    Returns:
        Dictionary with signal type keys and sets of normalized values.
        Keys: 'emails', 'phones', 'names', 'linkedin', 'github'.
    """
    signals: dict[str, set[str]] = {
        "emails": set(),
        "phones": set(),
        "names": set(),
        "linkedin": set(),
        "github": set(),
    }

    # Emails
    for email in record.emails:
        normalized = normalize_email(email)
        if normalized:
            signals["emails"].add(normalized)

    # Phones
    for phone in record.phones:
        normalized = normalize_phone(phone)
        if normalized:
            signals["phones"].add(normalized)

    # Name
    if record.full_name:
        normalized_name_val = normalize_name(record.full_name)
        if normalized_name_val:
            signals["names"].add(normalized_name_val.lower())

    # Links
    if record.links:
        if record.links.linkedin:
            normalized_linkedin = normalize_url(record.links.linkedin)
            if normalized_linkedin:
                signals["linkedin"].add(normalized_linkedin)
        if record.links.github:
            normalized_github = normalize_url(record.links.github)
            if normalized_github:
                signals["github"].add(normalized_github)

    return signals


def _has_conflict(r1: CandidateRecord, r2: CandidateRecord) -> bool:
    """Check if two records have conflicting unique identifiers.

    They conflict if they both have non-empty unique identifiers for
    a category, but share none.
    """
    # Emails
    e1 = {normalize_email(e) for e in r1.emails if normalize_email(e)}
    e2 = {normalize_email(e) for e in r2.emails if normalize_email(e)}
    if e1 and e2 and not (e1 & e2):
        return True

    # Phones
    p1 = {normalize_phone(p) for p in r1.phones if normalize_phone(p)}
    p2 = {normalize_phone(p) for p in r2.phones if normalize_phone(p)}
    if p1 and p2 and not (p1 & p2):
        return True

    # LinkedIn
    l1 = normalize_url(r1.links.linkedin) if r1.links and r1.links.linkedin else ""
    l2 = normalize_url(r2.links.linkedin) if r2.links and r2.links.linkedin else ""
    if l1 and l2 and l1 != l2:
        return True

    # GitHub
    g1 = normalize_url(r1.links.github) if r1.links and r1.links.github else ""
    g2 = normalize_url(r2.links.github) if r2.links and r2.links.github else ""
    if g1 and g2 and g1 != g2:
        return True

    return False


def match_records(
    records: list[CandidateRecord],
) -> list[list[CandidateRecord]]:
    """Group CandidateRecords that refer to the same person.

    Uses a multi-signal matching strategy with union-find to cluster
    records. Two records are considered to refer to the same person if
    they share ANY of the following:
      - A normalized email address (exact match)
      - A normalized phone number in E.164 (exact match)
      - A normalized full name (exact match after normalization, provided
        they do not have conflicting emails, phones, or URLs)
      - A LinkedIn profile URL (exact match after normalization)
      - A GitHub profile URL (exact match after normalization)

    Args:
        records: List of CandidateRecord instances to match.

    Returns:
        List of groups, where each group is a list of CandidateRecords
        that are believed to refer to the same person. Groups are sorted
        by the index of their first member for deterministic output.
        Within each group, records maintain their original order.
    """
    if not records:
        logger.info("No records to match.")
        return []

    n = len(records)
    if n == 1:
        logger.info("Single record — no matching needed.")
        return [records]

    logger.info("Matching %d candidate records for entity resolution.", n)

    uf = UnionFind(n)

    # Build inverted indices: signal_value -> list of record indices
    email_index: dict[str, list[int]] = {}
    phone_index: dict[str, list[int]] = {}
    name_index: dict[str, list[int]] = {}
    linkedin_index: dict[str, list[int]] = {}
    github_index: dict[str, list[int]] = {}

    for i, record in enumerate(records):
        signals = _extract_identity_signals(record)

        for email in signals["emails"]:
            email_index.setdefault(email, []).append(i)

        for phone in signals["phones"]:
            phone_index.setdefault(phone, []).append(i)

        for name in signals["names"]:
            name_index.setdefault(name, []).append(i)

        for linkedin in signals["linkedin"]:
            linkedin_index.setdefault(linkedin, []).append(i)

        for github in signals["github"]:
            github_index.setdefault(github, []).append(i)

    # Union records that share unique identity signals (emails, phones, links)
    merge_count = 0
    for signal_name, index_map in [
        ("email", email_index),
        ("phone", phone_index),
        ("linkedin", linkedin_index),
        ("github", github_index),
    ]:
        for signal_value, record_indices in index_map.items():
            if len(record_indices) > 1:
                first = record_indices[0]
                for other in record_indices[1:]:
                    if uf.union(first, other):
                        merge_count += 1
                        logger.debug(
                            "Merged records %d and %d via %s: %s",
                            first,
                            other,
                            signal_name,
                            signal_value,
                        )

    # Union records that share the same normalized name, but ONLY if they don't conflict
    for name, record_indices in name_index.items():
        if len(record_indices) > 1:
            for i in range(len(record_indices)):
                for j in range(i + 1, len(record_indices)):
                    idx1 = record_indices[i]
                    idx2 = record_indices[j]
                    if not _has_conflict(records[idx1], records[idx2]):
                        if uf.union(idx1, idx2):
                            merge_count += 1
                            logger.debug(
                                "Merged records %d and %d via name: %s",
                                idx1,
                                idx2,
                                name,
                            )

    logger.info(
        "Entity matching complete: %d records -> %d groups (%d merges).",
        n,
        len(uf.groups()),
        merge_count,
    )

    # Convert union-find groups to lists of CandidateRecords
    groups_dict = uf.groups()

    # Sort groups by the minimum index in each group for deterministic output
    sorted_group_keys = sorted(groups_dict.keys())

    result: list[list[CandidateRecord]] = []
    for key in sorted_group_keys:
        member_indices = groups_dict[key]
        group = [records[i] for i in member_indices]
        result.append(group)

    return result


match_candidates = match_records
