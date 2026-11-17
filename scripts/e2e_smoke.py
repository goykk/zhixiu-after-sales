"""端到端冒烟：认证→案例→上传→受理→证据→假设→规划→结果→结论。

用法：

    python scripts/e2e_smoke.py
    python scripts/e2e_smoke.py --base-url http://localhost:8000/api/v1 --variant with_photo

需要后端已启动并写入种子数据。全部步骤通过时输出 `E2E OK` 并退出码 0。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO = ROOT / "data" / "scenarios" / "v1" / "e106.json"
MAX_PLAN_ROUNDS = 5


class SmokeError(Exception):
    pass


class SmokeClient:
    def __init__(self, base_url: str, *, timeout: float = 120.0) -> None:
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        self.token: str | None = None

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, path: str, *, json_body: dict | None = None, files: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = self.client.request(method, path, json=json_body, files=files, headers=headers)
        try:
            payload = response.json()
        except ValueError:
            payload = {"raw": response.text}
        if response.status_code >= 400:
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else "HTTP_ERROR"
            message = error.get("message") if isinstance(error, dict) else response.reason_phrase
            raise SmokeError(f"{method} {path} -> {response.status_code} {code}: {message}")
        return payload

    def post(self, path: str, json_body: dict | None = None) -> dict:
        return self._request("POST", path, json_body=json_body)

    def upload(self, path: str, filename: str, content_type: str, data: bytes) -> dict:
        return self._request(
            "POST", path, files={"file": (filename, data, content_type)}
        )

    def login(self, email: str, password: str) -> None:
        payload = self.post("/auth/login", {"email": email, "password": password})
        self.token = payload.get("access_token") or payload.get("token")
        if not self.token:
            raise SmokeError("登录响应缺少 access_token")


def _upload_bytes(upload: dict) -> tuple[str, str, bytes]:
    filename = str(upload.get("filename") or "upload.bin")
    content_type = str(upload.get("content_type") or "application/octet-stream")
    data = str(upload.get("text") or "").encode("utf-8")
    if content_type.startswith("image/"):
        data = data + b"\x00" * max(0, 512 - len(data))
    return filename, content_type, data


def run(args: argparse.Namespace) -> int:
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    variant = next(
        (item for item in scenario.get("variants", []) if item.get("id") == args.variant), None
    )
    if variant is None:
        print(f"E2E FAILED: 变体 {args.variant} 不存在")
        return 1

    answers = variant.get("probe_answers") or {}
    client = SmokeClient(args.base_url)
    try:
        print("[1/9] 认证")
        client.login(args.email, args.password)

        print("[2/9] 创建案例")
        case = client.post(
            "/cases",
            {
                "device_model": scenario["device_model"],
                "symptom": variant["symptom"],
                "error_code": scenario["error_code"],
            },
        )
        case_id = case["id"]

        print("[3/9] 上传附件")
        upload = variant.get("upload")
        if upload:
            filename, content_type, data = _upload_bytes(upload)
            client.upload(f"/cases/{case_id}/uploads", filename, content_type, data)
        else:
            client.upload(
                f"/cases/{case_id}/uploads",
                "e2e-note.txt",
                "text/plain",
                f"{scenario['device_model']} {scenario['error_code']} 现象：{variant['symptom']}".encode(
                    "utf-8"
                ),
            )

        print("[4/9] 受理")
        intake = client.post(f"/cases/{case_id}/intake", {"user_text": variant["symptom"]})
        if intake["case"]["status"] not in {"COLLECTING_INFO", "NEED_HUMAN"}:
            raise SmokeError(f"受理后状态异常：{intake['case']['status']}")

        print("[5/9] 提交证据")
        for item in variant.get("evidence", []):
            client.post(
                f"/cases/{case_id}/evidence",
                {
                    "source_type": item["source_type"],
                    "polarity": item["polarity"],
                    "quote": item["quote"],
                },
            )

        print("[6/9] 生成候选根因")
        hypotheses = client.post(f"/cases/{case_id}/hypotheses/generate")
        if not hypotheses["items"]:
            raise SmokeError("未生成任何候选根因")

        print("[7/9] 规划检查")
        for round_no in range(1, MAX_PLAN_ROUNDS + 1):
            plan = client.post(f"/cases/{case_id}/probes/plan")
            probe = plan.get("probe")
            if not probe:
                break
            answer = answers.get(probe["code"])
            if answer is None:
                raise SmokeError(f"场景未提供 {probe['code']} 的观察值")
            print(f"[8/9] 回写检查结果 {round_no}：{probe['code']}")
            client.post(
                f"/cases/{case_id}/probes/{probe['probe_id']}/result",
                {"observed_value": answer},
            )

        print("[9/9] 生成结论")
        final = client.post(f"/cases/{case_id}/finalize-diagnosis")
        root_cause = final.get("root_cause") or {}
        if final.get("case_status") != "DIAGNOSED":
            raise SmokeError(f"案例状态不是 DIAGNOSED：{final.get('case_status')}")
        if root_cause.get("cause_code") != scenario["true_cause_code"]:
            raise SmokeError(
                f"根因 {root_cause.get('cause_code')} 与真根因 {scenario['true_cause_code']} 不一致"
            )
        if not final.get("evidence_chain"):
            raise SmokeError("结论缺少证据链")

        print(
            "结论：",
            json.dumps(
                {
                    "case_id": case_id,
                    "case_status": final["case_status"],
                    "root_cause": root_cause.get("cause_code"),
                    "confidence_level": root_cause.get("confidence_level"),
                    "evidence_chain": len(final["evidence_chain"]),
                },
                ensure_ascii=False,
            ),
        )
        print("E2E OK")
        return 0
    except (SmokeError, httpx.HTTPError, OSError, ValueError) as exc:
        print(f"E2E FAILED: {exc}")
        return 1
    finally:
        client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="智修 V1.2 端到端冒烟")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--scenario", default=str(DEFAULT_SCENARIO))
    parser.add_argument(
        "--variant", default="with_photo", choices=["text_only", "with_photo", "with_probe_result"]
    )
    parser.add_argument("--email", default="agent@demo.local")
    parser.add_argument("--password", default="demo1234")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())