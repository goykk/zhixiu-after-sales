import type {
  AdvanceResult,
  Approval,
  AuthResponse,
  CaseCreateInput,
  CaseDetail,
  CaseSummary,
  CompatibilityResult,
  Device,
  DiagnosisResult,
  DiagnosisSummary,
  EvalRunSummary,
  EvidenceInput,
  EvidenceItem,
  Hypothesis,
  ItemList,
  JsonRecord,
  OutcomeInput,
  Overview,
  Part,
  Probe,
  ProbeCard,
  RepairOutcome,
  RepairPlan,
  TaskAccepted,
  TaskInfo,
  TaskList,
  ScenarioRunInput,
  ScenarioRunReport,
  ScenarioRunResult,
  UploadItem,
  User,
  WorkOrder,
} from "@/lib/types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api/v1";

const TOKEN_KEY = "zhixiu_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, code: string, message: string, details: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return `${err.code}: ${err.message}`;
  if (err instanceof Error) return err.message;
  return String(err);
}

type ErrorBody = {
  error?: { code?: string; message?: string; details?: unknown };
};

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "无法连接后端服务，请确认 API 已启动");
  }

  if (response.status === 401) {
    if (token) {
      setToken(null);
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.assign("/login");
      }
    }
    throw new ApiError(401, "UNAUTHORIZED", "登录已失效，请重新登录");
  }

  if (!response.ok) {
    let body: ErrorBody = {};
    try {
      body = (await response.json()) as ErrorBody;
    } catch {
      body = {};
    }
    throw new ApiError(
      response.status,
      body.error?.code ?? `HTTP_${response.status}`,
      body.error?.message ?? response.statusText,
      body.error?.details ?? null,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function login(email: string, password: string): Promise<AuthResponse> {
  return apiFetch<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function register(
  email: string,
  password: string,
  displayName?: string | null,
): Promise<AuthResponse> {
  return apiFetch<AuthResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, display_name: displayName ?? null }),
  });
}

export function me(): Promise<User> {
  return apiFetch<User>("/auth/me");
}

export function listCases(
  params: { status?: string; limit?: number; offset?: number } = {},
): Promise<ItemList<CaseSummary>> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  const qs = query.toString();
  return apiFetch<ItemList<CaseSummary>>(`/cases${qs ? `?${qs}` : ""}`);
}

export function createCase(payload: CaseCreateInput): Promise<CaseSummary> {
  return apiFetch<CaseSummary>("/cases", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCase(caseId: string): Promise<CaseDetail> {
  return apiFetch<CaseDetail>(`/cases/${caseId}`);
}

export function uploadFile(caseId: string, file: File): Promise<UploadItem> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch<UploadItem>(`/cases/${caseId}/uploads`, {
    method: "POST",
    body: form,
  });
}

export function intake(caseId: string, userText = ""): Promise<JsonRecord> {
  return apiFetch<JsonRecord>(`/cases/${caseId}/intake`, {
    method: "POST",
    body: JSON.stringify({ user_text: userText }),
  });
}

export function addEvidence(caseId: string, payload: EvidenceInput): Promise<EvidenceItem> {
  return apiFetch<EvidenceItem>(`/cases/${caseId}/evidence`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listEvidence(caseId: string): Promise<ItemList<EvidenceItem>> {
  return apiFetch<ItemList<EvidenceItem>>(`/cases/${caseId}/evidence`);
}

export function generateHypotheses(
  caseId: string,
): Promise<{ case_status: string; items: Hypothesis[] }> {
  return apiFetch<{ case_status: string; items: Hypothesis[] }>(
    `/cases/${caseId}/hypotheses/generate`,
    { method: "POST" },
  );
}

export function listHypotheses(caseId: string): Promise<ItemList<Hypothesis>> {
  return apiFetch<ItemList<Hypothesis>>(`/cases/${caseId}/hypotheses`);
}

export function planProbe(
  caseId: string,
): Promise<{ case_status: string; probe: ProbeCard | null }> {
  return apiFetch<{ case_status: string; probe: ProbeCard | null }>(
    `/cases/${caseId}/probes/plan`,
    { method: "POST" },
  );
}

export function submitProbeResult(
  caseId: string,
  probeId: string,
  observedValue: string,
  sourceRef?: string | null,
): Promise<{
  probe: Probe;
  hypotheses: Hypothesis[];
  case_status: string;
  needs_human: boolean;
}> {
  return apiFetch<{
    probe: Probe;
    hypotheses: Hypothesis[];
    case_status: string;
    needs_human: boolean;
  }>(`/cases/${caseId}/probes/${probeId}/result`, {
    method: "POST",
    body: JSON.stringify({ observed_value: observedValue, source_ref: sourceRef || null }),
  });
}

export function listProbes(caseId: string): Promise<ItemList<Probe>> {
  return apiFetch<ItemList<Probe>>(`/cases/${caseId}/probes`);
}

export function finalizeDiagnosis(caseId: string): Promise<DiagnosisResult> {
  return apiFetch<DiagnosisResult>(`/cases/${caseId}/finalize-diagnosis`, {
    method: "POST",
  });
}

export function getDiagnosis(caseId: string): Promise<DiagnosisSummary> {
  return apiFetch<DiagnosisSummary>(`/cases/${caseId}/diagnosis`);
}

export function listDevices(): Promise<ItemList<Device>> {
  return apiFetch<ItemList<Device>>("/devices");
}
export function listParts(deviceModel: string): Promise<ItemList<Part>> {
  const query = new URLSearchParams({ device_model: deviceModel });
  return apiFetch<ItemList<Part>>(`/parts?${query.toString()}`);
}

export function checkPartCompatibility(
  partNo: string,
  deviceModel: string,
  hardwareVersion = "",
): Promise<CompatibilityResult> {
  const query = new URLSearchParams({ device_model: deviceModel });
  if (hardwareVersion) query.set("hardware_version", hardwareVersion);
  return apiFetch<CompatibilityResult>(
    `/parts/${encodeURIComponent(partNo)}/compatibility?${query.toString()}`,
  );
}

export function buildRepairPlan(caseId: string): Promise<RepairPlan> {
  return apiFetch<RepairPlan>(`/cases/${caseId}/repair-plan`, { method: "POST" });
}

export function getRepairPlan(caseId: string): Promise<RepairPlan> {
  return apiFetch<RepairPlan>(`/cases/${caseId}/repair-plan`);
}

export function submitApproval(
  caseId: string,
): Promise<{ case: CaseSummary; status: string }> {
  return apiFetch<{ case: CaseSummary; status: string }>(
    `/cases/${caseId}/submit-approval`,
    { method: "POST" },
  );
}

export function listApprovals(caseId: string): Promise<ItemList<Approval>> {
  return apiFetch<ItemList<Approval>>(`/cases/${caseId}/approvals`);
}

export function approveCase(
  caseId: string,
  decision: "approve" | "reject",
  reason = "",
): Promise<{ case: CaseSummary; approval: Approval }> {
  return apiFetch<{ case: CaseSummary; approval: Approval }>(
    `/cases/${caseId}/approvals`,
    {
      method: "POST",
      body: JSON.stringify({ decision, reason }),
    },
  );
}

export function createWorkOrder(
  caseId: string,
  idempotencyKey: string,
  assignee?: string | null,
): Promise<{ work_order: WorkOrder; created: boolean }> {
  return apiFetch<{ work_order: WorkOrder; created: boolean }>(
    `/cases/${caseId}/work-orders`,
    {
      method: "POST",
      body: JSON.stringify({ idempotency_key: idempotencyKey, assignee: assignee ?? null }),
    },
  );
}

export function listWorkOrders(
  caseId?: string,
): Promise<ItemList<WorkOrder>> {
  const query = new URLSearchParams();
  if (caseId) query.set("case_id", caseId);
  const qs = query.toString();
  return apiFetch<ItemList<WorkOrder>>(`/work-orders${qs ? `?${qs}` : ""}`);
}

export function getWorkOrder(workOrderId: string): Promise<WorkOrder> {
  return apiFetch<WorkOrder>(`/work-orders/${workOrderId}`);
}

export function recordOutcome(
  workOrderId: string,
  body: OutcomeInput,
): Promise<{ outcome: RepairOutcome; consistency: string }> {
  return apiFetch<{ outcome: RepairOutcome; consistency: string }>(
    `/work-orders/${workOrderId}/outcome`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
}

export function listOutcomes(caseId: string): Promise<ItemList<RepairOutcome>> {
  return apiFetch<ItemList<RepairOutcome>>(`/cases/${caseId}/outcomes`);
}

export function closeCase(
  caseId: string,
): Promise<{ case: CaseSummary; status: string }> {
  return apiFetch<{ case: CaseSummary; status: string }>(
    `/cases/${caseId}/close`,
    { method: "POST" },
  );
}

export function listScenarioRuns(limit = 20): Promise<ItemList<EvalRunSummary>> {
  const query = new URLSearchParams({ limit: String(limit) });
  return apiFetch<ItemList<EvalRunSummary>>(`/eval/scenarios/runs?${query.toString()}`);
}

export function getScenarioRun(runId: string): Promise<ScenarioRunReport> {
  return apiFetch<ScenarioRunReport>(
    `/eval/scenarios/runs/${encodeURIComponent(runId)}`,
  );
}

export function runScenarios(
  body: ScenarioRunInput,
  opts?: { async?: boolean },
): Promise<ScenarioRunResult | TaskAccepted> {
  const query = opts?.async ? "?async=true" : "";
  return apiFetch<ScenarioRunResult | TaskAccepted>(`/eval/scenarios/run${query}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getTask(taskId: string): Promise<TaskInfo> {
  return apiFetch<TaskInfo>(`/tasks/${encodeURIComponent(taskId)}`);
}

export function advanceCase(
  caseId: string,
  opts?: { async?: boolean },
): Promise<AdvanceResult | TaskAccepted> {
  const query = opts?.async ? "?async=true" : "";
  return apiFetch<AdvanceResult | TaskAccepted>(`/cases/${caseId}/diagnose${query}`, {
    method: "POST",
  });
}

export function isTaskAccepted(value: unknown): value is TaskAccepted {
  return (
    typeof value === "object" &&
    value !== null &&
    "task_id" in value &&
    "status" in value
  );
}
export function getOverview(): Promise<Overview> {
  return apiFetch<Overview>("/overview");
}

export function listTasks(params?: { limit?: number; owner?: "me" | "all" }): Promise<TaskList> {
  const search = new URLSearchParams();
  if (params?.limit !== undefined) search.set("limit", String(params.limit));
  if (params?.owner) search.set("owner", params.owner);
  const query = search.toString();
  return apiFetch<TaskList>(`/tasks${query ? `?${query}` : ""}`);
}