from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_]*$"
# Verilog keywords from the pinned Icarus v13_0 lexer, GN_KEYWORDS_1364_*:
# https://github.com/steveicarus/iverilog/blob/v13_0/lexor_keyword.gperf
_RESERVED = set("""
always and assign automatic begin buf bufif0 bufif1 case casex casez cell cmos
config deassign default defparam design disable edge else end endcase endconfig
endfunction endgenerate endmodule endprimitive endspecify endtable endtask event
for force forever fork function generate genvar highz0 highz1 if ifnone incdir
include initial inout input instance integer join large liblist library localparam
macromodule medium module nand negedge nmos nor noshowcancelled not notif0 notif1
or output parameter pmos posedge primitive pull0 pull1 pulldown pullup
pulsestyle_onevent pulsestyle_ondetect rcmos real realtime reg release repeat rnmos
rpmos rtran rtranif0 rtranif1 scalared showcancelled signed small specify specparam
strong0 strong1 supply0 supply1 table task time tran tranif0 tranif1 tri tri0 tri1
triand trior trireg unsigned use uwire vectored wait wand weak0 weak1 while wire
wone wor xnor xor
""".split()) | {"logic", "typedef", "enum", "always_ff", "always_comb", "always_latch"}


class Port(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(pattern=IDENTIFIER, max_length=128)
    direction: Literal["input", "output"]
    width: int = Field(default=1, ge=1, le=1024)
    description: str = Field(min_length=1, max_length=300)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if value in _RESERVED:
            raise ValueError("Port name is a reserved Verilog keyword")
        return value


class _Targets(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    clock_mhz: float | None = Field(default=None, ge=1, le=1000)
    max_area_um2: float | None = Field(default=None, gt=0)
    fit: Literal["tt_1x1_tile"] | None = None


class DesignSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    top_module: str = Field(pattern=r"^[a-z_][a-z0-9_]*$", max_length=128)
    summary: str = Field(min_length=1, max_length=1500)
    ports: list[Port] = Field(min_length=1, max_length=64)
    behavior: list[str] = Field(min_length=1, max_length=32)
    targets: dict[str, JsonValue] = Field(default_factory=dict, json_schema_extra=_Targets.model_json_schema())
    test_plan: list[str] = Field(min_length=4, max_length=32)
    purely_combinational: bool = False

    @field_validator("top_module")
    @classmethod
    def valid_top(cls, value: str) -> str:
        if value in _RESERVED:
            raise ValueError("Top module is a reserved Verilog keyword")
        return value

    @field_validator("behavior", "test_plan")
    @classmethod
    def nonempty_requirements(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 500 for value in values):
            raise ValueError("Requirements must be nonempty and at most 500 characters")
        return values

    @field_validator("targets")
    @classmethod
    def valid_targets(cls, values: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return _Targets.model_validate(values).model_dump()

    @model_validator(mode="after")
    def coherent_ports(self) -> "DesignSpec":
        ports = {port.name: port for port in self.ports}
        if len(ports) != len(self.ports):
            raise ValueError("Port names must be unique")
        for name in ("clk", "rst_n"):
            if name not in ports:
                if not self.purely_combinational:
                    raise ValueError(f"Sequential designs require {name}")
            elif ports[name].direction != "input" or ports[name].width != 1:
                raise ValueError(f"{name} must be a one-bit input")
        return self


# A run waiting at REVIEW holds the only worker slot. The API refuses answers after this long in REVIEW;
# the worker starts counting slightly later, so it never gives up on an answer the API accepted.
REVIEW_TIMEOUT_SECONDS = 30 * 60
# The reviewed initial flow takes only these knobs: the clock comes from the clock target and the planner sizes the die.
REVIEW_FLOW_KEYS = {"SYNTH_STRATEGY", "FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT"}


class BuildConfig(BaseModel):
    """Build settings an expert can lower or redirect at the REVIEW checkpoint; defaults are the normal build."""
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    optimize: bool = True
    max_flow_runs: int = Field(default=6, ge=1, le=6)
    max_repair_loops: int = Field(default=5, ge=0, le=5)
    initial_flow: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("initial_flow")
    @classmethod
    def valid_initial_flow(cls, values: dict[str, JsonValue]) -> dict[str, JsonValue]:
        from app.eda.flow import validate_flow_overrides

        if set(values) - REVIEW_FLOW_KEYS:
            raise ValueError("The initial flow accepts only SYNTH_STRATEGY, FP_CORE_UTIL and PL_TARGET_DENSITY_PCT")
        return validate_flow_overrides(values)


class Outcome(BaseModel):
    status: Literal["done", "failed"]
    summary: str
    best_run_tag: str | None = None
    tapeout_ready: bool = False
    block_signoff_clean: bool = False
    design_spec: DesignSpec | None = None
    error: str | None = None
    failure_class: str | None = Field(default=None, pattern=r"^[a-z_]+$", max_length=64)
    suggested_action: str | None = Field(default=None, min_length=1, max_length=1000)
    last_diagnostic: dict[str, JsonValue] | None = None
    scope_decision: Literal["decline", "ask_clarify", "scope_down"] | None = None
    scope_reason: str | None = Field(default=None, min_length=1, max_length=3000)

    @model_validator(mode="after")
    def visible_scope_outcome(self) -> "Outcome":
        if self.scope_decision is None:
            if self.scope_reason is not None:
                raise ValueError("A scope reason requires a scope decision")
            return self
        if not self.scope_reason or not self.scope_reason.strip():
            raise ValueError("A scope decision requires a nonempty visible reason")
        if self.status != "failed" or self.best_run_tag is not None or self.tapeout_ready or self.block_signoff_clean:
            raise ValueError("A scope decision cannot claim a completed or signed-off build")
        if self.summary != self.scope_reason or self.error not in (None, self.scope_reason):
            raise ValueError("The scope reason must exactly match the visible terminal explanation")
        return self
