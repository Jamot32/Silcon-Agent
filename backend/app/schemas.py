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


class Outcome(BaseModel):
    status: Literal["done", "failed"]
    summary: str
    best_run_tag: str | None = None
    tapeout_ready: bool = False
    block_signoff_clean: bool = False
    design_spec: DesignSpec | None = None
    error: str | None = None
