import type { PlanVersion, ScheduleBlock } from "./types";

export const EMPTY_VALUE = "—";

export function dateInTimezone(date: Date, timezone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

export function formatTime(value: string | null | undefined, timezone: string): string {
  if (!value) return EMPTY_VALUE;
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: timezone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function formatDateTime(value: string | null | undefined, timezone: string): string {
  if (!value) return EMPTY_VALUE;
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: timezone,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function minutesBetween(start: string, end: string): number {
  return Math.max(0, Math.round((new Date(end).getTime() - new Date(start).getTime()) / 60_000));
}

export function isBlockActive(block: ScheduleBlock, now = new Date()): boolean {
  const value = now.getTime();
  return value >= new Date(block.start_at).getTime() && value < new Date(block.end_at).getTime();
}

export function totalPlannedMinutes(plan: PlanVersion): number {
  return plan.blocks.reduce(
    (total, block) => total + minutesBetween(block.start_at, block.end_at),
    0,
  );
}

export function humanizeCode(value: string): string {
  return value.toLowerCase().replaceAll("_", " ");
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "发生未知错误";
}

export function toDatetimeLocal(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function csvItems(value: string): string[] {
  return [
    ...new Set(
      value
        .split(/[,\n]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ];
}
