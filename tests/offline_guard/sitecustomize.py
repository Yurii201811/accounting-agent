"""Fail-closed socket guard inherited by QA Python subprocesses."""

from __future__ import annotations

import os
import socket


if os.environ.get("ACCOUNTING_AGENT_TEST_OFFLINE") == "1":
    _ORIGINAL_SOCKET = socket.socket

    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("Network disabled by Accounting Agent QA guard")

    class _OfflineSocket(_ORIGINAL_SOCKET):
        def connect(self, *_args: object, **_kwargs: object) -> None:
            _blocked()

        def connect_ex(self, *_args: object, **_kwargs: object) -> int:
            _blocked()
            return 1

    socket.socket = _OfflineSocket
    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked
