"""演示脚本：按 受理→证据→假设→规划→结果→结论 顺序跑完一个 E106 场景。

用法：

    python scripts/demo_diagnosis.py --variant text_only
    python scripts/demo_diagnosis.py --variant with_photo --base-url http://localhost:8000/api/v1

脚本只通过 REST 接口驱动后端（需先启动 `uvicorn services.api.app.main:app` 并执行
`python scripts/seed_demo.py`）。每步打印 JSON，最终根因等于场景 `true_cause_code`
时输出 `DEMO OK` 并退出码 0，否则打印失败步骤并退出码 1。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO = ROOT / "data" / "scenarios" / "v1" / "e106.json"
MAX_PLAN_ROUNDS = 5


class DemoError(Exception):
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


class DemoClient:
    def __init__(self, base_url: str, *, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.token: str | None = None

    def close(self) -> None:
        self.client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        step: str,
        json_body: dict | None = None,
        files: dict | None = None,
    ) -> dict:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = self.client.request(
            method, path, json=json_body, files=files, headers=headers
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        if response.status_code >= 400:
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                raise DemoError(
                    step,
                    str(error.get("code") or "HTTP_ERROR"),
                    str(error.get("message") or response.reason_phrase),
                    error.get("details"),
                )
            raise DemoError(step, "HTTP_ERROR", response.reason_phrase, payload)
        return payload

    def post(self, path: str, *, step: str, json_body: dict | None = None) -> dict:
        return self._request("POST", path, step=step, json_body=json_body)

    def get(self, path: str, *, step: str) -> dict:
        return self._request("GET", path, step=step)

    def upload(self, case_id: str, filename: str, content_type: str, data: bytes, *, step: str) -> dict:
        return self._request(
            "POST",
            f"/cases/{case_id}/uploads",
            step=step,
            files={"file": (filename, data, content_type)},
        )

    def login(self, email: str, password: str) -> dict:
        payload = self.post(
            "/auth/login", step="login", json_body={"email": email, "password": password}
        )
        self.token = payload.get("access_token") or payload.get("token")
        if not self.token:
            raise DemoError("login", "NO_TOKEN", "登录响应缺少 access_token")
        return payload


def _print_step(step: str, **payload: Any) -> None:
    print(json.dumps({"step": step, **payload}, ensure_ascii=False, indent=2))


def _upload_bytes(upload: dict) -> tuple[str, str, bytes]:
    filename = str(upload.get("filename") or "upload.bin")
    content_type = str(upload.get("content_type") or "application/octet-stream")
    text = str(upload.get("text") or "")
    data = text.encode("utf-8")
    if content_type.startswith("image/"):
        # 图片只用于触发 OCR 的型号识别，补齐最小体积以满足上传校验
        data = data + b"\x00" * max(0, 512 - len(data))
    return filename, content_type, data


def run(args: argparse.Namespace) -> int:
    scenario_path = Path(args.scenario)
    try:
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({"step": "load_scenario", "error": str(exc)}, ensure_ascii=False))
        return 1

    variant = next(
        (item for item in scenario.get("variants", []) if item.get("id") == args.variant),
        None,
    )
    if variant is None:
        available = [item.get("id") for item in scenario.get("variants", [])]
        print(
            json.dumps(
                {
                    "step": "load_scenario",
                    "error": f"变体 {args.variant} 不存在",
                    "available": available,
                },
                ensure_ascii=False,
            )
        )
        return 1

    probe_answers: dict[str, str] = variant.get("probe_answers") or {}
    client = DemoClient(args.base_url)
    try:
        client.login(args.email, args.password)
        _print_step("login", user=args.email, role="agent")

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
        _print_step("create_case", case_id=case_id, case=case)

        upload = variant.get("upload")
        if upload:
            filename, content_type, data = _upload_bytes(upload)
            stored = client.upload(case_id, filename, content_type, data, step="upload")
            _print_step("upload", upload=stored)

        intake = client.post(
            f"/cases/{case_id}/intake", step="intake", json_body={"user_text": variant["symptom"]}
        )
        _print_step(
            "intake",
            case_status=intake["case"]["status"],
            device_model=intake["case"].get("device_model"),
            needs_human=intake.get("needs_human"),
        )

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
            _print_step(
                f"evidence_{index}",
                evidence_id=evidence["id"],
                source_type=evidence["source_type"],
                polarity=evidence["polarity"],
            )

        hypotheses = client.post(f"/cases/{case_id}/hypotheses/generate", step="generate_hypotheses")
        _print_step(
            "generate_hypotheses",
            case_status=hypotheses["case_status"],
            hypotheses=[
                {
                    "cause_code": item["cause_code"],
                    "label": item["label"],
                    "status": item["status"],
                    "confidence_level": item["confidence_level"],
                }
                for item in hypotheses["items"]
            ],
        )

        final: dict | None = None
        for round_no in range(1, MAX_PLAN_ROUNDS + 1):
            plan = client.post(f"/cases/{case_id}/probes/plan", step=f"plan_probe_{round_no}")
            probe = plan.get("probe")
            if not probe:
                _print_step(f"plan_probe_{round_no}", case_status=plan["case_status"], probe_card=None)
                final = client.post(f"/cases/{case_id}/finalize-diagnosis", step="finalize")
                break

            snapshot = client.get(f"/cases/{case_id}/hypotheses", step=f"hypotheses_{round_no}")
            _print_step(
                f"plan_probe_{round_no}",
                case_status=plan["case_status"],
                probe_card=probe,
                hypothesis_snapshot=[
                    {
                        "cause_code": item["cause_code"],
                        "status": item["status"],
                        "confidence_level": item["confidence_level"],
                    }
                    for item in snapshot["items"]
                ],
            )

            answer = probe_answers.get(probe["code"])
            if answer is None:
                print(
                    json.dumps(
                        {
                            "step": f"probe_result_{round_no}",
                            "warning": f"场景未提供 {probe['code']} 的观察值，停止规划",
                        },
                        ensure_ascii=False,
                    )
                )
                final = client.post(f"/cases/{case_id}/finalize-diagnosis", step="finalize")
                break

            result = client.post(
                f"/cases/{case_id}/probes/{probe['probe_id']}/result",
                step=f"probe_result_{round_no}",
                json_body={"observed_value": answer},
            )
            _print_step(
                f"probe_result_{round_no}",
                probe_code=probe["code"],
                observed_value=answer,
                result=result,
            )

            try:
                final = client.post(f"/cases/{case_id}/finalize-diagnosis", step="finalize")
                break
            except DemoError as exc:
                if exc.code == "PROBE_AVAILABLE" and round_no < MAX_PLAN_ROUNDS:
                    _print_step(f"finalize_after_{round_no}", case_status="PROBE_AVAILABLE", error=exc.as_dict())
                    continue
                raise

        if final is None:
            final = client.post(f"/cases/{case_id}/finalize-diagnosis", step="finalize")

        root_cause = final.get("root_cause") or {}
        cause_code = root_cause.get("cause_code")
        _print_step("final", final=final)

        if final.get("case_status") != "DIAGNOSED":
            _print_step("assert", failure=f"案例状态不是 DIAGNOSED：{final.get('case_status')}")
            return 1
        if cause_code != scenario["true_cause_code"]:
            _print_step(
                "assert",
                failure=f"根因 {cause_code} 与真根因 {scenario['true_cause_code']} 不一致",
            )
            return 1

        print("DEMO OK")
        return 0
    except DemoError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False, indent=2))
        return 1
    except httpx.HTTPError as exc:
        print(json.dumps({"step": "http", "error": str(exc)}, ensure_ascii=False))
        return 1
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="智修 V1.2 诊断演示脚本")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--scenario", default=str(DEFAULT_SCENARIO))
    parser.add_argument(
        "--variant", default="text_only", choices=["text_only", "with_photo", "with_probe_result"]
    )
    parser.add_argument("--email", default="agent@demo.local")
    parser.add_argument("--password", default="demo1234")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())