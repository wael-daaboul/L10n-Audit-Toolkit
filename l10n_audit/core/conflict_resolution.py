"""
l10n_audit/core/conflict_resolution.py
========================================
Phase 10 — Conflict Resolution & Mutation Governance.

This module provides a deterministic layer to prevent overlapping text
mutations from competing stages (auto_fix, ai_review, manual).

Governance Rules
----------------
1. Key Isolation: Conflicts are only possible within the same key.
2. Spatial Overlap: [offset, offset + length] check if available.
3. Priority Hierarchy: 3 (auto_fix) > 2 (ai_review) > 1 (manual).
   Higher priority wins; lower priority is rejected.
4. Fallback Identity: If offsets are missing, same key + original_text = conflict.
5. Determinism: Stable first-wins for tie-breaks in priority.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("l10n_audit.conflicts")


@dataclass
class MutationRecord:
    """Represents a proposed change to a specific string segment.
    
    Priority Model:
    3 = auto_fix
    2 = ai_review
    1 = manual
    """
    key: str
    original_text: str
    new_text: str
    offset: int         # -1 if unknown
    length: int         # 0 if unknown
    source: str         # "auto_fix", "ai_review", "manual"
    priority: int
    mutation_id: str = "" # Optional logical segment ID


class ConflictResolver:
    """A shared registry that tracks and resolves mutation overlaps.
    
    This object should be shared across a single run to ensure cross-stage
    governance (e.g., ai_review respects auto_fix).
    """
    def __init__(self) -> None:
        # Maps key -> list of MutationRecords that were accepted
        self._registry: Dict[str, List[MutationRecord]] = {}
        
        # Statistics
        self.conflicts_detected = 0
        self.conflicts_resolved = 0 # Higher priority overwriting or blocking
        self.rejected_low_priority = 0

    def register(self, record: MutationRecord) -> bool:
        """Attempt to register a mutation. Returns True if accepted.
        
        Rejects if it overlaps with an already accepted mutation of 
        equal or higher priority.
        """
        key = record.key
        if key not in self._registry:
            self._registry[key] = [record]
            return True

        existing_records = self._registry[key]
        
        conflicts = [ex for ex in existing_records if self._is_conflict(record, ex)]

        if not conflicts:
            existing_records.append(record)
            return True

        for existing in conflicts:
            self.conflicts_detected += 1

            if record.priority <= existing.priority:
                # Tie → stable first-wins; lower priority → reject new
                self.rejected_low_priority += 1
                logger.debug(
                    "CONFLICT REJECTED: key=%r source=%r (P%d) loses to existing P%d",
                    key, record.source, record.priority, existing.priority,
                )
                return False

        # New mutation has strictly higher priority than every conflicting record.
        # Replace all conflicting records with the new one.
        self._registry[key] = [r for r in existing_records if r not in conflicts]
        self._registry[key].append(record)
        self.conflicts_resolved += len(conflicts)
        logger.debug(
            "CONFLICT RESOLVED: key=%r source=%r (P%d) overrides %d lower-priority record(s)",
            key, record.source, record.priority, len(conflicts),
        )
        return True

    def _is_conflict(self, r1: MutationRecord, r2: MutationRecord) -> bool:
        """Return True if two mutations overlap spatially or logically."""
        # 1. Spatial check (if both have valid offsets)
        if r1.offset >= 0 and r2.offset >= 0:
            s1, e1 = r1.offset, r1.offset + r1.length
            s2, e2 = r2.offset, r2.offset + r2.length
            # Overlap exists if max start < min end
            if max(s1, s2) < min(e1, e2):
                return True
            return False

        # 2. Logical identity fallback
        if r1.mutation_id and r2.mutation_id:
            return r1.mutation_id == r2.mutation_id

        # 3. Safe fallback: any mutation on the same key with missing offset
        # is a conflict to prevent corruption.
        return r1.original_text == r2.original_text

    def summarize(self) -> Dict[str, int]:
        """Return metrics for injection into runtime.metadata."""
        return {
            "conflicts_detected": self.conflicts_detected,
            "conflicts_resolved": self.conflicts_resolved,
            "rejected_low_priority": self.rejected_low_priority,
        }


def get_conflict_resolver(runtime: Any) -> ConflictResolver:
    """Helper to retrieve or initialize a shared resolver on the runtime object.
    
    Ensures a single registry is used across the command execution.
    """
    if not hasattr(runtime, "_conflict_resolver"):
        setattr(runtime, "_conflict_resolver", ConflictResolver())
    return getattr(runtime, "_conflict_resolver")
