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
from app.remote_store import RemoteStoreError
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
    def __init__(self, store: WorkerStore, *, poll_interval: float = 0.5, reconnect_max_delay: float = 10, orchestrator_factory: Callable[..., Orchestrator] | None = None):
        if not math.isfinite(poll_interval) or poll_interval <= 0:
            raise ValueError("Worker polling interval must be positive")
        self.store = store
        self.poll_interval = poll_interval
        if not math.isfinite(reconnect_max_delay) or reconnect_max_delay <= 0:
            raise ValueError("Worker reconnect delay must be positive")
        self.reconnect_max_delay = reconnect_max_delay
        self.orchestrator_factory = orchestrator_factory
        self.stop_event = asyncio.Event()
        self.current_task: asyncio.Task[Outcome] | None = None

    def request_stop(self) -> None:
        self.stop_event.set()
        if self.current_task and not self.current_task.cancelling():
            self.current_task.cancel()

    async def _call(self, method, *args, **kwargs):
        # Cancelling a to_thread await does not stop its HTTP request. Wait for
        # that single attempt to settle before recovery can mark the job failed.
        request = asyncio.create_task(asyncio.to_thread(method, *args, **kwargs))
        try:
            return await asyncio.shield(request)
        except asyncio.CancelledError:
            while not request.done():
                try:
                    await asyncio.shield(request)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not request.cancelled():
                request.exception()
            raise

    async def _wait(self, delay: float) -> None:
        try:
            await asyncio.wait_for(self.stop_event.wait(), delay)
        except TimeoutError:
            pass

    async def run(self) -> None:
        recovery_needed = True
        failures = 0
        while not self.stop_event.is_set():
            try:
                if recovery_needed:
                    heartbeat = getattr(self.store, "heartbeat", None)
                    if heartbeat is not None:
                        await self._call(heartbeat)
                    if self.stop_event.is_set():
                        break
                    # A lost claim ACK may own a running job whose ID was never
                    # received. Fail abandoned jobs; never reset them to pending.
                    await self._call(self.store.recover_interrupted)
                    recovery_needed = False
                pending = await self._call(self.store.claim_pending)
                if pending is not None:
                    if self.stop_event.is_set():
                        await self._call(self.store.fail, pending.id, "Worker stopped before execution")
                        break
                    await self.execute(pending)
                failures = 0
                await self._wait(self.poll_interval)
            except RemoteStoreError:
                # execute() has already awaited owned task/subprocess and RPC
                # cleanup. No failed mutation is retried or job re-executed.
                recovery_needed = True
                failures = min(failures + 1, 10)
                delay = min(self.reconnect_max_delay, self.poll_interval * 2 ** (failures - 1))
                logger.warning("worker_api_disconnected reconnect_delay_seconds=%.3f", delay)
                await self._wait(delay)

    async def execute(self, run: Run) -> None:
        llm = None
        try:
            if run.is_replay:
                self.current_task = asyncio.create_task(self._replay(run))
                await self._complete_task(run)
                return
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
                            await self._call(self.store.register_artifact, run.id, kind, path, run_tag=tag)
                await self._call(self.store.emit, run.id, event_type, payload)

            work_dir = await self._call(self.store.work_dir, run.id)
            if self.stop_event.is_set():
                await self._call(self.store.fail, run.id, "Worker stopped before execution")
                return
            tools = ToolRunner(work_dir, run_id=run.id, event_callback=publish)

            async def package(best_run_tag: str) -> Path:
                if orchestrator.design_spec is None:
                    raise ValueError("A validated design spec is required for packaging")
                path = await package_design(tools, best_run_tag, orchestrator.design_spec)
                await self._call(self.store.register_artifact, run.id, "bundle", path)
                return path

            factory = self.orchestrator_factory
            if factory is None:
                from app.agent.orchestrator import Orchestrator

                factory = Orchestrator
            targets = json.loads(run.targets_json) if run.targets_json else None
            starter = {"starter_id": run.starter_id} if run.starter_id is not None else {}
            orchestrator = factory(llm, tools, spec_text=run.spec_text, targets=targets, package_callback=package, event_callback=publish, **starter)
            self.current_task = asyncio.create_task(orchestrator.run())
            await self._complete_task(run)
        except RemoteStoreError:
            raise
        except asyncio.CancelledError:
            cancelled = await self._call(self.store.cancel_requested, run.id)
            await self._call(self.store.fail, run.id, "Run cancelled by the user" if cancelled else "Worker stopped during the run", status="cancelled" if cancelled else "failed")
        except Exception as error:
            # Provider errors already exclude credentials; unexpected exceptions expose only their class.
            detail = str(error) if isinstance(error, LLMError) else f"Worker failed ({type(error).__name__})"
            logger.error("run_failed run_id=%s error_type=%s", run.id, type(error).__name__)
            await self._call(self.store.fail, run.id, detail)
        finally:
            if self.current_task and not self.current_task.done():
                if not self.current_task.cancelling():
                    self.current_task.cancel()
                await asyncio.gather(self.current_task, return_exceptions=True)
            self.current_task = None
            close = getattr(llm, "aclose", None)
            if close:
                try:
                    await close()
                except Exception:
                    logger.error("provider_close_failed run_id=%s", run.id)

    async def _complete_task(self, run: Run) -> None:
        async def watch_cancellation() -> None:
            while self.current_task and not self.current_task.done():
                if await self._call(self.store.cancel_requested, run.id):
                    if not self.current_task.cancelling():
                        self.current_task.cancel()
                    return
                await asyncio.sleep(self.poll_interval)
        monitor = asyncio.create_task(watch_cancellation())
        try:
            assert self.current_task is not None
            done, _ = await asyncio.wait({self.current_task, monitor}, return_when=asyncio.FIRST_COMPLETED)
            if monitor in done:
                # A failed cancellation check is a failed control plane, not a
                # background exception that permits an unmonitored design run.
                await monitor
            outcome = await self.current_task
            if await self._call(self.store.cancel_requested, run.id):
                await self._call(self.store.fail, run.id, "Run cancelled by the user", status="cancelled")
            else:
                await self._call(self.store.finish, run.id, outcome)
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
            if self.current_task and not self.current_task.done():
                if not self.current_task.cancelling():
                    self.current_task.cancel()
                await asyncio.gather(self.current_task, return_exceptions=True)

    async def _replay(self, run: Run) -> Outcome:
        from app.replay import load_recording, play_recording

        catalog = Path(os.getenv("RECORDINGS_DIR", str(REPO_ROOT / "demo_recordings")))
        try:
            recording = await asyncio.to_thread(load_recording, catalog, run.recording_id)
        except (ValueError, OSError, TypeError, KeyError):
            raise LLMError("Recording failed integrity validation; no replay events were emitted") from None
        work = await self._call(self.store.work_dir, run.id)
        async def emit(kind: str, payload: dict[str, JsonValue]) -> None:
            await self._call(self.store.emit, run.id, kind, payload)
        async def register(kind: str, path: Path, tag: str | None) -> None:
            await self._call(self.store.register_artifact, run.id, kind, path, tag)
        return await play_recording(recording, run.id, run.replay_speed, work, emit=emit, register=register)


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
