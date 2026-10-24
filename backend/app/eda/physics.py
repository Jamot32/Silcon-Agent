"""Source-bound mapped synthesis and conservative, explicitly estimated sizing."""

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, localcontext
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from uuid import uuid4

from pydantic import JsonValue

from app.eda import flow
from app.eda.sandbox import DockerSandbox, MAX_JSON_BYTES, safe_artifact

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ZERO_CHECKS = ("design__lint_error__count", "design__lint_timing_construct__count",
                "design__inferred_latch__count", "design__instance_unmapped__count",
                "synthesis__check_error__count")


def number(value: object, *, positive: bool = True) -> Decimal:
    if type(value) not in (int, float, str, Decimal):
        raise ValueError("Expected a finite numeric quantity, not a boolean")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid numeric quantity") from None
    if not result.is_finite() or (result <= 0 if positive else result < 0) or result > Decimal("1e12"):
        raise ValueError("Quantity is outside the supported finite range")
    if len(result.as_tuple().digits) > 30 or result and result < Decimal("1e-12"):
        raise ValueError("Numeric precision or range is unsupported")
    return result


def structured(raw: bytes) -> dict:
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_JSON_BYTES:
        raise ValueError("Missing or oversized mapped-synthesis JSON artifact")
    def reject(value: str) -> None:
        raise ValueError("Nonfinite JSON constant in mapped-synthesis artifact")
    def unique(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key in mapped-synthesis artifact")
            result[key] = value
        return result
    value = json.loads(raw, parse_float=Decimal, parse_constant=reject, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("Mapped-synthesis artifact must be an object")
    return value


@dataclass(frozen=True)
class MappedArea:
    area_um2: Decimal
    cell_count: int
    source_sha256: str
    synthesis_state_sha256: str
    checker_state_sha256: str
    config_sha256: str
    clock_period_ns: Decimal
    synthesis_strategy: str


def parse_mapped_area(
    synthesis_raw: bytes, checker_raw: bytes, config_raw: bytes, *, source_sha256: str,
    expected_top: str, expected_sources: list[str], expected_clock_port: str | None,
    expected_clock_period: object, expected_strategy: str,
) -> MappedArea:
    """Keys and stage state are from an actual LibreLane 3.0.16 partial run."""
    if not isinstance(source_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ValueError("Source snapshot digest is required")
    if not isinstance(expected_top, str) or not _IDENTIFIER.fullmatch(expected_top):
        raise ValueError("Validated logical top is required")
    if expected_clock_port is not None and (not isinstance(expected_clock_port, str) or not _IDENTIFIER.fullmatch(expected_clock_port)):
        raise ValueError("Clock port must be a plain identifier or explicit None")
    config = structured(config_raw)
    if config.get("DESIGN_NAME") != expected_top:
        raise ValueError("Mapped top differs from the frozen top")
    if config.get("PDK") != "sky130A" or config.get("STD_CELL_LIBRARY") != "sky130_fd_sc_hd":
        raise ValueError("Mapped parser is qualified only for sky130A/sky130_fd_sc_hd")
    if (type(expected_sources) is not list or not expected_sources or any(not isinstance(path, str) for path in expected_sources)
            or len(set(expected_sources)) != len(expected_sources)
            or any(not re.fullmatch(r"/input/src/[A-Za-z_][A-Za-z0-9_]*\.v", path) for path in expected_sources)
            or config.get("VERILOG_FILES") != expected_sources):
        raise ValueError("Mapped source list differs from the immutable source snapshot")
    if config.get("CLOCK_PORT") != expected_clock_port:
        raise ValueError("Mapped clock port differs from the requested clock or virtual clock")
    if type(config.get("CLOCK_PERIOD")) not in (int, Decimal):
        raise ValueError("Mapped clock period must be an actual numeric resolved value")
    period = number(config["CLOCK_PERIOD"])
    if period != number(expected_clock_period):
        raise ValueError("Mapped clock period differs from the requested target")
    strategy = config.get("SYNTH_STRATEGY")
    if not isinstance(strategy, str) or strategy not in flow.STRATEGIES or strategy != expected_strategy:
        raise ValueError("Mapped synthesis strategy differs from the requested strategy")
    observed = []
    states = [structured(raw) for raw in (synthesis_raw, checker_raw)]
    for state in states:
        metrics = state.get("metrics")
        if (not isinstance(metrics, dict) or any(not isinstance(state.get(key), str)
                or not state[key].startswith("/output/runs/") or ".." in PurePosixPath(state[key]).parts
                for key in ("nl", "json_h"))):
            raise ValueError("Mapped synthesis/checker state is incomplete")
        if PurePosixPath(state["nl"]).name != f"{expected_top}.nl.v" or PurePosixPath(state["json_h"]).name != f"{expected_top}.h.json":
            raise ValueError("Mapped state views differ from the requested top")
        for key in _ZERO_CHECKS:
            if type(metrics.get(key)) is not int or metrics[key] != 0:
                raise ValueError(f"Mapped sizing requires an explicit zero {key}")
        count = metrics.get("design__instance__count")
        if type(count) is not int or not 0 < count <= 1_000_000_000:
            raise ValueError("Missing positive mapped cell count")
        area = metrics.get("design__instance__area")
        if type(area) not in (int, Decimal):
            raise ValueError("Mapped area must be an actual numeric state metric")
        observed.append((number(area), count))
    if observed[0] != observed[1] or any(states[0][key] != states[1][key] for key in ("nl", "json_h")):
        raise ValueError("Synthesis and final checker states disagree")
    return MappedArea(*observed[1], source_sha256, hashlib.sha256(synthesis_raw).hexdigest(),
                      hashlib.sha256(checker_raw).hexdigest(), hashlib.sha256(config_raw).hexdigest(), period, strategy)


def site_size(raw: bytes, name: str) -> tuple[Decimal, Decimal]:
    """Limited TECH_LEF SITE reader; unsupported or ambiguous syntax fails."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_JSON_BYTES or not isinstance(name, str) or not _IDENTIFIER.fullmatch(name):
        raise ValueError("Bounded TECH_LEF and a plain placement SITE name are required")
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|[^\s;]+|;', re.sub(r"#[^\n]*", "", raw.decode("utf-8")))
    sizes = []
    for index in range(len(tokens) - 2):
        if tokens[index:index + 2] != ["SITE", name] or tokens[index + 2] == ";":
            continue
        end = next((i for i in range(index + 2, len(tokens) - 1) if tokens[i:i + 2] == ["END", name]), None)
        if end is None:
            raise ValueError("Unterminated placement SITE block")
        block = tokens[index + 2:end]
        positions = [i for i, token in enumerate(block) if token == "SIZE"]
        if len(positions) != 1:
            raise ValueError("Placement SITE needs exactly one explicit SIZE")
        i = positions[0]
        if i + 4 >= len(block) or block[i + 2] != "BY" or block[i + 4] != ";":
            raise ValueError("Unsupported placement SITE SIZE syntax")
        sizes.append((number(block[i + 1]), number(block[i + 3])))
    if len(sizes) != 1:
        raise ValueError("Expected exactly one matching placement SITE declaration")
    return sizes[0]


@dataclass(frozen=True)
class SiteGeometry:
    width_um: Decimal
    height_um: Decimal
    left_sites: int
    right_sites: int
    bottom_rows: int
    top_rows: int
    provenance: dict

    def __post_init__(self) -> None:
        object.__setattr__(self, "width_um", number(self.width_um))
        object.__setattr__(self, "height_um", number(self.height_um))
        for value in (self.left_sites, self.right_sites, self.bottom_rows, self.top_rows):
            if type(value) is not int or not 0 <= value <= 10_000:
                raise ValueError("Placement margins must be bounded nonnegative integers")
        if not isinstance(self.provenance, dict) or not self.provenance:
            raise ValueError("Placement geometry requires observed provenance")

    def available_core(self, width: Decimal, height: Decimal) -> Decimal:
        with localcontext() as context:
            context.prec = 50
            columns = int((width / self.width_um).to_integral_value(rounding=ROUND_FLOOR)) - self.left_sites - self.right_sites
            rows = int((height / self.height_um).to_integral_value(rounding=ROUND_FLOOR)) - self.bottom_rows - self.top_rows
            if columns <= 0 or rows <= 0:
                raise ValueError("Configured margins leave no placement sites")
            return columns * rows * self.width_um * self.height_um


def site_geometry(config_raw: bytes, tech_lefs: dict[str, bytes]) -> SiteGeometry:
    config = structured(config_raw)
    configured = config.get("TECH_LEFS")
    if (not isinstance(configured, dict) or not configured or len(configured) > 16
            or any(not isinstance(value, str) for value in configured.values())
            or set(tech_lefs) != set(configured.values())):
        raise ValueError("Every resolved technology corner must supply its authorized TECH_LEF")
    dimensions = [site_size(raw, config.get("PLACE_SITE")) for raw in tech_lefs.values()]
    if len(set(dimensions)) != 1:
        raise ValueError("Placement SITE geometry disagrees between technology corners")
    margins = []
    for key in ("LEFT_MARGIN_MULT", "RIGHT_MARGIN_MULT", "BOTTOM_MARGIN_MULT", "TOP_MARGIN_MULT"):
        value = config.get(key)
        if type(value) is not int or not 0 <= value <= 10_000:
            raise ValueError(f"Missing explicit integral placement margin {key}")
        margins.append(value)
    provenance = {"config_sha256": hashlib.sha256(config_raw).hexdigest(), "site": config["PLACE_SITE"],
                  "tech_lef_sha256": {path: hashlib.sha256(raw).hexdigest() for path, raw in sorted(tech_lefs.items())}}
    return SiteGeometry(*dimensions[0], *margins, provenance)


def read_technology_lefs(pdk_dir: Path, config_raw: bytes) -> dict[str, bytes]:
    """Only resolved HD technology files beneath the backend-authorized PDK."""
    config = structured(config_raw)
    configured = config.get("TECH_LEFS")
    if not isinstance(configured, dict) or not configured or len(configured) > 16:
        raise ValueError("Resolved TECH_LEFS are missing")
    root = pdk_dir.resolve()
    result = {}
    prefix = "/pdk/sky130A/libs.ref/sky130_fd_sc_hd/techlef/"
    for value in configured.values():
        if (not isinstance(value, str) or not value.startswith(prefix) or ".." in PurePosixPath(value).parts
                or "\\" in value or PurePosixPath(value).suffix not in {".tlef", ".lef"}):
            raise ValueError("Resolved TECH_LEF is outside the authorized technology library")
        path = root / PurePosixPath(value).relative_to("/pdk")
        if not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError("Resolved TECH_LEF escapes the authorized PDK or is missing")
        result[value] = _read(root, path)
    return result


@dataclass(frozen=True)
class SizePlan:
    die_area: tuple[Decimal, Decimal, Decimal, Decimal]
    planned_core_area_um2: Decimal
    mapped_cell_area_um2: Decimal
    planned_utilization_pct: Decimal
    target_utilization_pct: Decimal
    fixed_footprint: bool
    fits_estimate: bool
    recommended_action: str
    reason: str
    measured: bool = False
    signoff_clean: bool = False
    tiny_tapeout_ready: bool = False


def size_from_mapped_area(area: object, geometry: SiteGeometry, *, utilization_pct: object = 45,
                          min_die_um: object = 100, max_die_um: object = 500,
                          fixed_die_area: list | None = None) -> SizePlan:
    """Conservative site/row arithmetic, not routing, timing, or tile signoff."""
    if type(geometry) is not SiteGeometry:
        raise ValueError("Observed placement SITE geometry is required")
    area, util, minimum, maximum = map(number, (area, utilization_pct, min_die_um, max_die_um))
    if not 1 <= util <= 90 or not 100 <= minimum <= maximum <= 500:
        raise ValueError("Sizing must retain the qualified 100 µm PDN minimum and 500 µm maximum")
    with localcontext() as context:
        context.prec = 50
        if fixed_die_area is not None:
            validated = flow.validate_flow_overrides({"DIE_AREA": fixed_die_area})["DIE_AREA"]
            x0, y0, x1, y1 = [number(value, positive=False) for value in validated]
        else:
            needed = area * 100 / util
            columns = int((needed.sqrt() / geometry.width_um).to_integral_value(rounding=ROUND_CEILING))
            rows = int((needed / (columns * geometry.width_um * geometry.height_um)).to_integral_value(rounding=ROUND_CEILING))
            snap = lambda value, grid, rounding: (value / grid).to_integral_value(rounding=rounding) * grid
            width = max((columns + geometry.left_sites + geometry.right_sites) * geometry.width_um,
                        snap(minimum, geometry.width_um, ROUND_CEILING))
            height = max((rows + geometry.bottom_rows + geometry.top_rows) * geometry.height_um,
                         snap(minimum, geometry.height_um, ROUND_CEILING))
            x0 = y0 = Decimal(0)
            x1 = min(width, snap(maximum, geometry.width_um, ROUND_FLOOR))
            y1 = min(height, snap(maximum, geometry.height_um, ROUND_FLOOR))
        width, height = x1 - x0, y1 - y0
        core = geometry.available_core(width, height)
        occupancy = area * 100 / core
        fits = minimum <= width <= maximum and minimum <= height <= maximum and area * 100 <= core * util
        if fits:
            action, reason = "run_physical_flow", "Estimated site/row capacity meets the target; real physical verification is still required."
        elif fixed_die_area is not None:
            action, reason = "reduce_design_or_request_larger_footprint", "Keep the explicit footprint unchanged; estimated capacity or the qualified PDN minimum is insufficient."
        else:
            action, reason = "reduce_design", "Estimated placement capacity exceeds the authorized 500 µm sizing bounds."
        return SizePlan((x0, y0, x1, y1), core, area, occupancy, util,
                        fixed_die_area is not None, fits, action, reason)


def source_digest(source_dir: Path) -> str:
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise ValueError("Immutable RTL source directory is missing or unsafe")
    digest = hashlib.sha256()
    paths = sorted(source_dir.iterdir())
    if not paths or len(paths) > 64:
        raise ValueError("Mapped synthesis requires 1..64 source files")
    for path in paths:
        if path.is_symlink() or not path.is_file() or path.suffix != ".v" or not _IDENTIFIER.fullmatch(path.stem) or path.stat().st_size > 128 * 1024:
            raise ValueError("Unsafe or oversized mapped source snapshot")
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def _read(root: Path, path: Path) -> bytes:
    path = safe_artifact(root, path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("Mapped artifact exceeds 2 MB")
    return raw


def _json(value: object) -> JsonValue:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    return value


def _command_error(output_dir: Path, path: Path, fallback: str) -> str:
    """Keep the first fatal line even when trailing context displaced the tail."""
    path = safe_artifact(output_dir, path)
    remaining = 16 * 1024 * 1024
    with path.open("rb") as stream:
        while remaining > 0:
            raw = stream.readline(min(4096, remaining))
            if not raw:
                break
            remaining -= len(raw)
            line = raw.decode(errors="replace")
            if re.search(r"\[E\]|\bERROR:|\[ERROR\s", line):
                return line.strip()[:700]
    return fallback


async def mapped_synth_stats(sandbox: DockerSandbox, input_dir: Path, output_dir: Path,
                             top: str, clock_port: str | None, overrides: dict[str, JsonValue], *,
                             work_dir: Path, fixed_footprint: bool = False,
                             utilization_pct: float = 45) -> dict[str, JsonValue]:
    """A new opt-in route; legacy synthesis/full-flow methods remain unchanged."""
    if type(fixed_footprint) is not bool:
        raise ValueError("Fixed-footprint selection must be explicit")
    result: dict[str, JsonValue] = {"ok": False, "phase": "technology_mapped_synthesis", "area_estimate": None,
                                  "cell_count": None, "physical_signoff": False, "tiny_tapeout_ready": False}
    relative = lambda path: str(safe_artifact(work_dir, path).relative_to(work_dir.resolve()))
    results_path = safe_artifact(output_dir, output_dir / "mapped_synth.json")
    result["results_path"] = relative(results_path)
    try:
        digest = source_digest(input_dir / "src")
        utilization = number(utilization_pct)
        if not 1 <= utilization <= 90:
            raise ValueError("Planned utilization must be between 1 and 90 percent")
        strategy = overrides.get("SYNTH_STRATEGY", "AREA 0")
        flow.write_config(input_dir, output_dir, top, clock_port, {**overrides, "SYNTH_STRATEGY": strategy})
        request = structured(_read(output_dir, output_dir / "config.json"))
        result["source_sha256"] = digest
        if not isinstance(sandbox.image, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", sandbox.image):
            raise ValueError("Mapped synthesis requires the backend to pin an immutable EDA image first")
        result["image_identity"] = {"image_id": sandbox.image, "authority": "backend_pinned_sandbox"}
        tag = "map_" + uuid4().hex[:16]
        command = ["python3", "-m", "librelane", "--manual-pdk", "--pdk-root", "/pdk", "--pdk", "sky130A",
                   "--scl", "sky130_fd_sc_hd", "--design-dir", "/output", "--run-tag", tag, "--jobs", "4",
                   "--condensed", "--to", "Checker.YosysSynthChecks", "/output/config.json"]
        observed = await sandbox.run(command, input_dir=input_dir, output_dir=output_dir, timeout=60, require_pdk=True)
        result.update(log_path=relative(observed.log_path), log_tail=observed.log_tail[-2048:], timed_out=observed.timed_out)
        if not observed.ok:
            message = "Mapped synthesis timed out" if observed.timed_out else _command_error(
                output_dir, observed.log_path, f"Mapped synthesis exited with code {observed.returncode}")
            raise ValueError(message)
        root = safe_artifact(output_dir, output_dir / "runs" / tag)
        synthesis = list(root.glob("*-yosys-synthesis/state_out.json"))
        checker = list(root.glob("*-checker-yosyssynthchecks/state_out.json"))
        if len(synthesis) != 1 or len(checker) != 1:
            raise ValueError("Mapped synthesis did not produce exactly one synthesis and final checker state")
        config_path = root / "resolved.json"
        result.update(stats_path=relative(checker[0]), artifact_paths={"synthesis_state": relative(synthesis[0]),
                      "checker_state": relative(checker[0]), "resolved_config": relative(config_path)})
        config_raw, synthesis_raw, checker_raw = (_read(output_dir, path) for path in (config_path, synthesis[0], checker[0]))
        mapped = parse_mapped_area(synthesis_raw, checker_raw, config_raw, source_sha256=digest, expected_top=top,
                                  expected_sources=request["VERILOG_FILES"], expected_clock_port=clock_port,
                                  expected_clock_period=request["CLOCK_PERIOD"], expected_strategy=strategy)
        if source_digest(input_dir / "src") != digest:
            raise ValueError("Source snapshot changed during mapped synthesis")
        lefs = read_technology_lefs(sandbox.pdk_dir, config_raw)
        geometry = site_geometry(config_raw, lefs)
        plan = size_from_mapped_area(mapped.area_um2, geometry, utilization_pct=utilization_pct,
                                    fixed_die_area=request["DIE_AREA"] if fixed_footprint else None)
        views = structured(checker_raw)
        artifacts = {"synthesis_state": synthesis[0], "checker_state": checker[0], "resolved_config": config_path}
        for key in ("nl", "json_h"):
            view = views[key]
            if not isinstance(view, str) or not view.startswith(f"/output/runs/{tag}/") or ".." in PurePosixPath(view).parts:
                raise ValueError("Mapped output view escapes its own run")
            path = output_dir / PurePosixPath(view).relative_to("/output")
            if not _read(output_dir, path):
                raise ValueError("Mapped output view is missing or empty")
            artifacts[key] = path
        result.update(ok=True, area_estimate=float(mapped.area_um2), cell_count=mapped.cell_count,
                      pdk="sky130A", std_cell_library="sky130_fd_sc_hd",
                      clock_port=clock_port, clock_period_ns=float(mapped.clock_period_ns), synthesis_strategy=mapped.synthesis_strategy,
                      stats_path=relative(checker[0]), sizing_plan=_json(asdict(plan)), geometry_provenance=_json(geometry.provenance),
                      geometry_observation={**{key: str(getattr(geometry, key)) for key in ("width_um", "height_um")},
                                            **{key: getattr(geometry, key) for key in ("left_sites", "right_sites", "bottom_rows", "top_rows")},
                                            "provenance": geometry.provenance},
                      mapped_provenance=_json(asdict(mapped)), artifact_paths={key: relative(path) for key, path in artifacts.items()},
                      planned_config_overrides={"DIE_AREA": _json(plan.die_area), "FP_CORE_UTIL": float(plan.target_utilization_pct),
                                                "PL_TARGET_DENSITY_PCT": float(plan.target_utilization_pct)} if plan.fits_estimate else {})
    except (ValueError, OSError) as error:
        message = str(error)[:1000]
        result.update(ok=False, error=message, first_error=message)
    results_path.write_text(json.dumps(result, allow_nan=False, indent=2) + "\n")
    return result
