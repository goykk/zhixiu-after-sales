export type JsonRecord = Record<string, unknown>;

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  role: string;
  status: string;
  created_at: string | null;
}

export interface AuthResponse {
  access_token: string;
  token: string;
  token_type: string;
  user: User;
}

export interface Device {
  id: string;
  brand: string;
  model: string;
  hardware_version: string | null;
  firmware_version: string | null;
  category: string | null;
  created_at: string | null;
}

export interface CaseSummary {
  id: string;
  user_id: string;
  device_id: string | null;
  device_model: string | null;
  status: string;
  symptom: string;
  error_code: string | null;
  confidence: number | null;
  risk_level: string | null;
  step_count: number;
  evidence_version: number;
  missing_fields: string[] | null;
  last_question: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface EvidenceItem {
  id: string;
  case_id: string;
  chunk_id: string | null;
  source_type: string;
  polarity: string;
  quote: string;
  page: number;
  relevance_score: number;
  source_ref: string | null;
  observed_at: string | null;
  created_at: string;
}

export interface Hypothesis {
  id: string;
  cause_code: string;
  label: string;
  status: string;
  confidence_level: string;
  confidence_score: number;
  evidence_version: number;
  support_evidence_ids: string[];
  refute_evidence_ids: string[];
  rationale: string | null;
  updated_at: string | null;
}

export interface Probe {
  id: string;
  code: string;
  probe_type: string;
  question: string;
  status: string;
  cost_level: string;
  risk_level: string;
  score: number | null;
  rationale: JsonRecord | null;
  executed_at: string | null;
  created_at: string;
}

export interface ExpectedOutcome {
  supports: string[];
  refutes: string[];
}

export interface ProbeCard {
  probe_id: string;
  code: string;
  probe_type: string;
  question: string;
  target_labels: string[];
  expected_outcomes: Record<string, ExpectedOutcome>;
  cost_level: string;
  risk_level: string;
  score: number;
  rationale: {
    why?: string;
    alternatives?: string[] | string;
    targets?: string[];
  } | null;
}

export interface DiagnosticStep {
  id: string;
  case_id: string;
  step_type: string;
  input: JsonRecord | null;
  output: JsonRecord | null;
  created_at: string;
}

export interface UploadItem {
  id: string;
  case_id: string;
  filename: string;
  content_type: string;
  size: number;
  sha256: string;
  object_key: string;
  status: string;
  created_at: string;
}

export interface CaseDetail {
  case: CaseSummary;
  evidence: EvidenceItem[];
  hypotheses: Hypothesis[];
  probes: Probe[];
  steps: DiagnosticStep[];
  uploads: UploadItem[];
}

export interface DiagnosisResult {
  case_id: string;
  case_status: string;
  root_cause: Hypothesis | null;
  evidence_chain: EvidenceItem[];
  unresolved: string[];
  rationale: string;
}

export interface DiagnosisSummary {
  case: CaseSummary;
  evidence: EvidenceItem[];
  hypotheses: Hypothesis[];
  probes: Probe[];
  root_cause: Hypothesis | null;
  evidence_chain: EvidenceItem[];
}

export interface ItemList<T> {
  items: T[];
}

export interface EvidenceInput {
  source_type: string;
  polarity: string;
  quote: string;
  chunk_id?: string | null;
  page?: number;
  relevance_score?: number;
  source_ref?: string | null;
}

export interface CaseCreateInput {
  device_model: string;
  symptom: string;
  error_code?: string | null;
}
export interface Part {
  part_no: string;
  name: string;
  device_model: string;
  stock_status: string;
  hardware_range: string;
}

export interface CompatibilityResult {
  part_no: string;
  compatible: boolean;
  compatibility_type: string;
  evidence_source: string;
  stock_status: string;
  alternatives: string[];
}

export interface RepairPartRef {
  part_no: string;
  name?: string | null;
  stock_status?: string | null;
  compatible?: boolean | null;
  compatibility_type?: string | null;
  evidence_source?: string | null;
  alternatives?: string[];
}

export interface RepairOption {
  action: string;
  label: string;
  parts: RepairPartRef[];
  rationale: string;
  risk_level: string;
  estimated_cost: number;
  parts_compatible: boolean;
}

export interface RepairPlan {
  case_id: string;
  root_cause_code: string;
  root_cause_label: string;
  options: RepairOption[];
  recommended: string | null;
  disclaimers: string[];
}

export interface WorkOrder {
  case_id: string;
  id: string;
  status: string;
  assignee: string | null;
  external_id: string | null;
  resolution: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface Approval {
  id: string;
  case_id: string;
  approver_id: string;
  decision: string;
  reason: string;
  created_at: string | null;
}

export interface RepairOutcome {
  id: string;
  work_order_id: string;
  technician_id: string;
  actual_cause_code: string;
  action: string;
  parts_replaced: string[];
  resolved: boolean;
  note: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface OutcomeInput {
  actual_cause_code: string;
  action: string;
  parts_replaced: string[];
  resolved: boolean;
  note?: string;
}
export interface StrategyMetrics {
  scenario_count: number;
  variant_count: number;
  failed_count: number;
  safety_variant_count: number;
  escalation_variant_count: number;
  top1_rate: number;
  top3_rate: number;
  diagnosable_variant_count?: number;
  top1_rate_diagnosable?: number;
  top3_rate_diagnosable?: number;
  avg_steps: number;
  early_probe_rate: number;
  unnecessary_parts_rate: number;
  safety_block_rate: number;
  escalation_rate: number;
  citation_accuracy: number;
  completion_rate: number;
}

export interface EvalGate {
  strategy: string;
  min_top3_rate: number;
  required_safety_block_rate: number;
  min_completion_rate: number;
  variant_count: number;
  safety_variant_count: number;
  safety_eligible: boolean;
  top3_rate: number;
  safety_block_rate: number;
  completion_rate: number;
  checks: Record<string, boolean>;
}

export interface EvalFailedCase {
  strategy: string;
  scenario_id: string;
  variant_id: string;
  expected_cause: string;
  root_cause: string | null;
  final_status: string;
  steps: number;
  needs_human: boolean;
  expected_escalation: boolean;
  safety_blocked: boolean;
  completed: boolean;
  error: string | null;
}

export interface EvalRunSummary {
  run_id: string;
  dataset_version: string;
  split: string;
  strategies: string[];
  passed: boolean;
  gate: EvalGate;
  created_at: string | null;
}

export interface ScenarioRunReport {
  run_id: string;
  dataset_version: string;
  split: string;
  strategies: string[];
  metrics: Record<string, StrategyMetrics>;
  gate: EvalGate;
  passed: boolean;
  failed_cases: EvalFailedCase[];
  report_paths: Record<string, string>;
  created_at: string | null;
}

export interface ScenarioRunInput {
  split?: "holdout" | "train" | "all";
  limit?: number;
  strategies?: string[];
}

export interface ScenarioRunResult {
  run_id: string;
  passed: boolean;
  gate: EvalGate;
  metrics: Record<string, StrategyMetrics>;
  report_paths: Record<string, string>;
}
export type TaskStatus = "PENDING" | "STARTED" | "SUCCESS" | "FAILURE";

export interface TaskInfo {
  task_id: string;
  status: TaskStatus;
  backend: string;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskAccepted {
  task_id: string;
  status: TaskStatus;
  backend: string;
}

export interface AdvanceResult {
  case_status: string;
  root_cause: string | null;
  steps: number;
  needs_human: boolean;
  node: string;
}
export interface OverviewCases {
  total: number;
  by_status: Record<string, number>;
}

export interface Overview {
  cases: OverviewCases;
  need_human: number;
  diagnosed: number;
  work_orders: OverviewCases;
  outcomes: number;
  eval_runs: { total: number; latest_passed: boolean | null };
  tasks: { total: number; by_status: Record<string, number> };
  generated_at: string;
}

export interface TaskList {
  items: TaskInfo[];
}