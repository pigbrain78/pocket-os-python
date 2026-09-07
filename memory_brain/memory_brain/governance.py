"""governance.py -- policy gates.

Memory operations are governed. Deterministic business logic makes the final
decision; an LLM is only an advisory layer and NEVER rewrites authoritative
memory directly. Sensitive or irreversible operations (supersede, merge,
retract, delete, promote, share) pass through policy gates that require human
approval (represented as review-queue decisions or an explicit approval token).

This module encodes the *decision rules*. The review queue (review.py) holds
the pending human decisions; a governed operation consults both.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Operations that require human approval regardless of other factors
# (irreversible or authoritative-mutating).
_IRREVERSIBLE = {"retract", "delete", "promote", "share", "export_all"}
_MUTATING = {"supersede", "merge", "consolidate", "correct", "quarantine"}


@dataclass
class GovernanceDecision:
    allowed: bool
    requires_review: bool
    reason: str
    reviewer_hint: Optional[str] = None


class Governance:
    def __init__(self, allow_auto_commit: bool = False,
                 require_review_for_sensitive: bool = True):
        # Deterministic policy knobs. In production these come from a policy
        # store; here they are explicit so tests are deterministic.
        self.allow_auto_commit = allow_auto_commit
        self.require_review_for_sensitive = require_review_for_sensitive

    def evaluate(self, operation: str, *,
                 actor: Optional[str] = None,
                 is_llm: bool = False,
                 sensitive: bool = False,
                 high_impact: bool = False,
                 confidence: Optional[float] = None) -> GovernanceDecision:
        """Decide whether ``operation`` may proceed.

        Rules (deterministic, order matters):
          1. An LLM advisory actor may PROPOSE but never auto-commit an
             authoritative write unless the actor is explicitly an authorized
             operator (allow_auto_commit) -- by default LLM writes require
             review for anything mutating.
          2. Irreversible operations always require review (human gate).
          3. Mutating operations on sensitive or high-impact memories require
             review.
          4. New non-mutating, non-sensitive ACTIVE commits may auto-commit.
        """
        op = operation.lower()
        verb = op.split("_")[0]

        if op in _IRREVERSIBLE:
            return GovernanceDecision(
                False, True, "irreversible operation requires human approval",
                "owner/admin")

        mutating = op in _MUTATING or verb in {"supersede", "merge",
                                               "consolidate", "retract",
                                               "delete", "correct"}

        if is_llm and not self.allow_auto_commit:
            if mutating:
                return GovernanceDecision(
                    False, True,
                    "LLM advisory may not auto-commit a mutating memory "
                    "operation; requires human review", "owner/admin")
            # non-mutating proposal by an LLM: gate on sensitivity
            if sensitive and self.require_review_for_sensitive:
                return GovernanceDecision(
                    False, True, "sensitive proposal requires review",
                    "owner/admin")
            return GovernanceDecision(True, False, "advisory proposal allowed")

        if mutating and (sensitive or high_impact) and self.require_review_for_sensitive:
            return GovernanceDecision(
                False, True, "mutating operation on sensitive/high-impact "
                "memory requires human approval", "owner/admin")

        # Explicit low-confidence guard: never auto-commit very low confidence.
        if confidence is not None and confidence < 0.3 and mutating:
            return GovernanceDecision(
                False, True, "confidence below 0.3; requires human review",
                "reviewer")

        return GovernanceDecision(True, False, "operation allowed by policy")


def requires_review(decision: GovernanceDecision) -> bool:
    return decision.requires_review
