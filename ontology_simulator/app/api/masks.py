"""Mask (photomask / reticle) inventory by photo station.

Simulator-side data source for the V54 System MCP smoke flow. The
simulator already models photo lithography stations as MES steps whose
number is a multiple of 5 (see ``station_agent._is_photo_step`` and
``_build_mes_info`` which stamps ``photoLayerID = "M{step//5}"``). This
module exposes a small in-memory mask catalog keyed by those same
station ids so a System MCP can read it via plain HTTP and the V54 flow
can derive a Block + Skill on top.

In-memory only — restarting the simulator restores the seed list, no DB
involvement (intentionally lightweight: avoids Flyway / Java entity
work just to validate the MCP plumbing).
"""

from __future__ import annotations

from datetime import date
from typing import Final, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/masks", tags=["masks"])


# ── Photo station ids (must match simulator's _is_photo_step naming) ─────
# step_num % 5 == 0  →  STEP_005 / STEP_010 / STEP_015 / STEP_020
# layer_name follows the simulator's M{step_num // 5} convention.

PHOTO_STATIONS: Final[list[dict[str, str]]] = [
    {"station_id": "STEP_005", "layer_name": "M1"},
    {"station_id": "STEP_010", "layer_name": "M2"},
    {"station_id": "STEP_015", "layer_name": "M3"},
    {"station_id": "STEP_020", "layer_name": "M4"},
]


class Mask(BaseModel):
    """Photomask record. 10 attributes total — chosen to cover identity,
    lineage (product / layer / node), wear (usage / defect), quality (CD),
    state (status / last clean) and the lookup key (station_id)."""

    mask_id:         str   = Field(description="Unique mask identifier (e.g. MSK-A2901)")
    layer_name:      str   = Field(description="Process layer (M1, M2, ...) tied to the station")
    process_node:    str   = Field(description="Technology node (e.g. 28nm, 14nm, 7nm, 5nm)")
    product_id:      str   = Field(description="Product this mask is allocated to (e.g. PROD-A1)")
    usage_count:     int   = Field(description="Cumulative shot/exposure count")
    defect_count:    int   = Field(description="Defect count from the latest inspection")
    min_cd_nm:       float = Field(description="Minimum critical dimension in nanometres")
    status:          str   = Field(description="active | standby | cleaning | scrapped")
    last_clean_date: date  = Field(description="ISO date of the last mask clean")
    station_id:      str   = Field(description="Photo station id this mask belongs to (lookup key)")


class StationMasksResponse(BaseModel):
    station_id: str
    layer_name: Optional[str]
    mask_count: int
    masks:      list[Mask]


class StationListItem(BaseModel):
    station_id: str
    layer_name: str
    mask_count: int


# ── In-memory seed ───────────────────────────────────────────────────────
# 40 records: ~10 per station. Each station's masks cover multiple
# products + nodes + statuses so an analyst can filter / group meaningfully.
# usage_count + defect_count have gradients so SPC-like analysis is feasible.

_MASKS: Final[list[Mask]] = [
    # ── STEP_005 / M1 (mature node, high volume) ─────────────────────────
    Mask(mask_id="MSK-A2901", layer_name="M1", process_node="28nm", product_id="PROD-A1",
         usage_count=1248, defect_count=3,  min_cd_nm=90.5, status="active",
         last_clean_date=date(2026, 5, 30), station_id="STEP_005"),
    Mask(mask_id="MSK-A2902", layer_name="M1", process_node="28nm", product_id="PROD-A1",
         usage_count=956,  defect_count=1,  min_cd_nm=91.2, status="active",
         last_clean_date=date(2026, 5, 28), station_id="STEP_005"),
    Mask(mask_id="MSK-A2903", layer_name="M1", process_node="28nm", product_id="PROD-A2",
         usage_count=2310, defect_count=8,  min_cd_nm=89.8, status="cleaning",
         last_clean_date=date(2026, 6, 2),  station_id="STEP_005"),
    Mask(mask_id="MSK-B1450", layer_name="M1", process_node="22nm", product_id="PROD-B1",
         usage_count=540,  defect_count=0,  min_cd_nm=82.0, status="active",
         last_clean_date=date(2026, 5, 25), station_id="STEP_005"),
    Mask(mask_id="MSK-B1451", layer_name="M1", process_node="22nm", product_id="PROD-B1",
         usage_count=1820, defect_count=12, min_cd_nm=81.5, status="standby",
         last_clean_date=date(2026, 5, 10), station_id="STEP_005"),
    Mask(mask_id="MSK-B1452", layer_name="M1", process_node="22nm", product_id="PROD-B2",
         usage_count=3105, defect_count=18, min_cd_nm=80.8, status="scrapped",
         last_clean_date=date(2026, 4, 18), station_id="STEP_005"),
    Mask(mask_id="MSK-C0810", layer_name="M1", process_node="28nm", product_id="PROD-C1",
         usage_count=750,  defect_count=2,  min_cd_nm=90.0, status="active",
         last_clean_date=date(2026, 5, 31), station_id="STEP_005"),
    Mask(mask_id="MSK-C0811", layer_name="M1", process_node="28nm", product_id="PROD-C2",
         usage_count=420,  defect_count=0,  min_cd_nm=90.8, status="active",
         last_clean_date=date(2026, 6, 1),  station_id="STEP_005"),
    Mask(mask_id="MSK-C0812", layer_name="M1", process_node="28nm", product_id="PROD-C2",
         usage_count=1100, defect_count=5,  min_cd_nm=89.5, status="active",
         last_clean_date=date(2026, 5, 27), station_id="STEP_005"),
    Mask(mask_id="MSK-C0813", layer_name="M1", process_node="22nm", product_id="PROD-C3",
         usage_count=88,   defect_count=0,  min_cd_nm=82.5, status="standby",
         last_clean_date=date(2026, 5, 20), station_id="STEP_005"),

    # ── STEP_010 / M2 (14nm cohort) ──────────────────────────────────────
    Mask(mask_id="MSK-D3010", layer_name="M2", process_node="14nm", product_id="PROD-D1",
         usage_count=2680, defect_count=4,  min_cd_nm=48.0, status="active",
         last_clean_date=date(2026, 5, 29), station_id="STEP_010"),
    Mask(mask_id="MSK-D3011", layer_name="M2", process_node="14nm", product_id="PROD-D1",
         usage_count=1490, defect_count=2,  min_cd_nm=48.5, status="active",
         last_clean_date=date(2026, 6, 2),  station_id="STEP_010"),
    Mask(mask_id="MSK-D3012", layer_name="M2", process_node="14nm", product_id="PROD-D2",
         usage_count=910,  defect_count=1,  min_cd_nm=49.0, status="active",
         last_clean_date=date(2026, 5, 26), station_id="STEP_010"),
    Mask(mask_id="MSK-D3013", layer_name="M2", process_node="14nm", product_id="PROD-D2",
         usage_count=3520, defect_count=22, min_cd_nm=47.2, status="scrapped",
         last_clean_date=date(2026, 4, 30), station_id="STEP_010"),
    Mask(mask_id="MSK-E2200", layer_name="M2", process_node="14nm", product_id="PROD-E1",
         usage_count=602,  defect_count=0,  min_cd_nm=48.8, status="active",
         last_clean_date=date(2026, 6, 3),  station_id="STEP_010"),
    Mask(mask_id="MSK-E2201", layer_name="M2", process_node="14nm", product_id="PROD-E1",
         usage_count=1845, defect_count=6,  min_cd_nm=48.2, status="cleaning",
         last_clean_date=date(2026, 6, 4),  station_id="STEP_010"),
    Mask(mask_id="MSK-E2202", layer_name="M2", process_node="14nm", product_id="PROD-E2",
         usage_count=1230, defect_count=3,  min_cd_nm=48.5, status="active",
         last_clean_date=date(2026, 5, 30), station_id="STEP_010"),
    Mask(mask_id="MSK-E2203", layer_name="M2", process_node="14nm", product_id="PROD-E2",
         usage_count=270,  defect_count=0,  min_cd_nm=49.1, status="standby",
         last_clean_date=date(2026, 5, 22), station_id="STEP_010"),
    Mask(mask_id="MSK-E2204", layer_name="M2", process_node="14nm", product_id="PROD-E3",
         usage_count=2050, defect_count=9,  min_cd_nm=47.8, status="active",
         last_clean_date=date(2026, 5, 28), station_id="STEP_010"),
    Mask(mask_id="MSK-E2205", layer_name="M2", process_node="14nm", product_id="PROD-E3",
         usage_count=58,   defect_count=0,  min_cd_nm=49.3, status="active",
         last_clean_date=date(2026, 6, 3),  station_id="STEP_010"),

    # ── STEP_015 / M3 (7nm cohort) ───────────────────────────────────────
    Mask(mask_id="MSK-F1500", layer_name="M3", process_node="7nm",  product_id="PROD-F1",
         usage_count=820,  defect_count=2,  min_cd_nm=24.0, status="active",
         last_clean_date=date(2026, 5, 31), station_id="STEP_015"),
    Mask(mask_id="MSK-F1501", layer_name="M3", process_node="7nm",  product_id="PROD-F1",
         usage_count=1660, defect_count=5,  min_cd_nm=23.6, status="active",
         last_clean_date=date(2026, 5, 25), station_id="STEP_015"),
    Mask(mask_id="MSK-F1502", layer_name="M3", process_node="7nm",  product_id="PROD-F2",
         usage_count=2240, defect_count=14, min_cd_nm=23.2, status="cleaning",
         last_clean_date=date(2026, 6, 4),  station_id="STEP_015"),
    Mask(mask_id="MSK-G0900", layer_name="M3", process_node="7nm",  product_id="PROD-G1",
         usage_count=415,  defect_count=0,  min_cd_nm=24.2, status="active",
         last_clean_date=date(2026, 5, 30), station_id="STEP_015"),
    Mask(mask_id="MSK-G0901", layer_name="M3", process_node="7nm",  product_id="PROD-G1",
         usage_count=1078, defect_count=3,  min_cd_nm=23.8, status="active",
         last_clean_date=date(2026, 5, 28), station_id="STEP_015"),
    Mask(mask_id="MSK-G0902", layer_name="M3", process_node="7nm",  product_id="PROD-G2",
         usage_count=3110, defect_count=27, min_cd_nm=22.9, status="scrapped",
         last_clean_date=date(2026, 4, 20), station_id="STEP_015"),
    Mask(mask_id="MSK-G0903", layer_name="M3", process_node="7nm",  product_id="PROD-G2",
         usage_count=128,  defect_count=0,  min_cd_nm=24.5, status="standby",
         last_clean_date=date(2026, 5, 19), station_id="STEP_015"),
    Mask(mask_id="MSK-G0904", layer_name="M3", process_node="7nm",  product_id="PROD-G3",
         usage_count=905,  defect_count=2,  min_cd_nm=23.9, status="active",
         last_clean_date=date(2026, 5, 29), station_id="STEP_015"),
    Mask(mask_id="MSK-G0905", layer_name="M3", process_node="7nm",  product_id="PROD-G3",
         usage_count=2480, defect_count=11, min_cd_nm=23.4, status="active",
         last_clean_date=date(2026, 5, 26), station_id="STEP_015"),
    Mask(mask_id="MSK-G0906", layer_name="M3", process_node="7nm",  product_id="PROD-G4",
         usage_count=72,   defect_count=0,  min_cd_nm=24.6, status="active",
         last_clean_date=date(2026, 6, 2),  station_id="STEP_015"),

    # ── STEP_020 / M4 (5nm cohort, EUV) ──────────────────────────────────
    Mask(mask_id="MSK-H0501", layer_name="M4", process_node="5nm",  product_id="PROD-H1",
         usage_count=510,  defect_count=1,  min_cd_nm=18.0, status="active",
         last_clean_date=date(2026, 6, 1),  station_id="STEP_020"),
    Mask(mask_id="MSK-H0502", layer_name="M4", process_node="5nm",  product_id="PROD-H1",
         usage_count=1340, defect_count=6,  min_cd_nm=17.5, status="active",
         last_clean_date=date(2026, 5, 27), station_id="STEP_020"),
    Mask(mask_id="MSK-H0503", layer_name="M4", process_node="5nm",  product_id="PROD-H2",
         usage_count=1980, defect_count=13, min_cd_nm=17.2, status="cleaning",
         last_clean_date=date(2026, 6, 4),  station_id="STEP_020"),
    Mask(mask_id="MSK-J0301", layer_name="M4", process_node="5nm",  product_id="PROD-J1",
         usage_count=280,  defect_count=0,  min_cd_nm=18.3, status="active",
         last_clean_date=date(2026, 5, 31), station_id="STEP_020"),
    Mask(mask_id="MSK-J0302", layer_name="M4", process_node="5nm",  product_id="PROD-J1",
         usage_count=864,  defect_count=2,  min_cd_nm=17.9, status="active",
         last_clean_date=date(2026, 5, 29), station_id="STEP_020"),
    Mask(mask_id="MSK-J0303", layer_name="M4", process_node="5nm",  product_id="PROD-J2",
         usage_count=2620, defect_count=24, min_cd_nm=16.8, status="scrapped",
         last_clean_date=date(2026, 4, 15), station_id="STEP_020"),
    Mask(mask_id="MSK-J0304", layer_name="M4", process_node="5nm",  product_id="PROD-J2",
         usage_count=44,   defect_count=0,  min_cd_nm=18.5, status="standby",
         last_clean_date=date(2026, 5, 18), station_id="STEP_020"),
    Mask(mask_id="MSK-J0305", layer_name="M4", process_node="5nm",  product_id="PROD-J3",
         usage_count=1115, defect_count=4,  min_cd_nm=17.6, status="active",
         last_clean_date=date(2026, 5, 28), station_id="STEP_020"),
    Mask(mask_id="MSK-J0306", layer_name="M4", process_node="5nm",  product_id="PROD-J3",
         usage_count=2050, defect_count=10, min_cd_nm=17.3, status="active",
         last_clean_date=date(2026, 5, 26), station_id="STEP_020"),
    Mask(mask_id="MSK-J0307", layer_name="M4", process_node="5nm",  product_id="PROD-J4",
         usage_count=98,   defect_count=0,  min_cd_nm=18.4, status="active",
         last_clean_date=date(2026, 6, 3),  station_id="STEP_020"),
]


def _by_station(station_id: str) -> list[Mask]:
    return [m for m in _MASKS if m.station_id == station_id]


def _station_layer(station_id: str) -> Optional[str]:
    return next((s["layer_name"] for s in PHOTO_STATIONS if s["station_id"] == station_id), None)


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("/stations", response_model=list[StationListItem],
            summary="List photo stations that hold masks")
async def list_stations() -> list[StationListItem]:
    """Return the photo stations the simulator knows about (the ones whose
    step number is a multiple of 5 per ``_is_photo_step``)."""
    return [
        StationListItem(
            station_id=s["station_id"],
            layer_name=s["layer_name"],
            mask_count=len(_by_station(s["station_id"])),
        )
        for s in PHOTO_STATIONS
    ]


@router.get("/by-station", response_model=StationMasksResponse,
            summary="List masks at a given photo station")
async def masks_by_station(
    station_id: str = Query(..., description="Photo station id, e.g. STEP_005 / STEP_010 / STEP_015 / STEP_020"),
) -> StationMasksResponse:
    """Return all masks currently associated with the given photo station.

    Unknown station_id ⇒ 200 with mask_count=0, masks=[] (rather than 404)
    because LLM agents handle 200+empty more gracefully than 404 retries."""
    rows = _by_station(station_id)
    return StationMasksResponse(
        station_id=station_id,
        layer_name=_station_layer(station_id),
        mask_count=len(rows),
        masks=rows,
    )
