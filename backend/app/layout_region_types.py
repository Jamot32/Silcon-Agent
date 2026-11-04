"""Public image-space selection contracts, independent of storage and providers."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RegionModel(BaseModel):
    model_config = ConfigDict(strict=True, allow_inf_nan=False, extra="forbid")


class LayoutRegionBounds(RegionModel):
    """Normalized raster coordinates: origin at top left, x right, y down."""

    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self) -> "LayoutRegionBounds":
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("Select a nonempty rectangle inside the layout image")
        return self


class LayoutRegionInput(RegionModel):
    run_tag: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
    bounds: LayoutRegionBounds
    expected_image_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class LayoutPixelBounds(RegionModel):
    """Enclosing source pixel rectangle; right and bottom are exclusive."""

    x0: int = Field(ge=0)
    y0: int = Field(ge=0)
    x1: int = Field(gt=0)
    y1: int = Field(gt=0)


class LayoutRegionContext(RegionModel):
    source_run_id: str
    run_tag: str
    bounds: LayoutRegionBounds
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
    coordinate_space: Literal["image_normalized_top_left"] = "image_normalized_top_left"
    pixel_bounds: LayoutPixelBounds


class LayoutRegionImage(RegionModel):
    media_type: Literal["image/png"] = "image/png"
    data: str
    label: Literal["full_layout", "selected_region"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PreparedLayoutRegion(RegionModel):
    region: LayoutRegionContext
    images: list[LayoutRegionImage]
