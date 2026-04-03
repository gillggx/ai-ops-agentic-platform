"""Generated Events Router — aligned with actual DB schema."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_active_user
from app.core.response import StandardResponse
from app.ontology.models import User
from app.ontology.models.generated_event import GeneratedEvent
from app.ontology.schemas.generated_event import GeneratedEventCreate, GeneratedEventRead, GeneratedEventStatusUpdate
from sqlalchemy import select

router = APIRouter(prefix="/api/v1/generated-events", tags=["Generated Event"])


@router.get("", response_model=StandardResponse, summary="List Generated Events")
async def list_generated_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    result = await db.execute(select(GeneratedEvent).order_by(GeneratedEvent.created_at.desc()).offset(skip).limit(limit))
    items = result.scalars().all()
    return StandardResponse.success(data=[GeneratedEventRead.model_validate(i).model_dump() for i in items])


@router.post("", response_model=StandardResponse, status_code=201, summary="Create Generated Event")
async def create_generated_event(
    body: GeneratedEventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    obj = GeneratedEvent(**body.model_dump())
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await db.commit()
    return StandardResponse.success(data=GeneratedEventRead.model_validate(obj).model_dump())


@router.get("/{event_id}", response_model=StandardResponse, summary="Get Generated Event")
async def get_generated_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    result = await db.execute(select(GeneratedEvent).where(GeneratedEvent.id == event_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Generated event not found")
    return StandardResponse.success(data=GeneratedEventRead.model_validate(obj).model_dump())


@router.patch("/{event_id}/status", response_model=StandardResponse, summary="Update Event Status")
async def update_event_status(
    event_id: int,
    body: GeneratedEventStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    result = await db.execute(select(GeneratedEvent).where(GeneratedEvent.id == event_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Generated event not found")
    obj.status = body.status
    await db.flush()
    await db.commit()
    return StandardResponse.success(data=GeneratedEventRead.model_validate(obj).model_dump())


@router.delete("/{event_id}", response_model=StandardResponse, summary="Delete Generated Event")
async def delete_generated_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    result = await db.execute(select(GeneratedEvent).where(GeneratedEvent.id == event_id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Generated event not found")
    await db.delete(obj)
    await db.commit()
    return StandardResponse.success(data={"deleted_id": event_id})
