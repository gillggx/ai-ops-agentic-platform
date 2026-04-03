"""Actions router — dispatch automation actions with human-in-the-loop gate."""

from fastapi import APIRouter, Depends

from app.core.response import StandardResponse
from app.dependencies import get_current_user
from app.models.user import UserModel
from app.schemas.automation import DispatchActionRequest
from app.services.action_dispatcher_service import ActionDispatcherService

router = APIRouter(prefix="/actions", tags=["actions"])


def _get_svc() -> ActionDispatcherService:
    return ActionDispatcherService()


@router.post("/dispatch", response_model=StandardResponse)
async def dispatch_action(
    body: DispatchActionRequest,
    svc: ActionDispatcherService = Depends(_get_svc),
    _: UserModel = Depends(get_current_user),
):
    """Dispatch an automation action.

    Returns ``requires_confirm=true`` for critical actions — the frontend must
    display a confirmation dialog before re-calling with ``auto_execute=true``.
    """
    result = await svc.dispatch(body)
    return StandardResponse.success(data=result.model_dump())
