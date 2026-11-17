"""编排引擎工厂（C-LANGGRAPH@1）：native 默认，langgraph 可选且回退可观测。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.observability.tracer import get_tracer
from core.workflow.langgraph_adapter import (
    DiagnosisFlowSteps,
    FlowState,
    LangGraphDiagnosisFlow,
    available,
    summarize_state,
)
from services.api.app.config import settings


class NativeDiagnosisFlow:
    """确定性线性推进：与 LangGraph 图共用节点逻辑，差别只在没有图调度。"""

    def __init__(self, db: Session, retriever: Any = None, llm: Any = None) -> None:
        self._db = db
        self._retriever = retriever
        self._llm = llm
        self._steps = DiagnosisFlowSteps(db)

    def advance(self, case_id: str) -> dict[str, Any]:
        state: FlowState = self._steps.load_case({"case_id": case_id})
        state = {**state, **self._steps.ensure_hypotheses(state)}
        while True:
            state = {**state, **self._steps.plan_probe(state)}
            if not state.get("planned"):
                state = {**state, **self._steps.finalize(state)}
                break
            state = {**state, **self._steps.apply_pending(state)}
            if not state.get("applied"):
                break
            if int(state.get("steps") or 0) >= max(1, int(settings.max_probe_steps)):
                break
        return summarize_state(state)


def get_engine(
    db: Session, *, retriever: Any = None, llm: Any = None
) -> NativeDiagnosisFlow | LangGraphDiagnosisFlow:
    """按 `settings.workflow_engine` 选择引擎；请求 langgraph 不可用时回退并追踪。"""
    # `workflow_engine` 由 C-VECTOR@1 引入；缺失时按契约默认值 native 处理。
    requested = getattr(settings, "workflow_engine", "native")
    if requested == "langgraph":
        if not available():
            get_tracer().emit(
                "workflow_engine_fallback",
                requested="langgraph",
                reason="langgraph_not_installed",
            )
        else:
            try:
                return LangGraphDiagnosisFlow(db, retriever, llm)
            except Exception as exc:  # 适配层初始化失败不得中断诊断流程
                get_tracer().emit(
                    "workflow_engine_fallback",
                    requested="langgraph",
                    reason=f"adapter_init_failed:{type(exc).__name__}",
                )
    return NativeDiagnosisFlow(db, retriever, llm)