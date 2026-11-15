"""Compatibility adapter between the plugin config API and runtime consumers."""

from __future__ import annotations

import json

from gsuid_core.utils.plugins_config.models import GsStrConfig

from ..daily_config.daily_config import DailyConfig, set_config


class PluginConfigAdapter(dict):
    """Mapping interface over the flat DailyConfig fields."""

    def _group_value(self, key: str) -> object | None:
        parts = key.split(".")
        for index in range(len(parts) - 1, 0, -1):
            source_key = ".".join(parts[:index])
            source_field = DailyConfig.config.get(source_key)
            if not isinstance(source_field, GsStrConfig):
                continue
            try:
                raw_value = json.loads(str(source_field.data))
            except (json.JSONDecodeError, TypeError):
                return None
            current = raw_value
            for part in parts[index:]:
                if not isinstance(current, dict) or part not in current:
                    return None
                current = current[part]
            return current
        return None

    def get(self, key: str, default=None):
        field = DailyConfig.config.get(key)
        value = field.data if field is not None else None
        if field is None:
            value = self._group_value(key)
            if value is None:
                return default
        if isinstance(value, str) and value.strip().startswith("{"):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        return value

    def __getitem__(self, key: str):
        field = DailyConfig.config.get(key)
        value = field.data if field is not None else None
        if field is None:
            value = self._group_value(key)
            if value is None:
                raise KeyError(key)
        return value

    def __setitem__(self, key: str, value: object) -> None:
        set_config(key, value)

    def save_config(self) -> None:
        DailyConfig.write_config()


__all__ = ["PluginConfigAdapter"]
