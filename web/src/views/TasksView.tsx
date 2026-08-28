import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import type { LifeOSApi } from "../api";
import { Icon } from "../components/Icon";
import type { ActivityProfile, Task, TaskInput, TaskStatus } from "../types";
import { csvItems, errorMessage, formatDateTime, humanizeCode, toDatetimeLocal } from "../utils";

interface TasksViewProps {
  api: LifeOSApi;
  timezone: string;
  notify: (message: string) => void;
}

interface TaskDraft {
  title: string;
  description: string;
  status: TaskStatus;
  priority: number;
  mandatory: boolean;
  deadline: string;
  estimatedMinutes: number;
  remainingMinutes: number;
  minimumChunkMinutes: number;
  activityProfile: ActivityProfile;
  requiredLocation: string;
  capabilities: string;
  allowedApps: string;
  blockedApps: string;
  idleToleranceSeconds: number;
}

const EMPTY_DRAFT: TaskDraft = {
  title: "",
  description: "",
  status: "READY",
  priority: 3,
  mandatory: false,
  deadline: "",
  estimatedMinutes: 50,
  remainingMinutes: 50,
  minimumChunkMinutes: 25,
  activityProfile: "OTHER",
  requiredLocation: "",
  capabilities: "",
  allowedApps: "",
  blockedApps: "",
  idleToleranceSeconds: 300,
};

const STATUS_OPTIONS: TaskStatus[] = ["BACKLOG", "READY", "IN_PROGRESS", "COMPLETED", "CANCELLED"];
const PROFILE_OPTIONS: ActivityProfile[] = [
  "READING",
  "WRITING",
  "CODING",
  "CLASS",
  "ADMIN",
  "PHYSICAL",
  "PASSIVE_VIDEO",
  "OTHER",
];

function draftFromTask(task: Task): TaskDraft {
  return {
    title: task.title,
    description: task.description || "",
    status: task.status,
    priority: task.priority,
    mandatory: task.mandatory,
    deadline: toDatetimeLocal(task.deadline),
    estimatedMinutes: task.estimated_minutes,
    remainingMinutes: task.remaining_minutes,
    minimumChunkMinutes: task.minimum_chunk_minutes,
    activityProfile: task.activity_profile,
    requiredLocation: task.required_location || "",
    capabilities: task.required_device_capabilities.join(", "),
    allowedApps: task.allowed_apps.join(", "),
    blockedApps: task.blocked_apps.join(", "),
    idleToleranceSeconds: task.idle_tolerance_seconds,
  };
}

function payloadFromDraft(draft: TaskDraft): TaskInput {
  return {
    title: draft.title.trim(),
    description: draft.description.trim() || null,
    status: draft.status,
    priority: draft.priority,
    mandatory: draft.mandatory,
    deadline: draft.deadline ? new Date(draft.deadline).toISOString() : null,
    estimated_minutes: draft.estimatedMinutes,
    remaining_minutes: draft.remainingMinutes,
    minimum_chunk_minutes: draft.minimumChunkMinutes,
    activity_profile: draft.activityProfile,
    required_location: draft.requiredLocation.trim() || null,
    required_device_capabilities: csvItems(draft.capabilities),
    allowed_apps: csvItems(draft.allowedApps).map((item) => item.toLowerCase()),
    blocked_apps: csvItems(draft.blockedApps).map((item) => item.toLowerCase()),
    idle_tolerance_seconds: draft.idleToleranceSeconds,
  };
}

export function TasksView({ api, timezone, notify }: TasksViewProps) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<TaskStatus | "ACTIVE" | "ALL">("ACTIVE");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Task | null>(null);
  const [draft, setDraft] = useState<TaskDraft>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTasks(await api.listTasks(true));
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleTasks = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return tasks
      .filter((task) => {
        if (statusFilter === "ACTIVE" && ["COMPLETED", "CANCELLED"].includes(task.status))
          return false;
        if (statusFilter !== "ACTIVE" && statusFilter !== "ALL" && task.status !== statusFilter)
          return false;
        if (!normalizedQuery) return true;
        return `${task.title} ${task.description || ""}`.toLowerCase().includes(normalizedQuery);
      })
      .sort(
        (a, b) =>
          Number(b.mandatory) - Number(a.mandatory) ||
          b.priority - a.priority ||
          a.created_at.localeCompare(b.created_at),
      );
  }, [query, statusFilter, tasks]);

  const openCreate = () => {
    setEditing(null);
    setDraft({ ...EMPTY_DRAFT });
    setDialogOpen(true);
  };

  const openEdit = (task: Task) => {
    setEditing(task);
    setDraft(draftFromTask(task));
    setDialogOpen(true);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    const payload = payloadFromDraft(draft);
    if (!payload.title) {
      setError("任务标题不能为空");
      return;
    }
    if (payload.minimum_chunk_minutes > payload.estimated_minutes) {
      setError("最小任务块不能大于预计时长");
      return;
    }
    const overlap = payload.allowed_apps.filter((app) => payload.blocked_apps.includes(app));
    if (overlap.length > 0) {
      setError(`应用不能同时允许和阻止：${overlap.join(", ")}`);
      return;
    }

    setSaving(true);
    try {
      if (editing) {
        await api.updateTask(editing.task_id, { ...payload, expected_version: editing.version });
        notify("任务已更新");
      } else {
        await api.createTask(payload);
        notify("任务已创建");
      }
      setDialogOpen(false);
      await load();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  };

  const complete = async (task: Task) => {
    setError(null);
    try {
      await api.updateTask(task.task_id, {
        expected_version: task.version,
        status: "COMPLETED",
        remaining_minutes: 0,
      });
      notify(`“${task.title}”已完成`);
      await load();
    } catch (cause) {
      setError(errorMessage(cause));
    }
  };

  const remove = async (task: Task) => {
    if (!window.confirm(`取消任务“${task.title}”？此操作会保留审计记录。`)) return;
    setError(null);
    try {
      await api.deleteTask(task.task_id, task.version);
      notify("任务已取消");
      await load();
    } catch (cause) {
      setError(errorMessage(cause));
    }
  };

  return (
    <div className="view-stack">
      <section className="page-intro">
        <div>
          <p className="eyebrow">Task CRUD · optimistic concurrency</p>
          <h2>把意图变成可排程任务</h2>
          <p>预计时长、最小任务块和运行约束将直接进入 Planner。</p>
        </div>
        <button className="button primary" type="button" onClick={openCreate}>
          <Icon name="plus" size={17} />
          新建任务
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

      <section className="card task-browser" aria-labelledby="task-list-title">
        <div className="task-toolbar">
          <label className="search-field">
            <span className="sr-only">搜索任务</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索标题或描述"
            />
          </label>
          <label className="compact-field">
            <span className="sr-only">状态筛选</span>
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}
            >
              <option value="ACTIVE">进行中的任务</option>
              <option value="ALL">全部状态</option>
              {STATUS_OPTIONS.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
          <button
            className="icon-button"
            type="button"
            onClick={() => void load()}
            aria-label="刷新任务"
            disabled={loading}
          >
            <Icon name="refresh" />
          </button>
        </div>
        <div className="card-heading task-heading">
          <div>
            <p className="eyebrow">权威任务列表</p>
            <h3 id="task-list-title">{visibleTasks.length} 个任务</h3>
          </div>
          <span className="subtle-count">共 {tasks.length}</span>
        </div>

        {loading ? (
          <div className="loading-inline" role="status">
            <span className="spinner" />
            正在读取任务…
          </div>
        ) : visibleTasks.length === 0 ? (
          <div className="inline-empty">没有符合条件的真实任务。</div>
        ) : (
          <div className="task-list">
            {visibleTasks.map((task) => {
              const progress =
                task.estimated_minutes > 0
                  ? Math.max(
                      0,
                      Math.min(
                        100,
                        ((task.estimated_minutes - task.remaining_minutes) /
                          task.estimated_minutes) *
                          100,
                      ),
                    )
                  : 0;
              const terminal = ["COMPLETED", "CANCELLED"].includes(task.status);
              return (
                <article className={`task-row ${terminal ? "terminal" : ""}`} key={task.task_id}>
                  <div className="task-priority" aria-label={`优先级 ${task.priority}`}>
                    P{task.priority}
                  </div>
                  <div className="task-main">
                    <div className="task-title-row">
                      <h4>{task.title}</h4>
                      {task.mandatory && <span className="tag mandatory">MANDATORY</span>}
                      <span className={`tag status-${task.status.toLowerCase()}`}>
                        {task.status}
                      </span>
                    </div>
                    {task.description && <p>{task.description}</p>}
                    <div className="task-meta">
                      <span>{humanizeCode(task.activity_profile)}</span>
                      <span>
                        {task.remaining_minutes}/{task.estimated_minutes} min 剩余
                      </span>
                      <span>
                        {task.deadline
                          ? `截止 ${formatDateTime(task.deadline, timezone)}`
                          : "无 deadline"}
                      </span>
                      <span>v{task.version}</span>
                    </div>
                    <div
                      className="progress-track"
                      aria-label={`任务进度 ${Math.round(progress)}%`}
                    >
                      <span style={{ width: `${progress}%` }} />
                    </div>
                  </div>
                  <div className="task-actions">
                    {!terminal && (
                      <button
                        className="icon-button success"
                        type="button"
                        onClick={() => void complete(task)}
                        aria-label={`完成 ${task.title}`}
                      >
                        <Icon name="check" />
                      </button>
                    )}
                    <button
                      className="icon-button"
                      type="button"
                      onClick={() => openEdit(task)}
                      aria-label={`编辑 ${task.title}`}
                    >
                      <Icon name="edit" />
                    </button>
                    {!terminal && (
                      <button
                        className="icon-button danger"
                        type="button"
                        onClick={() => void remove(task)}
                        aria-label={`取消 ${task.title}`}
                      >
                        <Icon name="trash" />
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {dialogOpen && (
        <div
          className="dialog-backdrop"
          role="presentation"
          onMouseDown={() => setDialogOpen(false)}
        >
          <section
            className="dialog-card task-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="task-dialog-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <form onSubmit={submit}>
              <div className="dialog-heading">
                <div>
                  <p className="eyebrow">{editing ? `Task v${editing.version}` : "新 Task"}</p>
                  <h2 id="task-dialog-title">{editing ? "编辑任务" : "创建任务"}</h2>
                </div>
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => setDialogOpen(false)}
                  aria-label="关闭任务表单"
                >
                  <Icon name="close" />
                </button>
              </div>

              <div className="form-grid">
                <label className="field full-span">
                  <span>标题 *</span>
                  <input
                    required
                    maxLength={200}
                    value={draft.title}
                    onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                    autoFocus
                  />
                </label>
                <label className="field full-span">
                  <span>描述</span>
                  <textarea
                    maxLength={4000}
                    rows={3}
                    value={draft.description}
                    onChange={(event) => setDraft({ ...draft, description: event.target.value })}
                  />
                </label>
                <label className="field">
                  <span>状态</span>
                  <select
                    value={draft.status}
                    onChange={(event) =>
                      setDraft({ ...draft, status: event.target.value as TaskStatus })
                    }
                  >
                    {STATUS_OPTIONS.map((status) => (
                      <option key={status}>{status}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>活动类型</span>
                  <select
                    value={draft.activityProfile}
                    onChange={(event) =>
                      setDraft({ ...draft, activityProfile: event.target.value as ActivityProfile })
                    }
                  >
                    {PROFILE_OPTIONS.map((profile) => (
                      <option key={profile}>{profile}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>优先级（1–5）</span>
                  <input
                    type="number"
                    min={1}
                    max={5}
                    required
                    value={draft.priority}
                    onChange={(event) =>
                      setDraft({ ...draft, priority: event.target.valueAsNumber })
                    }
                  />
                </label>
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={draft.mandatory}
                    onChange={(event) => setDraft({ ...draft, mandatory: event.target.checked })}
                  />
                  <span>
                    <strong>Mandatory</strong>
                    <small>规划器必须优先考虑</small>
                  </span>
                </label>
                <label className="field">
                  <span>预计时长（分钟）</span>
                  <input
                    type="number"
                    min={1}
                    max={10080}
                    required
                    value={draft.estimatedMinutes}
                    onChange={(event) =>
                      setDraft({ ...draft, estimatedMinutes: event.target.valueAsNumber })
                    }
                  />
                </label>
                <label className="field">
                  <span>剩余时长（分钟）</span>
                  <input
                    type="number"
                    min={0}
                    max={10080}
                    required
                    value={draft.remainingMinutes}
                    onChange={(event) =>
                      setDraft({ ...draft, remainingMinutes: event.target.valueAsNumber })
                    }
                  />
                </label>
                <label className="field">
                  <span>最小任务块（分钟）</span>
                  <input
                    type="number"
                    min={5}
                    max={180}
                    required
                    value={draft.minimumChunkMinutes}
                    onChange={(event) =>
                      setDraft({ ...draft, minimumChunkMinutes: event.target.valueAsNumber })
                    }
                  />
                </label>
                <label className="field">
                  <span>Idle 容忍（秒）</span>
                  <input
                    type="number"
                    min={30}
                    max={7200}
                    required
                    value={draft.idleToleranceSeconds}
                    onChange={(event) =>
                      setDraft({ ...draft, idleToleranceSeconds: event.target.valueAsNumber })
                    }
                  />
                </label>
                <label className="field">
                  <span>Deadline</span>
                  <input
                    type="datetime-local"
                    value={draft.deadline}
                    onChange={(event) => setDraft({ ...draft, deadline: event.target.value })}
                  />
                </label>
                <label className="field">
                  <span>所需地点</span>
                  <input
                    maxLength={128}
                    value={draft.requiredLocation}
                    onChange={(event) =>
                      setDraft({ ...draft, requiredLocation: event.target.value })
                    }
                  />
                </label>

                <details className="advanced-fields full-span">
                  <summary>设备与应用约束</summary>
                  <div className="form-grid nested-grid">
                    <label className="field full-span">
                      <span>所需设备能力</span>
                      <input
                        value={draft.capabilities}
                        onChange={(event) =>
                          setDraft({ ...draft, capabilities: event.target.value })
                        }
                        placeholder="keyboard, windows"
                      />
                      <small>使用逗号分隔。</small>
                    </label>
                    <label className="field">
                      <span>允许应用</span>
                      <textarea
                        rows={3}
                        value={draft.allowedApps}
                        onChange={(event) =>
                          setDraft({ ...draft, allowedApps: event.target.value })
                        }
                        placeholder="code.exe, chrome.exe"
                      />
                    </label>
                    <label className="field">
                      <span>阻止应用</span>
                      <textarea
                        rows={3}
                        value={draft.blockedApps}
                        onChange={(event) =>
                          setDraft({ ...draft, blockedApps: event.target.value })
                        }
                        placeholder="cs2.exe"
                      />
                    </label>
                  </div>
                </details>
              </div>

              <div className="dialog-actions">
                <button className="button ghost" type="button" onClick={() => setDialogOpen(false)}>
                  取消
                </button>
                <button className="button primary" type="submit" disabled={saving}>
                  {saving ? "保存中…" : editing ? "保存修改" : "创建任务"}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
}
