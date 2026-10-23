import json
from pathlib import Path


class Memory:
    """Short stage summaries, with an independent verification context."""

    def __init__(self, path: Path):
        self.path = path
        self.summaries: dict[str, str] = {}

    def record(self, stage: str, text: str) -> None:
        lines = [line.strip()[:160] for line in text.splitlines() if line.strip()][:5]
        lines.extend(["Not provided by model."] * (5 - len(lines)))
        self.summaries[stage] = "\n".join(lines)
        self.path.write_text(json.dumps(self.summaries, indent=2) + "\n")

    def context(self, *, verify: bool = False) -> dict[str, str]:
        # RTL/optimization summaries may reveal implementation details. They must
        # never enter the independent spec-derived test-authoring conversation.
        allowed = {"SPEC", "VERIFY"} if verify else self.summaries.keys()
        selected = [(stage, summary) for stage, summary in self.summaries.items() if stage in allowed]
        return dict(selected[-3:])
