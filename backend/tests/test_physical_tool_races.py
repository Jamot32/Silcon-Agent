"""Tool-planning race control; all inputs/results are unit doubles."""
import asyncio
from types import SimpleNamespace
import pytest
from app.agent.tools import ToolRunner
from app.llm.types import ToolCall
from app.remote_store import RemoteStoreError
from test_tools import FakeEDA, verify_golden


def test_awaited_planning_cannot_oversubscribe_six_flow_limit(tmp_path):
    eda = FakeEDA()
    runner = ToolRunner(tmp_path, "unit-r4-race", eda=eda)
    entered = 0
    ready = asyncio.Event()

    async def prepare(top, overrides):
        nonlocal entered
        entered += 1
        if entered == 3:
            ready.set()
        await ready.wait()
        return {"ok": True, "planned_config_overrides": {}, "mapping_cache_key": "unit",
                "mapping_reused": False, "sizing_plan": {}, "footprint_policy": "unit-only"}

    async def scenario():
        await verify_golden(runner)
        runner.physical_planner = SimpleNamespace(prepare=prepare)
        runner.flow_runs = 5
        results = await asyncio.gather(*(runner.execute(ToolCall(
            id=f"unit-{index}", name="run_flow", arguments={"top": "counter", "config_overrides": {}}
        )) for index in range(3)))
        assert runner.flow_runs == 6
        assert eda.calls.count("run_flow") == 1
        assert sum(row.get("ok") is True for row in results) == 1
        assert sum("Flow budget exhausted" in row.get("error", "") for row in results) == 2
    asyncio.run(scenario())


@pytest.mark.parametrize("delay_stage", ["mapping", "event_save"])
def test_flow_rows_follow_proposal_order_when_awaits_finish_out_of_order(tmp_path, delay_stage):
    class MeasuredEDA(FakeEDA):
        async def run_flow(self, top, config_overrides):
            result = await super().run_flow(top, config_overrides)
            result["metrics"] = {"cell_count": 1}
            return result

    eda = MeasuredEDA()
    runner = ToolRunner(tmp_path, "unit-order", eda=eda)

    async def scenario():
        first = asyncio.Event()
        second = asyncio.Event()

        async def prepare(top, overrides):
            if delay_stage == "mapping":
                if overrides["CLOCK_PERIOD"] == 20:
                    first.set()
                    await second.wait()
                else:
                    await first.wait()
                    second.set()
            return {"ok": True, "planned_config_overrides": overrides, "mapping_cache_key": "unit",
                    "mapping_reused": False, "sizing_plan": {}, "footprint_policy": "unit-only"}

        await verify_golden(runner)

        async def publish(kind, payload):
            if delay_stage == "event_save" and kind == "tool_started":
                if payload["tool_call_id"] == "unit-0":
                    first.set()
                    await second.wait()
                else:
                    await first.wait()
                    second.set()

        runner.event_callback = publish
        runner.physical_planner = SimpleNamespace(prepare=prepare)
        results = await asyncio.gather(*(runner.execute(ToolCall(
            id=f"unit-{index}", name="run_flow", arguments={"top": "counter", "config_overrides": {"CLOCK_PERIOD": period}}
        )) for index, period in enumerate((20, 25))))
        assert [result["metrics"]["flow_index"] for result in results] == [1, 2]
        assert results[0]["run_tag"] == "unit_flow_2"
        assert runner.flow_runs == 2

    asyncio.run(scenario())


def test_single_metric_save_failure_propagates_without_a_failed_tool_result(tmp_path):
    class MeasuredEDA(FakeEDA):
        async def run_flow(self, top, config_overrides):
            result = await super().run_flow(top, config_overrides)
            result["metrics"] = {"cell_count": 1}
            return result

    events = []
    failed_saves = 0

    async def publish(kind, payload):
        nonlocal failed_saves
        if kind == "metric_recorded":
            failed_saves += 1
            raise RemoteStoreError("single unit outage")
        events.append((kind, payload))

    eda = MeasuredEDA()
    runner = ToolRunner(tmp_path, "unit-outage", eda=eda, event_callback=publish)

    async def scenario():
        await verify_golden(runner)
        with pytest.raises(RemoteStoreError):
            await runner.execute(ToolCall(id="unit-measured", name="run_flow", arguments={"top": "counter"}))

    asyncio.run(scenario())
    assert failed_saves == 1
    assert eda.calls.count("run_flow") == 1
    assert not any(kind == "tool_finished" and payload["tool_call_id"] == "unit-measured" for kind, payload in events)
