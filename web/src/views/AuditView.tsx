import { useCallback, useEffect, useMemo, useState } from "react";
import type { LifeOSApi } from "../api";
import { Icon } from "../components/Icon";
import type { EventEnvelope } from "../types";
import { errorMessage, formatDateTime } from "../utils";

interface AuditViewProps {
  api: LifeOSApi;
  timezone: string;
}

export function AuditView({ api, timezone }: AuditViewProps) {
  const [events, setEvents] = useState<EventEnvelope[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(200);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setEvents(await api.listEvents(limit));
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  }, [api, limit]);

  useEffect(() => {
    void load();
  }, [load]);

  const visibleEvents = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return [...events]
      .filter((event) =>
        !normalized
          ? true
          : `${event.event_type} ${event.source} ${event.entity_type} ${event.entity_id} ${event.reason_codes.join(" ")}`
              .toLowerCase()
              .includes(normalized),
      )
      .sort((a, b) => b.occurred_at.localeCompare(a.occurred_at));
  }, [events, query]);

  return (
    <div className="view-stack">
      <section className="page-intro">
        <div>
          <p className="eyebrow">Append-only EventLedger</p>
          <h2>每个决定都有来路</h2>
          <p>事件按发生时间展示；幂等键、原因码和载荷均来自 Core。</p>
        </div>
        <button
          className="button secondary"
          type="button"
          onClick={() => void load()}
          disabled={loading}
        >
          <Icon name="refresh" size={17} />
          刷新事件
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

      <section className="card audit-card" aria-labelledby="audit-title">
        <div className="task-toolbar">
          <label className="search-field">
            <span className="sr-only">筛选审计事件</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="筛选类型、来源、实体或原因码"
            />
          </label>
          <label className="compact-field">
            <span className="sr-only">返回事件数量</span>
            <select value={limit} onChange={(event) => setLimit(Number(event.target.value))}>
              <option value={50}>最近 50</option>
              <option value={200}>最近 200</option>
              <option value={500}>最近 500</option>
              <option value={1000}>最近 1000</option>
            </select>
          </label>
        </div>
        <div className="card-heading">
          <div>
            <p className="eyebrow">审计流</p>
            <h3 id="audit-title">{visibleEvents.length} 个事件</h3>
          </div>
          <span className="subtle-count">limit {limit}</span>
        </div>

        {loading ? (
          <div className="loading-inline">
            <span className="spinner" />
            读取 EventLedger…
          </div>
        ) : visibleEvents.length === 0 ? (
          <div className="inline-empty">Core 当前未返回匹配事件。</div>
        ) : (
          <ol className="audit-list">
            {visibleEvents.map((event) => (
              <li key={event.event_id} className="audit-event">
                <div className="audit-dot" aria-hidden="true" />
                <div className="audit-body">
                  <div className="audit-heading">
                    <div>
                      <strong>{event.event_type}</strong>
                      <span>{formatDateTime(event.occurred_at, timezone)}</span>
                    </div>
                    <span className="source-tag">{event.source}</span>
                  </div>
                  <p>
                    <span>{event.entity_type}</span>
                    <code>{event.entity_id}</code>
                  </p>
                  <div className="reason-list">
                    {event.reason_codes.map((reason) => (
                      <span key={reason}>{reason}</span>
                    ))}
                  </div>
                  <details className="event-details">
                    <summary>查看载荷与关联字段</summary>
                    <dl>
                      <div>
                        <dt>event_id</dt>
                        <dd>
                          <code>{event.event_id}</code>
                        </dd>
                      </div>
                      <div>
                        <dt>idempotency_key</dt>
                        <dd>
                          <code>{event.idempotency_key}</code>
                        </dd>
                      </div>
                      <div>
                        <dt>received_at</dt>
                        <dd>{formatDateTime(event.received_at, timezone)}</dd>
                      </div>
                      {event.correlation_id && (
                        <div>
                          <dt>correlation_id</dt>
                          <dd>
                            <code>{event.correlation_id}</code>
                          </dd>
                        </div>
                      )}
                    </dl>
                    <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                  </details>
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
