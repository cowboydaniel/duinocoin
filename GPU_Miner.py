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
import math
import socket
import sys
from datetime import datetime
from configparser import ConfigParser
from hashlib import sha1
from pathlib import Path
from random import randint
from time import time, time_ns, sleep
from typing import Optional, Sequence, Tuple

import numpy as np
import requests
from colorama import Fore, Style, init as colorama_init
from queue import Queue, Empty
from threading import Event, Thread

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
    GPU_SETTINGS_FILE = "/GPU_Settings.cfg"


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


def load_gpu_settings() -> Optional[ConfigParser]:
    cfg_path = Path(Settings.DATA_DIR + Settings.GPU_SETTINGS_FILE)
    if not cfg_path.is_file():
        return None

    config = ConfigParser()
    config.read(cfg_path)
    if "GPU Miner" not in config:
        return None

    return config


def _require_hasher() -> libducohasher.DUCOHasher:
    if libducohasher:
        return libducohasher

    message = (
        "libducohasher is required for hashing and is missing. Install GPU miner "
        "dependencies manually with `python3 -m pip install -r requirements.txt` "
        "or `python3 -m pip install libducohasher`. Auto-install for GPU "
        "dependencies is intentionally disabled because it depends on system "
        "drivers."
    )
    raise SystemExit(message)


def _require_opencl() -> None:
    if cl is not None:
        return

    message = (
        "PyOpenCL is required for the GPU backend and is not installed. Install it "
        "manually with `python3 -m pip install pyopencl` (or "
        "`python3 -m pip install -r requirements.txt`). GPU dependencies are not "
        "auto-installed because they require vendor drivers and headers."
    )
    raise SystemExit(message)


class GpuHasher:
    """GPU-first hashing wrapper with OpenCL device discovery."""

    KERNEL_SOURCE = r"""
    __kernel void ducos1(
        __global const uchar* base_msg,
        const uchar base_len,
        const uint start_nonce,
        const uint nonce_count,
        __global const uchar* expected,
        __global uint* found_nonce,
        __global int* found_flag)
    {
        size_t gid = get_global_id(0);
        if (gid >= nonce_count)
            return;

        if (atomic_or(found_flag, 0) != 0)
            return;

        uint nonce = start_nonce + (uint)gid;

        uchar message[80];
        for (uint i = 0; i < base_len; ++i) {
            message[i] = base_msg[i];
        }

        uchar digits[10];
        uint temp = nonce;
        uchar digit_count = 0;
        do {
            digits[digit_count++] = (uchar)('0' + (temp % 10));
            temp /= 10;
        } while (temp > 0 && digit_count < 10);

        for (uint i = 0; i < digit_count; ++i) {
            message[base_len + i] = digits[digit_count - 1 - i];
        }

        uint msg_len = base_len + digit_count;
        int length_index = 56;
        int total_blocks = 1;
        if ((msg_len + 1 + 8) > 64) {
            length_index = 120;
            total_blocks = 2;
        }

        uchar padded[128];
        for (uint i = 0; i < 128; ++i) {
            padded[i] = 0;
        }

        for (uint i = 0; i < msg_len; ++i) {
            padded[i] = message[i];
        }
        padded[msg_len] = 0x80;

        ulong bit_len = ((ulong)msg_len) * 8;
        padded[length_index + 0] = (uchar)((bit_len >> 56) & 0xFF);
        padded[length_index + 1] = (uchar)((bit_len >> 48) & 0xFF);
        padded[length_index + 2] = (uchar)((bit_len >> 40) & 0xFF);
        padded[length_index + 3] = (uchar)((bit_len >> 32) & 0xFF);
        padded[length_index + 4] = (uchar)((bit_len >> 24) & 0xFF);
        padded[length_index + 5] = (uchar)((bit_len >> 16) & 0xFF);
        padded[length_index + 6] = (uchar)((bit_len >> 8) & 0xFF);
        padded[length_index + 7] = (uchar)(bit_len & 0xFF);

        uint h0 = 0x67452301;
        uint h1 = 0xEFCDAB89;
        uint h2 = 0x98BADCFE;
        uint h3 = 0x10325476;
        uint h4 = 0xC3D2E1F0;

        for (int block = 0; block < total_blocks; ++block) {
            uint w[80];
            int offset = block * 64;
            for (int t = 0; t < 16; ++t) {
                int idx = offset + t * 4;
                w[t] = ((uint)padded[idx] << 24) |
                       ((uint)padded[idx + 1] << 16) |
                       ((uint)padded[idx + 2] << 8) |
                       ((uint)padded[idx + 3]);
            }

            for (int t = 16; t < 80; ++t) {
                uint v = w[t - 3] ^ w[t - 8] ^ w[t - 14] ^ w[t - 16];
                w[t] = (v << 1) | (v >> 31);
            }

            uint a = h0;
            uint b = h1;
            uint c = h2;
            uint d = h3;
            uint e = h4;

            for (int t = 0; t < 80; ++t) {
                uint f;
                uint k;
                if (t < 20) {
                    f = (b & c) | ((~b) & d);
                    k = 0x5A827999;
                } else if (t < 40) {
                    f = b ^ c ^ d;
                    k = 0x6ED9EBA1;
                } else if (t < 60) {
                    f = (b & c) | (b & d) | (c & d);
                    k = 0x8F1BBCDC;
                } else {
                    f = b ^ c ^ d;
                    k = 0xCA62C1D6;
                }

                uint tempv = ((a << 5) | (a >> 27)) + f + e + k + w[t];
                e = d;
                d = c;
                c = (b << 30) | (b >> 2);
                b = a;
                a = tempv;
            }

            h0 += a;
            h1 += b;
            h2 += c;
            h3 += d;
            h4 += e;
        }

        uchar digest[20];
        uint hs[5] = {h0, h1, h2, h3, h4};
        for (int i = 0; i < 5; ++i) {
            digest[i * 4 + 0] = (uchar)((hs[i] >> 24) & 0xFF);
            digest[i * 4 + 1] = (uchar)((hs[i] >> 16) & 0xFF);
            digest[i * 4 + 2] = (uchar)((hs[i] >> 8) & 0xFF);
            digest[i * 4 + 3] = (uchar)(hs[i] & 0xFF);
        }

        uchar match = 1;
        for (int i = 0; i < 20; ++i) {
            if (digest[i] != expected[i]) {
                match = 0;
                break;
            }
        }

        if (match) {
            if (atomic_cmpxchg(found_flag, 0, 1) == 0) {
                found_nonce[0] = nonce;
            }
        }
    }
    """

    def __init__(
        self,
        device,
        work_size: Optional[int],
        batch_multiplier: Optional[float],
        autotune_max_multiplier: Optional[float],
        autotune_samples: Optional[int],
        autotune_min_delta_scale: Optional[float],
    ) -> None:
        self.device = device
        self.context: Optional[cl.Context] = None
        self.queue: Optional[cl.CommandQueue] = None
        self.program: Optional[cl.Program] = None
        self.kernel: Optional[cl.Kernel] = None
        self.max_group = None
        self.compute_units = None
        self.max_items_dim0 = None
        self.batch_size = None
        self.work_group_size = None
        self.requested_work_size = work_size
        self.batch_multiplier_override = batch_multiplier is not None
        self.batch_multiplier = float(batch_multiplier) if batch_multiplier else 2.0
        self.autotune_max_multiplier_override = autotune_max_multiplier
        self.autotune_samples = (
            autotune_samples if autotune_samples is not None else 10
        )
        if self.autotune_samples < 2:
            self.autotune_samples = 2
        self.autotune_min_delta_scale = (
            autotune_min_delta_scale
            if autotune_min_delta_scale is not None and autotune_min_delta_scale > 0
            else 0.5
        )
        self.autotune_done = False
        self._setup_opencl(device)
        self._build_program()

    def _setup_opencl(self, device) -> None:
        if cl is None:
            raise SystemExit(
                f"PyOpenCL is required for GPU discovery ({_CL_IMPORT_ERROR})"
            )

        try:
            self.context = cl.Context(devices=[device])
            self.queue = cl.CommandQueue(self.context, device)
            self.max_group = int(device.get_info(cl.device_info.MAX_WORK_GROUP_SIZE))
            max_item_sizes = device.get_info(cl.device_info.MAX_WORK_ITEM_SIZES)
            self.max_items_dim0 = int(max_item_sizes[0]) if max_item_sizes else self.max_group
            self.compute_units = int(device.get_info(cl.device_info.MAX_COMPUTE_UNITS))
            self.work_group_size = self._resolve_work_group_size()
            self._update_batch_size()
        except Exception as exc:  # pragma: no cover - device provisioning
            raise SystemExit(f"Failed to initialize GPU device: {exc}")

    def _build_program(self) -> None:
        try:
            self.program = cl.Program(self.context, self.KERNEL_SOURCE).build()
            self.kernel = cl.Kernel(self.program, "ducos1")
        except Exception as exc:  # pragma: no cover - kernel compilation
            raise SystemExit(f"Failed to compile OpenCL kernel: {exc}")

    def _resolve_work_group_size(self) -> int:
        max_allowed = min(self.max_group, self.max_items_dim0)

        preferred_sizes = (1024, 512, 256, 128, 64)
        default_size = next(
            (size for size in preferred_sizes if size <= max_allowed),
            max_allowed,
        )

        if self.requested_work_size is None:
            return default_size

        if self.requested_work_size <= 0:
            raise SystemExit("Work size must be a positive integer.")

        limit = max_allowed
        if self.requested_work_size > limit:
            print(
                f"Requested work size {self.requested_work_size} exceeds device limit "
                f"{limit}; using {limit} instead.",
                file=sys.stderr,
            )
        return min(self.requested_work_size, limit)

    def _global_size(self, count: int) -> int:
        group = self.work_group_size
        groups = (count + group - 1) // group
        return max(group, groups * group)

    def _batch_size_for_multiplier(self, multiplier: float) -> int:
        raw_size = int(self.work_group_size * self.compute_units * multiplier)
        max_batch_limit = self.max_items_dim0 * max(1, self.compute_units) * 8
        clamped = min(max(self.work_group_size, raw_size), max_batch_limit)
        groups = max(1, clamped // self.work_group_size)
        return groups * self.work_group_size

    def _update_batch_size(self) -> None:
        self.batch_size = self._batch_size_for_multiplier(self.batch_multiplier)

    def _benchmark_multiplier(
        self,
        multiplier: float,
        last_buf,
        expected_buf,
        found_nonce_buf,
        found_flag_buf,
        last_len: int,
    ) -> Tuple[float, Sequence[float]]:
        nonce_count = self._batch_size_for_multiplier(multiplier)
        sample_rates = []

        for _ in range(self.autotune_samples):
            cl.enqueue_fill_buffer(self.queue, found_flag_buf, b"\x00\x00\x00\x00", 0, 4)

            self.kernel.set_args(
                last_buf,
                np.uint8(last_len),
                np.uint32(0),
                np.uint32(nonce_count),
                expected_buf,
                found_nonce_buf,
                found_flag_buf,
            )

            start = time_ns()
            cl.enqueue_nd_range_kernel(
                self.queue,
                self.kernel,
                (self._global_size(nonce_count),),
                (self.work_group_size,),
            )
            self.queue.finish()
            elapsed = time_ns() - start
            if elapsed > 0:
                sample_rates.append(1e9 * nonce_count / elapsed)

        if not sample_rates:
            return 0.0, sample_rates

        sorted_rates = sorted(sample_rates)
        mid = len(sorted_rates) // 2
        if len(sorted_rates) % 2 == 0:
            median_rate = (sorted_rates[mid - 1] + sorted_rates[mid]) / 2
        else:
            median_rate = sorted_rates[mid]
        return median_rate, sample_rates

    def _max_autotune_multiplier(self) -> float:
        if self.autotune_max_multiplier_override:
            return max(1.0, min(60.0, float(self.autotune_max_multiplier_override)))

        if not self.work_group_size or not self.max_items_dim0:
            return 60.0

        theoretical_cap = (self.max_items_dim0 * 8) / float(self.work_group_size)
        bounded_limit = min(theoretical_cap, 60.0)
        if bounded_limit <= 0:
            return 1.0
        if theoretical_cap < 1.0:
            return theoretical_cap
        return max(1.0, bounded_limit)

    def _autotune_multiplier(
        self,
        last_buf,
        expected_buf,
        found_nonce_buf,
        found_flag_buf,
        last_len: int,
    ) -> None:
        if self.autotune_done or self.batch_multiplier_override:
            return

        plateau_tolerance = 0.05
        max_multiplier = self._max_autotune_multiplier()
        step = 1.0

        best_multiplier = self.batch_multiplier
        best_rate = 0.0
        multiplier = self.batch_multiplier

        while multiplier <= max_multiplier:
            rate, samples = self._benchmark_multiplier(
                multiplier,
                last_buf,
                expected_buf,
                found_nonce_buf,
                found_flag_buf,
                last_len,
            )
            if not samples:
                break

            mean = sum(samples) / len(samples)
            variance = sum((val - mean) ** 2 for val in samples) / len(samples)
            relative_std = math.sqrt(variance) / mean if mean else 0.0
            dynamic_tolerance = max(
                plateau_tolerance, relative_std * self.autotune_min_delta_scale
            )

            if rate > best_rate * (1 + dynamic_tolerance):
                best_rate = rate
                best_multiplier = multiplier
                multiplier += step
            else:
                break

        if best_multiplier != self.batch_multiplier:
            print(
                f"Auto-tuned batch multiplier to {best_multiplier} "
                f"(batch size {self._batch_size_for_multiplier(best_multiplier)}, "
                f"{self.autotune_samples} samples, max {max_multiplier:.1f})",
                file=sys.stderr,
            )
        self.batch_multiplier = best_multiplier
        self.autotune_done = True
        self._update_batch_size()

    def solve_job(self, last_hash: str, expected: str, difficulty: int) -> Tuple[int, float, float]:
        if not isinstance(expected, str):
            expected = str(expected)

        mf = cl.mem_flags
        try:
            last_bytes = bytes(last_hash, encoding="ascii")
            expected_bytes = bytes(bytearray.fromhex(expected))
        except Exception:
            raise SystemExit("Invalid job payload received; cannot encode hashes.")

        if len(last_bytes) > 70:
            raise SystemExit("Job payload too large for GPU kernel input buffer.")

        if len(expected_bytes) != 20:
            raise SystemExit(f"Expected hash must be 20 bytes (got {len(expected_bytes)})")

        last_buf = cl.Buffer(self.context, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=last_bytes)
        expected_buf = cl.Buffer(
            self.context, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=expected_bytes
        )
        found_nonce_buf = cl.Buffer(
            self.context, mf.ALLOC_HOST_PTR | mf.READ_WRITE, size=4
        )
        found_flag_buf = cl.Buffer(
            self.context, mf.ALLOC_HOST_PTR | mf.READ_WRITE, size=4
        )

        self._autotune_multiplier(
            last_buf,
            expected_buf,
            found_nonce_buf,
            found_flag_buf,
            len(last_bytes),
        )
        mapping_supported = False
        try:
            probe_view, probe_event = cl.enqueue_map_buffer(
                self.queue,
                found_flag_buf,
                cl.map_flags.READ | cl.map_flags.WRITE,
                offset=0,
                shape=(1,),
                dtype=np.int32,
                is_blocking=False,
            )
            probe_event.wait()
            probe_view[...] = 0
            probe_unmap = cl.enqueue_unmap_mem_object(self.queue, found_flag_buf, probe_view)
            probe_unmap.wait()
            mapping_supported = True
        except Exception:
            self.queue.finish()
            mapping_supported = False

        nonce_limit = int(difficulty) * 100 + 1
        start_nonce = 0
        found_nonce = -1
        total_processed = 0

        flag_hosts = [np.zeros(1, dtype=np.int32), np.zeros(1, dtype=np.int32)] if not mapping_supported else None
        nonce_host = np.zeros(1, dtype=np.uint32) if not mapping_supported else None
        pending_result = None
        buffer_wait_event = None
        buffer_index = 0
        batch_latencies_ms = []

        time_start = time_ns()
        while start_nonce < nonce_limit and found_nonce == -1:
            if pending_result:
                if mapping_supported:
                    (
                        map_event,
                        kernel_event,
                        mapped_flag,
                        prev_batch,
                        prev_start,
                        batch_start_time,
                    ) = pending_result
                    map_event.wait()
                    batch_latencies_ms.append((time_ns() - batch_start_time) / 1e6)
                    found = int(mapped_flag[0]) != 0
                    unmap_event = cl.enqueue_unmap_mem_object(
                        self.queue,
                        found_flag_buf,
                        mapped_flag,
                        wait_for=[map_event],
                    )
                    buffer_wait_event = unmap_event
                    if found:
                        nonce_map, nonce_event = cl.enqueue_map_buffer(
                            self.queue,
                            found_nonce_buf,
                            cl.map_flags.READ,
                            offset=0,
                            shape=(1,),
                            dtype=np.uint32,
                            wait_for=[kernel_event],
                            is_blocking=False,
                        )
                        nonce_event.wait()
                        found_nonce = int(nonce_map[0])
                        nonce_unmap = cl.enqueue_unmap_mem_object(
                            self.queue,
                            found_nonce_buf,
                            nonce_map,
                            wait_for=[nonce_event],
                        )
                        nonce_unmap.wait()
                        total_processed = found_nonce + 1
                        break
                    total_processed = prev_start + prev_batch
                else:
                    (
                        prev_copy,
                        prev_kernel,
                        prev_buffer,
                        prev_batch,
                        prev_start,
                        batch_start_time,
                    ) = pending_result
                    prev_copy.wait()
                    batch_latencies_ms.append((time_ns() - batch_start_time) / 1e6)
                    found = int(prev_buffer[0]) != 0
                    if found:
                        nonce_event = cl.enqueue_copy(
                            self.queue,
                            nonce_host,
                            found_nonce_buf,
                            wait_for=[prev_kernel],
                            is_blocking=False,
                        )
                        nonce_event.wait()
                        found_nonce = int(nonce_host[0])
                        total_processed = found_nonce + 1
                        break
                    total_processed = prev_start + prev_batch
                pending_result = None

            if found_nonce != -1 or start_nonce >= nonce_limit:
                break

            batch = min(self.batch_size, nonce_limit - start_nonce)
            global_size = self._global_size(batch)
            nonce_count = batch

            wait_for = [buffer_wait_event] if buffer_wait_event else None
            fill_event = cl.enqueue_fill_buffer(
                self.queue,
                found_flag_buf,
                b"\x00\x00\x00\x00",
                0,
                4,
                wait_for=wait_for,
            )
            self.kernel.set_args(
                last_buf,
                np.uint8(len(last_bytes)),
                np.uint32(start_nonce),
                np.uint32(nonce_count),
                expected_buf,
                found_nonce_buf,
                found_flag_buf,
            )
            kernel_event = cl.enqueue_nd_range_kernel(
                self.queue,
                self.kernel,
                (global_size,),
                (self.work_group_size,),
                wait_for=[fill_event],
            )

            if mapping_supported:
                flag_map, map_event = cl.enqueue_map_buffer(
                    self.queue,
                    found_flag_buf,
                    cl.map_flags.READ,
                    offset=0,
                    shape=(1,),
                    dtype=np.int32,
                    wait_for=[kernel_event],
                    is_blocking=False,
                )
                pending_result = (
                    map_event,
                    kernel_event,
                    flag_map,
                    batch,
                    start_nonce,
                    time_ns(),
                )
                buffer_wait_event = map_event
            else:
                flag_host = flag_hosts[buffer_index]
                buffer_index ^= 1
                copy_event = cl.enqueue_copy(
                    self.queue,
                    flag_host,
                    found_flag_buf,
                    wait_for=[kernel_event],
                    is_blocking=False,
                )
                pending_result = (
                    copy_event,
                    kernel_event,
                    flag_host,
                    batch,
                    start_nonce,
                    time_ns(),
                )
                buffer_wait_event = copy_event
            start_nonce += batch

        if found_nonce == -1 and pending_result:
            if mapping_supported:
                (
                    map_event,
                    kernel_event,
                    mapped_flag,
                    prev_batch,
                    prev_start,
                    batch_start_time,
                ) = pending_result
                map_event.wait()
                batch_latencies_ms.append((time_ns() - batch_start_time) / 1e6)
                if int(mapped_flag[0]) != 0:
                    nonce_map, nonce_event = cl.enqueue_map_buffer(
                        self.queue,
                        found_nonce_buf,
                        cl.map_flags.READ,
                        offset=0,
                        shape=(1,),
                        dtype=np.uint32,
                        wait_for=[kernel_event],
                        is_blocking=False,
                    )
                    nonce_event.wait()
                    found_nonce = int(nonce_map[0])
                    nonce_unmap = cl.enqueue_unmap_mem_object(
                        self.queue,
                        found_nonce_buf,
                        nonce_map,
                        wait_for=[nonce_event],
                    )
                    nonce_unmap.wait()
                    total_processed = found_nonce + 1
                else:
                    total_processed = max(total_processed, prev_start + prev_batch)
                unmap_event = cl.enqueue_unmap_mem_object(
                    self.queue,
                    found_flag_buf,
                    mapped_flag,
                    wait_for=[map_event],
                )
                unmap_event.wait()
            else:
                (
                    prev_copy,
                    prev_kernel,
                    prev_buffer,
                    prev_batch,
                    prev_start,
                    batch_start_time,
                ) = pending_result
                prev_copy.wait()
                batch_latencies_ms.append((time_ns() - batch_start_time) / 1e6)
                if int(prev_buffer[0]) != 0:
                    nonce_event = cl.enqueue_copy(
                        self.queue,
                        nonce_host,
                        found_nonce_buf,
                        wait_for=[prev_kernel],
                        is_blocking=False,
                    )
                    nonce_event.wait()
                    found_nonce = int(nonce_host[0])
                    total_processed = found_nonce + 1
                else:
                    total_processed = max(total_processed, prev_start + prev_batch)

        if batch_latencies_ms:
            avg_latency = sum(batch_latencies_ms) / len(batch_latencies_ms)
            print(
                f"Avg GPU batch latency: {avg_latency:.3f} ms over {len(batch_latencies_ms)} batches",
                file=sys.stderr,
            )

        elapsed = time_ns() - time_start
        elapsed_seconds = elapsed / 1e9 if elapsed else 0.0
        hashrate = (1e9 * total_processed / elapsed) if elapsed else 0.0
        return (
            found_nonce if found_nonce != -1 else nonce_limit,
            hashrate,
            elapsed_seconds,
        )


def gpu_worker(
    hasher: GpuHasher,
    job_queue: Queue,
    result_queue: Queue,
    stop_event: Event,
) -> None:
    while not stop_event.is_set():
        try:
            job = job_queue.get(timeout=1)
        except Empty:
            continue

        last_hash, expected, difficulty = job
        try:
            nonce, hashrate, elapsed = hasher.solve_job(last_hash, expected, difficulty)
            result_queue.put((job, nonce, hashrate, elapsed, None))
        except Exception as exc:  # pragma: no cover - worker safety
            result_queue.put((job, None, 0.0, 0.0, exc))


def discover_gpu_devices() -> Sequence:
    if cl is None:
        _require_opencl()

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
            "No GPU devices exposed via OpenCL. Install vendor GPU drivers/runtime, "
            "ensure OpenCL ICDs are present, then retry."
        )

    return devices


def _decode_mining_key(raw_key: str) -> str:
    if raw_key == "None":
        return "None"
    try:
        return base64.b64decode(raw_key).decode("utf-8")
    except Exception:
        return raw_key


def get_prefix(symbol: str, val: float, accuracy: int) -> str:
    """
    Convert hashrate or difficulty figures to human friendly units.
    """
    if val >= 1_000_000_000_000:
        val = str(round((val / 1_000_000_000_000), accuracy)) + " T"
    elif val >= 1_000_000_000:
        val = str(round((val / 1_000_000_000), accuracy)) + " G"
    elif val >= 1_000_000:
        val = str(round((val / 1_000_000), accuracy)) + " M"
    elif val >= 1_000:
        val = str(round((val / 1_000), accuracy)) + " k"
    else:
        val = str(round(val)) + " "
    return val + symbol


def parse_args(
    config: Optional[ConfigParser], gpu_config: Optional[ConfigParser]
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Duino-Coin GPU miner")
    parser.add_argument(
        "--backend",
        type=str,
        choices=("opencl",),
        default=None,
        help="Hashing backend to use (default: opencl)",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="GPU index (default: first or GPU_Settings.cfg value)",
    )
    parser.add_argument(
        "--work-size",
        type=int,
        dest="work_size",
        default=None,
        help="Override kernel work group size (default: auto-detected)",
    )
    parser.add_argument(
        "--batch-multiplier",
        type=float,
        dest="batch_multiplier",
        default=None,
        help=(
            "Scale batch size beyond compute_units*2 (default: auto + autotune). "
            "Higher values increase queued nonces; lower values reduce latency."
        ),
    )
    parser.add_argument(
        "--autotune-max-multiplier",
        type=float,
        dest="autotune_max_multiplier",
        default=None,
        help="Upper bound for batch multiplier autotuning (default: device-derived).",
    )
    parser.add_argument(
        "--autotune-samples",
        type=int,
        dest="autotune_samples",
        default=None,
        help="Micro-benchmark samples per multiplier during autotune (default: 10).",
    )
    parser.add_argument(
        "--autotune-min-delta-scale",
        type=float,
        dest="autotune_min_delta_scale",
        default=None,
        help=(
            "Scale factor for variance-driven improvement threshold; larger values "
            "require bigger gains to keep tuning (default: 0.5)."
        ),
    )
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

    if gpu_config:
        section = gpu_config["GPU Miner"]
        args.backend = args.backend or section.get("backend", fallback=None)

        device_fallback = section.get("device", fallback=None)
        if args.device is None and device_fallback is not None:
            args.device = section.getint("device")

        work_size_fallback = section.get("work_size", fallback=None)
        if args.work_size is None and work_size_fallback is not None:
            args.work_size = section.getint("work_size")

        batch_mult_fallback = section.get("batch_multiplier", fallback=None)
        if args.batch_multiplier is None and batch_mult_fallback is not None:
            args.batch_multiplier = section.getfloat("batch_multiplier")

        auto_max_fallback = section.get("autotune_max_multiplier", fallback=None)
        if args.autotune_max_multiplier is None and auto_max_fallback is not None:
            args.autotune_max_multiplier = section.getfloat("autotune_max_multiplier")

        auto_samples_fallback = section.get("autotune_samples", fallback=None)
        if args.autotune_samples is None and auto_samples_fallback is not None:
            args.autotune_samples = section.getint("autotune_samples")

        auto_delta_fallback = section.get("autotune_min_delta_scale", fallback=None)
        if args.autotune_min_delta_scale is None and auto_delta_fallback is not None:
            args.autotune_min_delta_scale = section.getfloat("autotune_min_delta_scale")

    args.backend = (args.backend or "opencl").lower()
    if args.work_size is not None and args.work_size <= 0:
        raise SystemExit("Work size must be a positive integer.")
    if args.batch_multiplier is not None and args.batch_multiplier <= 0:
        raise SystemExit("Batch multiplier must be a positive number.")
    if args.autotune_max_multiplier is not None and args.autotune_max_multiplier <= 0:
        raise SystemExit("Autotune max multiplier must be a positive number.")
    if args.autotune_samples is not None and args.autotune_samples < 2:
        raise SystemExit("Autotune samples must be at least 2 to be meaningful.")
    if args.autotune_min_delta_scale is not None and args.autotune_min_delta_scale <= 0:
        raise SystemExit("Autotune minimum delta scale must be positive.")

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
) -> Tuple[str, float]:
    payload = (
        f"{nonce}"
        + Settings.SEPARATOR
        + f"{hashrate}"
        + Settings.SEPARATOR
        + "Experimental GPU Miner 1.0"
        + Settings.SEPARATOR
        + identifier
        + Settings.SEPARATOR
        + Settings.SEPARATOR
        + f"{single_miner_id}"
    )
    start = time()
    sock.sendall(payload.encode(Settings.ENCODING))
    response = sock.recv(128).decode(Settings.ENCODING).rstrip("\n")
    ping_ms = (time() - start) * 1000
    return response, ping_ms


def mine(args: argparse.Namespace) -> None:
    if args.backend != "opencl":
        raise SystemExit(
            f"Unsupported backend '{args.backend}'. Supported backends: opencl."
        )

    _require_opencl()
    _require_hasher()

    devices = discover_gpu_devices()
    device_index = 0 if args.device is None else args.device
    if device_index < 0 or device_index >= len(devices):
        raise SystemExit(
            f"Requested device index {device_index} is invalid. "
            f"Found {len(devices)} GPU device(s)."
        )

    device = devices[device_index]
    hasher = GpuHasher(
        device,
        args.work_size,
        args.batch_multiplier,
        args.autotune_max_multiplier,
        args.autotune_samples,
        args.autotune_min_delta_scale,
    )

    print(
        f"Using GPU device: {device.name} (platform: {device.platform.name})",
        file=sys.stderr,
    )

    job_queue: Queue = Queue(maxsize=8)
    result_queue: Queue = Queue(maxsize=8)
    stop_event = Event()
    accept_count = 0
    reject_count = 0
    worker = Thread(
        target=gpu_worker,
        args=(hasher, job_queue, result_queue, stop_event),
        daemon=True,
    )
    worker.start()

    mining_key = _decode_mining_key(args.mining_key or "None")
    single_miner_id = randint(0, 2811)

    while True:
        pool = PoolClient.fetch_pool()
        try:
            with PoolClient.connect(pool) as sock:
                pool_version = sock.recv(5).decode(Settings.ENCODING)
                print(f"Connected to pool {pool[0]}:{pool[1]} (v{pool_version})")

                while True:
                    time_start = time()
                    job = request_job(sock, args.username, args.start_diff or "LOW", mining_key)
                    ping_ms = (time() - time_start) * 1000
                    try:
                        job_queue.put(job, timeout=Settings.SOC_TIMEOUT)
                    except Exception:
                        print("GPU queue backpressure encountered; retrying", file=sys.stderr)
                        continue

                    try:
                        job_result = result_queue.get(timeout=Settings.SOC_TIMEOUT * 2)
                    except Empty:
                        print("GPU worker timeout waiting for result", file=sys.stderr)
                        continue

                    (last_hash, expected, difficulty), nonce, hashrate, compute_time, error = job_result
                    expected_hex = expected.lower()

                    if error:
                        print(f"GPU worker failed: {error}", file=sys.stderr)
                        continue

                    candidate_hash = sha1(f"{last_hash}{nonce}".encode("ascii")).hexdigest()
                    if candidate_hash != expected_hex:
                        print(
                            Style.BRIGHT
                            + Fore.YELLOW
                            + f"Discarded invalid share from GPU (nonce={nonce})",
                            file=sys.stderr,
                        )
                        continue

                    feedback, response_ping = submit_result(
                        sock,
                        nonce,
                        hashrate,
                        args.identifier or "GPU",
                        single_miner_id,
                    )
                    parts = feedback.split(Settings.SEPARATOR)
                    status = parts[0] if parts else "UNKNOWN"
                    total_ping = ping_ms + response_ping
                    total_shares = accept_count + reject_count + 1
                    success_percent = (
                        (accept_count + (1 if status in ("GOOD", "BLOCK") else 0))
                        / total_shares
                        * 100
                    )
                    hashrate_pretty = get_prefix("H/s", hashrate, 2)
                    total_hashrate_pretty = get_prefix("H/s", hashrate, 2)
                    diff_pretty = get_prefix("", int(difficulty), 0).strip()
                    worker_label = args.identifier or f"gpu{device_index}"
                    share_header = (
                        Fore.WHITE
                        + datetime.now().strftime(Style.DIM + "%H:%M:%S ")
                        + Style.RESET_ALL
                        + Style.BRIGHT
                        + Fore.YELLOW
                        + f" {worker_label} "
                        + Style.RESET_ALL
                        + Fore.GREEN
                        + "⛏ "
                    )
                    if status == "GOOD":
                        accept_count += 1
                        print(
                            share_header
                            + Fore.GREEN
                            + "Accepted "
                            + f"{accept_count}/{total_shares} ({success_percent:.0f}%) "
                            + Style.NORMAL
                            + Fore.RESET
                            + f"∙ {compute_time:04.1f}s ∙ "
                            + Fore.BLUE
                            + Style.BRIGHT
                            + f"{hashrate_pretty} "
                            + Style.NORMAL
                            + Fore.RESET
                            + f"({total_hashrate_pretty} total) "
                            + Fore.YELLOW
                            + "⚙ "
                            + Fore.RESET
                            + f"diff. {diff_pretty} ∙ "
                            + Fore.CYAN
                            + f"ping {int(total_ping)}ms"
                        )
                    elif status == "BLOCK":
                        accept_count += 1
                        print(
                            share_header
                            + Fore.CYAN
                            + "Block found "
                            + f"{accept_count}/{total_shares} ({success_percent:.0f}%) "
                            + Style.NORMAL
                            + Fore.RESET
                            + f"∙ {compute_time:04.1f}s ∙ "
                            + Fore.BLUE
                            + Style.BRIGHT
                            + f"{hashrate_pretty} "
                            + Style.NORMAL
                            + Fore.RESET
                            + f"({total_hashrate_pretty} total) "
                            + Fore.YELLOW
                            + "⚙ "
                            + Fore.RESET
                            + f"diff. {diff_pretty} "
                            + Fore.CYAN
                            + f"ping {int(total_ping)}ms"
                        )
                    else:
                        reject_count += 1
                        print(
                            share_header
                            + Fore.RED
                            + "Rejected "
                            + f"{accept_count}/{total_shares} ({success_percent:.0f}%) "
                            + Style.NORMAL
                            + Fore.RESET
                            + f"∙ {compute_time:04.1f}s ∙ "
                            + Fore.BLUE
                            + Style.BRIGHT
                            + f"{hashrate_pretty} "
                            + Style.NORMAL
                            + Fore.RESET
                            + f"({total_hashrate_pretty} total) "
                            + Fore.YELLOW
                            + "⚙ "
                            + Fore.RESET
                            + f"diff. {diff_pretty} ∙ "
                            + Fore.CYAN
                            + f"ping {int(total_ping)}ms"
                        )
        except Exception as exc:  # pragma: no cover - runtime resiliency
            print(f"Mining error: {exc}", file=sys.stderr)
            sleep(5)


def main():
    colorama_init(autoreset=True)
    config = load_user_settings()
    gpu_config = load_gpu_settings()
    args = parse_args(config, gpu_config)
    mine(args)


if __name__ == "__main__":
    main()
