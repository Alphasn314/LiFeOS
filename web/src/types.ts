export type TaskStatus = "BACKLOG" | "READY" | "IN_PROGRESS" | "COMPLETED" | "CANCELLED";

export type ActivityProfile =
  | "READING"
  | "WRITING"
  | "CODING"
  | "CLASS"
  | "ADMIN"
  | "PHYSICAL"
  | "PASSIVE_VIDEO"
  | "OTHER";

export type CommitmentMode = "ADVISORY" | "STANDARD" | "STRICT";

export type SessionState =
  | "PLANNED"
  | "DUE"
  | "STARTING"
  | "RUNNING"
  | "PAUSED"
  | "INTERRUPTED"
  | "RECOVERY"
  | "COMPLETED"
  | "ABORTED"
  | "MISSED";

export interface Health {
  status: string;
  service: string;
  version: string;
  dry_run: boolean;
  real_enforcement_enabled: boolean;
}

export interface TaskInput {
  title: string;
  description?: string | null;
  status: TaskStatus;
  priority: number;
  mandatory: boolean;
  deadline?: string | null;
  estimated_minutes: number;
  remaining_minutes?: number | null;
  minimum_chunk_minutes: number;
  activity_profile: ActivityProfile;
  required_location?: string | null;
  required_device_capabilities: string[];
  allowed_apps: string[];
  blocked_apps: string[];
  idle_tolerance_seconds: number;
}

export interface Task extends TaskInput {
  schema_version: "1.0";
  task_id: string;
  remaining_minutes: number;
  created_at: string;
  updated_at: string;
  version: number;
}

export interface TaskUpdate extends Partial<TaskInput> {
  expected_version: number;
}

export interface PlannerParameters {
  focus_minutes: number;
  break_minutes: number;
  max_focus_minutes: number;
  buffer_ratio: number;
  freeze_horizon_minutes: number;
  replan_debounce_seconds: number;
  maximum_automatic_replans_per_hour: number;
}

export interface ScheduleBlock {
  block_id: string;
  kind: "FIXED_EVENT" | "TASK" | "TRAVEL" | "MEAL" | "SLEEP" | "BREAK" | "BUFFER" | "UNPLANNED";
  title: string;
  start_at: string;
  end_at: string;
  task_id: string | null;
  fixed_event_id: string | null;
  source_block_id: string | null;
  hardness: "HARD" | "REQUIRED" | "SOFT";
  activity_profile: ActivityProfile;
  reason_codes: string[];
}

export interface PlanConflict {
  code: string;
  severity: "WARNING" | "ERROR";
  entity_ids: string[];
  start_at: string | null;
  end_at: string | null;
  required_minutes: number | null;
  available_minutes: number | null;
  detail: string;
}

export interface PlanVersion {
  schema_version: "1.0";
  plan_version_id: string;
  plan_date: string;
  display_timezone: string;
  revision: number;
  based_on_plan_version_id: string | null;
  trigger: string;
  status: "FEASIBLE" | "PARTIAL" | "INFEASIBLE";
  algorithm_version: string;
  created_at: string;
  created_state_version: number | null;
  parameters: PlannerParameters;
  blocks: ScheduleBlock[];
  conflicts: PlanConflict[];
  reason_codes: string[];
}

export interface Device {
  device_id: string;
  name: string;
  device_type: "WINDOWS" | "WEB" | "MOBILE" | "SERVER";
  capabilities: string[];
  status: "ONLINE" | "OFFLINE" | "UNKNOWN";
  last_heartbeat_at: string | null;
  version: number;
}

export interface RuntimeFeatures {
  window_60_coverage_seconds: number;
  window_300_coverage_seconds: number;
  allowed_app_ratio_60s: number;
  blocked_app_ratio_60s: number;
  blocked_continuous_seconds: number;
  allowed_continuous_seconds: number;
  idle_seconds: number | null;
  sensor_conflict: boolean;
}

export interface RuntimeState {
  schema_version: "1.0";
  state_id: string;
  device_id: string;
  session_id: string | null;
  estimated_at: string;
  context: string;
  presence: "PRESENT" | "ABSENT" | "UNKNOWN";
  engagement: "ON_TASK" | "OFF_TASK" | "IDLE" | "UNKNOWN";
  session_state: SessionState;
  device_role: string;
  confidence: number;
  reason_codes: string[];
  valid_until: string;
  state_version: number;
  features: RuntimeFeatures;
}

export interface ExecutionSession {
  session_id: string;
  plan_version_id: string;
  block_id: string;
  task_id: string | null;
  device_id: string;
  commitment_mode: CommitmentMode;
  session_state: SessionState;
  scheduled_start_at: string;
  scheduled_end_at: string;
  started_at: string | null;
  ended_at: string | null;
  dry_run: boolean;
  intervention_level: number;
  emergency_released_at: string | null;
  override_reason: string | null;
  version: number;
  reason_codes: string[];
}

export interface EventEnvelope {
  schema_version: "1.0";
  event_id: string;
  event_type: string;
  occurred_at: string;
  received_at: string;
  source: string;
  entity_type: string;
  entity_id: string;
  correlation_id: string | null;
  causation_id: string | null;
  idempotency_key: string;
  payload: Record<string, unknown>;
  reason_codes: string[];
}

export interface ErrorItem {
  path: string;
  message: string;
}

export interface ProblemDetails {
  title?: string;
  status?: number;
  detail?: string;
  error_code?: string;
  reason_codes?: string[];
  correlation_id?: string;
  errors?: ErrorItem[];
}
