// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa: the boot log export's contract (boot_log_export_put, which Adreno650's NativeAdrenoPublish.cpp calls for each
// piece of a blob its render-server connection hands over) with a store in kernel memory instead of the UFS export
// region. UniXNU-sheng's package/BootLog.c takes the pieces in order and writes them through a staging buffer into
// NativeUfs's export region at the end of userdata; pipa writes nothing to UFS (docs/kernel-integration.md), so here
// the pieces are assembled in a buffer of the blob's size and the newest complete blob is kept for the rest of the
// boot. Nothing persists across a restart and nothing reads the blob back yet: only the counters are visible.
//
// The rules are sheng's, with the same status codes where the case exists here:
//   -1  bad arguments (no generation, no total, no data, an empty piece, a piece that ends past total)
//   -2  no memory for the blob
//   -3  out of order: a piece that is not the next one of the blob being received (offset 0 always starts over)
//   -5  the blob is larger than the store's limit
// A complete blob replaces the previous one; a blob that is being received never touches the complete one.
// Plain C with the allocator passed in, so the host test (BootLogExportTests.c) runs the same code as the kernel.
#pragma once
#include <stdint.h>
#include <string.h>

// The largest blob kept: 16 MiB, a bound on what one render-server connection can pin in kernel memory.
#define BLE_LIMIT (16u << 20)

enum { BLE_OK = 0, BLE_ARGS = -1, BLE_NOMEM = -2, BLE_ORDER = -3, BLE_TOO_LARGE = -5 };

typedef struct {
    void *(*alloc)(uint32_t bytes);
    void (*release)(void *memory, uint32_t bytes);
} BleMemory;

typedef struct {
    uint8_t *building;           // the blob being received, total bytes, filled of them so far
    uint32_t generation, total, filled;
    uint8_t *ready;              // the newest complete blob
    uint32_t ready_generation, ready_total;
    uint32_t limit;
    uint32_t pieces, refused, completed;
    int last_status;
} BleStore;

static inline void ble_drop_building(BleStore *s, const BleMemory *m)
{
    if (s->building)
        m->release(s->building, s->total);
    s->building = 0;
    s->generation = s->total = s->filled = 0;
}

static inline int ble_put_locked(BleStore *s, const BleMemory *m, uint32_t generation, uint32_t total, uint32_t offset,
                                 const void *data, uint32_t size)
{
    if (!generation || !total || !data || !size || offset > total || size > total - offset)
        return BLE_ARGS;
    if (total > s->limit)
        return BLE_TOO_LARGE;
    if (offset == 0) {
        ble_drop_building(s, m);
        s->building = (uint8_t *)m->alloc(total);
        if (!s->building)
            return BLE_NOMEM;
        s->generation = generation;
        s->total = total;
    } else if (!s->building || generation != s->generation || total != s->total || offset != s->filled) {
        return BLE_ORDER;
    }
    memcpy(s->building + offset, data, size);
    s->filled = offset + size;
    if (s->filled == s->total) {
        if (s->ready)
            m->release(s->ready, s->ready_total);
        s->ready = s->building;
        s->ready_generation = s->generation;
        s->ready_total = s->total;
        s->building = 0;
        s->generation = s->total = s->filled = 0;
        s->completed++;
    }
    return BLE_OK;
}

// One piece; the caller holds the store's lock.
static inline int ble_put(BleStore *s, const BleMemory *m, uint32_t generation, uint32_t total, uint32_t offset,
                          const void *data, uint32_t size)
{
    const int status = ble_put_locked(s, m, generation, total, offset, data, size);
    if (status)
        s->refused++;
    else
        s->pieces++;
    s->last_status = status;
    return status;
}
