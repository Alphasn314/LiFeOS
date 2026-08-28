import { useEffect, useState } from "react";
import type { ApiConfig } from "../api";
import { LifeOSApi, normalizeBaseUrl } from "../api";
import { errorMessage } from "../utils";
import { Icon } from "./Icon";

interface SettingsDialogProps {
  config: ApiConfig;
  open: boolean;
  onClose: () => void;
  onSave: (config: ApiConfig) => void;
}

export function SettingsDialog({ config, open, onClose, onSave }: SettingsDialogProps) {
  const [draft, setDraft] = useState(config);
  const [testState, setTestState] = useState<"idle" | "testing" | "ok" | "error">("idle");
  const [testMessage, setTestMessage] = useState("");

  useEffect(() => {
    if (open) {
      setDraft(config);
      setTestState("idle");
      setTestMessage("");
    }
  }, [config, open]);

  if (!open) return null;

  const testConnection = async () => {
    setTestState("testing");
    try {
      const health = await new LifeOSApi({
        ...draft,
        baseUrl: normalizeBaseUrl(draft.baseUrl),
      }).health();
      setTestState("ok");
      setTestMessage(`已连接 ${health.service} · v${health.version}`);
    } catch (error) {
      setTestState("error");
      setTestMessage(errorMessage(error));
    }
  };

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="dialog-card settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="dialog-heading">
          <div>
            <p className="eyebrow">连接设置</p>
            <h2 id="settings-title">Core 配置</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="关闭设置">
            <Icon name="close" />
          </button>
        </div>

        <div className="form-stack">
          <label className="field">
            <span>API Base URL</span>
            <input
              type="url"
              value={draft.baseUrl}
              onChange={(event) => setDraft({ ...draft, baseUrl: event.target.value })}
              placeholder="http://localhost:8000"
              autoComplete="url"
            />
            <small>例如 http://localhost:8000；末尾斜杠会自动移除。</small>
          </label>

          <label className="field">
            <span>Bearer Token</span>
            <input
              type="password"
              value={draft.token}
              onChange={(event) => setDraft({ ...draft, token: event.target.value })}
              placeholder="Core 未启用鉴权时可留空"
              autoComplete="current-password"
            />
            <small>Token 只保存在当前浏览器会话；不会写入 PWA 离线缓存。</small>
          </label>

          <label className="field">
            <span>计划展示时区</span>
            <input
              value={draft.displayTimezone}
              onChange={(event) => setDraft({ ...draft, displayTimezone: event.target.value })}
              placeholder="Asia/Shanghai"
            />
            <small>使用 IANA 时区名称。Core 仍以 UTC 保存时间。</small>
          </label>
        </div>

        {testState !== "idle" && (
          <p className={`connection-result ${testState}`} role="status">
            {testState === "testing" ? "正在测试连接…" : testMessage}
          </p>
        )}

        <div className="dialog-actions split-actions">
          <button
            className="button secondary"
            type="button"
            onClick={testConnection}
            disabled={testState === "testing"}
          >
            测试连接
          </button>
          <div>
            <button className="button ghost" type="button" onClick={onClose}>
              取消
            </button>
            <button
              className="button primary"
              type="button"
              onClick={() =>
                onSave({
                  ...draft,
                  baseUrl: normalizeBaseUrl(draft.baseUrl),
                  displayTimezone: draft.displayTimezone.trim() || "Asia/Shanghai",
                })
              }
            >
              保存并重连
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
