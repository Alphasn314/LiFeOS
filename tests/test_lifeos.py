import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import lifeos


class PlanTests(unittest.TestCase):
    def test_parse_valid_plan(self):
        self.assertEqual(
            lifeos.parse_plan_text("09:00 | 晨跑\n14:30 | 开会\n"),
            [
                {"time": "09:00", "task": "晨跑"},
                {"time": "14:30", "task": "开会"},
            ],
        )

    def test_reject_invalid_time(self):
        with self.assertRaises(lifeos.LifeOSError):
            lifeos.parse_plan_text("25:00 | 无效计划\n")

    def test_write_plan_and_daily_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(lifeos, "PLANS_DIR", root / "plans"),
                patch.object(lifeos, "DATA_DIR", root / "data"),
            ):
                lifeos.write_plan(
                    "2026-09-01",
                    [{"time": "09:00", "task": "晨跑"}],
                )
                self.assertEqual(
                    (root / "plans" / "2026-09-01.plan").read_text(encoding="utf-8"),
                    "09:00 | 晨跑\n",
                )
                state = {"date": "2026-09-01", "sent": {"abc": {"time": "09:00"}}}
                lifeos.write_daily_state("2026-09-01", state)
                saved = json.loads(
                    (root / "data" / "2026-09-01.json").read_text(encoding="utf-8")
                )
                self.assertEqual(saved, state)

    def test_process_due_records_successful_reminder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(lifeos, "PLANS_DIR", root / "plans"),
                patch.object(lifeos, "DATA_DIR", root / "data"),
            ):
                client = Mock()
                lifeos.write_plan(
                    "2026-09-01",
                    [
                        {"time": "09:00", "task": "晨跑"},
                        {"time": "15:00", "task": "未来任务"},
                    ],
                )
                now = datetime(2026, 9, 1, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
                self.assertEqual(lifeos.process_due(now, client), 1)
                self.assertEqual(lifeos.process_due(now, client), 0)
                client.send_reminder.assert_called_once_with("09:00", "晨跑")

    def test_client_reuses_bridge_identity_and_unique_private_chat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            bridge_path = root / "bridge.json"
            config_path.write_text(
                json.dumps({"appId": "app", "appSecret": "secret", "domain": "feishu"}),
                encoding="utf-8",
            )
            bridge_path.write_text(
                json.dumps(
                    {
                        "routes": {
                            "p2p:user": {"chatType": "p2p", "chatId": "chat"},
                            "group:one": {"chatType": "group", "chatId": "group"},
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {
                    "FEISHU_CONFIG_PATH": str(config_path),
                    "FEISHU_BRIDGE_PATH": str(bridge_path),
                },
                clear=False,
            ):
                client = lifeos.FeishuClient.from_bridge()
            self.assertEqual(client.app_id, "app")
            self.assertEqual(client.chat_id, "chat")

    def test_client_sends_with_openapi(self):
        client = lifeos.FeishuClient("app", "secret", "chat", "feishu")
        with patch.object(lifeos, "post_json") as post:
            post.side_effect = [
                {"code": 0, "tenant_access_token": "token", "expire": 7200},
                {"code": 0},
            ]
            client.send_reminder("09:00", "晨跑")
        self.assertEqual(post.call_count, 2)
        request = post.call_args_list[1]
        self.assertIn("receive_id_type=chat_id", request.args[0])
        self.assertEqual(request.args[1]["receive_id"], "chat")
        self.assertEqual(request.args[2], "token")


if __name__ == "__main__":
    unittest.main()
