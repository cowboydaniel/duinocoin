"""Process management helpers for launching Duino Coin miners."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Iterable, List, Optional

STDOUT_BUFFER = 500


class ManagedMinerProcess:
    """Handle starting and stopping an individual miner process safely."""

    def __init__(self, script_path: Path, workdir: Optional[Path] = None) -> None:
        self.script_path = script_path
        self.workdir = workdir
        self.process: Optional[subprocess.Popen[str]] = None
        self._stdout_lines: deque[str] = deque(maxlen=STDOUT_BUFFER)
        self._stdout_thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def stdout(self) -> List[str]:
        return list(self._stdout_lines)

    def start(self, extra_args: Optional[Iterable[str]] = None) -> bool:
        if self.is_running:
            return True

        command = [sys.executable, str(self.script_path)]
        if extra_args:
            command.extend(extra_args)

        popen_kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "cwd": str(self.workdir) if self.workdir else None,
        }

        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["preexec_fn"] = os.setsid

        try:
            self.process = subprocess.Popen(command, **popen_kwargs)
        except OSError:
            self.process = None
            return False

        self._stdout_thread = threading.Thread(target=self._capture_stdout, daemon=True)
        self._stdout_thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        if not self.is_running or self.process is None:
            self.process = None
            return

        try:
            if os.name == "nt":
                self.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(self.process.pid, signal.SIGTERM)
        except (ProcessLookupError, ValueError):
            self.process.terminate()

        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
        finally:
            self.process = None

    def _capture_stdout(self) -> None:
        if not self.process or not self.process.stdout:
            return
        for line in self.process.stdout:
            self._stdout_lines.append(line.rstrip("\n"))


class MinerProcessManager:
    """Facade to manage both CPU and GPU miner subprocesses."""

    def __init__(self) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        self.cpu_miner = ManagedMinerProcess(base_dir / "PC_Miner.py", workdir=base_dir)
        self.gpu_miner = ManagedMinerProcess(base_dir / "GPU_Miner.py", workdir=base_dir)

    def start_cpu_miner(self) -> bool:
        return self.cpu_miner.start()

    def stop_cpu_miner(self) -> None:
        self.cpu_miner.stop()

    def start_gpu_miner(self) -> bool:
        return self.gpu_miner.start()

    def stop_gpu_miner(self) -> None:
        self.gpu_miner.stop()

    def stop_all(self) -> None:
        self.cpu_miner.stop()
        self.gpu_miner.stop()

    def is_cpu_running(self) -> bool:
        return self.cpu_miner.is_running

    def is_gpu_running(self) -> bool:
        return self.gpu_miner.is_running
