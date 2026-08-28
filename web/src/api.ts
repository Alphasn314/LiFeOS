import type {
  Device,
  EventEnvelope,
  ExecutionSession,
  Health,
  PlanVersion,
  ProblemDetails,
  RuntimeState,
  Task,
  TaskInput,
  TaskUpdate,
} from "./types";

export interface ApiConfig {
  baseUrl: string;
  token: string;
  displayTimezone: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly problem?: ProblemDetails;

  constructor(status: number, message: string, problem?: ProblemDetails) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.problem = problem;
  }
}

export function normalizeBaseUrl(value: string): string {
  const normalized = value.trim().replace(/\/+$/, "");
  return normalized || "http://localhost:8000";
}

export class LifeOSApi {
  constructor(private readonly config: ApiConfig) {}

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    if (this.config.token.trim()) {
      headers.set("Authorization", `Bearer ${this.config.token.trim()}`);
    }
    if (init.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }

    let response: Response;
    try {
      response = await fetch(`${normalizeBaseUrl(this.config.baseUrl)}${path}`, {
        ...init,
        headers,
      });
    } catch (cause) {
      throw new ApiError(
        0,
        cause instanceof Error ? `无法连接 Core：${cause.message}` : "无法连接 Core",
      );
    }

    if (!response.ok) {
      let problem: ProblemDetails | undefined;
      try {
        problem = (await response.json()) as ProblemDetails;
      } catch {
        problem = undefined;
      }
      const message = problem?.detail || problem?.title || `Core 返回 HTTP ${response.status}`;
      throw new ApiError(response.status, message, problem);
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  health(): Promise<Health> {
    return this.request<Health>("/health");
  }

  listTasks(includeTerminal = true): Promise<Task[]> {
    return this.request<Task[]>(`/api/v1/tasks?include_terminal=${includeTerminal}`);
  }

  createTask(payload: TaskInput): Promise<Task> {
    return this.request<Task>("/api/v1/tasks", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  updateTask(taskId: string, payload: TaskUpdate): Promise<Task> {
    return this.request<Task>(`/api/v1/tasks/${encodeURIComponent(taskId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  }

  deleteTask(taskId: string, expectedVersion: number): Promise<Task> {
    return this.request<Task>(
      `/api/v1/tasks/${encodeURIComponent(taskId)}?expected_version=${expectedVersion}`,
      { method: "DELETE" },
    );
  }

  currentPlan(planDate: string): Promise<PlanVersion> {
    const params = new URLSearchParams({
      plan_date: planDate,
      display_timezone: this.config.displayTimezone,
    });
    return this.request<PlanVersion>(`/api/v1/plans/current?${params}`);
  }

  generatePlan(
    planDate: string,
    trigger: "DAY_STARTED" | "USER_REQUESTED_REPLAN",
    availableStartLocal: string,
    availableEndLocal: string,
    availableLocation: string,
    availableDeviceCapabilities: string[],
  ): Promise<PlanVersion> {
    return this.request<PlanVersion>("/api/v1/plans/generate", {
      method: "POST",
      body: JSON.stringify({
        plan_date: planDate,
        display_timezone: this.config.displayTimezone,
        trigger,
        available_start_local: availableStartLocal,
        available_end_local: availableEndLocal,
        available_location: availableLocation.trim() || null,
        available_device_capabilities: [...new Set(availableDeviceCapabilities)].sort(),
      }),
    });
  }

  listDevices(): Promise<Device[]> {
    return this.request<Device[]>("/api/v1/devices");
  }

  runtimeState(deviceId: string): Promise<RuntimeState> {
    return this.request<RuntimeState>(
      `/api/v1/devices/${encodeURIComponent(deviceId)}/runtime-state`,
    );
  }

  startSession(
    blockId: string,
    deviceId: string,
    commitmentMode: "ADVISORY" | "STANDARD" | "STRICT",
    expectedPlanRevision: number,
  ): Promise<ExecutionSession> {
    return this.request<ExecutionSession>("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify({
        block_id: blockId,
        device_id: deviceId,
        commitment_mode: commitmentMode,
        expected_plan_revision: expectedPlanRevision,
      }),
    });
  }

  session(sessionId: string): Promise<ExecutionSession> {
    return this.request<ExecutionSession>(`/api/v1/sessions/${encodeURIComponent(sessionId)}`);
  }

  transitionSession(
    sessionId: string,
    action: "pause" | "resume" | "complete" | "abort",
    expectedVersion: number,
    reason?: string,
  ): Promise<ExecutionSession> {
    return this.request<ExecutionSession>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/${action}`,
      {
        method: "POST",
        body: JSON.stringify({ expected_version: expectedVersion, reason: reason || null }),
      },
    );
  }

  takeBreak(
    sessionId: string,
    expectedVersion: number,
    durationMinutes: number,
    reason: string,
  ): Promise<{ session: ExecutionSession; plan: PlanVersion }> {
    return this.request(`/api/v1/sessions/${encodeURIComponent(sessionId)}/break`, {
      method: "POST",
      body: JSON.stringify({
        expected_version: expectedVersion,
        duration_minutes: durationMinutes,
        reason,
      }),
    });
  }

  ordinaryOverride(
    sessionId: string,
    expectedVersion: number,
    reason: string,
  ): Promise<ExecutionSession> {
    return this.request<ExecutionSession>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/ordinary-override`,
      {
        method: "POST",
        body: JSON.stringify({ expected_version: expectedVersion, reason }),
      },
    );
  }

  emergencyRelease(
    sessionId: string,
    idempotencyKey: string,
    reason: string,
  ): Promise<ExecutionSession> {
    return this.request<ExecutionSession>(
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/emergency-release`,
      {
        method: "POST",
        body: JSON.stringify({ idempotency_key: idempotencyKey, reason }),
      },
    );
  }

  listEvents(limit = 200): Promise<EventEnvelope[]> {
    return this.request<EventEnvelope[]>(`/api/v1/events?limit=${limit}`);
  }
}
