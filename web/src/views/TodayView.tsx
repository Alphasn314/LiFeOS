import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, type LifeOSApi } from "../api";
import { Icon } from "../components/Icon";
import type { CommitmentMode, Device, PlanVersion, ScheduleBlock } from "../types";
import {
  dateInTimezone,
  errorMessage,
  formatDateTime,
  formatTime,
  humanizeCode,
  isBlockActive,
  minutesBetween,
  totalPlannedMinutes,
} from "../utils";

interface TodayViewProps {
  api: LifeOSApi;
  timezone: string;
  onSessionStarted: (sessionId: string) => void;
  notify: (message: string) => void;
}

const KIND_LABELS: Record<ScheduleBlock["kind"], string> = {
  FIXED_EVENT: "固定日程",
  TASK: "任务",
  TRAVEL: "通勤",
  MEAL: "用餐",
  SLEEP: "睡眠",
  BREAK: "休息",
  BUFFER: "缓冲",
  UNPLANNED: "未计划",
};

export function TodayView({ api, timezone, onSessionStarted, notify }: TodayViewProps) {
  const [planDate, setPlanDate] = useState(() => dateInTimezone(new Date(), timezone));
  const [plan, setPlan] = useState<PlanVersion | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [commitmentMode, setCommitmentMode] = useState<CommitmentMode>("ADVISORY");
  const [availableStart, setAvailableStart] = useState("07:00");
  const [availableEnd, setAvailableEnd] = useState("23:00");
  const [availableLocation, setAvailableLocation] = useState("");
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState(false);
  const [startingBlock, setStartingBlock] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [planResult, devicesResult] = await Promise.allSettled([
      api.currentPlan(planDate),
      api.listDevices(),
    ]);

    if (planResult.status === "fulfilled") {
      setPlan(planResult.value);
    } else if (planResult.reason instanceof ApiError && planResult.reason.status === 404) {
      setPlan(null);
    } else {
      setPlan(null);
      setError(errorMessage(planResult.reason));
    }

    if (devicesResult.status === "fulfilled") {
      setDevices(devicesResult.value);
      setDeviceId((current) =>
        devicesResult.value.some((device) => device.device_id === current)
          ? current
          : devicesResult.value.find((device) => device.status === "ONLINE")?.device_id ||
            devicesResult.value[0]?.device_id ||
            "",
      );
    }
    setLoading(false);
  }, [api, planDate]);

  useEffect(() => {
    void load();
  }, [load]);

  const sortedBlocks = useMemo(
    () => [...(plan?.blocks || [])].sort((a, b) => a.start_at.localeCompare(b.start_at)),
    [plan],
  );

  const generate = async () => {
    if (availableEnd <= availableStart) {
      setError("可用结束时间必须晚于开始时间");
      return;
    }
    setWorking(true);
    setError(null);
    try {
      const generated = await api.generatePlan(
        planDate,
        plan ? "USER_REQUESTED_REPLAN" : "DAY_STARTED",
        availableStart,
        availableEnd,
        availableLocation,
        devices.find((device) => device.device_id === deviceId)?.capabilities || [],
      );
      setPlan(generated);
      notify(plan ? `已生成计划 revision ${generated.revision}` : "今日计划已生成");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setWorking(false);
    }
  };

  const startSession = async (block: ScheduleBlock) => {
    if (!plan || !deviceId) return;
    setStartingBlock(block.block_id);
    setError(null);
    try {
      const session = await api.startSession(
        block.block_id,
        deviceId,
        commitmentMode,
        plan.revision,
      );
      onSessionStarted(session.session_id);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setStartingBlock(null);
    }
  };

  return (
    <div className="view-stack">
      <section className="page-intro">
        <div>
          <p className="eyebrow">确定性计划 · {timezone}</p>
          <h2>
            {planDate === dateInTimezone(new Date(), timezone) ? "今天如何推进？" : "查看指定日期"}
          </h2>
          <p>固定事件优先，任务、休息与缓冲按当前 Core 状态生成。</p>
        </div>
        <div className="toolbar">
          <label className="compact-field">
            <span className="sr-only">计划日期</span>
            <input
              type="date"
              value={planDate}
              onChange={(event) => setPlanDate(event.target.value)}
            />
          </label>
          <button
            className="button secondary"
            type="button"
            onClick={() => void load()}
            disabled={loading}
          >
            <Icon name="refresh" size={17} />
            刷新
          </button>
        </div>
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

      <section className="card plan-control-card" aria-labelledby="plan-control-title">
        <div className="card-heading plan-control-heading">
          <div>
            <p className="eyebrow">规划窗口</p>
            <h3 id="plan-control-title">
              {plan ? `当前 revision ${plan.revision}` : "尚无当前计划"}
            </h3>
          </div>
          {plan && <span className={`tag plan-${plan.status.toLowerCase()}`}>{plan.status}</span>}
        </div>
        <div className="plan-controls">
          <label className="compact-field">
            <span>可用开始</span>
            <input
              type="time"
              value={availableStart}
              onChange={(event) => setAvailableStart(event.target.value)}
            />
          </label>
          <label className="compact-field">
            <span>可用结束</span>
            <input
              type="time"
              value={availableEnd}
              onChange={(event) => setAvailableEnd(event.target.value)}
            />
          </label>
          <label className="compact-field">
            <span>可用地点</span>
            <input
              value={availableLocation}
              onChange={(event) => setAvailableLocation(event.target.value)}
              placeholder="例如 home / campus"
              maxLength={128}
            />
          </label>
          <button
            className="button primary"
            type="button"
            onClick={generate}
            disabled={working || loading}
          >
            <Icon name={plan ? "refresh" : "plus"} size={17} />
            {working ? "生成中…" : plan ? "滚动重排" : "生成今日计划"}
          </button>
        </div>
        <p className="muted-note">
          {plan
            ? `触发 ${humanizeCode(plan.trigger)} · ${formatDateTime(plan.created_at, timezone)}`
            : "时间窗口使用计划展示时区；所选设备能力会用于约束匹配。"}
        </p>
      </section>

      {loading ? (
        <div className="loading-card" role="status">
          <span className="spinner" />
          正在读取权威计划…
        </div>
      ) : !plan ? (
        <section className="empty-state card">
          <span className="empty-icon">
            <Icon name="today" size={28} />
          </span>
          <h3>这一天还没有 PlanVersion</h3>
          <p>先确认上方可用时间，再由 Core 生成真实计划。此处不会填充演示日程。</p>
        </section>
      ) : (
        <>
          <section className="metric-grid" aria-label="计划摘要">
            <article className="metric-card">
              <span>计划块</span>
              <strong>{plan.blocks.length}</strong>
              <small>revision {plan.revision}</small>
            </article>
            <article className="metric-card">
              <span>已排时间</span>
              <strong>
                {totalPlannedMinutes(plan)} <i>min</i>
              </strong>
              <small>{plan.algorithm_version}</small>
            </article>
            <article className="metric-card">
              <span>冲突</span>
              <strong>{plan.conflicts.length}</strong>
              <small>{plan.status === "FEASIBLE" ? "当前可行" : "需要人工确认"}</small>
            </article>
          </section>

          <div className="content-grid plan-layout">
            <section className="card timeline-card" aria-labelledby="timeline-title">
              <div className="card-heading">
                <div>
                  <p className="eyebrow">{plan.plan_date}</p>
                  <h3 id="timeline-title">时间线</h3>
                </div>
                <span className="subtle-count">{sortedBlocks.length} blocks</span>
              </div>

              {sortedBlocks.length === 0 ? (
                <div className="inline-empty">计划存在，但当前没有可排入的时间块。</div>
              ) : (
                <ol className="timeline-list">
                  {sortedBlocks.map((block) => {
                    const active = isBlockActive(block);
                    return (
                      <li
                        key={block.block_id}
                        className={`timeline-item kind-${block.kind.toLowerCase()} ${active ? "active" : ""}`}
                      >
                        <div className="timeline-time">
                          <strong>{formatTime(block.start_at, timezone)}</strong>
                          <span>{formatTime(block.end_at, timezone)}</span>
                        </div>
                        <div className="timeline-track" aria-hidden="true">
                          <span />
                        </div>
                        <div className="timeline-content">
                          <div className="timeline-title-row">
                            <div>
                              <span className="kind-label">{KIND_LABELS[block.kind]}</span>
                              {active && <span className="now-label">进行中</span>}
                              <h4>{block.title}</h4>
                            </div>
                            <span className="duration">
                              {minutesBetween(block.start_at, block.end_at)} min
                            </span>
                          </div>
                          <div className="timeline-meta">
                            <span>{block.hardness}</span>
                            <span>{block.activity_profile}</span>
                            <span title={block.reason_codes.join(", ")}>
                              {block.reason_codes[0]}
                            </span>
                          </div>
                          {block.kind === "TASK" && (
                            <button
                              className="text-button"
                              type="button"
                              onClick={() => void startSession(block)}
                              disabled={!deviceId || startingBlock === block.block_id}
                            >
                              {startingBlock === block.block_id ? "正在启动…" : "启动这个 Session"}
                              <Icon name="chevron" size={15} />
                            </button>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ol>
              )}
            </section>

            <aside className="side-stack">
              <section className="card session-launch-card" aria-labelledby="session-launch-title">
                <p className="eyebrow">Session 预授权</p>
                <h3 id="session-launch-title">启动设置</h3>
                <label className="field">
                  <span>执行设备</span>
                  <select value={deviceId} onChange={(event) => setDeviceId(event.target.value)}>
                    <option value="">选择设备</option>
                    {devices.map((device) => (
                      <option key={device.device_id} value={device.device_id}>
                        {device.name} · {device.status}
                      </option>
                    ))}
                  </select>
                </label>
                <fieldset className="segmented-field">
                  <legend>Commitment mode</legend>
                  {(["ADVISORY", "STANDARD", "STRICT"] as CommitmentMode[]).map((mode) => (
                    <label key={mode}>
                      <input
                        type="radio"
                        name="commitment-mode"
                        value={mode}
                        checked={commitmentMode === mode}
                        onChange={() => setCommitmentMode(mode)}
                      />
                      <span>{mode}</span>
                    </label>
                  ))}
                </fieldset>
                <p className="muted-note">模式只在 Session 开始前授权；Web 不直接执行系统命令。</p>
              </section>

              {plan.conflicts.length > 0 && (
                <section className="card conflicts-card" aria-labelledby="conflicts-title">
                  <div className="card-heading">
                    <div>
                      <p className="eyebrow">不可行性报告</p>
                      <h3 id="conflicts-title">冲突与警告</h3>
                    </div>
                    <Icon name="warning" />
                  </div>
                  <ul className="conflict-list">
                    {plan.conflicts.map((conflict, index) => (
                      <li key={`${conflict.code}-${index}`}>
                        <span className={`severity ${conflict.severity.toLowerCase()}`}>
                          {conflict.severity}
                        </span>
                        <strong>{conflict.code}</strong>
                        <p>{conflict.detail}</p>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
