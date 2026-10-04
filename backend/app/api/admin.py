"""Control plane: /admin/keys, /admin/stats, /admin/logs. Phases 2 and 4."""

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])
