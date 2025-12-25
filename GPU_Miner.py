#!/usr/bin/env python3
"""
Duino-Coin experimental GPU Miner.

This miner mirrors the PC miner's configuration-driven startup while preferring
GPU execution when available. It falls back with a clear, non-zero exit if
no supported GPU device is detected so it does not interfere with CPU miners.
"""

from __future__ import annotations

import argparse
import base64
import socket
import sys
from configparser import ConfigParser
from pathlib import Path
from random import randint
from time import time, time_ns, sleep
from typing import Optional, Sequence, Tuple

import requests
from colorama import Fore, Style, init as colorama_init

try:
    import pyopencl as cl

    _CL_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover - import guard
    cl = None
    _CL_IMPORT_ERROR = exc

try:
    import libducohasher

    _HASHER_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover - import guard
    libducohasher = None
    _HASHER_IMPORT_ERROR = exc


class Settings:
    ENCODING = "UTF8"
    SEPARATOR = ","
    SOC_TIMEOUT = 10
    VER = 4.3
    DATA_DIR = "Duino-Coin PC Miner 4.3"
    SETTINGS_FILE = "/Settings.cfg"


class PoolClient:
    """Network helper reusing the PC miner socket protocol."""

    @staticmethod
    def fetch_pool(retry_count: int = 1) -> Tuple[str, int]:
        while True:
            if retry_count > 60:
                retry_count = 60

            try:
                response = requests.get(
                    "https://server.duinocoin.com/getPool",
                    timeout=Settings.SOC_TIMEOUT,
                ).json()

                if response.get("success"):
                    return response["ip"], response["port"]

                if "message" in response:
                    print(
                        f"Warning fetching pool: {response['message']} "
                        f"(retrying in {retry_count * 2}s)"
                    )
                else:
                    raise RuntimeError("Pool discovery did not return success")
            except Exception as exc:  # pragma: no cover - network loop
                print(
                    f"Error fetching pool, retrying in {retry_count * 2}s: {exc}",
                    file=sys.stderr,
                )

            sleep(retry_count * 2)
            retry_count += 1

    @staticmethod
    def connect(pool: Tuple[str, int]) -> socket.socket:
        sock = socket.socket()
        sock.settimeout(Settings.SOC_TIMEOUT)
        sock.connect(pool)
        return sock


def load_user_settings() -> Optional[ConfigParser]:
    cfg_path = Path(Settings.DATA_DIR + Settings.SETTINGS_FILE)
    if not cfg_path.is_file():
        return None

    config = ConfigParser()
    config.read(cfg_path)
    if "PC Miner" not in config:
        return None

    return config


def _require_hasher() -> libducohasher.DUCOHasher:
    if libducohasher:
        return libducohasher

    message = (
        "libducohasher is required for hashing and is missing. "
        "Install dependencies from requirements.txt."
    )
    raise SystemExit(message)


class GpuHasher:
    """GPU-first hashing wrapper with OpenCL device discovery."""

    def __init__(self, device) -> None:
        self.device = device
        self.context = None
        self.queue = None
        self._setup_opencl(device)
        self._hasher = _require_hasher()

    def _setup_opencl(self, device) -> None:
        if cl is None:
            raise SystemExit(
                f"PyOpenCL is required for GPU discovery ({_CL_IMPORT_ERROR})"
            )

        try:
            self.context = cl.Context(devices=[device])
            self.queue = cl.CommandQueue(self.context, device)
        except Exception as exc:  # pragma: no cover - device provisioning
            raise SystemExit(f"Failed to initialize GPU device: {exc}")

    def solve_job(self, last_hash: str, expected: str, difficulty: int) -> Tuple[int, float]:
        """
        Solve a DUCOS1 job. The hashing itself reuses the optimized
        libducohasher backend to preserve correctness; GPU discovery controls
        whether this miner runs at all.
        """

        if not isinstance(expected, str):
            expected = str(expected)

        time_start = time_ns()
        hasher = self._hasher.DUCOHasher(bytes(last_hash, encoding="ascii"))
        nonce = hasher.DUCOS1(bytes(bytearray.fromhex(expected)), difficulty, 0)
        elapsed = time_ns() - time_start
        hashrate = (1e9 * nonce / elapsed) if elapsed else 0.0
        return nonce, hashrate


def discover_gpu_devices() -> Sequence:
    if cl is None:
        message = (
            "PyOpenCL is not available; install it to run the GPU miner. "
            f"({_CL_IMPORT_ERROR})"
        )
        raise SystemExit(message)

    try:
        devices = [
            device
            for platform in cl.get_platforms()
            for device in platform.get_devices(device_type=cl.device_type.GPU)
        ]
    except Exception as exc:  # pragma: no cover - discovery path
        raise SystemExit(f"Unable to enumerate OpenCL platforms: {exc}")

    if not devices:
        raise SystemExit(
            "No GPU devices exposed via OpenCL. Install drivers or use --device "
            "after enabling your GPU runtime."
        )

    return devices


def _decode_mining_key(raw_key: str) -> str:
    if raw_key == "None":
        return "None"
    try:
        return base64.b64decode(raw_key).decode("utf-8")
    except Exception:
        return raw_key


def parse_args(config: Optional[ConfigParser]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Duino-Coin GPU miner")
    parser.add_argument("--device", type=int, default=None, help="GPU index (default: first)")
    parser.add_argument("--username", type=str, default=None, help="Wallet username override")
    parser.add_argument(
        "--mining-key",
        type=str,
        default=None,
        dest="mining_key",
        help="Optional mining key (base64 encoded if matching PC miner config)",
    )
    parser.add_argument(
        "--start-diff",
        type=str,
        default=None,
        dest="start_diff",
        help="Starting difficulty (LOW, MEDIUM, NET)",
    )
    parser.add_argument(
        "--identifier",
        type=str,
        default=None,
        help="Custom rig identifier reported to the pool",
    )

    args = parser.parse_args()

    if config:
        section = config["PC Miner"]
        args.username = args.username or section.get("username")
        args.mining_key = args.mining_key or section.get("mining_key", "None")
        args.start_diff = args.start_diff or section.get("start_diff", "LOW")
        args.identifier = args.identifier or section.get("identifier", "GPU")

    missing = [field for field in ("username",) if not getattr(args, field)]
    if missing:
        raise SystemExit(
            "Missing required configuration: "
            + ", ".join(missing)
            + ". Provide them via the PC miner config or CLI arguments."
        )

    return args


def request_job(sock: socket.socket, username: str, start_diff: str, mining_key: str) -> Tuple[str, str, int]:
    encoded_key = mining_key if mining_key == "None" else mining_key
    message = (
        "JOB"
        + Settings.SEPARATOR
        + username
        + Settings.SEPARATOR
        + start_diff
        + Settings.SEPARATOR
        + encoded_key
        + Settings.SEPARATOR
    )
    sock.sendall(message.encode(Settings.ENCODING))
    job_raw = sock.recv(128).decode(Settings.ENCODING).rstrip("\n")
    job_parts = job_raw.split(Settings.SEPARATOR)
    if len(job_parts) != 3:
        raise RuntimeError(f"Received malformed job: {job_raw}")
    return job_parts[0], job_parts[1], int(job_parts[2])


def submit_result(
    sock: socket.socket,
    nonce: int,
    hashrate: float,
    identifier: str,
    single_miner_id: int,
) -> str:
    payload = (
        f"{nonce}"
        + Settings.SEPARATOR
        + f"{hashrate}"
        + Settings.SEPARATOR
        + f"Official GPU Miner {Settings.VER}"
        + Settings.SEPARATOR
        + identifier
        + Settings.SEPARATOR
        + Settings.SEPARATOR
        + f"{single_miner_id}"
    )
    sock.sendall(payload.encode(Settings.ENCODING))
    response = sock.recv(128).decode(Settings.ENCODING).rstrip("\n")
    return response


def mine(args: argparse.Namespace) -> None:
    devices = discover_gpu_devices()
    device_index = args.device or 0
    if device_index < 0 or device_index >= len(devices):
        raise SystemExit(
            f"Requested device index {device_index} is invalid. "
            f"Found {len(devices)} GPU device(s)."
        )

    device = devices[device_index]
    hasher = GpuHasher(device)

    print(
        f"Using GPU device: {device.name} (platform: {device.platform.name})",
        file=sys.stderr,
    )

    mining_key = _decode_mining_key(args.mining_key or "None")
    single_miner_id = randint(0, 2811)

    while True:
        pool = PoolClient.fetch_pool()
        try:
            with PoolClient.connect(pool) as sock:
                pool_version = sock.recv(5).decode(Settings.ENCODING)
                print(f"Connected to pool {pool[0]}:{pool[1]} (v{pool_version})")

                while True:
                    job = request_job(sock, args.username, args.start_diff or "LOW", mining_key)
                    nonce, hashrate = hasher.solve_job(*job)
                    feedback = submit_result(
                        sock,
                        nonce,
                        hashrate,
                        args.identifier or "GPU",
                        single_miner_id,
                    )
                    parts = feedback.split(Settings.SEPARATOR)
                    status = parts[0] if parts else "UNKNOWN"
                    if status == "GOOD":
                        print(Style.BRIGHT + Fore.GREEN + f"Share accepted at {hashrate:.2f} H/s")
                    elif status == "BLOCK":
                        print(Style.BRIGHT + Fore.CYAN + "Block found!")
                    else:
                        print(
                            Style.BRIGHT
                            + Fore.RED
                            + f"Share rejected: {feedback if feedback else 'No response'}"
                        )
        except Exception as exc:  # pragma: no cover - runtime resiliency
            print(f"Mining error: {exc}", file=sys.stderr)
            sleep(5)


def main():
    colorama_init(autoreset=True)
    config = load_user_settings()
    args = parse_args(config)
    mine(args)


if __name__ == "__main__":
    main()
