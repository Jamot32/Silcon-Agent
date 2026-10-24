"""Tool-planning race control; all inputs/results are unit doubles."""
import asyncio
from types import SimpleNamespace
from app.agent.tools import ToolRunner
from app.llm.types import ToolCall
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
