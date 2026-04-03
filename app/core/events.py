"""
Event system for domain-driven architecture.

用于域驱动架构的事件系统。
"""

from typing import Optional, Dict, List, Callable, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import logging
import asyncio

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """
    Types of events in the system.
    
    系统中的事件类型。
    """

    # User events
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    USER_LOGGED_IN = "user.logged_in"
    USER_LOGGED_OUT = "user.logged_out"

    # Agent events
    AGENT_CREATED = "agent.created"
    AGENT_STARTED = "agent.started"
    AGENT_STOPPED = "agent.stopped"
    AGENT_FAILED = "agent.failed"

    # Data events
    DATA_IMPORTED = "data.imported"
    DATA_PROCESSED = "data.processed"
    DATA_EXPORTED = "data.exported"

    # System events
    SYSTEM_INITIALIZED = "system.initialized"
    SYSTEM_ERROR = "system.error"
    HEALTH_CHECK = "health.check"


class EventPriority(int, Enum):
    """
    Event priority levels.
    
    事件优先级。
    """

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Event:
    """
    Domain event.
    
    域事件。
    """

    event_type: EventType
    aggregate_id: str
    data: Dict[str, Any]
    priority: EventPriority = EventPriority.NORMAL
    timestamp: Optional[datetime] = None
    correlation_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Initialize event."""
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert event to dictionary.
        
        Returns:
            Event as dictionary
        
        将事件转换为字典。
        """
        return {
            "event_type": self.event_type.value,
            "aggregate_id": self.aggregate_id,
            "data": self.data,
            "priority": self.priority.value,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata
        }


class EventHandler:
    """
    Base event handler.
    
    基础事件处理程序。
    """

    def __init__(self, event_types: List[EventType]):
        """
        Initialize event handler.
        
        Args:
            event_types: List of event types to handle
        
        初始化事件处理程序。
        """
        self.event_types = event_types

    def can_handle(self, event: Event) -> bool:
        """
        Check if handler can handle event.
        
        Args:
            event: Event to check
        
        Returns:
            True if can handle, False otherwise
        
        检查处理程序是否可以处理事件。
        """
        return event.event_type in self.event_types

    async def handle(self, event: Event) -> None:
        """
        Handle event.
        
        Args:
            event: Event to handle
        
        处理事件。
        """
        raise NotImplementedError


class EventBus:
    """
    In-process event bus for domain events.
    
    用于域事件的进程内事件总线。
    """

    def __init__(self):
        """Initialize event bus."""
        self.handlers: Dict[EventType, List[EventHandler]] = {}
        self.event_history: List[Event] = []
        self.subscribers: Dict[EventType, List[Callable]] = {}

    def register_handler(
        self,
        handler: EventHandler
    ) -> None:
        """
        Register event handler.
        
        Args:
            handler: Event handler to register
        
        注册事件处理程序。
        """
        for event_type in handler.event_types:
            if event_type not in self.handlers:
                self.handlers[event_type] = []
            self.handlers[event_type].append(handler)

    def subscribe(
        self,
        event_type: EventType,
        callback: Callable
    ) -> None:
        """
        Subscribe to event.
        
        Args:
            event_type: Event type to subscribe to
            callback: Callback function
        
        订阅事件。
        """
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)

    async def publish(self, event: Event) -> None:
        """
        Publish event.
        
        Args:
            event: Event to publish
        
        发送事件。
        """
        # Add to history
        self.event_history.append(event)

        # Call handlers
        handlers = self.handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                if handler.can_handle(event):
                    await handler.handle(event)
            except Exception as e:
                logger.error(f"Error in event handler: {e}")

        # Call subscribers
        subscribers = self.subscribers.get(event.event_type, [])
        for subscriber in subscribers:
            try:
                if asyncio.iscoroutinefunction(subscriber):
                    await subscriber(event)
                else:
                    subscriber(event)
            except Exception as e:
                logger.error(f"Error in event subscriber: {e}")

    def get_events(
        self,
        aggregate_id: Optional[str] = None,
        event_type: Optional[EventType] = None
    ) -> List[Event]:
        """
        Get events from history.
        
        Args:
            aggregate_id: Filter by aggregate ID
            event_type: Filter by event type
        
        Returns:
            List of matching events
        
        从历史记录获取事件。
        """
        result = self.event_history

        if aggregate_id:
            result = [e for e in result if e.aggregate_id == aggregate_id]

        if event_type:
            result = [e for e in result if e.event_type == event_type]

        return result

    def clear_history(self) -> None:
        """Clear event history."""
        self.event_history.clear()


class EventSourcing:
    """
    Event sourcing for aggregate state reconstruction.
    
    用于聚合状态重建的事件溯源。
    """

    def __init__(self, event_bus: EventBus):
        """
        Initialize event sourcing.
        
        Args:
            event_bus: Event bus instance
        
        初始化事件溯源。
        """
        self.event_bus = event_bus
        self.snapshots: Dict[str, Any] = {}
        self.snapshot_interval: int = 100

    async def reconstruct_state(
        self,
        aggregate_id: str,
        event_type: Optional[EventType] = None
    ) -> Dict[str, Any]:
        """
        Reconstruct aggregate state from events.
        
        Args:
            aggregate_id: Aggregate ID
            event_type: Filter by event type
        
        Returns:
            Reconstructed state
        
        从事件重建聚合状态。
        """
        # Check for snapshot
        if aggregate_id in self.snapshots:
            state = self.snapshots[aggregate_id].copy()
        else:
            state = {}

        # Apply events
        events = self.event_bus.get_events(aggregate_id, event_type)
        for event in events:
            state = await self._apply_event(state, event)

        return state

    async def _apply_event(
        self,
        state: Dict[str, Any],
        event: Event
    ) -> Dict[str, Any]:
        """
        Apply event to state.
        
        Args:
            state: Current state
            event: Event to apply
        
        Returns:
            Updated state
        
        将事件应用于状态。
        """
        # Generic event application
        state[f"event_{event.event_type.value}"] = event.data
        state["last_updated"] = event.timestamp

        return state

    def create_snapshot(
        self,
        aggregate_id: str,
        state: Dict[str, Any]
    ) -> None:
        """
        Create state snapshot.
        
        Args:
            aggregate_id: Aggregate ID
            state: State to snapshot
        
        创建状态快照。
        """
        self.snapshots[aggregate_id] = state.copy()


class AuditLogger:
    """
    Audit logging using events.
    
    使用事件的审计日志记录。
    """

    def __init__(self, event_bus: EventBus):
        """
        Initialize audit logger.
        
        Args:
            event_bus: Event bus instance
        
        初始化审计记录器。
        """
        self.event_bus = event_bus
        self.audit_entries: List[Dict[str, Any]] = []

    async def log_action(
        self,
        action: str,
        user_id: str,
        resource_id: str,
        resource_type: str,
        changes: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log audit action.
        
        Args:
            action: Action performed
            user_id: User performing action
            resource_id: Resource ID
            resource_type: Type of resource
            changes: Changes made
        
        记录审计操作。
        """
        entry = {
            "action": action,
            "user_id": user_id,
            "resource_id": resource_id,
            "resource_type": resource_type,
            "changes": changes or {},
            "timestamp": datetime.utcnow().isoformat()
        }

        self.audit_entries.append(entry)

        # Also publish as event
        event = Event(
            event_type=EventType.SYSTEM_INITIALIZED,  # Or specific audit event
            aggregate_id=resource_id,
            data=entry,
            priority=EventPriority.HIGH
        )
        await self.event_bus.publish(event)

    def get_audit_trail(
        self,
        resource_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get audit trail.
        
        Args:
            resource_id: Filter by resource ID
            user_id: Filter by user ID
        
        Returns:
            Audit entries
        
        获取审计跟踪。
        """
        result = self.audit_entries

        if resource_id:
            result = [e for e in result if e["resource_id"] == resource_id]

        if user_id:
            result = [e for e in result if e["user_id"] == user_id]

        return result


# Global event bus instance
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """
    Get global event bus.
    
    Returns:
        Event bus instance
    
    获取全局事件总线。
    """
    global _event_bus
    if not _event_bus:
        _event_bus = EventBus()
    return _event_bus


def initialize_event_bus() -> EventBus:
    """
    Initialize global event bus.
    
    Returns:
        Initialized event bus
    
    初始化全局事件总线。
    """
    global _event_bus
    _event_bus = EventBus()
    return _event_bus
