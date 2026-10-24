"""Kill only an owned inference child when its Python host exits, including crashes."""

import os
import subprocess
from typing import Any

from adam.compute.contracts import ComputeError


class ChildGuard:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.handle: Any = None
        if os.name != "nt":
            return
        try:
            import win32api  # type: ignore[import-untyped]
            import win32job  # type: ignore[import-untyped]

            self.handle = win32job.CreateJobObject(None, "")
            limits = win32job.QueryInformationJobObject(
                self.handle, win32job.JobObjectExtendedLimitInformation
            )
            limits["BasicLimitInformation"]["LimitFlags"] |= (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            )
            win32job.SetInformationJobObject(
                self.handle, win32job.JobObjectExtendedLimitInformation, limits
            )
            win32api.SetHandleInformation(self.handle, 1, 0)  # Never inherited by children.
            win32job.AssignProcessToJobObject(self.handle, int(process._handle))  # type: ignore[attr-defined]
        except Exception:
            self.close()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            raise ComputeError("MODEL.PROCESS_GUARD_FAILED") from None

    def close(self) -> None:
        if self.handle is not None:
            import win32api

            win32api.CloseHandle(self.handle)
            self.handle = None
