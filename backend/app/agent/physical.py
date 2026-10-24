"""Host-owned physical planning from source-bound measurements, never guesses."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json

from pydantic import JsonValue

from app.eda.flow import validate_flow_overrides
from app.eda.physics import SiteGeometry, size_from_mapped_area
from app.eda.sandbox import pin_sandbox_image, read_json_artifact, safe_artifact
from app.eda.service import EDA
from app.schemas import DesignSpec

# Boundary from the pinned TT SKY 1x1 DEF. This standalone flow does not prove
# wrapper/pin/precheck integration merely by respecting that boundary.
TT_TILE_BOUNDARY = [0, 0, 161.0, 111.52]


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class PhysicalPlanner:
    def __init__(self, spec: DesignSpec, eda: EDA):
        self.spec = DesignSpec.model_validate(spec.model_dump(mode="json"))
        self.eda = eda
        self.image_identity: dict[str, str] | None = None
        self._cache: dict[str, dict[str, JsonValue]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def initialize(self) -> None:
        pinned, identity = await pin_sandbox_image(self.eda.sandbox)
        self.eda.sandbox = pinned
        self.image_identity = identity

    def overrides(self, requested: dict[str, JsonValue]) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        path = safe_artifact(self.eda.work_dir, self.eda.work_dir / "config.json")
        if path.is_file():
            stored = read_json_artifact(self.eda.work_dir, path, finite=True)
            if not isinstance(stored, dict):
                raise ValueError("Stored flow overrides must be an object")
            result.update(validate_flow_overrides(stored))
        result.update(validate_flow_overrides(requested))
        clock = self.spec.targets.get("clock_mhz")
        result.setdefault("CLOCK_PERIOD", 1000 / float(clock) if clock is not None else 20)
        result.setdefault("SYNTH_STRATEGY", "AREA 0")
        return result

    @property
    def fixed_tile(self) -> bool:
        return self.spec.targets.get("fit") == "tt_1x1_tile"

    async def prepare(self, top: str, requested: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if self.image_identity is None:
            raise ValueError("Physical planner is not initialized")
        if self.eda.sandbox.image != self.image_identity["image_id"]:
            raise ValueError("EDA sandbox image changed after physical planning was initialized")
        if top != self.spec.top_module:
            raise ValueError("Physical top differs from the frozen logical top")
        overrides = self.overrides(requested)
        from app.eda.physics import source_digest
        revision = source_digest(self.eda.work_dir / "src")
        key_data = {"source_sha256": revision, "top": top, "clock_port": self.eda.clock_port,
                    "clock_period": float(overrides["CLOCK_PERIOD"]), "strategy": overrides["SYNTH_STRATEGY"],
                    "image_id": self.image_identity["image_id"]}
        key = hashlib.sha256(canonical(key_data)).hexdigest()
        async with self._locks.setdefault(key, asyncio.Lock()):
            if source_digest(self.eda.work_dir / "src") != revision:
                raise ValueError("RTL changed while waiting for mapped synthesis; verify the new source")
            reused = key in self._cache
            if not reused:
                mapped = await self.eda.mapped_synth_stats(top, overrides)
                if mapped.get("ok") is not True:
                    return {**mapped, "physical_flow_started": False}
                if (mapped.get("source_sha256") != revision
                        or mapped.get("clock_port") != self.eda.clock_port
                        or mapped.get("clock_period_ns") != overrides["CLOCK_PERIOD"]
                        or mapped.get("synthesis_strategy") != overrides["SYNTH_STRATEGY"]
                        or mapped.get("image_identity", {}).get("image_id") != self.image_identity["image_id"]):
                    raise ValueError("Mapped synthesis receipt differs from the frozen request")
                if source_digest(self.eda.work_dir / "src") != revision:
                    raise ValueError("RTL changed during mapped synthesis; verify the new source")
                self._cache[key] = deepcopy(mapped)
            mapped = deepcopy(self._cache[key])
        if source_digest(self.eda.work_dir / "src") != revision:
            raise ValueError("RTL changed before physical sizing; verify the new source")
        geometry = SiteGeometry(**mapped["geometry_observation"])
        utilization = overrides.get("FP_CORE_UTIL", 45)
        explicit = overrides.get("DIE_AREA")
        fixed = explicit
        if self.fixed_tile:
            if explicit is not None:
                x0, y0, x1, y1 = explicit
                if x0 < 0 or y0 < 0 or x1 > TT_TILE_BOUNDARY[2] or y1 > TT_TILE_BOUNDARY[3]:
                    raise ValueError("The requested die exceeds the fixed 1x1 boundary; reduce logic or explicitly request a larger footprint")
            else:
                fixed = list(TT_TILE_BOUNDARY)
        plan = size_from_mapped_area(mapped["area_estimate"], geometry, utilization_pct=utilization,
                                    fixed_die_area=fixed)
        planned = dict(overrides)
        if plan.fits_estimate:
            planned.update(DIE_AREA=[float(value) for value in plan.die_area],
                           FP_CORE_UTIL=float(plan.target_utilization_pct))
            planned.setdefault("PL_TARGET_DENSITY_PCT", float(plan.target_utilization_pct))
        result = {**mapped, "sizing_plan": json.loads(json.dumps(asdict(plan), default=str)),
                  "mapping_reused": reused, "mapping_cache_key": key,
                  "planned_config_overrides": planned if plan.fits_estimate else {},
                  "physical_flow_started": False, "footprint_boundary_verified": False,
                  "footprint_policy": "fixed_1x1_boundary_only" if self.fixed_tile else "standalone"}
        if not plan.fits_estimate:
            result.update(ok=False, error=plan.reason, error_kind="sizing_preflight",
                          first_error=plan.reason, suggested_action=plan.recommended_action)
        return result
