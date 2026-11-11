// SPDX-License-Identifier: BSD-2-Clause-Patent
// Host test for PipaStorageGuard.h (when SourceStorage.cpp may start the UFS adapter) and for the two pipa storage
// sources that are plain C: BootLog.c (no writer) and BootReset.c (refusals). The C++ sources need XNU headers and are
// compiled on the macOS runner only.
// cc -std=gnu11 -Wall -Wextra -Werror package/PipaStorageGuardTests.c && ./a.out
#include "PipaStorageGuard.h"
#include "BootLog.c"
#include "BootReset.c"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(c) do{if(!(c)){printf("FAIL %s:%d %s\n",__FILE__,__LINE__,#c);exit(1);}}while(0)

static PipaStorageArgs on(void) {
    PipaStorageArgs a = {{1, 1}, {0, 0}, {0, 0}, {0, 0}, {0, 0}};
    return a;
}

int main(void) {
    PipaStorageArgs a = {{0, 0}, {0, 0}, {0, 0}, {0, 0}, {0, 0}};
    CHECK(pipa_storage_decide(&a) == PipaStorageOff);               // the board's own arguments: nothing starts
    a.source_storage = (PipaBootArg){1, 2};
    CHECK(pipa_storage_decide(&a) == PipaStorageOff);               // only 1 enables it, as in sheng
    a = on();
    CHECK(pipa_storage_decide(&a) == PipaStorageStart);

    // Every mode in which NativeUfs writes userdata or mounts a root from it is refused, whatever else is set.
    a = on(); a.ufs_root = (PipaBootArg){1, 1};
    CHECK(pipa_storage_decide(&a) == PipaStorageRefusedRoot);
    a = on(); a.ufs_root = (PipaBootArg){1, 0};
    CHECK(pipa_storage_decide(&a) == PipaStorageStart);             // native-ufs-root=0 is the off value
    a = on(); a.ufs_root_noverify = (PipaBootArg){1, 0};
    CHECK(pipa_storage_decide(&a) == PipaStorageRefusedRoot);       // present at all: refused
    a = on(); a.data_persist = (PipaBootArg){1, 1};
    CHECK(pipa_storage_decide(&a) == PipaStorageRefusedStore);
    a = on(); a.data_persist = (PipaBootArg){1, 2};
    CHECK(pipa_storage_decide(&a) == PipaStorageRefusedStore);
    a = on(); a.log = (PipaBootArg){1, 1};
    CHECK(pipa_storage_decide(&a) == PipaStorageRefusedLog);
    a = on(); a.log = (PipaBootArg){1, 1}; a.ufs_root = (PipaBootArg){1, 1};
    CHECK(pipa_storage_decide(&a) == PipaStorageRefusedRoot);       // the root refusal is reported first
    for (int d = PipaStorageStart; d <= PipaStorageRefusedLog; ++d)
        CHECK(strlen(pipa_storage_reason((PipaStorageDecision)d)) > 4);
    CHECK(strcmp(pipa_storage_reason((PipaStorageDecision)42), "?") == 0);

    // BootLog: no writer; the tick records why.
    CHECK(boot_log_state == 0 && boot_log_rounds == 0);
    boot_log_tick(0);
    CHECK(boot_log_state == 3 && boot_log_rounds == 0 && boot_log_errors == 0);
    CHECK(boot_log_open_refusal && strstr(boot_log_open_refusal, "no log on UFS"));

    // BootReset: both calls refuse, with the reason, within the buffer.
    char text[16];
    CHECK(boot_reset_probe(text, sizeof text) == -1 && strlen(text) == sizeof text - 1);
    char big[128];
    CHECK(boot_reset_bootloader(big, sizeof big) == -1 && strstr(big, "no restart into fastboot"));
    CHECK(boot_reset_bootloader(NULL, 0) == -1);
    char one[1] = {'x'};
    CHECK(boot_reset_probe(one, 1) == -1 && one[0] == 0);

    puts("PASS: pipa storage guard (off, start, root/store/log refusals) and the no-write BootLog/BootReset");
    return 0;
}
