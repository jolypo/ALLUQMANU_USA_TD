from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Any

from app.config import settings


class JsonRepository:
    """
    Thread-safe JSON repository.

    Important:
    - Uses atomic file replacement to reduce corruption risk.
    - Keeps the existing interface:
        all()
        append()
        replace()
    - Suitable for current Paper Trading V1.

    Note:
    Render local filesystem is still ephemeral.
    This repository improves file safety, but it does NOT
    make Render local storage persistent across redeploys.
    """

    def __init__(
        self,
        name: str,
    ):
        self.path = (
            Path(settings.data_path)
            / name
        )

        self.lock = Lock()

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if not self.path.exists():
            self._write_atomic(
                []
            )

    # =========================================================
    # Internal Read
    # =========================================================

    def _read_unlocked(
        self,
    ) -> list[dict[str, Any]]:
        try:
            raw = self.path.read_text(
                encoding="utf-8"
            )

            data = json.loads(
                raw
            )

            if isinstance(
                data,
                list,
            ):
                return data

            return []

        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
        ):
            return []

    # =========================================================
    # Atomic Write
    # =========================================================

    def _write_atomic(
        self,
        data: list[dict[str, Any]],
    ) -> None:
        """
        Writes to a temporary file first,
        then atomically replaces the target file.

        This greatly reduces the chance of leaving
        half-written JSON after a crash/restart.
        """

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fd, temp_path = tempfile.mkstemp(
            prefix=(
                f".{self.path.name}."
            ),
            suffix=".tmp",
            dir=str(
                self.path.parent
            ),
        )

        try:
            with os.fdopen(
                fd,
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    data,
                    file,
                    ensure_ascii=False,
                    indent=2,
                )

                file.flush()

                os.fsync(
                    file.fileno()
                )

            os.replace(
                temp_path,
                self.path,
            )

        except Exception:
            try:
                if os.path.exists(
                    temp_path
                ):
                    os.remove(
                        temp_path
                    )
            except OSError:
                pass

            raise

    # =========================================================
    # Public API
    # =========================================================

    def all(
        self,
    ) -> list[dict[str, Any]]:
        with self.lock:
            return self._read_unlocked()

    def append(
        self,
        item: dict[str, Any],
    ) -> None:
        with self.lock:
            data = self._read_unlocked()

            data.append(
                item
            )

            self._write_atomic(
                data
            )

    def replace(
        self,
        data: list[dict[str, Any]],
    ) -> None:
        if not isinstance(
            data,
            list,
        ):
            raise TypeError(
                "JsonRepository.replace() "
                "expects list[dict]"
            )

        with self.lock:
            self._write_atomic(
                data
            )
