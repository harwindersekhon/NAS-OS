"""auth.* RPC methods."""

from __future__ import annotations

from nasos.agent.dispatcher import handler
from nasos.agent.state import AgentState
from nasos.rpc.schemas import AuthLoginParams, AuthLoginResult, RpcContext, RpcException


@handler("auth.login")
async def login(params: AuthLoginParams, ctx: RpcContext, state: AgentState) -> AuthLoginResult:  # noqa: ARG001
    identity = await state.authenticator.authenticate(params.username, params.password)
    if identity is None:
        raise RpcException("invalid_credentials", "invalid username or password")
    return identity
