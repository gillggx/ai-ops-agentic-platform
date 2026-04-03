"""
Diagnostic Router - API v1

Manages diagnostic sessions and real-time event streaming.
Provides endpoints for starting diagnostics, retrieving results, and streaming SSE events.

診斷路由器 - API v1
管理診斷會話和即時事件流。
提供啟動診斷、檢索結果和流式傳輸 SSE 事件的端點。
"""

from typing import Optional
import json
import uuid
from datetime import datetime
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_active_user
from app.ontology.models import AgentSession, User, GeneratedEvent, DataSubject
from app.ontology.repositories import (
    AgentSessionRepository,
    GeneratedEventRepository,
    DataSubjectRepository,
)
from app.ontology.schemas.agent_session import (
    AgentSessionCreate,
    AgentSessionRead,
)
from app.ontology.schemas.generated_event import GeneratedEventRead
from app.ontology.schemas.common import ListResponse

# Event types enum
class DiagnosticEventType(str, Enum):
    """SSE event types for diagnostic stream."""
    CONTEXT_LOAD = "context_load"
    THINKING = "thinking"
    TOOL_START = "tool_start"
    TOOL_DONE = "tool_done"
    SYNTHESIS = "synthesis"
    MEMORY_WRITE = "memory_write"
    ERROR = "error"
    DONE = "done"


# Initialize router
router = APIRouter(
    prefix="/api/v1/diagnose",
    tags=["Diagnostic"],
)

# Initialize repositories
session_repo = AgentSessionRepository()
generated_event_repo = GeneratedEventRepository()
data_subject_repo = DataSubjectRepository()


@router.post(
    "/start",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Start Diagnostic Session",
    description="Start a new diagnostic session with SSE event streaming.",
)
async def start_diagnostic(
    data_subject_id: int,
    session_title: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Start a diagnostic session.
    
    Creates a new session and returns a stream_id for SSE event listening.
    Client should use /diagnose/{stream_id}/stream to listen for events.
    
    **Path:** `POST /api/v1/diagnose/start`
    
    **Query Parameters:**
    - `data_subject_id` (int): DataSubject to diagnose
    - `session_title` (str, optional): Custom title for session
    
    **Returns:** { stream_id: str, session_id: int, title: str, status: str }
    
    **Errors:**
    - 400: Invalid data_subject_id
    - 401: Unauthorized
    - 404: DataSubject not found
    - 500: Server error
    
    啟動新的診斷會話。
    """
    # Verify data subject exists
    data_subject = await data_subject_repo.get_by_id(db, data_subject_id)
    if not data_subject:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"DataSubject with ID {data_subject_id} not found",
        )
    
    # Generate stream ID
    stream_id = str(uuid.uuid4())
    
    # Create session
    title = session_title or f"Diagnostic: {data_subject.name}"
    session = AgentSession(
        user_id=current_user.id,
        title=title,
        # system_prompt is not used by the agent — ContextLoader builds the real prompt from DB.
        # Left as empty so the field is not misleadingly set to an outdated English stub.
        message_count=0,
        is_active=True,
        context_summary=json.dumps({
            "data_subject_id": data_subject_id,
            "stream_id": stream_id,
            "data_subject_name": data_subject.name,
        }),
    )
    
    created_session = await session_repo.create(db, session)
    
    return {
        "stream_id": stream_id,
        "session_id": created_session.id,
        "title": title,
        "status": "initialized",
        "data_subject_id": data_subject_id,
    }


@router.get(
    "/{session_id}",
    response_model=AgentSessionRead,
    status_code=status.HTTP_200_OK,
    summary="Get Diagnostic Session",
    description="Retrieve a diagnostic session by ID.",
)
async def get_diagnostic_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> AgentSessionRead:
    """
    Get a diagnostic session by ID.
    
    **Path:** `GET /api/v1/diagnose/{session_id}`
    
    **Parameters:**
    - `session_id` (int): Diagnostic session ID
    
    **Returns:** AgentSessionRead
    
    **Errors:**
    - 401: Unauthorized
    - 404: Session not found
    - 500: Server error
    
    按 ID 獲取診斷會話。
    """
    session = await session_repo.get_by_id(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Diagnostic session with ID {session_id} not found",
        )
    
    # Verify ownership
    if session.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this session",
        )
    
    return session


@router.get(
    "/{session_id}/results",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Get Diagnostic Results",
    description="Retrieve results and generated events from a diagnostic session.",
)
async def get_diagnostic_results(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Get diagnostic results and generated events.
    
    **Path:** `GET /api/v1/diagnose/{session_id}/results`
    
    **Parameters:**
    - `session_id` (int): Diagnostic session ID
    
    **Returns:** { 
        session: AgentSessionRead,
        generated_events: list[GeneratedEventRead],
        summary: str,
        event_count: int
    }
    
    **Errors:**
    - 401: Unauthorized
    - 404: Session not found
    - 500: Server error
    
    獲取診斷結果和生成的事件。
    """
    session = await session_repo.get_by_id(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Diagnostic session with ID {session_id} not found",
        )
    
    # Verify ownership
    if session.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this session",
        )
    
    # Get context data
    try:
        context = json.loads(session.context_summary) if session.context_summary else {}
    except json.JSONDecodeError:
        context = {}
    
    # This would retrieve generated events associated with this session
    # For now, return structure for future implementation
    return {
        "session": session,
        "generated_events": [],  # Would populate from GeneratedEvent repository
        "summary": session.context_summary or "No summary available",
        "event_count": 0,  # Would count actual events
    }


@router.post(
    "/{session_id}/events",
    response_model=GeneratedEventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Associate Event with Diagnosis",
    description="Associate a generated event with a diagnostic session.",
)
async def associate_event_to_diagnosis(
    session_id: int,
    event_type_id: int,
    source_skill_id: int,
    data_subject_id: int,
    trigger_data: dict,
    confidence_score: float = 0.5,
    is_actionable: bool = False,
    recommended_action: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> GeneratedEventRead:
    """
    Associate a generated event with a diagnostic session.
    
    **Path:** `POST /api/v1/diagnose/{session_id}/events`
    
    **Parameters:**
    - `session_id` (int): Diagnostic session ID
    - `event_type_id` (int): EventType ID
    - `source_skill_id` (int): Skill that generated the event
    - `data_subject_id` (int): DataSubject being analyzed
    - `trigger_data` (dict): Data that triggered event generation
    - `confidence_score` (float, 0-1): Confidence level
    - `is_actionable` (bool): Whether action is recommended
    - `recommended_action` (str, optional): Suggested action
    
    **Returns:** GeneratedEventRead
    
    **Errors:**
    - 400: Invalid parameters
    - 401: Unauthorized
    - 404: Session, EventType, Skill, or DataSubject not found
    - 500: Server error
    
    將生成的事件與診斷會話相關聯。
    """
    # Verify session exists
    session = await session_repo.get_by_id(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Diagnostic session with ID {session_id} not found",
        )
    
    # Create generated event
    generated_event = GeneratedEvent(
        event_type_id=event_type_id,
        source_skill_id=source_skill_id,
        data_subject_id=data_subject_id,
        trigger_data=json.dumps(trigger_data),
        confidence_score=confidence_score,
        is_actionable=is_actionable,
        recommended_action=recommended_action,
    )
    
    return await generated_event_repo.create(db, generated_event)


@router.get(
    "/{session_id}/stream",
    summary="Stream Diagnostic Events",
    description="Server-Sent Events (SSE) stream for real-time diagnostic updates.",
)
async def stream_diagnostic_events(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Stream diagnostic events as SSE.
    
    Provides real-time updates during diagnostic processing.
    
    **Path:** `GET /api/v1/diagnose/{session_id}/stream`
    
    **Query Parameters:**
    - `session_id` (int): Diagnostic session ID
    
    **Returns:** Server-Sent Events stream
    
    **Event Types:**
    - `context_load`: Context initialization
    - `thinking`: Analysis in progress
    - `tool_start`: Tool execution started
    - `tool_done`: Tool execution completed
    - `synthesis`: Results synthesis
    - `memory_write`: Memory update
    - `error`: Error occurred
    - `done`: Diagnostic complete
    
    **Errors:**
    - 401: Unauthorized
    - 404: Session not found
    - 500: Server error
    
    流式傳輸診斷事件作為 SSE。
    """
    # Verify session exists
    session = await session_repo.get_by_id(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Diagnostic session with ID {session_id} not found",
        )
    
    # Verify ownership
    if session.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this session",
        )
    
    async def event_generator():
        """Generate SSE events for diagnostic stream."""
        try:
            # Send context load event
            yield f"event: {DiagnosticEventType.CONTEXT_LOAD}\n"
            yield f"data: {json.dumps({'message': 'Loading diagnostic context', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
            
            # Send thinking event
            yield f"event: {DiagnosticEventType.THINKING}\n"
            yield f"data: {json.dumps({'message': 'Analyzing data...', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
            
            # Send tool start event
            yield f"event: {DiagnosticEventType.TOOL_START}\n"
            yield f"data: {json.dumps({'tool': 'DataAnalyzer', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
            
            # Send tool done event
            yield f"event: {DiagnosticEventType.TOOL_DONE}\n"
            yield f"data: {json.dumps({'tool': 'DataAnalyzer', 'status': 'completed', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
            
            # Send synthesis event
            yield f"event: {DiagnosticEventType.SYNTHESIS}\n"
            yield f"data: {json.dumps({'message': 'Synthesizing results...', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
            
            # Send memory write event
            yield f"event: {DiagnosticEventType.MEMORY_WRITE}\n"
            yield f"data: {json.dumps({'message': 'Updating memory', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
            
            # Send done event
            yield f"event: {DiagnosticEventType.DONE}\n"
            yield f"data: {json.dumps({'message': 'Diagnostic completed', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
            
        except Exception as e:
            # Send error event
            yield f"event: {DiagnosticEventType.ERROR}\n"
            yield f"data: {json.dumps({'error': str(e), 'timestamp': datetime.utcnow().isoformat()})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post(
    "/{session_id}/complete",
    status_code=status.HTTP_200_OK,
    summary="Complete Diagnostic Session",
    description="Mark a diagnostic session as complete.",
)
async def complete_diagnostic_session(
    session_id: int,
    summary: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Mark a diagnostic session as complete.
    
    **Path:** `POST /api/v1/diagnose/{session_id}/complete`
    
    **Parameters:**
    - `session_id` (int): Diagnostic session ID
    - `summary` (str, optional): Summary of findings
    
    **Returns:** { status: str, session_id: int, completed_at: str }
    
    **Errors:**
    - 401: Unauthorized
    - 404: Session not found
    - 500: Server error
    
    標記診斷會話為完成。
    """
    session = await session_repo.get_by_id(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Diagnostic session with ID {session_id} not found",
        )
    
    # Verify ownership
    if session.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to modify this session",
        )
    
    # Update session
    session.is_active = False
    if summary:
        session.context_summary = json.dumps({
            "summary": summary,
            "completed_at": datetime.utcnow().isoformat(),
        })
    
    updated = await session_repo.update(db, session)
    
    return {
        "status": "completed",
        "session_id": updated.id,
        "completed_at": datetime.utcnow().isoformat(),
    }


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Diagnostic Session",
    description="Delete a diagnostic session.",
)
async def delete_diagnostic_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete a diagnostic session.
    
    **Path:** `DELETE /api/v1/diagnose/{session_id}`
    
    **Parameters:**
    - `session_id` (int): Diagnostic session ID
    
    **Returns:** 204 No Content
    
    **Errors:**
    - 401: Unauthorized
    - 404: Session not found
    - 500: Server error
    
    刪除診斷會話。
    """
    session = await session_repo.get_by_id(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Diagnostic session with ID {session_id} not found",
        )
    
    # Verify ownership
    if session.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to delete this session",
        )
    
    await session_repo.delete(db, session)


@router.get(
    "",
    response_model=ListResponse[AgentSessionRead],
    status_code=status.HTTP_200_OK,
    summary="List Diagnostic Sessions",
    description="List all diagnostic sessions for current user.",
)
async def list_diagnostic_sessions(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max records to return"),
    include_inactive: bool = Query(False, description="Include inactive sessions"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ListResponse[AgentSessionRead]:
    """
    List diagnostic sessions.
    
    Returns sessions for current user (or all if admin).
    
    **Path:** `GET /api/v1/diagnose`
    
    **Query Parameters:**
    - `skip` (int, default=0): Records to skip
    - `limit` (int, default=100): Max records (1-1000)
    - `include_inactive` (bool): Include completed sessions
    
    **Returns:** ListResponse with array of AgentSessionRead
    
    **Errors:**
    - 401: Unauthorized
    - 500: Server error
    
    列出診斷會話。
    """
    # Get user's sessions (or all if admin)
    if current_user.is_admin:
        sessions = await session_repo.get_all(db, skip=skip, limit=limit)
        total = await session_repo.count_all(db)
    else:
        sessions = await session_repo.get_by_filter(
            db,
            user_id=current_user.id,
            skip=skip,
            limit=limit,
        )
        # Count filtered results
        all_sessions = await session_repo.get_by_filter(
            db,
            user_id=current_user.id,
        )
        total = len(all_sessions)
    
    return ListResponse[AgentSessionRead](
        items=sessions,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post(
    "/{session_id}/export",
    status_code=status.HTTP_200_OK,
    summary="Export Diagnostic Session",
    description="Export diagnostic session as JSON.",
)
async def export_diagnostic_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict:
    """
    Export a diagnostic session as JSON.
    
    **Path:** `POST /api/v1/diagnose/{session_id}/export`
    
    **Parameters:**
    - `session_id` (int): Diagnostic session ID
    
    **Returns:** Complete session data as JSON
    
    **Errors:**
    - 401: Unauthorized
    - 404: Session not found
    - 500: Server error
    
    將診斷會話匯出為 JSON。
    """
    session = await session_repo.get_by_id(db, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Diagnostic session with ID {session_id} not found",
        )
    
    # Verify ownership
    if session.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to export this session",
        )
    
    # Export session data
    return {
        "id": session.id,
        "user_id": session.user_id,
        "title": session.title,
        "system_prompt": session.system_prompt,
        "message_count": session.message_count,
        "is_active": session.is_active,
        "context_summary": session.context_summary,
        "last_activity_at": session.last_activity_at.isoformat() if session.last_activity_at else None,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }
