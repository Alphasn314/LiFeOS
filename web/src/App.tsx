import { useCallback, useEffect, useMemo, useState } from "react";
import { type ApiConfig, LifeOSApi } from "./api";
import { Icon, type IconName } from "./components/Icon";
import { SettingsDialog } from "./components/SettingsDialog";
import type { Health } from "./types";
import { AuditView } from "./views/AuditView";
import { StatusView } from "./views/StatusView";
import { TasksView } from "./views/TasksView";
import { TodayView } from "./views/TodayView";

type ViewName = "today" | "tasks" | "status" | "audit";

const NAV_ITEMS: { id: ViewName; label: string; shortLabel: string; icon: IconName }[] = [
  { id: "today", label: "今日计划", shortLabel: "今日", icon: "today" },
  { id: "tasks", label: "任务", shortLabel: "任务", icon: "tasks" },
  { id: "status", label: "执行状态", shortLabel: "状态", icon: "pulse" },
  { id: "audit", label: "审计事件", shortLabel: "审计", icon: "audit" },
];

function initialConfig(): ApiConfig {
  let baseUrl = import.meta.env.VITE_LIFEOS_API_BASE || "http://localhost:8000";
  let displayTimezone = "Asia/Shanghai";
  let token = "";
  try {
    baseUrl = localStorage.getItem("lifeos.apiBase") || baseUrl;
    displayTimezone = localStorage.getItem("lifeos.displayTimezone") || displayTimezone;
    token = sessionStorage.getItem("lifeos.token") || "";
  } catch {
    // Storage can be disabled; in-memory configuration still works.
  }
  return { baseUrl, displayTimezone, token };
}

export function App() {
  const [view, setView] = useState<ViewName>("today");
  const [config, setConfig] = useState<ApiConfig>(initialConfig);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [activeSessionId, setActiveSessionId] = useState(() => {
    try {
      return sessionStorage.getItem("lifeos.activeSessionId") || "";
    } catch {
      return "";
    }
  });
  const [toast, setToast] = useState<string | null>(null);
  const api = useMemo(() => new LifeOSApi(config), [config]);

  const refreshHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const value = await api.health();
      setHealth(value);
      setHealthError(null);
    } catch (error) {
      setHealth(null);
      setHealthError(error instanceof Error ? error.message : "Core 连接失败");
    } finally {
      setHealthLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void refreshHealth();
    const interval = window.setInterval(() => void refreshHealth(), 15_000);
    return () => window.clearInterval(interval);
  }, [refreshHealth]);

  useEffect(() => {
    if (!toast) return;
    const timeout = window.setTimeout(() => setToast(null), 4_000);
    return () => window.clearTimeout(timeout);
  }, [toast]);

  const rememberSession = (sessionId: string) => {
    setActiveSessionId(sessionId);
    try {
      sessionStorage.setItem("lifeos.activeSessionId", sessionId);
    } catch {
      // The current React state remains the source for this tab.
    }
  };

  const saveConfig = (next: ApiConfig) => {
    setConfig(next);
    try {
      localStorage.setItem("lifeos.apiBase", next.baseUrl);
      localStorage.setItem("lifeos.displayTimezone", next.displayTimezone);
      sessionStorage.setItem("lifeos.token", next.token);
    } catch {
      // Saving is best-effort; the in-memory values are already applied.
    }
    setSettingsOpen(false);
    setToast("连接设置已更新");
  };

  const safetyMode = healthError
    ? "offline"
    : healthLoading
      ? "checking"
      : health?.dry_run
        ? "dry"
        : health?.real_enforcement_enabled
          ? "live"
          : "disabled";

  const safetyText = {
    offline: "Core 未连接 · 不执行新强制动作",
    checking: "正在确认 Core 安全状态",
    dry: "DRY RUN · 仅记录拟执行动作",
    live: "注意 · 真实强制功能已启用",
    disabled: "真实强制功能已关闭",
  }[safetyMode];

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <aside className="sidebar" aria-label="主导航">
        <div className="brand" aria-label="LifeOS">
          <span className="brand-mark">L</span>
          <span className="brand-copy">
            <strong>LifeOS</strong>
            <small>闭环执行系统</small>
          </span>
        </div>

        <nav className="nav-list">
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${view === item.id ? "active" : ""}`}
              type="button"
              aria-current={view === item.id ? "page" : undefined}
              onClick={() => setView(item.id)}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className={`core-mini-status ${health ? "online" : "offline"}`}>
            <span className="status-dot" />
            <span>
              <strong>{health ? "Core 在线" : "Core 未连接"}</strong>
              <small>{health ? `v${health.version}` : "请检查连接设置"}</small>
            </span>
          </div>
          <button className="nav-item" type="button" onClick={() => setSettingsOpen(true)}>
            <Icon name="settings" />
            <span>连接设置</span>
          </button>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <div>
            <p className="mobile-brand">LifeOS</p>
            <h1>{NAV_ITEMS.find((item) => item.id === view)?.label}</h1>
          </div>
          <div className="topbar-actions">
            <div className={`safety-pill ${safetyMode}`} title={healthError || safetyText}>
              <span className="status-dot" />
              <span>{safetyText}</span>
            </div>
            <button
              className="icon-button top-settings"
              type="button"
              onClick={() => setSettingsOpen(true)}
              aria-label="打开连接设置"
            >
              <Icon name="settings" />
            </button>
          </div>
        </header>

        <div className={`safety-banner ${safetyMode}`} role="status">
          <Icon name={safetyMode === "live" ? "warning" : "shield"} />
          <span>{safetyText}</span>
          {healthError && <button onClick={() => void refreshHealth()}>重试</button>}
        </div>

        <main id="main-content" className="main-content" tabIndex={-1}>
          {view === "today" && (
            <TodayView
              api={api}
              timezone={config.displayTimezone}
              onSessionStarted={(id) => {
                rememberSession(id);
                setToast("Session 已启动");
                setView("status");
              }}
              notify={setToast}
            />
          )}
          {view === "tasks" && (
            <TasksView api={api} timezone={config.displayTimezone} notify={setToast} />
          )}
          {view === "status" && (
            <StatusView
              api={api}
              timezone={config.displayTimezone}
              activeSessionId={activeSessionId}
              onActiveSessionChange={rememberSession}
              notify={setToast}
            />
          )}
          {view === "audit" && <AuditView api={api} timezone={config.displayTimezone} />}
        </main>
      </div>

      <nav className="mobile-nav" aria-label="移动端主导航">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            className={view === item.id ? "active" : ""}
            type="button"
            aria-current={view === item.id ? "page" : undefined}
            onClick={() => setView(item.id)}
          >
            <Icon name={item.icon} size={19} />
            <span>{item.shortLabel}</span>
          </button>
        ))}
      </nav>

      <SettingsDialog
        config={config}
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onSave={saveConfig}
      />
      <div className="toast-region" aria-live="polite" aria-atomic="true">
        {toast && <div className="toast">{toast}</div>}
      </div>
    </div>
  );
}
