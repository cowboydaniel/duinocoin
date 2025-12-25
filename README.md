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
   python3 GPU_Miner.py --backend opencl --device 0 --work-size 128
   ```
   CLI flags are optional; omit them to use the first detected GPU and auto-detected kernel work sizes. Any CLI option takes precedence over configuration files.
3. (Optional) Save defaults in `GPU_Settings.cfg`:
   ```ini
   [GPU Miner]
   backend = opencl
   device = 0
   work_size = 128
   ```
   Place this file inside `Duino-Coin PC Miner 4.3/` alongside `Settings.cfg`. If both `GPU_Settings.cfg` and CLI options are present, CLI values win.

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
- `LICENSE` – MIT license covering the release.
