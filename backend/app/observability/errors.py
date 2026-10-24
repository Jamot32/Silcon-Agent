"""Fixed host diagnostics for request transport/facade binding failures."""
from app.llm.policy import ProviderFailureHint


_REASONS = {
    "not_configured": "The request observer has no configured real transport.",
    "unreadable_binding": "The host request facade bindings could not be read.",
    "transport_binding": "The request facade does not share the configured transport Budget object and selected model.",
    "callback_ownership": "Provider callback ownership changed between the facade and configured transport.",
    "unobservable_facade": "The request facade has no owned response hook or shared transport Budget.",
    "response_missing": "The request returned without a completed observed transport response.",
    "response_mismatch": "The request facade returned usage or model metadata different from the measured transport Completion.",
}
_ACTION = "Configure the real transport once, preserve its Budget/model/callback bindings, and forward its measured Completion through the host facade."


class ObservationBindingError(ValueError):
    def __init__(self, kind: str):
        if type(kind) is not str or kind not in _REASONS:
            raise ValueError("Unknown host observation binding reason")
        self.kind = kind
        self.failure_hint = ProviderFailureHint("observability_incomplete", "observability", kind, _REASONS[kind], _ACTION)
        super().__init__(_REASONS[kind] + " " + _ACTION)
