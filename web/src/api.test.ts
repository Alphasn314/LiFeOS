import { afterEach, describe, expect, it, vi } from "vitest";
import { LifeOSApi, normalizeBaseUrl } from "./api";

const config = {
  baseUrl: "http://localhost:8000/",
  token: "local-token",
  displayTimezone: "Asia/Shanghai",
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("normalizeBaseUrl", () => {
  it("removes trailing slashes and preserves the configured origin", () => {
    expect(normalizeBaseUrl(" https://core.local/// ")).toBe("https://core.local");
  });

  it("uses the conservative local default for an empty value", () => {
    expect(normalizeBaseUrl("   ")).toBe("http://localhost:8000");
  });
});

describe("LifeOSApi", () => {
  it("sends the bearer token and optimistic-concurrency version", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ task_id: "task-1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await new LifeOSApi(config).deleteTask("task-1", 7);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/tasks/task-1?expected_version=7");
    expect(init.method).toBe("DELETE");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer local-token");
  });

  it("surfaces Core problem details without treating them as success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            title: "Version Conflict",
            detail: "expected version 2 but found 3",
            error_code: "VERSION_CONFLICT",
          }),
          { status: 409, headers: { "Content-Type": "application/problem+json" } },
        ),
      ),
    );

    await expect(new LifeOSApi(config).session("session-1")).rejects.toMatchObject({
      status: 409,
      message: "expected version 2 but found 3",
    });
  });

  it("sends planning location and selected-device capabilities", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ plan_version_id: "plan-1" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await new LifeOSApi(config).generatePlan(
      "2026-08-29",
      "DAY_STARTED",
      "07:00",
      "23:00",
      "campus",
      ["IDLE_SECONDS", "FOREGROUND_PROCESS", "IDLE_SECONDS"],
    );

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toMatchObject({
      available_location: "campus",
      available_device_capabilities: ["FOREGROUND_PROCESS", "IDLE_SECONDS"],
    });
  });
});
