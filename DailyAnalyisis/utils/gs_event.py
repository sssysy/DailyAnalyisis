from __future__ import annotations

from gsuid_core.models import Event


def event_platform_id(event: Event) -> str:
    return str(event.WS_BOT_ID or event.real_bot_id or event.bot_id or "gscore")


def event_umo(event: Event) -> str:
    platform_id = event_platform_id(event)
    if event.group_id:
        return f"{platform_id}:GroupMessage:{event.group_id}"
    return f"{platform_id}:FriendMessage:{event.user_id}"


def event_group_id(event: Event) -> str | None:
    if not event.group_id:
        return None
    return str(event.group_id)


def event_sender_name(event: Event) -> str:
    sender = event.sender
    return str(sender.get("card") or sender.get("nickname") or sender.get("name") or event.user_id)


__all__ = [
    "event_group_id",
    "event_platform_id",
    "event_sender_name",
    "event_umo",
]
