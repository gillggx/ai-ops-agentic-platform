"""Recipe Service – stable master data, snapshot per event."""
from app.database import get_db


async def upload_snapshot(recipe_id: str, context: dict) -> str:
    """Store a Recipe snapshot and return its inserted _id as string."""
    db = get_db()
    recipe = await db.recipe_data.find_one({"recipe_id": recipe_id}, {"_id": 0})

    snapshot = {
        "eventTime":        context["eventTime"],
        "status":           context.get("status", "ProcessStart"),
        "lotID":            context["lotID"],
        "toolID":           context["toolID"],
        "step":             context["step"],
        "objectName":       "RECIPE",
        "objectID":         recipe_id,
        "parameters":       recipe["parameters"],   # 20 params, stable master data
        "last_updated_time": context["eventTime"],
        "updated_by":       "recipe_service",
    }
    result = await db.object_snapshots.insert_one(snapshot)
    return str(result.inserted_id)
