"""Compose actual command observations and durable evidence without inference."""
from app.observability.observer import RunObserver


class Integration:
    def __init__(self, observer: RunObserver):
        self.observer = observer
        self.failure = None

    def _failed(self, phase, error):
        if self.failure is None:
            self.failure = {"phase": phase, "exception_type": type(error).__name__}

    @staticmethod
    def _budget(llm):
        budget = getattr(llm, "budget", None)
        if budget is None:
            return None
        return {"calls": budget.calls, "input_tokens": budget.input_tokens,
                "output_tokens": budget.output_tokens, "cost_usd": budget.cost_usd}

    async def ask(self, llm, messages, tools, metadata):
        # The app supplies actual typed messages/schemas. No raw material is
        # passed to the writer; hashing is inside the observer's inference scope.
        plain = lambda values: [value if type(value) is dict else value.model_dump(mode="json") for value in values]
        with self.observer.inference(plain(messages), plain(tools), metadata,
                                     budget_snapshot=lambda: self._budget(llm)):
            return await llm.complete(messages, tools)

    async def tool(self, call, dispatch):
        with self.observer.tool(call.name, call.id, call.arguments):
            return await dispatch()

    def bind(self, sandbox, evidence, snapshots, *, view):
        """After image pinning; view returns caller-owned current revision args."""
        if sandbox.completion_callback not in (None, evidence.observe) or evidence.callback is not None:
            raise ValueError("Explicit ownership of callback composition required")

        def command_finished(observation):
            try:
                evidence.observe(observation)
                self.observer.command_observed(command=observation.command,
                    returncode=observation.result.returncode, timed_out=observation.result.timed_out,
                    process_launched=observation.process_launched, duration_seconds=observation.duration_seconds)
            except Exception as error:
                self._failed("command_trace", error)
                raise

        def evidence_finished(wrapped):
            # Existing ToolEvidence swallows callback exceptions. Sticky failure
            # is checked by the Worker before claiming complete observability.
            try:
                self.observer.evidence_finished(wrapped)
                snapshots.record(wrapped, **view(wrapped))
            except Exception as error:
                self._failed("ledger_snapshot", error)
                raise

        sandbox.completion_callback, evidence.callback = command_finished, evidence_finished

    def finish_worker(self, status, *, failure_class=None, error=None, store_confirmed=False):
        self.failure = self.failure or self.observer.failure
        if self.failure is not None and not store_confirmed and status in {"done", "replay_done"}:
            status, failure_class = "failed", "observability_incomplete"
            store_confirmed = False  # A changed local decision was not committed.
        self.observer.finish_run(status, failure_class=failure_class, error=error,
                                 outcome_authority="store_confirmed" if store_confirmed else "worker_local")
        return {"status": status, "failure_class": failure_class,
                "observability_complete": self.failure is None}

    @property
    def incomplete(self):
        return self.failure is not None or self.observer.failure is not None
