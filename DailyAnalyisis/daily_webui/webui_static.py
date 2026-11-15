from __future__ import annotations

from typing import Any
from pathlib import Path

from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from gsuid_core.webconsole.app_app import app

WEBUI_PATH = Path(__file__).resolve().parent.parent / "pages" / "daily-analysis"
WEBUI_ROUTE = "/daily-analyisis-gscore"


def _external_webui_enabled() -> bool:
    from gsuid_core.utils.plugins_config.models import GsBoolConfig

    from ..daily_config import DailyConfig

    field = DailyConfig.get_config("ExternalWebUIEnabled")
    if not isinstance(field, GsBoolConfig):
        return False
    return bool(field.data)


class _ExternalWebUIGate:
    def __init__(self, application: Any) -> None:
        self.application = application

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "http" and not _external_webui_enabled():
            response = JSONResponse(
                {"status": "disabled", "message": "DailyAnalyisis 外部 WebUI 当前已关闭"},
                status_code=404,
            )
            await response(scope, receive, send)
            return
        await self.application(scope, receive, send)


if WEBUI_PATH.is_dir() and not any(getattr(route, "path", None) == WEBUI_ROUTE for route in app.routes):
    app.mount(
        WEBUI_ROUTE,
        _ExternalWebUIGate(StaticFiles(directory=WEBUI_PATH, html=True)),
        name="daily-analyisis-gscore",
    )


__all__ = ["WEBUI_PATH", "WEBUI_ROUTE"]
