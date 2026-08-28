import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiError, type LifeOSApi } from "../api";
import { Icon } from "../components/Icon";
import type { Device, ExecutionSession, RuntimeState } from "../types";
import { errorMessage, formatDateTime, humanizeCode } from "../utils";

interface StatusViewProps {
  api: LifeOSApi;
  timezone: string;
  activeSessionId: string;
  onActiveSessionChange: (sessionId: string) => void;
  notify: (message: string) => void;
}

type SafetyAction = "override" | "emergency" | "break" | null;

export function StatusView({
  api,
  timezone,
  activeSessionId,
  onActiveSessionChange,
  notify,
}: StatusViewProps) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [runtime, setRuntime] = useState<RuntimeState | null>(null);
  const [sessionIdInput, setSessionIdInput] = useState(activeSessionId);
  const [session, setSession] = useState<ExecutionSession | null>(null);
  const [loadingDevices, setLoadingDevices] = useState(true);
  const [loadingState, setLoadingState] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runtimeNote, setRuntimeNote] = useState<string | null>(null);
  const [action, setAction] = useState<SafetyAction>(null);
  const [actionReason, setActionReason] = useState("");
  const [breakMinutes, setBreakMinutes] = useState(10);
  const [emergencyKey, setEmergencyKey] = useState("");

  const loadDevices = useCallback(async () => {
    setLoadingDevices(true);
    try {
      const values = await api.listDevices();
      setDevices(values);
      setSelectedDeviceId((current) =>
        values.some((device) => device.device_id === current)
          ? current
          : values.find((device) => device.status === "ONLINE")?.device_id ||
            values[0]?.device_id ||
            "",
      );
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoadingDevices(false);
    }
  }, [api]);

  const loadSession = useCallback(
    async (id: string, quiet = false) => {
      if (!id.trim()) {
        setSession(null);
        return;
      }
      if (!quiet) setLoadingState(true);
      try {
        const value = await api.session(id.trim());
        setSession(value);
        setSessionIdInput(value.session_id);
        onActiveSessionChange(value.session_id);
      } catch (cause) {
        if (!quiet) setError(errorMessage(cause));
      } finally {
        if (!quiet) setLoadingState(false);
      }
    },
    [api, onActiveSessionChange],
  );

  const loadRuntime = useCallback(
    async (deviceId: string, quiet = false) => {
      if (!deviceId) {
        setRuntime(null);
        return;
      }
      if (!quiet) setLoadingState(true);
      try {
        const value = await api.runtimeState(deviceId);
        setRuntime(value);
        setRuntimeNote(null);
        if (value.session_id) {
          await loadSession(value.session_id, true);
        }
      } catch (cause) {
        if (cause instanceof ApiError && cause.status === 404) {
          setRuntime(null);
          setRuntimeNote("该设备尚无 RuntimeState；等待 Agent 上报 observation 或启动 Session。 ");
        } else if (!quiet) {
          setError(errorMessage(cause));
        }
      } finally {
        if (!quiet) setLoadingState(false);
      }
    },
    [api, loadSession],
  );

  useEffect(() => {
    void loadDevices();
  }, [loadDevices]);

  useEffect(() => {
    if (selectedDeviceId) void loadRuntime(selectedDeviceId);
  }, [loadRuntime, selectedDeviceId]);

  useEffect(() => {
    if (activeSessionId && !session) void loadSession(activeSessionId);
  }, [activeSessionId, loadSession, session]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (selectedDeviceId) void loadRuntime(selectedDeviceId, true);
      if (session?.session_id) void loadSession(session.session_id, true);
    }, 15_000);
    return () => window.clearInterval(interval);
  }, [loadRuntime, loadSession, selectedDeviceId, session?.session_id]);

  const selectedDevice = devices.find((device) => device.device_id === selectedDeviceId) || null;
  const runtimeExpired = runtime ? new Date(runtime.valid_until).getTime() < Date.now() : false;
  const terminalSession = session
    ? ["COMPLETED", "ABORTED", "MISSED"].includes(session.session_state)
    : false;

  const refreshAll = async () => {
    await loadDevices();
    if (selectedDeviceId) await loadRuntime(selectedDeviceId);
    if (sessionIdInput) await loadSession(sessionIdInput);
  };

  const transition = async (nextAction: "pause" | "resume" | "complete" | "abort") => {
    if (!session) return;
    setWorking(true);
    setError(null);
    try {
      const value = await api.transitionSession(
        session.session_id,
        nextAction,
        session.version,
        `user requested ${nextAction} from web`,
      );
      setSession(value);
      notify(
        `Session 已${{ pause: "暂停", resume: "恢复", complete: "完成", abort: "终止" }[nextAction]}`,
      );
      if (selectedDeviceId) await loadRuntime(selectedDeviceId, true);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setWorking(false);
    }
  };

  const openAction = (next: Exclude<SafetyAction, null>) => {
    setAction(next);
    setActionReason(
      next === "emergency"
        ? "user emergency release"
        : next === "break"
          ? "user requested rest"
          : "",
    );
    if (next === "emergency") {
      const unique =
        typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      setEmergencyKey(`web-emergency:${unique}`);
    }
  };

  const submitSafetyAction = async (event: FormEvent) => {
    event.preventDefault();
    if (!session || !action || !actionReason.trim()) return;
    setWorking(true);
    setError(null);
    try {
      let value: ExecutionSession;
      if (action === "emergency") {
        value = await api.emergencyRelease(session.session_id, emergencyKey, actionReason.trim());
        notify("Core 已接受 Emergency Release，并已排队发送 RELEASE_ALL");
      } else if (action === "override") {
        value = await api.ordinaryOverride(
          session.session_id,
          session.version,
          actionReason.trim(),
        );
        notify("普通 Override 已记录并解除当前限制");
      } else {
        const response = await api.takeBreak(
          session.session_id,
          session.version,
          breakMinutes,
          actionReason.trim(),
        );
        value = response.session;
        notify(`已插入 ${breakMinutes} 分钟休息并生成新 PlanVersion`);
      }
      setSession(value);
      setAction(null);
      if (selectedDeviceId) await loadRuntime(selectedDeviceId, true);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setWorking(false);
    }
  };

  const featureRows = useMemo(
    () =>
      runtime
        ? [
            ["60s 数据覆盖", `${runtime.features.window_60_coverage_seconds.toFixed(0)}s`],
            ["300s 数据覆盖", `${runtime.features.window_300_coverage_seconds.toFixed(0)}s`],
            ["Allowed ratio", `${Math.round(runtime.features.allowed_app_ratio_60s * 100)}%`],
            ["Blocked ratio", `${Math.round(runtime.features.blocked_app_ratio_60s * 100)}%`],
            ["Blocked 连续", `${runtime.features.blocked_continuous_seconds.toFixed(0)}s`],
            [
              "Idle",
              runtime.features.idle_seconds === null ? "未知" : `${runtime.features.idle_seconds}s`,
            ],
          ]
        : [],
    [runtime],
  );

  return (
    <div className="view-stack">
      <section className="page-intro">
        <div>
          <p className="eyebrow">Observation → Feature → State Estimate</p>
          <h2>现在发生了什么？</h2>
          <p>状态来自 Core 的当前 head；过期或缺失数据会明确显示为未知。</p>
        </div>
        <button
          className="button secondary"
          type="button"
          onClick={() => void refreshAll()}
          disabled={loadingDevices || loadingState}
        >
          <Icon name="refresh" size={17} />
          刷新状态
        </button>
      </section>

      {error && (
        <div className="error-banner" role="alert">
          <Icon name="warning" />
          <span>{error}</span>
          <button type="button" onClick={() => setError(null)} aria-label="关闭错误">
            <Icon name="close" size={16} />
          </button>
        </div>
      )}

      <section className="device-strip" aria-labelledby="devices-title">
        <div className="section-heading-row">
          <div>
            <p className="eyebrow">设备 Heartbeat</p>
            <h3 id="devices-title">设备</h3>
          </div>
          <span className="subtle-count">{devices.length}</span>
        </div>
        {loadingDevices ? (
          <div className="loading-inline">
            <span className="spinner" />
            读取设备…
          </div>
        ) : devices.length === 0 ? (
          <div className="inline-empty card">Core 中尚未注册设备。</div>
        ) : (
          <div className="device-list">
            {devices.map((device) => (
              <button
                key={device.device_id}
                className={`device-card ${selectedDeviceId === device.device_id ? "selected" : ""}`}
                type="button"
                onClick={() => setSelectedDeviceId(device.device_id)}
                aria-pressed={selectedDeviceId === device.device_id}
              >
                <span className="device-icon">
                  <Icon name="device" />
                </span>
                <span className="device-copy">
                  <strong>{device.name}</strong>
                  <small>
                    {device.device_type} · {formatDateTime(device.last_heartbeat_at, timezone)}
                  </small>
                </span>
                <span className={`device-status ${device.status.toLowerCase()}`}>
                  <i />
                  {device.status}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      <div className="content-grid status-layout">
        <section className="card runtime-card" aria-labelledby="runtime-title">
          <div className="card-heading">
            <div>
              <p className="eyebrow">RuntimeState</p>
              <h3 id="runtime-title">{selectedDevice?.name || "未选择设备"}</h3>
            </div>
            {runtime && (
              <span className={`freshness ${runtimeExpired ? "expired" : "fresh"}`}>
                {runtimeExpired ? "已过期" : "有效"}
              </span>
            )}
          </div>

          {loadingState && !runtime ? (
            <div className="loading-inline">
              <span className="spinner" />
              读取状态…
            </div>
          ) : !runtime ? (
            <div className="inline-empty">{runtimeNote || "选择设备以读取 RuntimeState。"}</div>
          ) : (
            <>
              <div className="state-triad">
                <div>
                  <span>Context</span>
                  <strong>{runtime.context}</strong>
                </div>
                <div>
                  <span>Presence</span>
                  <strong>{runtime.presence}</strong>
                </div>
                <div className={`engagement-${runtime.engagement.toLowerCase()}`}>
                  <span>Engagement</span>
                  <strong>{runtime.engagement}</strong>
                </div>
              </div>
              <div className="confidence-block">
                <div>
                  <span>Confidence</span>
                  <strong>{Math.round(runtime.confidence * 100)}%</strong>
                </div>
                <div className="confidence-track">
                  <span style={{ width: `${runtime.confidence * 100}%` }} />
                </div>
              </div>
              <dl className="feature-grid">
                {featureRows.map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
              <div className="state-footer">
                <span>state_version {runtime.state_version}</span>
                <span>role {humanizeCode(runtime.device_role)}</span>
                <span>valid until {formatDateTime(runtime.valid_until, timezone)}</span>
              </div>
              <div className="reason-list" aria-label="状态原因码">
                {runtime.reason_codes.map((reason) => (
                  <span key={reason}>{reason}</span>
                ))}
              </div>
            </>
          )}
        </section>

        <section className="card session-card" aria-labelledby="session-title">
          <div className="card-heading">
            <div>
              <p className="eyebrow">ExecutionSession</p>
              <h3 id="session-title">当前 Session</h3>
            </div>
            {session && (
              <span className={`tag status-${session.session_state.toLowerCase()}`}>
                {session.session_state}
              </span>
            )}
          </div>

          <form
            className="session-id-form"
            onSubmit={(event) => {
              event.preventDefault();
              void loadSession(sessionIdInput);
            }}
          >
            <label>
              <span className="sr-only">Session ID</span>
              <input
                value={sessionIdInput}
                onChange={(event) => setSessionIdInput(event.target.value)}
                placeholder="输入 Session UUID"
              />
            </label>
            <button className="button secondary small" type="submit">
              载入
            </button>
          </form>

          {!session ? (
            <div className="inline-empty">从 RuntimeState 自动载入，或手动输入 Session ID。</div>
          ) : (
            <>
              <div className="session-summary">
                <div className="session-mode">
                  <span>Commitment</span>
                  <strong>{session.commitment_mode}</strong>
                  <small>{session.dry_run ? "DRY RUN" : "LIVE"}</small>
                </div>
                <div className="intervention-meter">
                  <span>Intervention level</span>
                  <div>
                    {[0, 1, 2, 3, 4, 5].map((level) => (
                      <i
                        key={level}
                        className={level <= session.intervention_level ? "active" : ""}
                      />
                    ))}
                  </div>
                  <strong>Level {session.intervention_level}</strong>
                </div>
              </div>
              <dl className="session-details">
                <div>
                  <dt>计划时段</dt>
                  <dd>
                    {formatDateTime(session.scheduled_start_at, timezone)} –{" "}
                    {formatDateTime(session.scheduled_end_at, timezone)}
                  </dd>
                </div>
                <div>
                  <dt>实际开始</dt>
                  <dd>{formatDateTime(session.started_at, timezone)}</dd>
                </div>
                <div>
                  <dt>Version</dt>
                  <dd>{session.version}</dd>
                </div>
                <div>
                  <dt>Reason</dt>
                  <dd>{session.reason_codes.join(", ")}</dd>
                </div>
              </dl>

              {!terminalSession && (
                <div className="session-controls">
                  {session.session_state === "RUNNING" && (
                    <button
                      className="button secondary small"
                      type="button"
                      disabled={working}
                      onClick={() => void transition("pause")}
                    >
                      暂停
                    </button>
                  )}
                  {["PAUSED", "INTERRUPTED"].includes(session.session_state) && (
                    <button
                      className="button primary small"
                      type="button"
                      disabled={working}
                      onClick={() => void transition("resume")}
                    >
                      恢复
                    </button>
                  )}
                  {["RUNNING", "PAUSED", "INTERRUPTED"].includes(session.session_state) && (
                    <button
                      className="button secondary small"
                      type="button"
                      disabled={working}
                      onClick={() => void transition("complete")}
                    >
                      完成
                    </button>
                  )}
                  <button
                    className="button ghost small"
                    type="button"
                    disabled={working}
                    onClick={() => void transition("abort")}
                  >
                    终止
                  </button>
                </div>
              )}

              {!terminalSession && (
                <div className="release-panel">
                  <div className="ordinary-actions">
                    <button
                      className="button secondary"
                      type="button"
                      onClick={() => openAction("break")}
                      disabled={working}
                    >
                      休息 10 分钟
                    </button>
                    <button
                      className="button override"
                      type="button"
                      onClick={() => openAction("override")}
                      disabled={working}
                    >
                      Ordinary Override
                    </button>
                  </div>
                  <button
                    className="emergency-button"
                    type="button"
                    onClick={() => openAction("emergency")}
                    disabled={working}
                  >
                    <Icon name="shield" size={23} />
                    <span>
                      <strong>Emergency Release</strong>
                      <small>立即解除 · 永远优先</small>
                    </span>
                  </button>
                </div>
              )}
            </>
          )}
        </section>
      </div>

      {action && session && (
        <div className="dialog-backdrop" role="presentation" onMouseDown={() => setAction(null)}>
          <section
            className={`dialog-card action-dialog ${action}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby="action-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <form onSubmit={submitSafetyAction}>
              <div className="dialog-heading">
                <div>
                  <p className="eyebrow">
                    {action === "emergency"
                      ? "安全优先"
                      : action === "override"
                        ? "记录后解除"
                        : "滚动重排"}
                  </p>
                  <h2 id="action-title">
                    {action === "emergency"
                      ? "Emergency Release"
                      : action === "override"
                        ? "Ordinary Override"
                        : "插入休息"}
                  </h2>
                </div>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => setAction(null)}
                  aria-label="关闭"
                >
                  <Icon name="close" />
                </button>
              </div>
              <p className="action-explanation">
                {action === "emergency"
                  ? "Core 将立即取消当前强制升级、创建 RELEASE_ALL 命令，并把 Session 标为 INTERRUPTED。此操作不要求 expected_version。"
                  : action === "override"
                    ? "Core 会记录具体原因、暂停 Session，并解除当前限制。若版本已变化，操作会被拒绝并要求刷新。"
                    : "Core 将暂停 Session、插入休息块，并创建新的 PlanVersion。"}
              </p>
              {action === "break" && (
                <label className="field">
                  <span>休息时长（5–30 分钟）</span>
                  <input
                    type="number"
                    min={5}
                    max={30}
                    value={breakMinutes}
                    onChange={(event) => setBreakMinutes(event.target.valueAsNumber)}
                  />
                </label>
              )}
              <label className="field">
                <span>原因 *</span>
                <textarea
                  required
                  minLength={1}
                  maxLength={500}
                  rows={3}
                  value={actionReason}
                  onChange={(event) => setActionReason(event.target.value)}
                  autoFocus
                />
              </label>
              {action === "emergency" && (
                <p className="idempotency-note">
                  本次重试沿用同一幂等键：<code>{emergencyKey}</code>
                </p>
              )}
              <div className="dialog-actions">
                <button className="button ghost" type="button" onClick={() => setAction(null)}>
                  取消
                </button>
                <button
                  className={action === "emergency" ? "button emergency" : "button primary"}
                  type="submit"
                  disabled={working || !actionReason.trim()}
                >
                  {working ? "提交中…" : action === "emergency" ? "立即解除" : "确认并记录"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
