"""Event Management Router - API v1 (10 endpoints)"""

from typing import Optional
import json
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_active_user
from app.ontology.models import Event, EventType, User
from app.ontology.repositories import EventRepository, EventTypeRepository
from app.ontology.schemas.event import EventCreate, EventRead
from app.ontology.schemas.common import ListResponse

router = APIRouter(prefix="/api/v1/events", tags=["Event"])

event_repo = EventRepository()
event_type_repo = EventTypeRepository()

# In-memory event history
event_history: dict = {}


@router.post("", response_model=EventRead, status_code=status.HTTP_201_CREATED, summary="Create Event")
async def create_event(
    event_type_id: int,
    source: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EventRead:
    """Create new event."""
    event_type = await event_type_repo.get_by_id(db, event_type_id)
    if not event_type:
        raise HTTPException(status_code=404, detail="EventType not found")
    
    event = Event(
        event_type_id=event_type_id,
        source=source,
        data=json.dumps(data),
        processed=False,
    )
    return await event_repo.create(db, event)


@router.get("", response_model=ListResponse[EventRead], summary="List Events")
async def list_events(
    processed_only: bool = False,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[EventRead]:
    """List events with pagination."""
    events = await event_repo.get_all(db, skip=skip, limit=limit)
    if processed_only:
        events = [e for e in events if e.processed]
    
    total = await event_repo.count_all(db)
    return ListResponse(items=events, total=total, skip=skip, limit=limit)


@router.get("/{event_id}", response_model=EventRead, summary="Get Event")
async def get_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> EventRead:
    """Get specific event."""
    event = await event_repo.get_by_id(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("/{event_id}/process", summary="Process Event")
async def process_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Mark event as processed."""
    event = await event_repo.get_by_id(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    event.processed = True
    await event_repo.update(db, event)
    
    return {"event_id": event_id, "processed": True}


@router.post("/{event_id}/revert", summary="Revert Event Processing")
async def revert_processing(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Mark event as unprocessed."""
    event = await event_repo.get_by_id(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    
    event.processed = False
    await event_repo.update(db, event)
    return {"event_id": event_id, "processed": False}


@router.delete("/{event_id}", status_code=204, summary="Delete Event")
async def delete_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Delete event."""
    event = await event_repo.get_by_id(db, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    await event_repo.delete(db, event)


@router.get("/type/{event_type_id}", response_model=ListResponse[EventRead], summary="Events by Type")
async def get_events_by_type(
    event_type_id: int,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[EventRead]:
    """Get events of a specific type."""
    events = await event_repo.get_by_filter(db, event_type_id=event_type_id)
    total = len(events)
    paginated = events[skip:skip+limit]
    return ListResponse(items=paginated, total=total, skip=skip, limit=limit)


@router.post("/batch-process", summary="Batch Process Events")
async def batch_process_events(
    filter_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Process all unprocessed events."""
    events = await event_repo.get_all(db)
    unprocessed = [e for e in events if not e.processed]
    
    for event in unprocessed:
        event.processed = True
        await event_repo.update(db, event)
    
    return {"processed_count": len(unprocessed)}


@router.get("/source/{source}", response_model=ListResponse[EventRead], summary="Events by Source")
async def get_events_by_source(
    source: str,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[EventRead]:
    """Get events from specific source."""
    events = await event_repo.get_by_filter(db, source=source)
    total = len(events)
    paginated = events[skip:skip+limit]
    return ListResponse(items=paginated, total=total, skip=skip, limit=limit)


@router.post("/bulk-delete", summary="Bulk Delete Events")
async def bulk_delete_events(
    older_than_days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """Delete old processed events."""
    from datetime import timedelta
    
    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    events = await event_repo.get_all(db)
    deleted = 0
    
    for event in events:
        if event.processed and event.created_at and event.created_at < cutoff:
            await event_repo.delete(db, event)
            deleted += 1
    
    return {"deleted_count": deleted}
