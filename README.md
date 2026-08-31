# LifeOS v1

一个本地运行的每日计划提醒器。它读取当天的计划文件，到点后通过飞书 OpenAPI，以现有 LifeOS 机器人身份发送私聊提醒。

## 文件结构

```text
lifeos/
├── lifeos.py                    # 独立运行的提醒器和 CLI
├── plans/YYYY-MM-DD.plan        # 每天一个计划文件
├── data/YYYY-MM-DD.json         # 每天一个已发送状态文件
├── .pi/extensions/lifeos.ts     # Pi Agent 工具接口
├── deploy/lifeos.service        # systemd user service 模板
└── tests/test_lifeos.py
```

计划文件只包含 `时间 | 任务`：

```text
09:00 | 晨跑
10:30 | 完成项目方案
14:00 | 和小王开会
```

日期位于文件名，不写入文件内容。空行会被忽略；时间必须是 24 小时制 `HH:MM`。

## 配置和运行

```bash
cd ~/lifeos
python3 lifeos.py notify-test
python3 lifeos.py
```

LifeOS 默认读取 `~/.pi/agent/feishu/config.pi.json` 中现有 Bridge 的 App ID/Secret，并从 `bridge.pi.json` 自动选择唯一的私聊目标。不使用 Webhook，发送提醒时也不需要 Pi 或模型运行。

运行前需要先在飞书中私聊一次 LifeOS 机器人，让 Bridge 记录私聊路由。如果存在多个私聊用户，请复制 `.env.example` 为 `.env`，并明确配置 `FEISHU_CHAT_ID`。

未指定子命令时等同于 `python3 lifeos.py run`。服务启动或恢复后，会补发当天已经到点但尚未成功发送的计划。

长期运行可安装 user service：

```bash
mkdir -p ~/.config/systemd/user
cp deploy/lifeos.service ~/.config/systemd/user/lifeos.service
systemctl --user daemon-reload
systemctl --user enable --now lifeos
```

## LifeOS CLI 接口

写入某天的完整计划（会覆盖该日期的原计划）：

```bash
printf '%s' '[{"time":"09:00","task":"晨跑"},{"time":"14:00","task":"开会"}]' \
  | python3 lifeos.py plan-set --date 2026-09-01
```

读取和校验：

```bash
python3 lifeos.py plan-show --date 2026-09-01
python3 lifeos.py plan-validate --date 2026-09-01
```

命令成功和失败都返回 JSON；失败时退出码为非零，方便 Agent 稳定调用。

## Pi Agent 接口

从项目目录启动 Pi，项目扩展会提供：

- `lifeos_get_plan`：读取某天已有计划。
- `lifeos_set_plan`：覆盖写入某天完整计划。
- `lifeos_validate_plan`：校验某天计划。

修改已有计划时，Pi 应先调用 `lifeos_get_plan`，合并用户的新要求后，再调用 `lifeos_set_plan`。时间含糊时应先询问用户，不自行猜测。

项目级 Pi 扩展首次加载可能需要确认信任当前项目。LifeOS 的运行和 CLI 不依赖 Pi。

## 测试

```bash
python3 -m unittest discover -s tests -v
```
