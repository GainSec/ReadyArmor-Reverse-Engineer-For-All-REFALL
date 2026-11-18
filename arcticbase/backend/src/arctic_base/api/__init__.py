from fastapi import APIRouter

from arctic_base.api import (
    agent,
    objects,
    refall_capabilities,
    refall_closeout,
    refall_coverage,
    refall_disposition,
    refall_ledger,
    refall_ops,
    refall_ops_commands,
    refall_ops_context,
    refall_ops_sse,
    refall_pending_actions,
    refall_reports,
    refall_runtime,
    refall_subjects,
    render,
    responses,
    theme,
    workbenches,
)

router = APIRouter(prefix="/api")
router.include_router(workbenches.router)
router.include_router(theme.router)
router.include_router(objects.router)
router.include_router(responses.router)
router.include_router(render.router)
router.include_router(agent.router)  # mounts /api/agent/*
router.include_router(refall_coverage.router)
router.include_router(refall_disposition.router)
router.include_router(refall_pending_actions.router)
router.include_router(refall_closeout.router)
router.include_router(refall_capabilities.router)
router.include_router(refall_runtime.router)
router.include_router(refall_ledger.router)
router.include_router(refall_ops.router)
router.include_router(refall_ops_context.router)
router.include_router(refall_ops_commands.router)
router.include_router(refall_ops_sse.router)
router.include_router(refall_reports.router)
router.include_router(refall_subjects.router)

# Root-level /agent → /openapi.json redirect, registered on the app separately.
agent_top = agent.top_router

__all__ = ["router", "agent_top"]
