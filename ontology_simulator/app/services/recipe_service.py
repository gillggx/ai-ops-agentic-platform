"""Recipe Service – stable master data, snapshot per event."""
from app.database import get_db


async def get_params(recipe_id: str) -> dict:
    """Fetch recipe parameters (no snapshot write)."""
    db = get_db()
    recipe = await db.recipe_data.find_one({"recipe_id": recipe_id}, {"_id": 0})
    return recipe.get("parameters", {}) if recipe else {}


async def upload_snapshot_from_params(recipe_id: str, parameters: dict, context: dict) -> str:
    """Write Recipe snapshot with unified eventTime. Returns inserted _id."""
    db = get_db()
    snapshot = {
        "eventTime":        context["eventTime"],
        "lotID":            context["lotID"],
        "toolID":           context["toolID"],
        "step":             context["step"],
        "objectName":       "RECIPE",
        "objectID":         recipe_id,
        "parameters":       parameters,
        "last_updated_time": context["eventTime"],
        "updated_by":       "recipe_service",
    }
    result = await db.object_snapshots.insert_one(snapshot)
    return str(result.inserted_id)


# Keep backward compat
async def upload_snapshot(recipe_id: str, context: dict) -> str:
    """Legacy: fetch + write in one call."""
    params = await get_params(recipe_id)
    return await upload_snapshot_from_params(recipe_id, params, context)
