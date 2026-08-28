from __future__ import annotations

from typing import Any
from uuid import uuid4

from conftest import ApiHarness
from fastapi.testclient import TestClient

from lifeos.api import create_app
from lifeos.context import build_planning_context


class InvalidAIProvider:
    name = "invalid-test-provider"

    def plan(self, _request: object) -> Any:
        return {"free_form": "this is deliberately not a valid AIPlanningResponse"}


def test_context_builder_is_bounded_and_has_no_archive_input(api_harness: ApiHarness) -> None:
    context = build_planning_context(
        now=api_harness.clock.now(),
        runtime_state={"state_version": 7},
        current_plan={"revision": 3},
        current_block_id=None,
        future_blocks=[{"index": index} for index in range(5)],
        today_progress={"completed": 2},
        unfinished_tasks=[{"index": index} for index in range(300)],
        active_incident=None,
        policy_constraints={"dry_run": True},
    )
    serialized = context.model_dump(mode="json")
    assert len(serialized["future_blocks"]) == 3
    assert len(serialized["unfinished_tasks"]) == 256
    assert "archive" not in serialized
    assert context.reason_codes == ["CONTEXT_DEFAULT_BOUNDED"]


def test_invalid_ai_output_is_recorded_and_falls_back(api_harness: ApiHarness) -> None:
    invalid_app = create_app(
        settings=api_harness.settings,
        database=api_harness.database,
        clock=api_harness.clock,
        ai_provider=InvalidAIProvider(),
    )
    with TestClient(invalid_app) as client:
        now = api_harness.clock.now()
        request_id = uuid4()
        response = client.post(
            "/api/v1/ai/jobs",
            headers=api_harness.headers,
            json={
                "idempotency_key": f"ai-job:{uuid4()}",
                "request": {
                    "request_id": str(request_id),
                    "requested_at": now.isoformat(),
                    "current_time": now.isoformat(),
                    "runtime_state": None,
                    "current_plan": None,
                    "current_block_id": None,
                    "future_blocks": [],
                    "today_progress": {},
                    "unfinished_tasks": [],
                    "active_incident": None,
                    "policy_constraints": {"dry_run": True},
                    "reason_codes": ["CONTEXT_DEFAULT_BOUNDED"],
                },
            },
        )
    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"
    assert response.json()["fallback_used"] is True
    assert "schema validation" in response.json()["last_error"]
