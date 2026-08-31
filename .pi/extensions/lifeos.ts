import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const lifeosScript = path.join(projectRoot, "lifeos.py");

type RunResult = { code: number; stdout: string; stderr: string };

function runLifeOS(args: string[], stdin?: string): Promise<RunResult> {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", [lifeosScript, ...args], {
      cwd: projectRoot,
      env: process.env,
      stdio: ["pipe", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", reject);
    child.on("close", (code) => resolve({ code: code ?? 1, stdout, stderr }));
    child.stdin.end(stdin);
  });
}

function resultContent(result: RunResult) {
  const text = result.code === 0 ? result.stdout.trim() : result.stderr.trim();
  return {
    content: [{ type: "text" as const, text: text || `LifeOS 退出码：${result.code}` }],
    details: { exitCode: result.code },
    isError: result.code !== 0,
  };
}

export default function lifeosExtension(pi: ExtensionAPI) {
  pi.registerTool({
    name: "lifeos_set_plan",
    label: "写入 LifeOS 计划",
    description:
      "覆盖写入指定日期的完整计划。仅在所有任务都有明确的 24 小时制时间后调用；时间不明确时先询问用户。",
    parameters: Type.Object({
      date: Type.String({ description: "日期，严格使用 YYYY-MM-DD" }),
      items: Type.Array(
        Type.Object({
          time: Type.String({ description: "24 小时制时间 HH:MM" }),
          task: Type.String({ description: "简洁、完整的任务描述" }),
        }),
        { description: "当天全部计划；调用会覆盖原文件" },
      ),
    }),
    async execute(_toolCallId, params) {
      const result = await runLifeOS(
        ["plan-set", "--date", params.date],
        JSON.stringify(params.items),
      );
      return resultContent(result);
    },
  });

  pi.registerTool({
    name: "lifeos_get_plan",
    label: "读取 LifeOS 计划",
    description: "读取指定日期当前已有的完整计划；修改计划前应先读取，避免意外覆盖。",
    parameters: Type.Object({
      date: Type.String({ description: "日期，严格使用 YYYY-MM-DD" }),
    }),
    async execute(_toolCallId, params) {
      return resultContent(await runLifeOS(["plan-show", "--date", params.date]));
    },
  });

  pi.registerTool({
    name: "lifeos_validate_plan",
    label: "校验 LifeOS 计划",
    description: "检查指定日期的计划文件格式是否合法。",
    parameters: Type.Object({
      date: Type.String({ description: "日期，严格使用 YYYY-MM-DD" }),
    }),
    async execute(_toolCallId, params) {
      return resultContent(await runLifeOS(["plan-validate", "--date", params.date]));
    },
  });
}
