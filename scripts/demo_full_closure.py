"""全链路演示：诊断 → 维修方案 → 配件校验 → 审批 → 幂等工单 → 结果回收 → 关闭。

用法：

    python scripts/demo_full_closure.py
    python scripts/demo_full_closure.py --base-url http://localhost:8000/api/v1
    python scripts/demo_full_closure.py --variant text_only

要求后端已启动并写入种子数据（`seed_demo.py` + `seed_parts.py`）。脚本只通过 REST
接口驱动业务，最终案例进入 `CLOSED` 且结果与诊断一致时输出 `CLOSURE OK` 并退出码 0；
任一步失败会打印失败步骤并以退出码 1 结束。结果录入使用 technician 账号，工单 assignee
设为该 technician 的 user id。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO = ROOT / "data" / "scenarios" / "v1" / "e106.json"
MAX_PLAN_ROUNDS = 5


class ClosureError(Exception):
    def __init__(self, step: str, code: str, message: str, details: Any = None) -> None:
        super().__init__(f"{step}: {code} {message}")
        self.step = step
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "error": {"code": self.code, "message": self.message, "details": self.details},
        }


class ApiClient:
    def __init__(self, base_url: str, *, timeout: float = 120.0) -> None:
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        self.token: str | None = None

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, path: str, *, step: str, json_body: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = self.client.request(method, path, json=json_body, headers=headers)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        if response.status_code >= 400:
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                raise ClosureError(
                    step,
                    str(error.get("code") or "HTTP_ERROR"),
                    str(error.get("message") or response.reason_phrase),
                    error.get("details"),
                )
            raise ClosureError(step, "HTTP_ERROR", response.reason_phrase, payload)
        return payload

    def post(self, path: str, *, step: str, json_body: dict | None = None) -> dict:
        return self._request("POST", path, step=step, json_body=json_body)

    def get(self, path: str, *, step: str) -> dict:
        return self._request("GET", path, step=step)

    def login(self, email: str, password: str, *, step: str = "login") -> dict:
        payload = self.post(
            "/auth/login", step=step, json_body={"email": email, "password": password}
        )
        self.token = payload.get("access_token") or payload.get("token")
        if not self.token:
            raise ClosureError(step, "NO_TOKEN", "登录响应缺少 access_token")
        return payload


def _print_step(step: str, **payload: Any) -> None:
    print(json.dumps({"step": step, **payload}, ensure_ascii=False, indent=2))


def _expect(step: str, actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise ClosureError(step, "ASSERTION_FAILED", f"{label} 期望 {expected}，实际 {actual}")


def _run_diagnosis(client: ApiClient, scenario: dict, variant: dict) -> tuple[str, dict]:
    case = client.post(
        "/cases",
        step="create_case",
        json_body={
            "device_model": scenario["device_model"],
            "symptom": variant["symptom"],
            "error_code": scenario["error_code"],
        },
    )
    case_id = case["id"]
    _print_step("create_case", case_id=case_id, case_status=case.get("status"))

    intake = client.post(
        f"/cases/{case_id}/intake", step="intake", json_body={"user_text": variant["symptom"]}
    )
    _print_step("intake", case_status=intake["case"]["status"])

    for index, item in enumerate(variant.get("evidence", []), start=1):
        evidence = client.post(
            f"/cases/{case_id}/evidence",
            step=f"evidence_{index}",
            json_body={
                "source_type": item["source_type"],
                "polarity": item["polarity"],
                "quote": item["quote"],
            },
        )
        _print_step(f"evidence_{index}", evidence_id=evidence["id"], polarity=evidence["polarity"])

    hypotheses = client.post(f"/cases/{case_id}/hypotheses/generate", step="generate_hypotheses")
    _print_step(
        "generate_hypotheses",
        case_status=hypotheses["case_status"],
        hypotheses=[
            {
                "cause_code": item["cause_code"],
                "status": item["status"],
                "confidence_level": item["confidence_level"],
            }
            for item in hypotheses["items"]
        ],
    )

    probe_answers: dict[str, str] = variant.get("probe_answers") or {}
    final: dict | None = None
    for round_no in range(1, MAX_PLAN_ROUNDS + 1):
        plan = client.post(f"/cases/{case_id}/probes/plan", step=f"plan_probe_{round_no}")
        probe = plan.get("probe")
        if not probe:
            _print_step(f"plan_probe_{round_no}", case_status=plan["case_status"], probe_card=None)
            final = client.post(f"/cases/{case_id}/finalize-diagnosis", step="finalize")
            break

        answer = probe_answers.get(probe["code"])
        _print_step(
            f"plan_probe_{round_no}",
            case_status=plan["case_status"],
            probe_code=probe["code"],
            observed_value=answer,
        )
        if answer is None:
            final = client.post(f"/cases/{case_id}/finalize-diagnosis", step="finalize")
            break

        result = client.post(
            f"/cases/{case_id}/probes/{probe['probe_id']}/result",
            step=f"probe_result_{round_no}",
            json_body={"observed_value": answer},
        )
        _print_step(f"probe_result_{round_no}", case_status=result.get("case_status"))
        try:
            final = client.post(f"/cases/{case_id}/finalize-diagnosis", step="finalize")
            break
        except ClosureError as exc:
            if exc.code == "PROBE_AVAILABLE" and round_no < MAX_PLAN_ROUNDS:
                _print_step(f"finalize_after_{round_no}", waiting_for="PROBE_AVAILABLE")
                continue
            raise

    if final is None:
        final = client.post(f"/cases/{case_id}/finalize-diagnosis", step="finalize")
    _expect("finalize", final.get("case_status"), "DIAGNOSED", "案例状态")
    root_cause = final.get("root_cause") or {}
    cause_code = root_cause.get("cause_code")
    if not cause_code:
        raise ClosureError("finalize", "NO_ROOT_CAUSE", "诊断结论缺少根因")
    _print_step("finalize", case_status=final["case_status"], root_cause=cause_code)
    return case_id, final


def _pick_option(plan: dict) -> dict:
    options = plan.get("options") or []
    if not options:
        raise ClosureError("repair_plan", "NO_OPTIONS", "维修方案为空")
    recommended = plan.get("recommended")
    for option in options:
        if recommended and option.get("action") == recommended:
            return option
    return options[0]


def _option_part_numbers(option: dict) -> list[str]:
    part_numbers: list[str] = []
    for part in option.get("parts") or []:
        if isinstance(part, dict) and part.get("part_no"):
            part_numbers.append(str(part["part_no"]))
    return part_numbers


def _actor_id(payload: dict) -> str:
    user = payload.get("user") if isinstance(payload.get("user"), dict) else payload
    actor_id = user.get("id") or user.get("user_id")
    if not actor_id:
        raise ClosureError("technician_profile", "NO_ACTOR_ID", "当前用户档案缺少 user id")
    return str(actor_id)


def run(args: argparse.Namespace) -> int:
    try:
        scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _print_step("load_scenario", error=str(exc))
        return 1

    variant = next(
        (item for item in scenario.get("variants", []) if item.get("id") == args.variant),
        None,
    )
    if variant is None:
        _print_step(
            "load_scenario",
            error=f"变体 {args.variant} 不存在",
            available=[item.get("id") for item in scenario.get("variants", [])],
        )
        return 1

    agent = ApiClient(args.base_url)
    technician = ApiClient(args.base_url)
    try:
        agent.login(args.email, args.password, step="login_agent")
        technician.login(args.tech_email, args.tech_password, step="login_technician")
        technician_id = _actor_id(technician.get("/auth/me", step="technician_profile"))
        _print_step(
            "login", agent=args.email, technician=args.tech_email, technician_id=technician_id
        )

        case_id, final = _run_diagnosis(agent, scenario, variant)
        cause_code = str((final.get("root_cause") or {})["cause_code"])
        device_model = str(scenario["device_model"])

        plan = agent.post(f"/cases/{case_id}/repair-plan", step="repair_plan")
        _expect("repair_plan", plan.get("case_id"), case_id, "方案所属案例")
        option = _pick_option(plan)
        _print_step(
            "repair_plan",
            root_cause_code=plan.get("root_cause_code"),
            recommended=plan.get("recommended"),
            options=[
                {
                    "action": item.get("action"),
                    "parts_compatible": item.get("parts_compatible"),
                    "estimated_cost": item.get("estimated_cost"),
                }
                for item in plan.get("options") or []
            ],
            disclaimers=plan.get("disclaimers"),
        )

        model_query = quote(device_model, safe="")
        parts = agent.get(f"/parts?device_model={model_query}", step="list_parts")
        part_numbers = [item["part_no"] for item in parts.get("items") or []]
        if not part_numbers:
            raise ClosureError("list_parts", "NO_PARTS", f"型号 {device_model} 没有配件")
        checked = agent.get(
            f"/parts/{quote(part_numbers[0], safe='')}/compatibility?device_model={model_query}",
            step="check_part_compatibility",
        )
        _print_step(
            "check_part_compatibility",
            device_model=device_model,
            part_no=checked.get("part_no"),
            compatible=checked.get("compatible"),
            compatibility_type=checked.get("compatibility_type"),
            stock_status=checked.get("stock_status"),
            alternatives=checked.get("alternatives"),
        )

        submit = agent.post(f"/cases/{case_id}/submit-approval", step="submit_approval")
        _expect("submit_approval", submit.get("status"), "APPROVAL_PENDING", "审批状态")
        approval = agent.post(
            f"/cases/{case_id}/approvals",
            step="approve",
            json_body={"decision": "approve", "reason": "演示：方案与配件已校验"},
        )
        _expect("approve", approval["case"]["status"], "APPROVAL_PENDING", "审批后案例状态")
        _print_step("approve", approval_id=approval["approval"]["id"], decision="approve")

        idempotency_key = f"demo-{case_id}"
        first = agent.post(
            f"/cases/{case_id}/work-orders",
            step="create_work_order",
            json_body={"idempotency_key": idempotency_key, "assignee": technician_id},
        )
        second = agent.post(
            f"/cases/{case_id}/work-orders",
            step="create_work_order_repeat",
            json_body={"idempotency_key": idempotency_key, "assignee": technician_id},
        )
        _expect("create_work_order", first.get("created"), True, "首次建单 created")
        _expect("create_work_order_repeat", second.get("created"), False, "重复建单 created")
        _expect(
            "create_work_order_repeat",
            second["work_order"]["id"],
            first["work_order"]["id"],
            "重复建单工单号",
        )
        work_order_id = first["work_order"]["id"]
        _print_step(
            "create_work_order",
            work_order_id=work_order_id,
            idempotency_key=idempotency_key,
            created=first["created"],
            repeated_created=second["created"],
        )

        action = str(option.get("action") or "on_site")
        outcome = technician.post(
            f"/work-orders/{work_order_id}/outcome",
            step="record_outcome",
            json_body={
                "actual_cause_code": cause_code,
                "action": action,
                "parts_replaced": _option_part_numbers(option),
                "resolved": True,
                "note": "全链路演示：模拟维修结果，与诊断结论一致。",
            },
        )
        _expect("record_outcome", outcome.get("consistency"), "match", "结果一致性")
        _print_step(
            "record_outcome",
            outcome_id=outcome["outcome"]["id"],
            consistency=outcome.get("consistency"),
            action=action,
        )

        closed = agent.post(f"/cases/{case_id}/close", step="close_case")
        _expect("close_case", closed.get("status"), "CLOSED", "关闭后状态")
        _print_step("close_case", case_id=case_id, case_status=closed.get("status"))

        print("CLOSURE OK")
        return 0
    except ClosureError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2))
        return 1
    except httpx.HTTPError as exc:
        print(json.dumps({"step": "http", "error": str(exc)}, ensure_ascii=False))
        return 1
    finally:
        agent.close()
        technician.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="智修 V1.2 维修闭环全链路演示")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--scenario", default=str(DEFAULT_SCENARIO))
    parser.add_argument(
        "--variant", default="text_only", choices=["text_only", "with_photo", "with_probe_result"]
    )
    parser.add_argument("--email", default="agent@demo.local")
    parser.add_argument("--password", default="demo1234")
    parser.add_argument("--tech-email", default="tech@demo.local")
    parser.add_argument("--tech-password", default="demo1234")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())