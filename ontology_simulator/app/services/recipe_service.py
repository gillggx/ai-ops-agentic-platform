"""Recipe Service — 10% version bump per process with parameter offset adjustment.

Each process has a 10% chance of triggering a recipe version bump, which:
  1. Increments recipe version (v1 → v2 → v3...)
  2. Adjusts 3 key params by ±offset (simulating recipe tuning)
  3. Persists the new version + params back to recipe_data collection

This creates "step function" patterns in recipe parameter trend charts —
mostly flat with occasional jumps, like real fab recipe revisions.
"""
import random
from app.database import get_db
from app.services import audit_service

VERSION_BUMP_PROBABILITY = 0.10

# Params that get adjusted on version bump, with max offset %
_BUMP_PARAMS = {
    "etch_time_s":   0.05,   # ±5%
    "source_power_w": 0.03,  # ±3%
    "bias_power_w":  0.03,   # ±3%
}


async def get_and_maybe_bump_params(recipe_id: str) -> dict:
    """Fetch recipe params; 10% chance of version bump with offset adjustment.

    Returns dict with {parameters, recipe_version, version_bumped}.
    """
    db = get_db()
    recipe = await db.recipe_data.find_one({"recipe_id": recipe_id}, {"_id": 0})
    if not recipe:
        return {"parameters": {}, "recipe_version": 1, "version_bumped": False}

    params = dict(recipe.get("parameters", {}))
    version = recipe.get("version", 1)
    bumped = False

    if random.random() < VERSION_BUMP_PROBABILITY:
        # Version bump: adjust key params
        version += 1
        bumped = True
        audit_changes: list[tuple[str, float, float]] = []
        for param_name, max_pct in _BUMP_PARAMS.items():
            if param_name in params:
                old_val = params[param_name]
                offset = old_val * random.uniform(-max_pct, max_pct)
                new_val = round(old_val + offset, 4)
                params[param_name] = new_val
                audit_changes.append((param_name, old_val, new_val))

        # Persist new version + params
        await db.recipe_data.update_one(
            {"recipe_id": recipe_id},
            {"$set": {"parameters": params, "version": version}},
        )

        # Phase 12: audit log the bump
        if audit_changes:
            await audit_service.record_changes(
                object_name="RECIPE",
                object_id=recipe_id,
                changes=audit_changes,
                source="recipe_version_bump",
                reason=f"auto version bump v{version - 1} → v{version}",
                metadata={"new_version": version, "prev_version": version - 1},
            )

    return {
        "parameters": params,
        "recipe_version": version,
        "version_bumped": bumped,
    }


async def upload_snapshot_from_params(
    recipe_id: str,
    parameters: dict,
    context: dict,
    recipe_version: int = 1,
) -> str:
    """Write Recipe snapshot with unified eventTime. Returns inserted _id."""
    db = get_db()
    snapshot = {
        "eventTime":        context["eventTime"],
        "lotID":            context["lotID"],
        "toolID":           context["toolID"],
        "step":             context["step"],
        "objectName":       "RECIPE",
        "objectID":         recipe_id,
        "recipe_version":   recipe_version,
        "parameters":       parameters,
        "last_updated_time": context["eventTime"],
        "updated_by":       "recipe_service",
    }
    result = await db.object_snapshots.insert_one(snapshot)
    return str(result.inserted_id)
