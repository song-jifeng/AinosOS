"""
Ainos OS - Plugin API
=====================
Core plugin API providing the base class, hook system, event system,
service registry, and API versioning for the Ainos plugin system.

This module is the foundation that all plugins build upon. It defines:
- PluginBase: Abstract base class with lifecycle hooks
- Hook system: Synchronous interceptor pattern
- Event system: Asynchronous pub/sub communication
- ServiceRegistry: Service discovery and dependency injection
- API versioning: Forward and backward compatibility
"""

import abc
import enum
import functools
import inspect
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
    Generic,
)

logger = logging.getLogger("ainos.plugins.api")

# ──────────────────────────────────────────────
# Versioning
# ──────────────────────────────────────────────

API_VERSION_MAJOR = 1
API_VERSION_MINOR = 0
API_VERSION_PATCH = 0
API_VERSION = f"{API_VERSION_MAJOR}.{API_VERSION_MINOR}.{API_VERSION_PATCH}"

T = TypeVar("T")
PluginT = TypeVar("PluginT", bound="PluginBase")


# ──────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────

class PluginException(Exception):
    """Base exception for all plugin-related errors."""
    pass


class PluginLoadError(PluginException):
    """Raised when a plugin cannot be loaded."""
    pass


class PluginDependencyError(PluginException):
    """Raised when a plugin's dependencies cannot be satisfied."""
    pass


class PluginVersionError(PluginException):
    """Raised on API version mismatch."""
    pass


class HookException(PluginException):
    """Raised when a hook handler raises an exception."""
    pass


class EventException(PluginException):
    """Raised on event bus errors."""
    pass


class ServiceException(PluginException):
    """Raised on service registry errors."""
    pass


# ──────────────────────────────────────────────
# Enums and Data Classes
# ──────────────────────────────────────────────

class PluginState(enum.Enum):
    """Lifecycle states of a plugin."""
    CREATED = "created"
    INITIALIZED = "initialized"
    STARTED = "started"
    STOPPED = "stopped"
    ERROR = "error"
    DISABLED = "disabled"
    UNINSTALLED = "uninstalled"


class HookPriority(enum.IntEnum):
    """Priority levels for hook handlers. Lower = earlier execution."""
    EARLIEST = 0
    EARLY = 25
    NORMAL = 50
    LATE = 75
    LATEST = 100


class EventPriority(enum.IntEnum):
    """Priority levels for event listeners. Lower = earlier dispatch."""
    SYSTEM = 0
    HIGH = 25
    NORMAL = 50
    LOW = 75
    MONITOR = 100


@dataclass
class PluginMetadata:
    """Metadata describing a plugin."""
    name: str
    version: str
    description: str = ""
    author: str = ""
    license: str = "MIT"
    homepage: str = ""
    api_version: str = API_VERSION
    min_api_version: str = "1.0.0"
    tags: List[str] = field(default_factory=list)
    dependencies: Dict[str, str] = field(default_factory=dict)
    optional_dependencies: Dict[str, str] = field(default_factory=dict)
    provides_services: List[str] = field(default_factory=list)
    requires_services: List[str] = field(default_factory=list)
    hooks: List[str] = field(default_factory=list)
    events_listen: List[str] = field(default_factory=list)
    events_emit: List[str] = field(default_factory=list)
    config_schema: Optional[Dict[str, Any]] = None
    permissions: List[str] = field(default_factory=list)
    resource_limits: Optional[Dict[str, Any]] = None


@dataclass
class PluginConfig:
    """Configuration for a single plugin instance."""
    name: str
    enabled: bool = True
    settings: Dict[str, Any] = field(default_factory=dict)
    overrides: Dict[str, Any] = field(default_factory=dict)
    isolation: Optional[str] = None  # None, "subprocess", "container"
    resource_limits: Dict[str, Any] = field(default_factory=lambda: {
        "max_memory_mb": 256,
        "max_cpu_percent": 50,
        "max_startup_time_sec": 30,
        "max_restarts": 5,
    })


# ──────────────────────────────────────────────
# Hook System
# ──────────────────────────────────────────────

class Hook:
    """
    A hook point in the system that plugins can intercept.

    Hooks are synchronous interception points. When a hook is triggered,
    all registered handlers are called in priority order. Handlers can:
    - Inspect/modify the arguments
    - Short-circuit by returning a value
    - Raise exceptions to abort the operation

    Args:
        name: Unique identifier for the hook
        description: Human-readable description
        args_schema: Optional dict describing expected argument types
        return_schema: Optional dict describing return value types
        allow_short_circuit: Whether handlers can short-circuit the chain
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        args_schema: Optional[Dict[str, type]] = None,
        return_schema: Optional[Dict[str, type]] = None,
        allow_short_circuit: bool = True,
    ):
        self.name = name
        self.description = description
        self.args_schema = args_schema or {}
        self.return_schema = return_schema or {}
        self.allow_short_circuit = allow_short_circuit
        self._handlers: List[Tuple[HookPriority, str, Callable]] = []
        self._lock = threading.RLock()

    def register(
        self,
        handler: Callable,
        priority: HookPriority = HookPriority.NORMAL,
        plugin_name: str = "",
    ) -> None:
        """
        Register a handler for this hook.

        Args:
            handler: Callable that accepts hook arguments
            priority: Execution priority (lower = earlier)
            plugin_name: Name of the registering plugin (for debugging)
        """
        if not callable(handler):
            raise HookException(f"Handler must be callable, got {type(handler)}")
        with self._lock:
            self._handlers.append((priority, plugin_name, handler))
            self._handlers.sort(key=lambda x: x[0].value)

    def unregister(self, handler: Callable) -> bool:
        """Remove a handler from this hook."""
        with self._lock:
            for i, (_, _, h) in enumerate(self._handlers):
                if h is handler:
                    self._handlers.pop(i)
                    return True
            return False

    def unregister_all(self, plugin_name: str) -> int:
        """Remove all handlers registered by a given plugin."""
        count = 0
        with self._lock:
            self._handlers = [
                h for h in self._handlers
                if h[1] != plugin_name and (count := count + 1)
            ]
        return count

    def trigger(
        self,
        *args: Any,
        _hook_context: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Any]:
        """
        Trigger the hook, calling all registered handlers in priority order.

        Args:
            *args: Positional arguments to pass to handlers
            _hook_context: Optional context dict for metadata
            **kwargs: Keyword arguments to pass to handlers

        Returns:
            List of return values from each handler (or [None] if none)

        Raises:
            HookException: If a handler raises an exception
        """
        results: List[Any] = []
        context = _hook_context or {}

        with self._lock:
            handlers = list(self._handlers)

        for priority, plugin_name, handler in handlers:
            try:
                # Determine if handler accepts context
                sig = inspect.signature(handler)
                has_context = any(
                    p.name == "hook_context" for p in sig.parameters.values()
                )

                if has_context:
                    result = handler(*args, **kwargs, hook_context=context)
                else:
                    result = handler(*args, **kwargs)

                results.append(result)

                # Check for short-circuit (non-None return)
                if self.allow_short_circuit and result is not None:
                    logger.debug(
                        f"Hook '{self.name}' short-circuited by {plugin_name}"
                    )
                    break

            except Exception as e:
                logger.error(
                    f"Hook '{self.name}' handler {plugin_name} failed: {e}",
                    exc_info=True,
                )
                raise HookException(
                    f"Hook '{self.name}' handler '{plugin_name}' failed: {e}"
                ) from e

        return results

    @property
    def handler_count(self) -> int:
        """Number of registered handlers."""
        with self._lock:
            return len(self._handlers)

    @property
    def registered_plugins(self) -> List[str]:
        """Names of plugins with registered handlers."""
        with self._lock:
            return list(set(h[1] for h in self._handlers if h[1]))

    def clear(self) -> None:
        """Remove all handlers."""
        with self._lock:
            self._handlers.clear()

    def __repr__(self) -> str:
        return (
            f"<Hook '{self.name}' "
            f"handlers={self.handler_count} "
            f"short_circuit={self.allow_short_circuit}>"
        )


class HookRegistry:
    """
    Central registry for all hooks in the system.

    Manages named hooks and provides bulk operations for plugin lifecycle.
    """

    def __init__(self):
        self._hooks: Dict[str, Hook] = {}
        self._lock = threading.RLock()

    def register_hook(
        self,
        name: str,
        description: str = "",
        allow_short_circuit: bool = True,
    ) -> Hook:
        """
        Register a new hook point.

        Args:
            name: Unique hook name (namespaced, e.g., 'inference.before')
            description: Human-readable description
            allow_short_circuit: Whether handlers can short-circuit

        Returns:
            The created Hook instance

        Raises:
            HookException: If hook name already exists
        """
        with self._lock:
            if name in self._hooks:
                raise HookException(f"Hook '{name}' already registered")
            hook = Hook(
                name=name,
                description=description,
                allow_short_circuit=allow_short_circuit,
            )
            self._hooks[name] = hook
            return hook

    def get_hook(self, name: str) -> Optional[Hook]:
        """Get a hook by name, or None if not found."""
        with self._lock:
            return self._hooks.get(name)

    def get_or_create_hook(
        self,
        name: str,
        description: str = "",
        allow_short_circuit: bool = True,
    ) -> Hook:
        """Get an existing hook or create it if it doesn't exist."""
        with self._lock:
            hook = self._hooks.get(name)
            if hook is None:
                hook = Hook(
                    name=name,
                    description=description,
                    allow_short_circuit=allow_short_circuit,
                )
                self._hooks[name] = hook
            return hook

    def remove_hook(self, name: str) -> bool:
        """Remove a hook and all its handlers."""
        with self._lock:
            hook = self._hooks.pop(name, None)
            if hook:
                hook.clear()
                return True
            return False

    def unregister_plugin(self, plugin_name: str) -> int:
        """Remove all handlers registered by a plugin across all hooks."""
        count = 0
        with self._lock:
            for hook in self._hooks.values():
                count += hook.unregister_all(plugin_name)
        return count

    def list_hooks(self, pattern: Optional[str] = None) -> List[str]:
        """List all registered hook names, optionally filtered by pattern."""
        with self._lock:
            names = list(self._hooks.keys())
            if pattern:
                names = [n for n in names if pattern in n]
            return sorted(names)

    def trigger(
        self,
        hook_name: str,
        *args: Any,
        **kwargs: Any,
    ) -> List[Any]:
        """
        Trigger a hook by name.

        Args:
            hook_name: Name of the hook to trigger
            *args, **kwargs: Arguments to pass to handlers

        Returns:
            List of handler return values

        Raises:
            HookException: If hook doesn't exist
        """
        hook = self.get_hook(hook_name)
        if hook is None:
            logger.warning(f"Hook '{hook_name}' not registered, skipping")
            return []
        return hook.trigger(*args, **kwargs)

    def clear(self) -> None:
        """Remove all hooks."""
        with self._lock:
            for hook in self._hooks.values():
                hook.clear()
            self._hooks.clear()

    def __len__(self) -> int:
        return len(self._hooks)

    def __contains__(self, name: str) -> bool:
        return name in self._hooks

    def __repr__(self) -> str:
        return f"<HookRegistry hooks={len(self._hooks)}>"


# ──────────────────────────────────────────────
# Event System
# ──────────────────────────────────────────────

class Event:
    """
    An event message in the event bus.

    Events are the primary asynchronous communication mechanism
    between plugins. They carry typed payloads and metadata.

    Args:
        type: Event type identifier (e.g., 'model.loaded')
        payload: Arbitrary event data
        source: Plugin name or system component that emitted the event
        id: Unique event ID (auto-generated if not provided)
        timestamp: Event creation time (auto-generated if not provided)
        priority: Event priority for delivery ordering
        ttl: Time-to-live in seconds (None = no expiry)
    """

    def __init__(
        self,
        type: str,
        payload: Any = None,
        source: str = "system",
        id: Optional[str] = None,
        timestamp: Optional[float] = None,
        priority: EventPriority = EventPriority.NORMAL,
        ttl: Optional[float] = None,
    ):
        self.id = id or str(uuid.uuid4())
        self.type = type
        self.payload = payload
        self.source = source
        self.timestamp = timestamp or time.time()
        self.priority = priority
        self.ttl = ttl

    @property
    def expired(self) -> bool:
        """Check if the event has expired based on TTL."""
        if self.ttl is None:
            return False
        return (time.time() - self.timestamp) > self.ttl

    def __repr__(self) -> str:
        return (
            f"<Event '{self.type}' "
            f"source={self.source} "
            f"id={self.id[:8]}>"
        )


class EventSubscription:
    """
    Represents a subscription to an event type.

    Used internally by EventBus to track listeners.
    """

    def __init__(
        self,
        event_type: str,
        callback: Callable[[Event], Any],
        priority: EventPriority = EventPriority.NORMAL,
        plugin_name: str = "",
        filter_func: Optional[Callable[[Event], bool]] = None,
        once: bool = False,
    ):
        self.id = str(uuid.uuid4())
        self.event_type = event_type
        self.callback = callback
        self.priority = priority
        self.plugin_name = plugin_name
        self.filter_func = filter_func
        self.once = once
        self.created_at = time.time()

    def matches(self, event: Event) -> bool:
        """Check if this subscription should receive the event."""
        if self.event_type != event.type and self.event_type != "*":
            return False
        if self.filter_func and not self.filter_func(event):
            return False
        return True

    def __repr__(self) -> str:
        return (
            f"<EventSubscription "
            f"type='{self.event_type}' "
            f"plugin={self.plugin_name}>"
        )


class EventBus:
    """
    Asynchronous event bus for plugin communication.

    The event bus provides a publish/subscribe model where:
    - Plugins emit events by publishing them
    - Plugins listen for events by subscribing
    - Events are delivered to all matching subscribers
    - Wildcard '*' subscribes to all events
    - Optional filtering via filter functions
    - One-shot subscriptions via 'once' flag

    This implementation uses a thread pool for async delivery
    to avoid blocking the publisher.
    """

    def __init__(
        self,
        async_delivery: bool = True,
        max_workers: int = 4,
    ):
        self._subscriptions: Dict[str, List[EventSubscription]] = {}
        self._wildcard_subscriptions: List[EventSubscription] = []
        self._lock = threading.RLock()
        self._async_delivery = async_delivery
        self._thread_pool: List[threading.Thread] = []
        self._max_workers = max_workers
        self._stats: Dict[str, int] = {
            "published": 0,
            "delivered": 0,
            "dropped": 0,
            "errors": 0,
        }

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[Event], Any],
        priority: EventPriority = EventPriority.NORMAL,
        plugin_name: str = "",
        filter_func: Optional[Callable[[Event], bool]] = None,
        once: bool = False,
    ) -> str:
        """
        Subscribe to an event type.

        Args:
            event_type: Event type to listen for ('*' for all)
            callback: Function to call when event is received
            priority: Delivery priority
            plugin_name: Name of subscribing plugin
            filter_func: Optional filter function (must return True to deliver)
            once: If True, auto-unsubscribe after first delivery

        Returns:
            Subscription ID (can be used to unsubscribe)
        """
        sub = EventSubscription(
            event_type=event_type,
            callback=callback,
            priority=priority,
            plugin_name=plugin_name,
            filter_func=filter_func,
            once=once,
        )

        with self._lock:
            if event_type == "*":
                self._wildcard_subscriptions.append(sub)
                self._wildcard_subscriptions.sort(key=lambda s: s.priority.value)
            else:
                if event_type not in self._subscriptions:
                    self._subscriptions[event_type] = []
                self._subscriptions[event_type].append(sub)
                self._subscriptions[event_type].sort(
                    key=lambda s: s.priority.value
                )

        return sub.id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe by subscription ID."""
        with self._lock:
            # Check named subscriptions
            for subs in self._subscriptions.values():
                for i, s in enumerate(subs):
                    if s.id == subscription_id:
                        subs.pop(i)
                        return True
            # Check wildcard subscriptions
            for i, s in enumerate(self._wildcard_subscriptions):
                if s.id == subscription_id:
                    self._wildcard_subscriptions.pop(i)
                    return True
        return False

    def unsubscribe_plugin(self, plugin_name: str) -> int:
        """Remove all subscriptions from a plugin."""
        count = 0
        with self._lock:
            for event_type in list(self._subscriptions.keys()):
                subs = self._subscriptions[event_type]
                self._subscriptions[event_type] = [
                    s for s in subs if s.plugin_name != plugin_name
                ]
                count += len(subs) - len(self._subscriptions[event_type])
                if not self._subscriptions[event_type]:
                    del self._subscriptions[event_type]

            self._wildcard_subscriptions = [
                s for s in self._wildcard_subscriptions
                if s.plugin_name != plugin_name
            ]
            count += sum(
                1 for s in self._wildcard_subscriptions
                if s.plugin_name == plugin_name
            )
        return count

    def publish(
        self,
        event: Event,
        synchronous: bool = False,
    ) -> None:
        """
        Publish an event to all matching subscribers.

        Args:
            event: The event to publish
            synchronous: If True, deliver in the current thread
        """
        if event.expired:
            logger.debug(f"Event '{event.type}' expired, dropping")
            with self._lock:
                self._stats["dropped"] += 1
            return

        with self._lock:
            self._stats["published"] += 1

        if synchronous or not self._async_delivery:
            self._deliver(event)
        else:
            thread = threading.Thread(
                target=self._deliver,
                args=(event,),
                daemon=True,
            )
            thread.start()

    def _deliver(self, event: Event) -> None:
        """Deliver an event to all matching subscribers."""
        # Collect matching subscriptions
        to_deliver: List[EventSubscription] = []
        once_subs: List[EventSubscription] = []

        with self._lock:
            # Named subscriptions
            subs = list(self._subscriptions.get(event.type, []))
            to_deliver.extend(subs)

            # Wildcard subscriptions
            to_deliver.extend(list(self._wildcard_subscriptions))

            # Sort by priority
            to_deliver.sort(key=lambda s: s.priority.value)

            # Track one-shot subscriptions to remove
            once_subs = [s for s in to_deliver if s.once]

        # Deliver
        for sub in to_deliver:
            if not sub.matches(event):
                continue
            try:
                sub.callback(event)
                with self._lock:
                    self._stats["delivered"] += 1
            except Exception as e:
                logger.error(
                    f"Event '{event.type}' delivery to "
                    f"{sub.plugin_name} failed: {e}",
                    exc_info=True,
                )
                with self._lock:
                    self._stats["errors"] += 1

        # Remove one-shot subscriptions
        if once_subs:
            with self._lock:
                for sub in once_subs:
                    self.unsubscribe(sub.id)

    def get_subscription_count(self, event_type: Optional[str] = None) -> int:
        """Get count of subscriptions for an event type (or total)."""
        with self._lock:
            if event_type:
                named = len(self._subscriptions.get(event_type, []))
                wild = sum(
                    1 for s in self._wildcard_subscriptions
                    if s.event_type == event_type or s.event_type == "*"
                )
                return named + wild
            total = sum(len(s) for s in self._subscriptions.values())
            total += len(self._wildcard_subscriptions)
            return total

    def get_stats(self) -> Dict[str, int]:
        """Get event bus statistics."""
        with self._lock:
            return dict(self._stats)

    def clear(self) -> None:
        """Remove all subscriptions."""
        with self._lock:
            self._subscriptions.clear()
            self._wildcard_subscriptions.clear()

    def __repr__(self) -> str:
        return (
            f"<EventBus "
            f"subs={self.get_subscription_count()} "
            f"published={self._stats['published']}>"
        )


# ──────────────────────────────────────────────
# Service Registry
# ──────────────────────────────────────────────

class ServiceRegistry:
    """
    Registry for plugin-provided services.

    Services are named objects (instances, factories, or callables) that
    plugins can register and discover. This enables dependency injection
    and loose coupling between plugins.

    Supports:
    - Singleton services (one instance, shared)
    - Factory services (new instance per request)
    - Service aliases
    - Service lifecycle callbacks
    - Service dependency tracking
    """

    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._aliases: Dict[str, str] = {}
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def register(
        self,
        name: str,
        service: Any,
        *,
        description: str = "",
        version: str = "1.0.0",
        plugin_name: str = "",
        tags: List[str] = None,
        overwrite: bool = False,
    ) -> None:
        """
        Register a singleton service.

        Args:
            name: Unique service name
            service: The service instance or object
            description: Human-readable description
            version: Service version
            plugin_name: Name of providing plugin
            tags: Optional categorization tags
            overwrite: Whether to overwrite an existing service

        Raises:
            ServiceException: If service already exists and overwrite=False
        """
        with self._lock:
            if name in self._services and not overwrite:
                raise ServiceException(
                    f"Service '{name}' already registered"
                )
            self._services[name] = service
            self._metadata[name] = {
                "type": "singleton",
                "description": description,
                "version": version,
                "plugin_name": plugin_name,
                "tags": tags or [],
                "registered_at": time.time(),
            }
            logger.debug(f"Service '{name}' registered by {plugin_name}")

    def register_factory(
        self,
        name: str,
        factory: Callable[[], Any],
        *,
        description: str = "",
        version: str = "1.0.0",
        plugin_name: str = "",
        tags: List[str] = None,
        overwrite: bool = False,
    ) -> None:
        """
        Register a factory service (creates new instance on each get).

        Args:
            name: Unique service name
            factory: Callable that creates a new service instance
            description: Human-readable description
            version: Service version
            plugin_name: Name of providing plugin
            tags: Optional categorization tags
            overwrite: Whether to overwrite an existing factory
        """
        if not callable(factory):
            raise ServiceException("Factory must be callable")
        with self._lock:
            if name in self._factories and not overwrite:
                raise ServiceException(
                    f"Factory '{name}' already registered"
                )
            self._factories[name] = factory
            self._metadata[name] = {
                "type": "factory",
                "description": description,
                "version": version,
                "plugin_name": plugin_name,
                "tags": tags or [],
                "registered_at": time.time(),
            }
            logger.debug(f"Factory '{name}' registered by {plugin_name}")

    def register_alias(self, alias: str, target: str) -> None:
        """
        Create an alias for an existing service.

        Args:
            alias: Alias name
            target: Target service name

        Raises:
            ServiceException: If target doesn't exist or alias already exists
        """
        with self._lock:
            if alias in self._aliases:
                raise ServiceException(f"Alias '{alias}' already exists")
            if alias in self._services or alias in self._factories:
                raise ServiceException(
                    f"Name '{alias}' is already a service"
                )
            if target not in self._services and target not in self._factories:
                raise ServiceException(
                    f"Target service '{target}' not found"
                )
            self._aliases[alias] = target

    def get(self, name: str) -> Any:
        """
        Get a service by name.

        Resolves aliases and creates instances from factories.

        Args:
            name: Service name or alias

        Returns:
            The service instance

        Raises:
            ServiceException: If service not found
        """
        with self._lock:
            # Resolve alias
            while name in self._aliases:
                name = self._aliases[name]

            # Check singletons
            if name in self._services:
                return self._services[name]

            # Check factories
            if name in self._factories:
                return self._factories[name]()

            raise ServiceException(f"Service '{name}' not found")

    def get_or_none(self, name: str) -> Optional[Any]:
        """Get a service by name, returning None if not found."""
        try:
            return self.get(name)
        except ServiceException:
            return None

    def get_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a registered service."""
        with self._lock:
            # Resolve alias
            actual = name
            while actual in self._aliases:
                actual = self._aliases[actual]
            return self._metadata.get(actual)

    def unregister(self, name: str) -> bool:
        """Unregister a service, factory, or alias."""
        with self._lock:
            if name in self._services:
                del self._services[name]
                self._metadata.pop(name, None)
                return True
            if name in self._factories:
                del self._factories[name]
                self._metadata.pop(name, None)
                return True
            if name in self._aliases:
                del self._aliases[name]
                return True
            return False

    def unregister_plugin(self, plugin_name: str) -> int:
        """Remove all services registered by a plugin."""
        count = 0
        with self._lock:
            for name, meta in list(self._metadata.items()):
                if meta.get("plugin_name") == plugin_name:
                    self._services.pop(name, None)
                    self._factories.pop(name, None)
                    self._metadata.pop(name, None)
                    count += 1
        return count

    def list_services(
        self,
        tag: Optional[str] = None,
        plugin_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all registered services with metadata."""
        with self._lock:
            results = []
            for name, meta in self._metadata.items():
                if tag and tag not in meta.get("tags", []):
                    continue
                if plugin_name and meta.get("plugin_name") != plugin_name:
                    continue
                results.append({
                    "name": name,
                    **meta,
                })
            return results

    def has_service(self, name: str) -> bool:
        """Check if a service (or alias) is registered."""
        with self._lock:
            return (
                name in self._services
                or name in self._factories
                or name in self._aliases
            )

    def clear(self) -> None:
        """Remove all services, factories, and aliases."""
        with self._lock:
            self._services.clear()
            self._factories.clear()
            self._aliases.clear()
            self._metadata.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._services) + len(self._factories) + len(self._aliases)

    def __contains__(self, name: str) -> bool:
        return self.has_service(name)

    def __repr__(self) -> str:
        return (
            f"<ServiceRegistry "
            f"services={len(self._services)} "
            f"factories={len(self._factories)} "
            f"aliases={len(self._aliases)}>"
        )


# ──────────────────────────────────────────────
# Plugin Base Class
# ──────────────────────────────────────────────

class PluginBase(abc.ABC):
    """
    Abstract base class for all Ainos plugins.

    All plugins must inherit from this class and implement at minimum
    the `on_initialize` method. The base class provides:

    - Lifecycle management (init, start, stop, cleanup)
    - Hook registration and triggering
    - Event publishing and subscription
    - Service registration and discovery
    - Configuration management
    - Logging utilities

    Lifecycle order:
    1. __init__() - Create plugin instance
    2. on_initialize() - Setup resources, register hooks/services
    3. on_start() - Begin active operations
    4. on_stop() - Pause active operations
    5. on_cleanup() - Release all resources

    Usage:
        class MyPlugin(PluginBase):
            def on_initialize(self):
                self.log.info("Plugin initialized")

            def on_start(self):
                self.log.info("Plugin started")

            def on_stop(self):
                self.log.info("Plugin stopped")

            def on_cleanup(self):
                self.log.info("Plugin cleaned up")
    """

    def __init__(
        self,
        metadata: PluginMetadata,
        config: Optional[PluginConfig] = None,
    ):
        self._metadata = metadata
        self._config = config or PluginConfig(name=metadata.name)
        self._state = PluginState.CREATED
        self._hook_registry: Optional[HookRegistry] = None
        self._event_bus: Optional[EventBus] = None
        self._service_registry: Optional[ServiceRegistry] = None
        self._subscription_ids: List[str] = []
        self._registered_hooks: List[str] = []
        self._lock = threading.RLock()

        # Set up logger
        self._log = logging.getLogger(f"ainos.plugins.{metadata.name}")
        self._log.setLevel(logging.DEBUG)

    # ── Properties ──

    @property
    def metadata(self) -> PluginMetadata:
        """Plugin metadata."""
        return self._metadata

    @property
    def name(self) -> str:
        """Plugin name (shortcut)."""
        return self._metadata.name

    @property
    def version(self) -> str:
        """Plugin version (shortcut)."""
        return self._metadata.version

    @property
    def state(self) -> PluginState:
        """Current lifecycle state."""
        return self._state

    @property
    def config(self) -> PluginConfig:
        """Plugin configuration."""
        return self._config

    @config.setter
    def config(self, value: PluginConfig) -> None:
        self._config = value

    @property
    def log(self) -> logging.Logger:
        """Plugin-specific logger."""
        return self._log

    @property
    def hook_registry(self) -> Optional[HookRegistry]:
        """The system hook registry (set by PluginManager)."""
        return self._hook_registry

    @property
    def event_bus(self) -> Optional[EventBus]:
        """The system event bus (set by PluginManager)."""
        return self._event_bus

    @property
    def service_registry(self) -> Optional[ServiceRegistry]:
        """The system service registry (set by PluginManager)."""
        return self._service_registry

    # ── Lifecycle Hooks (override in subclasses) ──

    def on_create(self) -> None:
        """
        Called after plugin instance is created.
        Minimal setup only — no external dependencies.
        """
        pass

    def on_initialize(self) -> None:
        """
        Initialize plugin resources.

        This is the main setup method. Plugins should:
        - Register hooks and event listeners
        - Register services
        - Load configuration
        - Initialize internal resources
        """
        pass

    def on_start(self) -> None:
        """
        Start plugin active operations.

        Called after initialization. Plugins should begin:
        - Background threads or timers
        - Network connections
        - Active monitoring
        """
        pass

    def on_stop(self) -> None:
        """
        Stop plugin active operations.

        Called before cleanup. Plugins should:
        - Stop background threads
        - Close network connections
        - Save state
        """
        pass

    def on_cleanup(self) -> None:
        """
        Clean up all plugin resources.

        Called after stop. Plugins should:
        - Release external resources
        - Close file handles
        - Clean up temporary files
        - Unregister hooks/services
        """
        pass

    def on_config_change(self, old_config: PluginConfig, new_config: PluginConfig) -> None:
        """
        Called when plugin configuration changes.

        Args:
            old_config: Previous configuration
            new_config: New configuration
        """
        pass

    def on_hot_reload(self) -> None:
        """
        Called when plugin is hot-reloaded.

        The plugin should re-read its source code and re-initialize
        state without losing existing runtime context.
        """
        self.on_initialize()

    # ── Internal Lifecycle Methods ──

    def _set_state(self, state: PluginState) -> None:
        """Set the plugin state (thread-safe)."""
        with self._lock:
            self._state = state

    def _initialize(self, runtime: "PluginAPI") -> None:
        """Internal initialization with runtime API injection."""
        self._hook_registry = runtime.hook_registry
        self._event_bus = runtime.event_bus
        self._service_registry = runtime.service_registry

        try:
            self._set_state(PluginState.INITIALIZED)
            self.on_initialize()
            self._log.info(f"Plugin '{self.name}' initialized")
        except Exception as e:
            self._set_state(PluginState.ERROR)
            self._log.error(
                f"Plugin '{self.name}' initialization failed: {e}",
                exc_info=True,
            )
            raise PluginLoadError(
                f"Failed to initialize plugin '{self.name}': {e}"
            ) from e

    def _start(self) -> None:
        """Internal start wrapper."""
        try:
            self.on_start()
            self._set_state(PluginState.STARTED)
            self._log.info(f"Plugin '{self.name}' started")
        except Exception as e:
            self._set_state(PluginState.ERROR)
            self._log.error(
                f"Plugin '{self.name}' start failed: {e}",
                exc_info=True,
            )
            raise

    def _stop(self) -> None:
        """Internal stop wrapper."""
        try:
            self.on_stop()
            # Don't set state to STOPPED here — cleanup does it
        except Exception as e:
            self._log.error(
                f"Plugin '{self.name}' stop failed: {e}",
                exc_info=True,
            )

    def _cleanup(self) -> None:
        """Internal cleanup wrapper."""
        try:
            self.on_cleanup()
            self._unregister_all()
            self._set_state(PluginState.STOPPED)
            self._log.info(f"Plugin '{self.name}' cleaned up")
        except Exception as e:
            self._log.error(
                f"Plugin '{self.name}' cleanup failed: {e}",
                exc_info=True,
            )

    def _unregister_all(self) -> None:
        """Unregister all hooks, event subscriptions, and services."""
        if self._hook_registry:
            self._hook_registry.unregister_plugin(self.name)
        if self._event_bus:
            for sub_id in self._subscription_ids:
                self._event_bus.unsubscribe(sub_id)
            self._subscription_ids.clear()
        if self._service_registry:
            self._service_registry.unregister_plugin(self.name)

    # ── Hook Helpers ──

    def register_hook_handler(
        self,
        hook_name: str,
        handler: Callable,
        priority: HookPriority = HookPriority.NORMAL,
    ) -> None:
        """
        Register a handler for a system hook.

        Args:
            hook_name: Name of the hook to handle
            handler: Handler function
            priority: Execution priority
        """
        if self._hook_registry is None:
            raise PluginException("Hook registry not available")
        hook = self._hook_registry.get_or_create_hook(hook_name)
        hook.register(handler, priority=priority, plugin_name=self.name)
        self._registered_hooks.append(hook_name)

    def trigger_hook(self, hook_name: str, *args: Any, **kwargs: Any) -> List[Any]:
        """
        Trigger a system hook.

        Args:
            hook_name: Name of the hook to trigger
            *args, **kwargs: Arguments to pass to handlers

        Returns:
            List of handler results
        """
        if self._hook_registry is None:
            raise PluginException("Hook registry not available")
        return self._hook_registry.trigger(hook_name, *args, **kwargs)

    # ── Event Helpers ──

    def publish_event(
        self,
        event_type: str,
        payload: Any = None,
        priority: EventPriority = EventPriority.NORMAL,
        synchronous: bool = False,
    ) -> None:
        """
        Publish an event to the event bus.

        Args:
            event_type: Event type identifier
            payload: Event data payload
            priority: Event priority
            synchronous: Deliver synchronously (blocking)
        """
        if self._event_bus is None:
            raise PluginException("Event bus not available")
        event = Event(
            type=event_type,
            payload=payload,
            source=self.name,
            priority=priority,
        )
        self._event_bus.publish(event, synchronous=synchronous)

    def subscribe_event(
        self,
        event_type: str,
        callback: Callable[[Event], Any],
        priority: EventPriority = EventPriority.NORMAL,
        filter_func: Optional[Callable[[Event], bool]] = None,
        once: bool = False,
    ) -> str:
        """
        Subscribe to an event type.

        Args:
            event_type: Event type or '*' for all
            callback: Event handler function
            priority: Delivery priority
            filter_func: Optional filter
            once: Auto-unsubscribe after first delivery

        Returns:
            Subscription ID
        """
        if self._event_bus is None:
            raise PluginException("Event bus not available")
        sub_id = self._event_bus.subscribe(
            event_type=event_type,
            callback=callback,
            priority=priority,
            plugin_name=self.name,
            filter_func=filter_func,
            once=once,
        )
        self._subscription_ids.append(sub_id)
        return sub_id

    # ── Service Helpers ──

    def register_service(
        self,
        name: str,
        service: Any,
        *,
        description: str = "",
        version: str = "1.0.0",
        tags: List[str] = None,
        overwrite: bool = False,
    ) -> None:
        """
        Register a service provided by this plugin.

        Args:
            name: Service name (should be namespaced, e.g., 'myplugin.storage')
            service: Service instance
            description: Human-readable description
            version: Service version
            tags: Categorization tags
            overwrite: Overwrite existing service
        """
        if self._service_registry is None:
            raise PluginException("Service registry not available")
        self._service_registry.register(
            name=name,
            service=service,
            description=description,
            version=version,
            plugin_name=self.name,
            tags=tags,
            overwrite=overwrite,
        )

    def register_factory(
        self,
        name: str,
        factory: Callable[[], Any],
        *,
        description: str = "",
        version: str = "1.0.0",
        tags: List[str] = None,
        overwrite: bool = False,
    ) -> None:
        """
        Register a factory service.

        Args:
            name: Service name
            factory: Factory function
            description: Description
            version: Version
            tags: Tags
            overwrite: Overwrite existing
        """
        if self._service_registry is None:
            raise PluginException("Service registry not available")
        self._service_registry.register_factory(
            name=name,
            factory=factory,
            description=description,
            version=version,
            plugin_name=self.name,
            tags=tags,
            overwrite=overwrite,
        )

    def get_service(self, name: str) -> Any:
        """
        Get a service from the registry.

        Args:
            name: Service name

        Returns:
            Service instance
        """
        if self._service_registry is None:
            raise PluginException("Service registry not available")
        return self._service_registry.get(name)

    def get_service_or_none(self, name: str) -> Optional[Any]:
        """Get a service, returning None if not found."""
        if self._service_registry is None:
            return None
        return self._service_registry.get_or_none(name)

    # ── Config Helpers ──

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a configuration setting."""
        return self._config.settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        """Set a configuration setting."""
        old_config = self._config
        new_config = PluginConfig(
            name=self._config.name,
            enabled=self._config.enabled,
            settings={**self._config.settings, key: value},
            isolation=self._config.isolation,
            resource_limits=dict(self._config.resource_limits),
        )
        self._config = new_config
        self.on_config_change(old_config, new_config)

    # ── Utility Methods ──

    def get_data_dir(self, base_data_dir: str = "") -> str:
        """
        Get the plugin's data directory path.

        Args:
            base_data_dir: Base data directory

        Returns:
            Path to plugin-specific data directory
        """
        import os
        if not base_data_dir:
            base_data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data",
                "plugins",
            )
        return os.path.join(base_data_dir, self.name)

    def create_data_dir(self, base_data_dir: str = "") -> str:
        """Create and return the plugin's data directory."""
        import os
        path = self.get_data_dir(base_data_dir)
        os.makedirs(path, exist_ok=True)
        return path

    def __repr__(self) -> str:
        return (
            f"<Plugin '{self.name}' "
            f"v{self.version} "
            f"state={self.state.value}>"
        )


# ──────────────────────────────────────────────
# PluginAPI Container
# ──────────────────────────────────────────────

class PluginAPI:
    """
    Container for the runtime API that plugins interact with.

    This is passed to plugins during initialization and provides
    access to the core system services.
    """

    def __init__(
        self,
        hook_registry: HookRegistry,
        event_bus: EventBus,
        service_registry: ServiceRegistry,
    ):
        self.hook_registry = hook_registry
        self.event_bus = event_bus
        self.service_registry = service_registry
        self.api_version = API_VERSION

    def __repr__(self) -> str:
        return (
            f"<PluginAPI v{self.api_version}>"
        )


# ──────────────────────────────────────────────
# Built-in Hook Definitions
# ──────────────────────────────────────────────

# Standard hook names used throughout the system
HOOKS = {
    # System lifecycle
    "system.startup": "System startup sequence",
    "system.shutdown": "System shutdown sequence",
    "system.config_change": "System configuration changed",

    # Plugin lifecycle
    "plugin.before_load": "Before a plugin is loaded",
    "plugin.after_load": "After a plugin is loaded",
    "plugin.before_unload": "Before a plugin is unloaded",
    "plugin.after_unload": "After a plugin is unloaded",
    "plugin.before_enable": "Before a plugin is enabled",
    "plugin.after_enable": "After a plugin is enabled",
    "plugin.before_disable": "Before a plugin is disabled",
    "plugin.after_disable": "After a plugin is disabled",

    # Inference pipeline
    "inference.before": "Before inference execution",
    "inference.after": "After inference execution",
    "inference.prompt_transform": "Transform/modify the prompt before inference",
    "inference.response_transform": "Transform/modify the response after inference",
    "inference.token_stream": "Intercept individual tokens during streaming",

    # Model management
    "model.before_load": "Before a model is loaded",
    "model.after_load": "After a model is loaded",
    "model.before_unload": "Before a model is unloaded",
    "model.after_unload": "After a model is unloaded",

    # Context management
    "context.before_store": "Before context is stored",
    "context.after_store": "After context is stored",
    "context.before_retrieve": "Before context is retrieved",
    "context.after_retrieve": "After context is retrieved",

    # Security
    "security.auth_check": "Authentication check",
    "security.permission_check": "Permission check",
    "security.rate_limit": "Rate limiting check",

    # Monitoring
    "monitor.metrics_collect": "Collect metrics data",
    "monitor.health_check": "Health check execution",
    "monitor.alert": "Alert trigger",
}

# Standard event types
EVENTS = {
    "system.started": "System has started",
    "system.stopping": "System is stopping",
    "system.shutdown": "System has shut down",

    "plugin.loaded": "A plugin was loaded",
    "plugin.unloaded": "A plugin was unloaded",
    "plugin.enabled": "A plugin was enabled",
    "plugin.disabled": "A plugin was disabled",
    "plugin.error": "A plugin encountered an error",

    "model.loaded": "A model was loaded",
    "model.unloaded": "A model was unloaded",
    "model.error": "Model loading/unloading error",

    "inference.started": "Inference execution started",
    "inference.completed": "Inference execution completed",
    "inference.error": "Inference execution error",
    "inference.token": "A token was generated during streaming",

    "context.stored": "Context was stored",
    "context.retrieved": "Context was retrieved",

    "monitor.metrics": "Metrics data collected",
    "monitor.alert": "An alert was triggered",
    "monitor.health_changed": "Health status changed",

    "config.changed": "Configuration was changed",
    "error.unhandled": "An unhandled error occurred",
}