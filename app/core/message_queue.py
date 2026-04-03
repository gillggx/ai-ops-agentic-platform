"""
Message queue integration with RabbitMQ/Celery.

带有 RabbitMQ/Celery 的消息队列集成。
"""

from abc import ABC, abstractmethod
from typing import Optional, Any, Dict, Callable
import logging
import json
from datetime import datetime
import asyncio

try:
    import aio_pika
except ImportError:
    aio_pika = None

logger = logging.getLogger(__name__)


class Message:
    """
    Message wrapper for queue operations.
    
    消息队列操作的消息包装器。
    """

    def __init__(
        self,
        body: Dict[str, Any],
        message_type: str,
        priority: int = 0,
        retry_count: int = 0,
        metadata: Optional[Dict] = None
    ):
        """
        Initialize message.
        
        Args:
            body: Message body
            message_type: Type of message
            priority: Message priority (0-10)
            retry_count: Number of retries
            metadata: Additional metadata
        
        初始化消息。
        """
        self.id = datetime.utcnow().isoformat()
        self.body = body
        self.message_type = message_type
        self.priority = priority
        self.retry_count = retry_count
        self.metadata = metadata or {}
        self.created_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert message to dictionary.
        
        Returns:
            Message as dictionary
        
        将消息转换为字典。
        """
        return {
            "id": self.id,
            "body": self.body,
            "type": self.message_type,
            "priority": self.priority,
            "retry_count": self.retry_count,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat()
        }

    def to_json(self) -> str:
        """
        Convert message to JSON string.
        
        Returns:
            Message as JSON string
        
        将消息转换为 JSON 字符串。
        """
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, json_str: str) -> 'Message':
        """
        Create message from JSON string.
        
        Args:
            json_str: JSON string
        
        Returns:
            Message instance
        
        从 JSON 字符串创建消息。
        """
        data = json.loads(json_str)
        return cls(
            body=data["body"],
            message_type=data["type"],
            priority=data.get("priority", 0),
            retry_count=data.get("retry_count", 0),
            metadata=data.get("metadata", {})
        )


class MessageQueue(ABC):
    """
    Abstract base class for message queue implementations.
    
    消息队列实现的抽象基类。
    """

    @abstractmethod
    async def connect(self) -> None:
        """
        Connect to message queue.
        
        连接到消息队列。
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Disconnect from message queue.
        
        从消息队列断开连接。
        """
        pass

    @abstractmethod
    async def publish(
        self,
        queue: str,
        message: Message
    ) -> None:
        """
        Publish message to queue.
        
        Args:
            queue: Queue name
            message: Message to publish
        
        将消息发送到队列。
        """
        pass

    @abstractmethod
    async def subscribe(
        self,
        queue: str,
        callback: Callable
    ) -> None:
        """
        Subscribe to queue messages.
        
        Args:
            queue: Queue name
            callback: Callback function for messages
        
        订阅队列消息。
        """
        pass

    @abstractmethod
    async def acknowledge(self, message_id: str) -> None:
        """
        Acknowledge message processing.
        
        Args:
            message_id: Message ID
        
        确认消息处理。
        """
        pass


class RabbitMQQueue(MessageQueue):
    """
    RabbitMQ message queue implementation.
    
    RabbitMQ 消息队列实现。
    """

    def __init__(
        self,
        url: str = "amqp://guest:guest@localhost/",
        prefetch_count: int = 10
    ):
        """
        Initialize RabbitMQ queue.
        
        Args:
            url: RabbitMQ connection URL
            prefetch_count: Prefetch count for consumers
        
        初始化 RabbitMQ 队列。
        """
        self.url = url
        self.prefetch_count = prefetch_count
        self.connection = None
        self.channel = None
        self.exchanges: Dict[str, Any] = {}
        self.queues: Dict[str, Any] = {}

    async def connect(self) -> None:
        """
        Connect to RabbitMQ.
        
        连接到 RabbitMQ。
        """
        if not aio_pika:
            raise ImportError("aio_pika is not installed")

        try:
            self.connection = await aio_pika.connect_robust(self.url)
            self.channel = await self.connection.channel()
            await self.channel.set_qos(prefetch_count=self.prefetch_count)
            logger.info(f"Connected to RabbitMQ at {self.url}")
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise

    async def disconnect(self) -> None:
        """
        Disconnect from RabbitMQ.
        
        从 RabbitMQ 断开连接。
        """
        if self.connection:
            await self.connection.close()
            logger.info("Disconnected from RabbitMQ")

    async def declare_queue(
        self,
        name: str,
        durable: bool = True
    ) -> Any:
        """
        Declare a queue.
        
        Args:
            name: Queue name
            durable: Queue durability
        
        Returns:
            Queue object
        
        声明队列。
        """
        if not self.channel:
            raise RuntimeError("Not connected to RabbitMQ")

        if name in self.queues:
            return self.queues[name]

        queue = await self.channel.declare_queue(
            name=name,
            durable=durable
        )
        self.queues[name] = queue
        return queue

    async def publish(
        self,
        queue: str,
        message: Message
    ) -> None:
        """
        Publish message to RabbitMQ queue.
        
        Args:
            queue: Queue name
            message: Message to publish
        
        将消息发送到 RabbitMQ 队列。
        """
        if not self.channel:
            raise RuntimeError("Not connected to RabbitMQ")

        try:
            # Declare queue if not exists
            await self.declare_queue(queue)

            # Get exchange
            exchange = self.channel.default_exchange

            # Publish message
            msg = aio_pika.Message(
                body=message.to_json().encode(),
                content_type="application/json",
                priority=message.priority,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            )
            await exchange.publish(msg, routing_key=queue)
            logger.debug(f"Published message {message.id} to {queue}")

        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            raise

    async def subscribe(
        self,
        queue: str,
        callback: Callable
    ) -> None:
        """
        Subscribe to RabbitMQ queue.
        
        Args:
            queue: Queue name
            callback: Callback function for messages
        
        订阅 RabbitMQ 队列。
        """
        if not self.channel:
            raise RuntimeError("Not connected to RabbitMQ")

        try:
            # Declare queue
            queue_obj = await self.declare_queue(queue)

            # Set up consumer
            async with queue_obj.iterator() as queue_iter:
                async for message in queue_iter:
                    try:
                        # Parse message
                        msg_data = Message.from_json(message.body.decode())

                        # Call callback
                        result = await callback(msg_data)

                        # Acknowledge if successful
                        await message.ack()
                        logger.debug(f"Processed message {msg_data.id}")

                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
                        # Nack to retry
                        await message.nack(requeue=True)

        except Exception as e:
            logger.error(f"Subscription error: {e}")

    async def acknowledge(self, message_id: str) -> None:
        """
        Acknowledge message processing.
        
        Args:
            message_id: Message ID
        
        确认消息处理。
        """
        # RabbitMQ handles acknowledgment in callback
        pass


class InMemoryQueue(MessageQueue):
    """
    In-memory message queue for testing and development.
    
    用于测试和开发的内存中消息队列。
    """

    def __init__(self):
        """Initialize in-memory queue."""
        self.queues: Dict[str, list] = {}
        self.subscribers: Dict[str, Callable] = {}
        self.tasks: Dict[str, asyncio.Task] = {}

    async def connect(self) -> None:
        """Connect (no-op for in-memory)."""
        logger.info("In-memory queue initialized")

    async def disconnect(self) -> None:
        """Disconnect and cleanup tasks."""
        for task in self.tasks.values():
            task.cancel()

    async def publish(
        self,
        queue: str,
        message: Message
    ) -> None:
        """
        Publish message to in-memory queue.
        
        Args:
            queue: Queue name
            message: Message to publish
        
        将消息发送到内存中队列。
        """
        if queue not in self.queues:
            self.queues[queue] = []

        self.queues[queue].append(message)

        # Process if subscriber exists
        if queue in self.subscribers:
            await self.subscribers[queue](message)

    async def subscribe(
        self,
        queue: str,
        callback: Callable
    ) -> None:
        """
        Subscribe to in-memory queue.
        
        Args:
            queue: Queue name
            callback: Callback function
        
        订阅内存中队列。
        """
        self.subscribers[queue] = callback

        # Process existing messages
        if queue in self.queues:
            while self.queues[queue]:
                message = self.queues[queue].pop(0)
                try:
                    await callback(message)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")

    async def acknowledge(self, message_id: str) -> None:
        """Acknowledge message."""
        pass


class MessageQueueManager:
    """
    High-level message queue manager.
    
    高级消息队列管理器。
    """

    def __init__(self, queue: MessageQueue):
        """
        Initialize queue manager.
        
        Args:
            queue: Message queue implementation
        
        初始化队列管理器。
        """
        self.queue = queue
        self.handlers: Dict[str, list] = {}

    async def connect(self) -> None:
        """Connect queue."""
        await self.queue.connect()

    async def disconnect(self) -> None:
        """Disconnect queue."""
        await self.queue.disconnect()

    async def publish(
        self,
        queue_name: str,
        message_type: str,
        body: Dict[str, Any],
        priority: int = 0
    ) -> None:
        """
        Publish message.
        
        Args:
            queue_name: Queue name
            message_type: Message type
            body: Message body
            priority: Priority level
        
        发送消息。
        """
        message = Message(
            body=body,
            message_type=message_type,
            priority=priority
        )
        await self.queue.publish(queue_name, message)

    async def subscribe(
        self,
        queue_name: str,
        message_type: str,
        handler: Callable
    ) -> None:
        """
        Subscribe to queue.
        
        Args:
            queue_name: Queue name
            message_type: Message type to handle
            handler: Handler function
        
        订阅队列。
        """
        if message_type not in self.handlers:
            self.handlers[message_type] = []

        self.handlers[message_type].append(handler)

        async def callback(message: Message):
            if message.message_type == message_type:
                await handler(message.body)

        await self.queue.subscribe(queue_name, callback)


# Global message queue manager
_queue_manager: Optional[MessageQueueManager] = None


def get_queue_manager() -> Optional[MessageQueueManager]:
    """
    Get global message queue manager.
    
    Returns:
        Queue manager or None
    
    获取全局消息队列管理器。
    """
    return _queue_manager


async def initialize_queue(queue: MessageQueue) -> None:
    """
    Initialize global queue manager.
    
    Args:
        queue: Message queue implementation
    
    初始化全局队列管理器。
    """
    global _queue_manager
    _queue_manager = MessageQueueManager(queue)
    await _queue_manager.connect()


async def shutdown_queue() -> None:
    """
    Shutdown message queue.
    
    关闭消息队列。
    """
    global _queue_manager
    if _queue_manager:
        await _queue_manager.disconnect()
