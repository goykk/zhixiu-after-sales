"""LangGraph 可选编排适配（C-LANGGRAPH@1）。

默认编排由 `engine_factory.NativeDiagnosisFlow` 提供；本模块在
`WORKFLOW_ENGINE=langgraph` 时把同一组单步推进逻辑包装成 StateGraph。
业务判断全部委托 `core.diagnosis` / `core.probes` 服务，这里只做流程编排与状态读取；
因此 `DiagnosisFlowSteps` 同时被两种引擎复用，保证同一案例的推进结果一致。
"""

from __future__ import annotations

import importlib.util
from collections.abc import Mapping
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.cases.service import get_case
from core.db.models import Probe, ProbeResult
from core.diagnosis.hypotheses import generate_hypotheses
from core.diagnosis.orchestrator import finalize_diagnosis
from core.policy.rbac import Actor, Role
from core.probes.planner import plan_next_probe, record_probe_result
from core.workflow.states import CaseStatus
from services.api.app.config import settings
from services.api.app.errors import ApiError

# 编排由系统发起、没有登录用户；使用 admin 以满足案例可见性与最终定案权限。
SYSTEM_ACTOR = Actor(actor_id="system:workflow", role=Role.ADMIN)

_PLANNABLE = frozenset({CaseStatus.HYPOTHESIZING.value, CaseStatus.PROBE_PENDING.value})
_FINALIZABLE = frozenset(
    {
        CaseStatus.HYPOTHESIZING.value,
        CaseStatus.PROBE_PENDING.value,
        CaseStatus.DIAGNOSED.value,
    }
)
_STOP_CODES = frozenset({"INSUFFICIENT_EVIDENCE", "PROBE_AVAILABLE", "PENDING_PROBE"})


class FlowState(TypedDict, total=False):
    case_id: str
    case_status: str
    root_cause: str | None
    steps: int
    needs_human: bool
    node: str
    planned: bool
    applied: bool
    loops: int
    halted: str | None


def available() -> bool:
    """langgraph 是否可导入；只做模块探测，不触发实际导入。"""
    return importlib.util.find_spec("langgraph") is not None


def summarize_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """两种引擎共用出参：`{case_status, root_cause, steps, needs_human, node}`。"""
    return {
        "case_status": state["case_status"],
        "root_cause": state.get("root_cause"),
        "steps": int(state.get("steps") or 0),
        "needs_human": bool(state.get("needs_human")) or state.get("halted") is not None,
        "node": state.get("node") or "load_case",
    }


class DiagnosisFlowSteps:
    """单步推进节点：只调用既有服务，并按案例状态决定下一步走向。"""

    def __init__(self, db: Session) -> None:
        self._db = db

    def load_case(self, state: Mapping[str, Any]) -> dict[str, Any]:
        return self._refresh(state, "load_case")

    def ensure_hypotheses(self, state: Mapping[str, Any]) -> dict[str, Any]:
        if state["case_status"] == CaseStatus.EVIDENCE_READY.value:
            generate_hypotheses(self._db, case_id=state["case_id"], actor=SYSTEM_ACTOR)
            return self._refresh(state, "ensure_hypotheses")
        return {"node": "ensure_hypotheses"}

    def plan_probe(self, state: Mapping[str, Any]) -> dict[str, Any]:
        loops = int(state.get("loops") or 0) + 1
        if state["case_status"] not in _PLANNABLE:
            return {
                "node": "plan_probe",
                "planned": False,
                "loops": loops,
                "halted": "status_not_plannable",
            }
        probe = plan_next_probe(self._db, case_id=state["case_id"], actor=SYSTEM_ACTOR)
        return {
            **self._refresh(state, "plan_probe"),
            "planned": probe is not None,
            "loops": loops,
            "halted": None if probe is not None else "no_candidate_probe",
        }

    def apply_pending(self, state: Mapping[str, Any]) -> dict[str, Any]:
        probe = self._pending_probe(state["case_id"])
        if probe is None:
            return {"node": "apply_pending", "applied": False, "halted": "no_pending_probe"}
        stored = self._db.scalar(select(ProbeResult).where(ProbeResult.probe_id == probe.id))
        if stored is None:
            # 检查已规划但外部尚未回写观察值：停在等待人工输入。
            return {"node": "apply_pending", "applied": False, "halted": "awaiting_input"}
        try:
            record_probe_result(
                self._db,
                case_id=state["case_id"],
                probe_id=probe.id,
                observed_value=stored.observed_value,
                source_ref=stored.source_ref,
                actor=SYSTEM_ACTOR,
            )
        except (ApiError, IntegrityError):
            # 结果行已存在时再次回写会撞 `probe_results.probe_id` 唯一约束；
            # 这种不一致数据下停止推进，交给人工处理。
            self._db.rollback()
            return {
                "node": "apply_pending",
                "applied": False,
                "halted": "result_already_recorded",
            }
        return {**self._refresh(state, "apply_pending"), "applied": True, "halted": None}

    def finalize(self, state: Mapping[str, Any]) -> dict[str, Any]:
        status = state["case_status"]
        if status not in _FINALIZABLE:
            return {"node": "finalize", "needs_human": True, "halted": "status_not_finalizable"}
        if self._pending_probe(state["case_id"]) is not None:
            return {"node": "finalize", "needs_human": True, "halted": "pending_probe"}
        try:
            result = finalize_diagnosis(self._db, case_id=state["case_id"], actor=SYSTEM_ACTOR)
        except ApiError as exc:
            if exc.code not in _STOP_CODES:
                raise
            return {"node": "finalize", "needs_human": True, "halted": exc.code}
        return {
            **self._refresh(state, "finalize"),
            "case_status": result.case_status,
            "root_cause": result.root_cause.cause_code if result.root_cause is not None else None,
            "needs_human": False,
            "halted": None,
        }

    def _refresh(self, state: Mapping[str, Any], node: str) -> dict[str, Any]:
        case = get_case(self._db, state["case_id"])
        return {
            "case_id": case.id,
            "case_status": str(case.status),
            "steps": int(case.step_count or 0),
            "node": node,
        }

    def _pending_probe(self, case_id: str) -> Probe | None:
        return self._db.scalar(
            select(Probe).where(Probe.case_id == case_id, Probe.status == "pending")
        )


def _route_after_plan(state: Mapping[str, Any]) -> str:
    return "apply_pending" if state.get("planned") else "finalize"


def _route_after_apply(state: Mapping[str, Any]) -> str:
    if not state.get("applied"):
        return "end"
    if int(state.get("loops") or 0) >= max(1, int(settings.max_probe_steps)):
        return "finalize"
    return "plan_probe"


class LangGraphDiagnosisFlow:
    """由 StateGraph 调度 `DiagnosisFlowSteps` 的案例推进器。"""

    def __init__(self, db: Session, retriever: Any = None, llm: Any = None) -> None:
        # 延迟导入：未安装 langgraph 时本模块仍可用于 native 回退探测。
        from langgraph.graph import END, START, StateGraph

        self._db = db
        self._retriever = retriever
        self._llm = llm
        steps = DiagnosisFlowSteps(db)
        graph = StateGraph(FlowState)
        graph.add_node("load_case", steps.load_case)
        graph.add_node("ensure_hypotheses", steps.ensure_hypotheses)
        graph.add_node("plan_probe", steps.plan_probe)
        graph.add_node("apply_pending", steps.apply_pending)
        graph.add_node("finalize", steps.finalize)
        graph.add_edge(START, "load_case")
        graph.add_edge("load_case", "ensure_hypotheses")
        graph.add_edge("ensure_hypotheses", "plan_probe")
        graph.add_conditional_edges(
            "plan_probe",
            _route_after_plan,
            {"apply_pending": "apply_pending", "finalize": "finalize"},
        )
        graph.add_conditional_edges(
            "apply_pending",
            _route_after_apply,
            {"plan_probe": "plan_probe", "end": END},
        )
        graph.add_edge("finalize", END)
        self._graph = graph.compile()

    def advance(self, case_id: str) -> dict[str, Any]:
        # 每轮检查最多 4 个节点，按 max_probe_steps 放大递归上限，避免图默认 25 步截断。
        limit = max(25, 4 * max(1, int(settings.max_probe_steps)) + 8)
        state = self._graph.invoke({"case_id": case_id}, config={"recursion_limit": limit})
        return summarize_state(state)