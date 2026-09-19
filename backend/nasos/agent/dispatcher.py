"""Binds RPC method names to handler coroutines and validates both sides of
every call. Handlers register themselves with `@handler("method.name")`;
importing `nasos.agent.handlers` (done once, in agent/main.py) is what
actually populates the registry — see that package's `__init__.py`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from nasos.rpc.schemas import (
    REGISTRY,
    RpcContext,
    RpcError,
    RpcException,
    RpcRequest,
    RpcResponse,
)

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("nasos.rpc.audit")

# Each handler's own Params/Result/state types are narrower than this (e.g.
# AuthLoginParams/AuthLoginResult/AgentState, not RpcModel/object), which is
# exactly right for the handler itself; the registry that stores handlers for
# many different methods necessarily erases that to Any, since dispatch is by
# runtime string lookup rather than a statically-checked call site. State is
# erased the same way so the same Dispatcher/REGISTRY/@handler machinery
# serves both the root agent (state: AgentState) and the per-user fileworker
# (state: WorkerState, agent/fileworker.py) — two different processes with
# two different state shapes registering into the same global REGISTRY, each
# only importing the handler modules meant for it.
HandlerFn = TypeVar("HandlerFn", bound=Callable[[Any, RpcContext, Any], Awaitable[Any]])

_HANDLERS: dict[str, Callable[[Any, RpcContext, Any], Awaitable[Any]]] = {}


def handler(method: str) -> Callable[[HandlerFn], HandlerFn]:
    """Decorator registering `fn` as the implementation of an RPC method
    declared in `nasos.rpc.schemas.REGISTRY`.
    """

    def decorate(fn: HandlerFn) -> HandlerFn:
        if method not in REGISTRY:
            raise KeyError(f"{method!r} is not declared in rpc.schemas.REGISTRY")
        if method in _HANDLERS:
            raise KeyError(f"{method!r} already has a handler")
        _HANDLERS[method] = fn
        return fn

    return decorate


class Dispatcher:
    """Validates, routes, and journals every RPC call (PLAN.md §1: "Every
    call ... is journaled").
    """

    def __init__(self, state: object) -> None:
        self._state = state

    async def handle(self, request: RpcRequest) -> RpcResponse:
        who = request.ctx.user or "anonymous"
        origin = f"{who}@{request.ctx.ip}" if request.ctx.ip else who

        spec = REGISTRY.get(request.method)
        if spec is None:
            audit_logger.warning("rpc %s by %s -> unknown method", request.method, origin)
            return _error(request.id, "unknown_method", f"no such method: {request.method}")

        fn = _HANDLERS.get(request.method)
        if fn is None:
            audit_logger.error("rpc %s by %s -> no handler registered", request.method, origin)
            return _error(request.id, "not_implemented", f"no handler for: {request.method}")

        try:
            params = spec.params.model_validate(request.params)
        except Exception as exc:  # pydantic.ValidationError
            audit_logger.warning("rpc %s by %s -> bad params: %s", request.method, origin, exc)
            return _error(request.id, "invalid_params", str(exc))

        try:
            result = await fn(params, request.ctx, self._state)
        except RpcException as exc:
            audit_logger.info("rpc %s by %s -> %s", request.method, origin, exc.code)
            return _error(request.id, exc.code, exc.message)
        except Exception:
            logger.exception("rpc %s by %s -> unhandled exception", request.method, origin)
            return _error(request.id, "internal_error", "internal error")

        audit_logger.info("rpc %s by %s -> ok", request.method, origin)
        return RpcResponse(id=request.id, ok=True, result=result.model_dump(mode="json"))


def _error(request_id: str, code: str, message: str) -> RpcResponse:
    return RpcResponse(id=request_id, ok=False, error=RpcError(code=code, message=message))
