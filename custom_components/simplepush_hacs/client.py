"""Simplepush client construction shared by the config flow and the notify service."""

from __future__ import annotations

from collections.abc import Mapping

from simplepush import Client


def create_client(
    api_token: str,
    password: str | None = None,
    topics: Mapping[str, str | None] | None = None,
) -> Client:
    """Build a personal Simplepush client.

    `password` is the personal password: it encrypts sends to your own devices.
    `topics` maps each topic to its password, or None for an unencrypted topic.
    The client encrypts a topic send with that topic's password on its own.
    """
    passwords: list[tuple[str, str] | str] = [
        (topic_password, topic)
        for topic, topic_password in (topics or {}).items()
        if topic_password
    ]
    if password:
        passwords.append(password)
    return Client(api_token=api_token, passwords=passwords or None)
