"""Host worker: saved Codex authentication stays outside every EDA container."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import math
import os
from pathlib import Path
import signal
from typing import TYPE_CHECKING, Callable, Protocol

from pydantic import JsonValue

from app.agent.tools import ToolRunner
from app.llm.factory import create_llm
from app.llm.types import LLMError
from app.packaging import package_design
from app.schemas import Outcome

if TYPE_CHECKING:
    from app.agent.orchestrator import Orchestrator
    from app.models import Run

logger = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]


class WorkerStore(Protocol):
    def recover_interrupted(self) -> None: ...
    def claim_pending(self) -> Run | None: ...
    def work_dir(self, run_id: str) -> Path: ...
    def emit(self, run_id: str, event_type: str, payload: dict[str, JsonValue]) -> None: ...
    def cancel_requested(self, run_id: str) -> bool: ...
    def register_artifact(self, run_id: str, kind: str, path: Path, run_tag: str | None = None) -> None: ...
    def finish(self, run_id: str, outcome: Outcome) -> None: ...
    def fail(self, run_id: str, error: str, status: str = "failed") -> None: ...


class Worker:
    def __init__(self, store: WorkerStore, *, poll_interval: float = 0.5, orchestrator_factory: Callable[..., Orchestrator] | None = None):
        if not math.isfinite(poll_interval) or poll_interval <= 0:
            raise ValueError("Worker polling interval must be positive")
        self.store = store
        self.poll_interval = poll_interval
        self.orchestrator_factory = orchestrator_factory
        self.stop_event = asyncio.Event()
        self.current_task: asyncio.Task[Outcome] | None = None

    def request_stop(self) -> None:
        self.stop_event.set()
        if self.current_task:
            self.current_task.cancel()

    async def run(self) -> None:
        await asyncio.to_thread(self.store.recover_interrupted)
        while not self.stop_event.is_set():
            pending = await asyncio.to_thread(self.store.claim_pending)
            if pending is not None:
                if self.stop_event.is_set():
                    await asyncio.to_thread(self.store.fail, pending.id, "Worker stopped before execution")
                    break
                await self.execute(pending)
                continue
            try:
                await asyncio.wait_for(self.stop_event.wait(), self.poll_interval)
            except TimeoutError:
                pass

    async def execute(self, run: Run) -> None:
        llm = None
        monitor: asyncio.Task[None] | None = None
        try:
            if run.llm_provider != os.getenv("LLM_PROVIDER", "codex"):
                raise LLMError("Queued provider does not match the worker configuration; restart with the selected LLM_PROVIDER")
            llm = create_llm()
            orchestrator: Orchestrator

            async def publish(event_type: str, payload: dict[str, JsonValue]) -> None:
                spec = getattr(orchestrator, "design_spec", None)
                if spec is not None:
                    tools.eda.clock_port = None if spec.purely_combinational else "clk"
                result = payload.get("result", {})
                tag = result.get("run_tag") if isinstance(result, dict) else None
                if event_type == "layout_rendered":
                    tag = payload.get("run_tag")
                if isinstance(tag, str) and (event_type == "layout_rendered" or (event_type == "tool_finished" and payload.get("tool") == "run_flow")):
                    for kind, path in tools.eda.flow_artifacts(tag).items():
                        if kind not in {"logs_dir", "source_dir", "tests_dir"} and path.is_file():
                            await asyncio.to_thread(self.store.register_artifact, run.id, kind, path, run_tag=tag)
                await asyncio.to_thread(self.store.emit, run.id, event_type, payload)

            work_dir = await asyncio.to_thread(self.store.work_dir, run.id)
            if self.stop_event.is_set():
                await asyncio.to_thread(self.store.fail, run.id, "Worker stopped before execution")
                return
            tools = ToolRunner(work_dir, run_id=run.id, event_callback=publish)

            async def package(best_run_tag: str) -> Path:
                if orchestrator.design_spec is None:
                    raise ValueError("A validated design spec is required for packaging")
                path = await package_design(tools, best_run_tag, orchestrator.design_spec)
                await asyncio.to_thread(self.store.register_artifact, run.id, "bundle", path)
                return path

            factory = self.orchestrator_factory
            if factory is None:
                from app.agent.orchestrator import Orchestrator

                factory = Orchestrator
            targets = json.loads(run.targets_json) if run.targets_json else None
            orchestrator = factory(llm, tools, spec_text=run.spec_text, targets=targets, package_callback=package, event_callback=publish)
            self.current_task = asyncio.create_task(orchestrator.run())

            async def watch_cancellation() -> None:
                while self.current_task and not self.current_task.done():
                    if await asyncio.to_thread(self.store.cancel_requested, run.id):
                        self.current_task.cancel()
                        return
                    await asyncio.sleep(self.poll_interval)

            monitor = asyncio.create_task(watch_cancellation())
            outcome = await self.current_task
            if await asyncio.to_thread(self.store.cancel_requested, run.id):
                await asyncio.to_thread(self.store.fail, run.id, "Run cancelled by the user", status="cancelled")
            else:
                await asyncio.to_thread(self.store.finish, run.id, outcome)
        except asyncio.CancelledError:
            cancelled = await asyncio.to_thread(self.store.cancel_requested, run.id)
            await asyncio.to_thread(self.store.fail, run.id, "Run cancelled by the user" if cancelled else "Worker stopped during the run", status="cancelled" if cancelled else "failed")
        except Exception as error:
            # Provider errors already exclude credentials; unexpected exceptions expose only their class.
            detail = str(error) if isinstance(error, LLMError) else f"Worker failed ({type(error).__name__})"
            logger.error("run_failed run_id=%s error_type=%s", run.id, type(error).__name__)
            await asyncio.to_thread(self.store.fail, run.id, detail)
        finally:
            if monitor:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
            if self.current_task and not self.current_task.done():
                self.current_task.cancel()
                await asyncio.gather(self.current_task, return_exceptions=True)
            self.current_task = None
            close = getattr(llm, "aclose", None)
            if close:
                try:
                    await close()
                except Exception:
                    logger.error("provider_close_failed run_id=%s", run.id)


async def _serve(store: WorkerStore) -> None:
    worker = Worker(store)
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, worker.request_stop)
    await worker.run()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=REPO_ROOT / "runs")
    parser.add_argument("--owner-token", default="manual")
    options = parser.parse_args()
    root = options.runs_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from app.remote_store import HTTPRunStore

    with (root / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("A Silicon Agent worker already owns this run directory.")
            return 2
        store = HTTPRunStore(root)
        try:
            asyncio.run(_serve(store))
        finally:
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
