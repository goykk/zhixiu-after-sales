"""HTTP 认证、权限、全链路与 409 测试（C-APP@1 / C-AUTH@1 / C-WORKFLOW）。"""

from __future__ import annotations


from services.api.app.config import settings

API = "/api/v1"

_PROBE_ANSWERS = {
    "ASK_SOUND": "有摩擦或刮擦声",
    "CHECK_ROTATION": "拨动叶片有明显卡滞或阻力",
    "PHOTO_BLADE": "叶片有异物或变形",
}


def _error_code(response) -> str:
    return response.json()["error"]["code"]


def _headers(seed_base, auth_headers, key: str) -> dict[str, str]:
    return auth_headers(seed_base["users"][key].email, seed_base["password"])


def _create_case(client, headers, *, device_model: str = "AC-Pro 1200", symptom: str = "风扇异响"):
    response = client.post(
        f"{API}/cases",
        json={"device_model": device_model, "symptom": symptom, "error_code": "E106"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _hypothesizing_case_via_api(client, headers):
    case = _create_case(client, headers)
    intake = client.post(
        f"{API}/cases/{case['id']}/intake",
        json={"user_text": "故障现象: 风扇转动时有摩擦异响"},
        headers=headers,
    )
    assert intake.status_code == 200, intake.text
    assert intake.json()["case"]["status"] == "COLLECTING_INFO"

    for quote in ("风扇叶片有异物卡阻", "风扇区域有摩擦异响"):
        response = client.post(
            f"{API}/cases/{case['id']}/evidence",
            json={"source_type": "customer", "polarity": "support", "quote": quote},
            headers=headers,
        )
        assert response.status_code == 201, response.text

    generated = client.post(f"{API}/cases/{case['id']}/hypotheses/generate", headers=headers)
    assert generated.status_code == 200, generated.text
    assert generated.json()["case_status"] == "HYPOTHESIZING"
    return case


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_register_login_and_me(client):
    payload = {"email": "signup@demo.local", "password": "secret123"}
    registered = client.post(f"{API}/auth/register", json=payload)
    assert registered.status_code == 201, registered.text
    body = registered.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "signup@demo.local"
    assert body["user"]["role"] == "user"

    duplicate = client.post(f"{API}/auth/register", json=payload)
    assert duplicate.status_code == 409
    assert _error_code(duplicate) == "EMAIL_EXISTS"

    login = client.post(f"{API}/auth/login", json=payload)
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "signup@demo.local"


def test_authentication_failures_are_indistinguishable(client):
    wrong = client.post(
        f"{API}/auth/login",
        json={"email": "nobody@demo.local", "password": "whatever"},
    )
    assert wrong.status_code == 401
    assert _error_code(wrong) == "INVALID_CREDENTIALS"

    missing = client.get(f"{API}/auth/me")
    assert missing.status_code == 401
    assert _error_code(missing) == "UNAUTHORIZED"

    invalid = client.get(f"{API}/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert invalid.status_code == 401
    body = invalid.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}


def test_user_creation_requires_admin(client, seed_base, auth_headers):
    user_headers = _headers(seed_base, auth_headers, "user")
    forbidden = client.post(
        f"{API}/auth/users",
        json={"email": "tech2@demo.local", "password": "test1234", "role": "technician"},
        headers=user_headers,
    )
    assert forbidden.status_code == 403
    assert _error_code(forbidden) == "FORBIDDEN"

    admin_headers = _headers(seed_base, auth_headers, "admin")
    created = client.post(
        f"{API}/auth/users",
        json={"email": "tech2@demo.local", "password": "test1234", "role": "technician"},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "technician"


def test_case_visibility_isolation_and_list_scoping(client, seed_base, auth_headers):
    user_headers = _headers(seed_base, auth_headers, "user")
    other_headers = _headers(seed_base, auth_headers, "technician")
    agent_headers = _headers(seed_base, auth_headers, "agent")

    case = _create_case(client, user_headers)
    detail = client.get(f"{API}/cases/{case['id']}", headers=user_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert set(body) == {"case", "evidence", "hypotheses", "probes", "steps", "uploads"}
    assert body["case"]["status"] == "DRAFT"

    denied = client.get(f"{API}/cases/{case['id']}", headers=other_headers)
    assert denied.status_code == 403
    assert _error_code(denied) == "FORBIDDEN"

    staff_view = client.get(f"{API}/cases/{case['id']}", headers=agent_headers)
    assert staff_view.status_code == 200

    unauthenticated = client.get(f"{API}/cases/{case['id']}")
    assert unauthenticated.status_code == 401

    own_list = client.get(f"{API}/cases", headers=user_headers).json()["items"]
    assert [item["id"] for item in own_list] == [case["id"]]
    assert own_list[0]["user_id"] == seed_base["users"]["user"].id

    staff_list = client.get(f"{API}/cases", headers=agent_headers).json()["items"]
    assert case["id"] in {item["id"] for item in staff_list}

    bad_status = client.get(f"{API}/cases?status=BOGUS", headers=user_headers)
    assert bad_status.status_code == 422
    assert _error_code(bad_status) == "INVALID_STATUS"

    missing = client.get(f"{API}/cases/does-not-exist", headers=user_headers)
    assert missing.status_code == 404
    assert _error_code(missing) == "CASE_NOT_FOUND"


def test_technician_cannot_create_case(client, seed_base, auth_headers):
    technician_headers = _headers(seed_base, auth_headers, "technician")
    response = client.post(
        f"{API}/cases",
        json={"device_model": "AC-Pro 1200", "symptom": "风扇异响"},
        headers=technician_headers,
    )
    assert response.status_code == 403
    assert _error_code(response) == "FORBIDDEN"


def test_invalid_evidence_via_api_returns_422(client, seed_base, auth_headers):
    user_headers = _headers(seed_base, auth_headers, "user")
    case = _create_case(client, user_headers)

    response = client.post(
        f"{API}/cases/{case['id']}/evidence",
        json={"source_type": "unknown", "polarity": "support", "quote": "引用"},
        headers=user_headers,
    )
    assert response.status_code == 422
    assert _error_code(response) == "INVALID_EVIDENCE"


def test_full_diagnosis_chain(client, seed_base, auth_headers):
    user_headers = _headers(seed_base, auth_headers, "user")
    agent_headers = _headers(seed_base, auth_headers, "agent")
    case = _hypothesizing_case_via_api(client, user_headers)

    # 更新后的矩阵：user 可规划检查并提交结果，但不可 finalize。
    codes: list[str] = []
    for _ in range(8):
        plan = client.post(f"{API}/cases/{case['id']}/probes/plan", headers=user_headers)
        assert plan.status_code == 200, plan.text
        card = plan.json()["probe"]
        if card is None:
            break
        codes.append(card["code"])
        submitted = client.post(
            f"{API}/cases/{case['id']}/probes/{card['probe_id']}/result",
            json={"observed_value": _PROBE_ANSWERS[card["code"]]},
            headers=user_headers,
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["needs_human"] is False

    assert codes == ["ASK_SOUND", "CHECK_ROTATION", "PHOTO_BLADE"]

    finalized = client.post(
        f"{API}/cases/{case['id']}/finalize-diagnosis", headers=agent_headers
    )
    assert finalized.status_code == 200, finalized.text
    diagnosis = finalized.json()
    assert diagnosis["case_status"] == "DIAGNOSED"
    assert diagnosis["root_cause"]["cause_code"] == "FAN_BLOCKED"
    assert diagnosis["root_cause"]["confidence_level"] == "high"
    assert diagnosis["evidence_chain"]
    assert all(item["source_type"] for item in diagnosis["evidence_chain"])



def test_diagnosis_summary_shape(client, seed_base, auth_headers):
    user_headers = _headers(seed_base, auth_headers, "user")
    agent_headers = _headers(seed_base, auth_headers, "agent")
    case = _hypothesizing_case_via_api(client, user_headers)

    for _ in range(8):
        plan = client.post(f"{API}/cases/{case['id']}/probes/plan", headers=user_headers)
        card = plan.json()["probe"]
        if card is None:
            break
        client.post(
            f"{API}/cases/{case['id']}/probes/{card['probe_id']}/result",
            json={"observed_value": _PROBE_ANSWERS[card["code"]]},
            headers=user_headers,
        )
    finalized = client.post(
        f"{API}/cases/{case['id']}/finalize-diagnosis", headers=agent_headers
    )
    assert finalized.status_code == 200

    summary = client.get(f"{API}/cases/{case['id']}/diagnosis", headers=user_headers)
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert set(body) == {
        "case",
        "evidence",
        "hypotheses",
        "probes",
        "root_cause",
        "evidence_chain",
    }
    assert body["root_cause"]["cause_code"] == "FAN_BLOCKED"
    assert body["evidence_chain"]


def test_conflict_resolution_409_paths(client, seed_base, auth_headers):
    user_headers = _headers(seed_base, auth_headers, "user")
    agent_headers = _headers(seed_base, auth_headers, "agent")
    case = _create_case(client, user_headers)

    not_ready = client.post(f"{API}/cases/{case['id']}/hypotheses/generate", headers=user_headers)
    assert not_ready.status_code == 409
    assert _error_code(not_ready) == "ILLEGAL_TRANSITION"

    no_plan = client.post(f"{API}/cases/{case['id']}/probes/plan", headers=agent_headers)
    assert no_plan.status_code == 409
    assert _error_code(no_plan) == "ILLEGAL_TRANSITION"

    forbidden_finalize = client.post(
        f"{API}/cases/{case['id']}/finalize-diagnosis", headers=user_headers
    )
    assert forbidden_finalize.status_code == 403
    assert _error_code(forbidden_finalize) == "FORBIDDEN"

    no_diagnosis = client.post(
        f"{API}/cases/{case['id']}/finalize-diagnosis", headers=agent_headers
    )
    assert no_diagnosis.status_code == 409
    assert _error_code(no_diagnosis) == "ILLEGAL_TRANSITION"


def test_duplicate_probe_result_returns_409(client, seed_base, auth_headers):
    user_headers = _headers(seed_base, auth_headers, "user")
    agent_headers = _headers(seed_base, auth_headers, "agent")
    case = _hypothesizing_case_via_api(client, user_headers)

    plan = client.post(f"{API}/cases/{case['id']}/probes/plan", headers=agent_headers)
    assert plan.status_code == 200
    probe = plan.json()["probe"]
    url = f"{API}/cases/{case['id']}/probes/{probe['probe_id']}/result"

    first = client.post(url, json={"observed_value": _PROBE_ANSWERS[probe["code"]]}, headers=agent_headers)
    assert first.status_code == 200
    second = client.post(url, json={"observed_value": _PROBE_ANSWERS[probe["code"]]}, headers=agent_headers)
    assert second.status_code == 409
    assert _error_code(second) == "PROBE_NOT_PENDING"


def test_upload_validation_and_text_intake(client, seed_base, auth_headers):
    user_headers = _headers(seed_base, auth_headers, "user")
    case = _create_case(client, user_headers)

    stored = client.post(
        f"{API}/cases/{case['id']}/uploads",
        files={
            "file": (
                "fault.txt",
                "型号 AC-Pro 1200 故障码 E106 故障现象: 风扇转动有摩擦声".encode("utf-8"),
                "text/plain",
            )
        },
        headers=user_headers,
    )
    assert stored.status_code == 201, stored.text
    assert stored.json()["status"] == "stored"

    rejected = client.post(
        f"{API}/cases/{case['id']}/uploads",
        files={"file": ("payload.exe", b"\x00" * 32, "application/x-msdownload")},
        headers=user_headers,
    )
    assert rejected.status_code == 422
    assert _error_code(rejected) == "UPLOAD_REJECTED"

    listed = client.get(f"{API}/cases/{case['id']}/uploads", headers=user_headers)
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1

    intake = client.post(f"{API}/cases/{case['id']}/intake", json={}, headers=user_headers)
    assert intake.status_code == 200
    assert intake.json()["extracted"]["device_model"] == "AC-Pro 1200"
    assert intake.json()["extracted"]["error_code"] == "E106"

def test_finalize_stop_conditions(client, seed_base, auth_headers):
    user_headers = _headers(seed_base, auth_headers, "user")
    agent_headers = _headers(seed_base, auth_headers, "agent")

    thin_case = _create_case(client, user_headers)
    evidence = client.post(
        f"{API}/cases/{thin_case['id']}/evidence",
        json={"source_type": "customer", "polarity": "support", "quote": "风扇叶片有异物"},
        headers=user_headers,
    )
    assert evidence.status_code == 201
    generated = client.post(
        f"{API}/cases/{thin_case['id']}/hypotheses/generate", headers=user_headers
    )
    assert generated.status_code == 200
    insufficient = client.post(
        f"{API}/cases/{thin_case['id']}/finalize-diagnosis", headers=agent_headers
    )
    assert insufficient.status_code == 409
    assert _error_code(insufficient) == "INSUFFICIENT_EVIDENCE"

    available_case = _hypothesizing_case_via_api(client, user_headers)
    available = client.post(
        f"{API}/cases/{available_case['id']}/finalize-diagnosis", headers=agent_headers
    )
    assert available.status_code == 409
    assert _error_code(available) == "PROBE_AVAILABLE"

    pending_case = _hypothesizing_case_via_api(client, user_headers)
    plan = client.post(f"{API}/cases/{pending_case['id']}/probes/plan", headers=agent_headers)
    assert plan.status_code == 200
    pending = client.post(
        f"{API}/cases/{pending_case['id']}/finalize-diagnosis", headers=agent_headers
    )
    assert pending.status_code == 409
    assert _error_code(pending) == "PENDING_PROBE"



def test_repeat_finalize_in_diagnosed_returns_existing_result(client, seed_base, auth_headers):
    user_headers = _headers(seed_base, auth_headers, "user")
    agent_headers = _headers(seed_base, auth_headers, "agent")
    case = _hypothesizing_case_via_api(client, user_headers)

    for _ in range(8):
        plan = client.post(f"{API}/cases/{case['id']}/probes/plan", headers=agent_headers)
        card = plan.json()["probe"]
        if card is None:
            break
        client.post(
            f"{API}/cases/{case['id']}/probes/{card['probe_id']}/result",
            json={"observed_value": _PROBE_ANSWERS[card["code"]]},
            headers=agent_headers,
        )

    first = client.post(f"{API}/cases/{case['id']}/finalize-diagnosis", headers=agent_headers)
    assert first.status_code == 200
    repeated = client.post(
        f"{API}/cases/{case['id']}/finalize-diagnosis", headers=agent_headers
    )
    assert repeated.status_code == 200
    assert repeated.json()["root_cause"]["cause_code"] == first.json()["root_cause"]["cause_code"]


def test_device_administration(client, seed_base, auth_headers):
    agent_headers = _headers(seed_base, auth_headers, "agent")
    user_headers = _headers(seed_base, auth_headers, "user")

    listed = client.get(f"{API}/devices", headers=agent_headers)
    assert listed.status_code == 200
    assert seed_base["device"].id in {item["id"] for item in listed.json()}

    filtered = client.get(
        f"{API}/devices",
        params={"brand": "aurorahome", "model": "ac-pro 1200"},
        headers=agent_headers,
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()] == [seed_base["device"].id]

    created = client.post(
        f"{API}/devices",
        json={"brand": "AuroraHome", "model": "AC-Pro 900", "hardware_version": "HW-1"},
        headers=agent_headers,
    )
    assert created.status_code == 201, created.text
    device_id = created.json()["id"]

    duplicate = client.post(
        f"{API}/devices",
        json={"brand": "AuroraHome", "model": "AC-Pro 900"},
        headers=agent_headers,
    )
    assert duplicate.status_code == 409
    assert _error_code(duplicate) == "DEVICE_EXISTS"

    fetched = client.get(f"{API}/devices/{device_id}", headers=agent_headers)
    assert fetched.status_code == 200
    assert fetched.json()["model"] == "AC-Pro 900"

    missing = client.get(f"{API}/devices/does-not-exist", headers=agent_headers)
    assert missing.status_code == 404
    assert _error_code(missing) == "DEVICE_NOT_FOUND"

    forbidden = client.post(
        f"{API}/devices",
        json={"brand": "Other", "model": "X-1"},
        headers=user_headers,
    )
    assert forbidden.status_code == 403
    assert _error_code(forbidden) == "FORBIDDEN"


def test_manual_upload_list_and_index(client, seed_base, auth_headers):
    agent_headers = _headers(seed_base, auth_headers, "agent")
    user_headers = _headers(seed_base, auth_headers, "user")
    device_id = seed_base["device"].id

    uploaded = client.post(
        f"{API}/manuals",
        data={"device_id": device_id, "title": "风扇补充手册", "version": "v2"},
        files={"file": ("fan.md", "# 风扇\n叶片卡阻检查流程".encode("utf-8"), "text/markdown")},
        headers=agent_headers,
    )
    assert uploaded.status_code == 201, uploaded.text
    manual = uploaded.json()
    assert manual["status"] == "pending"
    assert manual["title"] == "风扇补充手册"

    listed = client.get(f"{API}/manuals", params={"device_id": device_id}, headers=agent_headers)
    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()} >= {manual["id"], seed_base["manual"].id}

    indexed = client.post(f"{API}/manuals/{manual['id']}/index", headers=agent_headers)
    assert indexed.status_code == 200, indexed.text
    assert indexed.json()["status"] == "indexed"
    assert indexed.json()["chunk_count"] >= 1

    missing_manual = client.post(f"{API}/manuals/does-not-exist/index", headers=agent_headers)
    assert missing_manual.status_code == 404
    assert _error_code(missing_manual) == "MANUAL_NOT_FOUND"

    unsupported = client.post(
        f"{API}/manuals",
        data={"device_id": device_id},
        files={"file": ("manual.zip", b"x" * 32, "application/zip")},
        headers=agent_headers,
    )
    assert unsupported.status_code == 422
    assert _error_code(unsupported) == "MANUAL_TYPE_UNSUPPORTED"

    empty = client.post(
        f"{API}/manuals",
        data={"device_id": device_id},
        files={"file": ("empty.md", b"", "text/markdown")},
        headers=agent_headers,
    )
    assert empty.status_code == 422
    assert _error_code(empty) == "MANUAL_REJECTED"

    missing_device = client.post(
        f"{API}/manuals",
        data={"device_id": "does-not-exist"},
        files={"file": ("fan.md", b"# fan", "text/markdown")},
        headers=agent_headers,
    )
    assert missing_device.status_code == 404
    assert _error_code(missing_device) == "DEVICE_NOT_FOUND"

    forbidden = client.post(
        f"{API}/manuals",
        data={"device_id": device_id},
        files={"file": ("fan.md", b"# fan", "text/markdown")},
        headers=user_headers,
    )
    assert forbidden.status_code == 403


def test_search_returns_ranked_version_aware_items(client, seed_base, auth_headers, monkeypatch):
    headers = _headers(seed_base, auth_headers, "user")
    # Mock Embedder 是哈希向量，语义相似度不可靠；把阈值降到 0 以下以覆盖召回与重排路径。
    monkeypatch.setattr(settings, "relevance_threshold", -1.0)

    response = client.get(
        f"{API}/search",
        params={"q": "风扇异响", "device_id": seed_base["device"].id, "top_k": 3},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["query"] == "风扇异响"
    assert body["device_id"] == seed_base["device"].id
    assert body["items"]
    first = body["items"][0]
    assert first["manual_id"] == seed_base["manual"].id
    assert first["model"] == "AC-Pro 1200"
    assert first["version"] == "v1.2"
    assert first["page"] in (1, 2)
    assert first["relevance_score"] >= 0.0

    unscoped = client.get(f"{API}/search", params={"q": "风扇"}, headers=headers)
    assert unscoped.status_code == 200

    missing_device = client.get(
        f"{API}/search", params={"q": "风扇", "device_id": "does-not-exist"}, headers=headers
    )
    assert missing_device.status_code == 404
    assert _error_code(missing_device) == "DEVICE_NOT_FOUND"

    blank = client.get(f"{API}/search", params={"q": ""}, headers=headers)
    assert blank.status_code == 422