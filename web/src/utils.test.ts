import { describe, expect, it } from "vitest";
import { csvItems, dateInTimezone, isBlockActive, minutesBetween } from "./utils";
import type { ScheduleBlock } from "./types";

describe("time helpers", () => {
  it("calculates a date in the configured display timezone", () => {
    expect(dateInTimezone(new Date("2026-01-01T18:00:00Z"), "Asia/Shanghai")).toBe("2026-01-02");
  });

  it("calculates schedule duration from UTC timestamps", () => {
    expect(minutesBetween("2026-08-28T01:00:00Z", "2026-08-28T02:25:00Z")).toBe(85);
  });

  it("uses a half-open interval for the active block", () => {
    const block = {
      start_at: "2026-08-28T01:00:00Z",
      end_at: "2026-08-28T02:00:00Z",
    } as ScheduleBlock;
    expect(isBlockActive(block, new Date("2026-08-28T01:59:59Z"))).toBe(true);
    expect(isBlockActive(block, new Date("2026-08-28T02:00:00Z"))).toBe(false);
  });
});

describe("csvItems", () => {
  it("normalizes comma/newline separated constraints and removes duplicates", () => {
    expect(csvItems("code.exe, chrome.exe\ncode.exe, ")).toEqual(["code.exe", "chrome.exe"]);
  });
});
