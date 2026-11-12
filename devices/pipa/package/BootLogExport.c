// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa: boot_log_export_put for Adreno650 (NativeAdrenoPublish.cpp, method NativeAdrenoExportMethod), with the export
// kept in kernel memory (BootLogExportCore.h says what and why). UniXNU-sheng's BootLog.c writes the same pieces into
// NativeUfs's export region; pipa writes nothing to UFS, so this file has no storage call at all.
// Compiled into build/pipa-gpu/libPipaGpu.a (devices/pipa/scripts/build-pipa-gpu.py) for pipa_macos26_gpu_defconfig.
// A strong definition: the caller's weak import then resolves in the static kernel link and leaves no import.
// Not run anywhere yet. Note that the fork's caller only admits a connection whose process is backboardd (the iPadOS
// render server); on macOS no such process exists, so this is not reached until that check names WindowServer.
#include <stdint.h>
#include <IOKit/IOLib.h>
#include "BootLogExportCore.h"

static IOLock *export_lock;   // set once, through the atomic exchange below
static BleStore export_store = {.limit = BLE_LIMIT};
// [0] pieces taken, [1] refused, [2] complete blobs, [3] generation of the kept blob, [4] its bytes, [5] last status.
volatile uint32_t boot_log_export_stats[6];

static void *export_alloc(uint32_t bytes)
{
    return IOMallocData(bytes);
}

static void export_release(void *memory, uint32_t bytes)
{
    IOFreeData(memory, bytes);
}

static const BleMemory export_memory = {export_alloc, export_release};

static IOLock *export_get_lock(void)
{
    IOLock *lock = __atomic_load_n(&export_lock, __ATOMIC_ACQUIRE);
    if (lock)
        return lock;
    IOLock *fresh = IOLockAlloc();
    if (!fresh)
        return 0;
    IOLock *expected = 0;
    if (__atomic_compare_exchange_n(&export_lock, &expected, fresh, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
        return fresh;
    IOLockFree(fresh);   // another caller installed its lock first
    return expected;
}

int boot_log_export_put(uint32_t generation, uint32_t total, uint32_t offset, const void *data, uint32_t size)
{
    IOLock *lock = export_get_lock();
    if (!lock)
        return BLE_NOMEM;
    IOLockLock(lock);
    const int status = ble_put(&export_store, &export_memory, generation, total, offset, data, size);
    boot_log_export_stats[0] = export_store.pieces;
    boot_log_export_stats[1] = export_store.refused;
    boot_log_export_stats[2] = export_store.completed;
    boot_log_export_stats[3] = export_store.ready_generation;
    boot_log_export_stats[4] = export_store.ready_total;
    boot_log_export_stats[5] = (uint32_t)status;
    IOLockUnlock(lock);
    return status;
}
