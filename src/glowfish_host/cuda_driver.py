"""Minimal Windows CUDA Driver API probe; no `nvidia-smi` dependency."""

from __future__ import annotations

import ctypes
import os


class CudaDriverProbe:
    def inspect(self):
        if os.name != "nt":
            return None, "no_nvidia_gpu"
        try:
            cuda = ctypes.WinDLL("nvcuda.dll")
            if cuda.cuInit(0) != 0:
                return None, "no_nvidia_gpu"
            count = ctypes.c_int()
            if cuda.cuDeviceGetCount(ctypes.byref(count)) != 0 or count.value < 1:
                return None, "no_nvidia_gpu"
            best = None
            for index in range(count.value):
                device = ctypes.c_int()
                major, minor, memory = ctypes.c_int(), ctypes.c_int(), ctypes.c_size_t()
                if (cuda.cuDeviceGet(ctypes.byref(device), index) != 0 or
                    cuda.cuDeviceComputeCapability(ctypes.byref(major), ctypes.byref(minor), device) != 0 or
                    cuda.cuDeviceTotalMem_v2(ctypes.byref(memory), device) != 0):
                    continue
                name = ctypes.create_string_buffer(256)
                cuda.cuDeviceGetName(name, len(name), device)
                item = {"name": name.value.decode("utf-8", "replace"), "index": index,
                        "compute_capability": f"{major.value}.{minor.value}",
                        "vram_mb": memory.value // (1024 * 1024)}
                if best is None or item["vram_mb"] > best["vram_mb"]:
                    best = item
            driver = ctypes.c_int()
            if best is None or cuda.cuDriverGetVersion(ctypes.byref(driver)) != 0:
                return None, "no_nvidia_gpu"
            best["driver_version"] = f"{driver.value // 1000}.{(driver.value % 1000) // 10}"
            return best, None
        except (AttributeError, OSError):
            return None, "no_nvidia_gpu"
