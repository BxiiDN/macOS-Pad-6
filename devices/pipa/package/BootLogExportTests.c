// SPDX-License-Identifier: BSD-2-Clause-Patent
// Host test for BootLogExportCore.h, the in-memory boot log export behind pipa's boot_log_export_put (BootLogExport.c).
// cc -std=gnu11 -Wall -Wextra -Werror package/BootLogExportTests.c && ./a.out
#include "BootLogExportCore.h"
#include <stdio.h>
#include <stdlib.h>
#define CHECK(c) do{if(!(c)){printf("FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1);}}while(0)

static long live_bytes, live_blocks, fail_next;
static void *test_alloc(uint32_t bytes) {
    if (fail_next) {fail_next = 0; return 0;}
    live_bytes += bytes; live_blocks++;
    return malloc(bytes);
}
static void test_release(void *p, uint32_t bytes) {live_bytes -= bytes; live_blocks--; free(p);}
static const BleMemory mem = {test_alloc, test_release};

int main(void) {
    BleStore s = {.limit = BLE_LIMIT};
    uint8_t blob[10000];
    for (unsigned i = 0; i < sizeof blob; i++) blob[i] = (uint8_t)(i * 7 + 3);

    // Arguments, as sheng's BootLog.c refuses them.
    CHECK(ble_put(&s, &mem, 0, 10, 0, blob, 10) == BLE_ARGS);          // generation 0
    CHECK(ble_put(&s, &mem, 1, 0, 0, blob, 1) == BLE_ARGS);            // no total
    CHECK(ble_put(&s, &mem, 1, 10, 0, 0, 10) == BLE_ARGS);             // no data
    CHECK(ble_put(&s, &mem, 1, 10, 0, blob, 0) == BLE_ARGS);           // empty piece
    CHECK(ble_put(&s, &mem, 1, 10, 11, blob, 1) == BLE_ARGS);          // starts past total
    CHECK(ble_put(&s, &mem, 1, 10, 8, blob, 3) == BLE_ARGS);           // ends past total
    CHECK(ble_put(&s, &mem, 1, 0xfffffff0u, 0xfffffff0u, blob, 0x20) == BLE_ARGS);   // no wrap
    CHECK(ble_put(&s, &mem, 1, BLE_LIMIT + 1, 0, blob, 1) == BLE_TOO_LARGE);
    CHECK(s.refused == 8 && s.pieces == 0 && live_blocks == 0 && !s.ready);

    // In order: 10000 bytes in pieces of 3968 (NativeAdrenoExportMaxPiece), then the blob is complete and kept.
    uint32_t at = 0;
    while (at < sizeof blob) {
        const uint32_t n = sizeof blob - at < 3968 ? sizeof blob - at : 3968;
        CHECK(!s.ready || at == 0);
        CHECK(ble_put(&s, &mem, 7, sizeof blob, at, blob + at, n) == BLE_OK);
        at += n;
    }
    CHECK(s.ready && s.ready_generation == 7 && s.ready_total == sizeof blob && !memcmp(s.ready, blob, sizeof blob));
    CHECK(!s.building && s.completed == 1 && s.pieces == 3 && live_blocks == 1 && live_bytes == (long)sizeof blob);

    // Out of order: a skipped piece, a different generation or total, a piece without a start; the kept blob stays.
    CHECK(ble_put(&s, &mem, 8, 100, 50, blob, 10) == BLE_ORDER);       // nothing being received
    CHECK(ble_put(&s, &mem, 8, 100, 0, blob, 40) == BLE_OK);
    CHECK(ble_put(&s, &mem, 8, 100, 50, blob, 10) == BLE_ORDER);       // gap
    CHECK(ble_put(&s, &mem, 9, 100, 40, blob, 10) == BLE_ORDER);       // other generation
    CHECK(ble_put(&s, &mem, 8, 101, 40, blob, 10) == BLE_ORDER);       // other total
    CHECK(ble_put(&s, &mem, 8, 100, 30, blob, 10) == BLE_ORDER);       // repeat
    CHECK(s.ready_generation == 7 && !memcmp(s.ready, blob, sizeof blob) && s.filled == 40);
    // Offset 0 starts over (the old partial blob is released), and completing it replaces the kept one.
    CHECK(ble_put(&s, &mem, 9, 100, 0, blob + 1, 60) == BLE_OK);
    CHECK(live_blocks == 2 && s.generation == 9);
    CHECK(ble_put(&s, &mem, 9, 100, 60, blob + 61, 40) == BLE_OK);
    CHECK(s.ready_generation == 9 && s.ready_total == 100 && !memcmp(s.ready, blob + 1, 100));
    CHECK(live_blocks == 1 && live_bytes == 100);

    // No memory: refused, nothing half-made, the kept blob untouched; a whole blob in one piece also works.
    fail_next = 1;
    CHECK(ble_put(&s, &mem, 10, 50, 0, blob, 50) == BLE_NOMEM);
    CHECK(!s.building && s.ready_generation == 9 && live_blocks == 1);
    CHECK(ble_put(&s, &mem, 11, 50, 0, blob, 50) == BLE_OK && s.ready_generation == 11 && live_bytes == 50);
    CHECK(s.last_status == BLE_OK);

    ble_drop_building(&s, &mem);
    test_release(s.ready, s.ready_total);
    CHECK(live_blocks == 0 && live_bytes == 0);
    printf("PASS: BootLogExportTests (in-order export kept in memory; no storage call exists)\n");
    return 0;
}
