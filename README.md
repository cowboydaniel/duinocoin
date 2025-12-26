# Duino-Coin PC Miner 4.3

This repository packages the official Duino-Coin PC miner script (`PC_Miner.py`) and its Python dependencies for version 4.3.

## Getting started
1. Ensure Python 3.7+ is installed.
2. Install dependencies:
   ```bash
   python3 -m pip install -r requirements.txt
   ```
3. Run the miner:
   ```bash
   python3 PC_Miner.py
   ```

The miner will prompt for configuration details on first launch and downloads language translations from the upstream Duino-Coin repository as needed.

## GUI dashboard (PySide6)
The repository includes a PySide6-based GUI preview that surfaces wallet, miner, and live stats in a single window. To set up the GUI:

1. (Recommended) Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\\Scripts\\activate
   ```
2. Install base miner dependencies and the GUI toolkit:
   ```bash
   python3 -m pip install -r requirements.txt -r requirements-gui.txt
   ```
   `requirements-gui.txt` isolates the GUI toolkit and Qt runtime bindings (PySide6). Ensure your system has an X11/Wayland session and OpenGL drivers when running the GUI on Linux.
3. Launch the GUI:
   ```bash
   python3 -m gui.main
   ```
   The window seeds placeholder data on first launch; future updates can wire it to live miner data.

## GPU mining
`GPU_Miner.py` uses the same wallet configuration as the PC miner and supports GPU-specific defaults via an optional `GPU_Settings.cfg` file stored next to `Settings.cfg` in the `Duino-Coin PC Miner 4.3` data directory.

1. Install GPU dependencies (manual installation is recommended because GPU packages rely on vendor drivers):
   ```bash
   python3 -m pip install pyopencl
   # or install everything, including the hasher backend:
   python3 -m pip install -r requirements.txt
   ```
   Make sure your GPU drivers expose an OpenCL runtime/ICD; without drivers PyOpenCL cannot discover devices.
2. Run the GPU miner (it will reuse your PC miner username/mining key unless overridden):
   ```bash
   # Auto-tunes work group size and batch sizing; overrides are optional:
   python3 GPU_Miner.py --backend opencl --device 0
   # Advanced overrides:
   python3 GPU_Miner.py --backend opencl --device 0 --work-size 256 --batch-multiplier 3
   ```
   CLI flags are optional; omit them to use the first detected GPU and auto-detected kernel work sizes and batch sizes. The miner will auto-tune batch sizing per session unless a multiplier is provided. Any CLI option takes precedence over configuration files.
3. (Optional) Save defaults in `GPU_Settings.cfg`:
   ```ini
   [GPU Miner]
   backend = opencl
   device = 0
   # Preferred work group size (auto-selects 512/1024 when supported)
   work_size = 256
   # Scale batches beyond compute_units*2; leave unset to auto-tune
   batch_multiplier = 3
   ```
   Place this file inside `Duino-Coin PC Miner 4.3/` alongside `Settings.cfg`. If both `GPU_Settings.cfg` and CLI options are present, CLI values win.

### GPU batch sizing defaults
- **Discrete NVIDIA/AMD (e.g., RTX 20xx/30xx, RX 5000/6000):** auto-detected work groups usually pick 512–1024; start with `--batch-multiplier 2` (default) and let autotune raise it if the device remains underutilized.
- **Integrated GPUs (Intel/AMD iGPU):** work groups often cap at 256; keep the default multiplier or lower it (`--batch-multiplier 1`) if you see driver resets or throttling.
- Autotune now benchmarks each multiplier with additional samples (10 by default) and can explore up to a 60× batch multiplier before plateau detection stops the sweep.
- The miner clamps batch sizes to each device's `MAX_WORK_ITEM_SIZES[0]` and stops increasing the multiplier once throughput gains plateau to reduce instability on marginal devices.
- Batch sizing scales from `work_group_size * compute_units * multiplier` and is bounded by the device work-item limit across compute units so high multipliers don't starve throughput on larger GPUs.

### Troubleshooting GPU startup
- **Missing PyOpenCL:** install it manually as shown above. Auto-installation is disabled for GPU packages to avoid driver conflicts.
- **No devices found:** install or update your GPU drivers, ensure the OpenCL ICD is registered, and verify `clinfo` (if available) lists your device. Re-run `GPU_Miner.py` after drivers are in place.
- **Backend errors:** only the `opencl` backend is currently supported; set `backend = opencl` (or `--backend opencl`) and retry.

## Fast hashing backend
`libducohasher` provides the optimized hashing backend used by the PC miner. Installing the requirements will pull a prebuilt wheel for common 64-bit platforms (Windows, macOS, and most glibc-based Linux distributions on x86_64). The miner will also attempt to auto-install the package on startup if it is missing; if installation is not possible, it exits with a warning instead of silently continuing with a slower pure-Python path.

### Unsupported or source-only platforms
If a prebuilt wheel is not available for your platform (for example, on ARMv6/ARMv7 SBCs or other niche architectures), you can build the extension locally:
1. Install build prerequisites: a C/C++ toolchain, Python headers (`python3-dev`), and `pip` build helpers (`python3 -m pip install --upgrade pip setuptools wheel pybind11`).
2. Clone the hasher source: `git clone https://github.com/revoxhere/libducohasher.git` and enter the directory.
3. Build and install from source: `python3 -m pip install .` (or `python3 setup.py bdist_wheel` followed by installing the produced wheel from `dist/`).
4. Re-run the miner after installation completes; it will use the compiled backend automatically.

## Project contents
- `PC_Miner.py` – main PC miner script.
- `requirements.txt` – Python dependencies used by the miner.
- `requirements-gui.txt` – PySide6 toolkit/runtime dependencies for the GUI dashboard.
- `LICENSE` – MIT license covering the release.
