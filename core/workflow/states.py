"""C-STATE@1: V1.2 deterministic 13-state case workflow."""

from __future__ import annotations

from enum import Enum


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    COLLECTING_INFO = "COLLECTING_INFO"
    EVIDENCE_READY = "EVIDENCE_READY"
    HYPOTHESIZING = "HYPOTHESIZING"
    PROBE_PENDING = "PROBE_PENDING"
    PROBE_EVALUATING = "PROBE_EVALUATING"
    DIAGNOSED = "DIAGNOSED"
    REPAIR_PLANNING = "REPAIR_PLANNING"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    WORK_ORDER_CREATED = "WORK_ORDER_CREATED"
    OUTCOME_PENDING = "OUTCOME_PENDING"
    NEED_HUMAN = "NEED_HUMAN"
    CLOSED = "CLOSED"


ALLOWED_TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.DRAFT: frozenset(
        {CaseStatus.COLLECTING_INFO, CaseStatus.NEED_HUMAN, CaseStatus.CLOSED}
    ),
    CaseStatus.COLLECTING_INFO: frozenset({CaseStatus.EVIDENCE_READY, CaseStatus.NEED_HUMAN}),
    CaseStatus.EVIDENCE_READY: frozenset({CaseStatus.HYPOTHESIZING, CaseStatus.NEED_HUMAN}),
    CaseStatus.HYPOTHESIZING: frozenset(
        {CaseStatus.PROBE_PENDING, CaseStatus.DIAGNOSED, CaseStatus.NEED_HUMAN}
    ),
    CaseStatus.PROBE_PENDING: frozenset(
        {CaseStatus.PROBE_EVALUATING, CaseStatus.HYPOTHESIZING, CaseStatus.NEED_HUMAN}
    ),
    CaseStatus.PROBE_EVALUATING: frozenset(
        {CaseStatus.HYPOTHESIZING, CaseStatus.PROBE_PENDING, CaseStatus.NEED_HUMAN}
    ),
    CaseStatus.DIAGNOSED: frozenset(
        {CaseStatus.REPAIR_PLANNING, CaseStatus.HYPOTHESIZING, CaseStatus.NEED_HUMAN}
    ),
    CaseStatus.REPAIR_PLANNING: frozenset({CaseStatus.APPROVAL_PENDING, CaseStatus.NEED_HUMAN}),
    CaseStatus.APPROVAL_PENDING: frozenset(
        {CaseStatus.WORK_ORDER_CREATED, CaseStatus.NEED_HUMAN, CaseStatus.CLOSED}
    ),
    CaseStatus.WORK_ORDER_CREATED: frozenset({CaseStatus.OUTCOME_PENDING, CaseStatus.CLOSED}),
    CaseStatus.OUTCOME_PENDING: frozenset({CaseStatus.CLOSED, CaseStatus.NEED_HUMAN}),
    CaseStatus.NEED_HUMAN: frozenset(
        {CaseStatus.HYPOTHESIZING, CaseStatus.APPROVAL_PENDING, CaseStatus.CLOSED}
    ),
    CaseStatus.CLOSED: frozenset(),
}


class IllegalTransition(Exception):
    def __init__(self, from_status: CaseStatus | str, to_status: CaseStatus | str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"illegal transition: {_label(from_status)} -> {_label(to_status)}")


def _label(value: CaseStatus | str) -> str:
    return value.value if isinstance(value, CaseStatus) else str(value)


def coerce_status(value: CaseStatus | str) -> CaseStatus:
    if isinstance(value, CaseStatus):
        return value
    return CaseStatus(str(value).strip().upper())


def assert_transition(src: CaseStatus | str, dst: CaseStatus | str) -> CaseStatus:
    """Return the target status, or raise IllegalTransition when the edge is absent."""
    try:
        source = coerce_status(src)
        target = coerce_status(dst)
    except ValueError as exc:
        raise IllegalTransition(src, dst) from exc
    if target not in ALLOWED_TRANSITIONS[source]:
        raise IllegalTransition(source, target)
    return target