// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa: when the source UFS adapter (PipaUfs as ShengUfs, under arm64e) may start, as a pure function of the boot
// arguments. Used by SourceStorage.cpp; host-tested by PipaStorageGuardTests.c. New in macOS-Pad-6.
//
// The board does not use userdata as a root file system and does not write to UFS. NativeUfs.cpp writes in exactly
// two places, both inside userdata (its own header says so): the persistent Data store (sheng-data-persist=2) and the
// diagnostic log with its export region (sheng-log=1); it mounts a root from userdata windows with native-ufs-root
// (native-ufs-root-noverify skips the policy check). The guard refuses to start the adapter when any of those is
// asked for, and requires native-source-storage=1 as UniXNU-sheng's SourceStorage does. With the guard passed the
// driver can probe the controller and read; whether it reads correctly has not been tried on the tablet.
#ifndef PIPA_STORAGE_GUARD_H
#define PIPA_STORAGE_GUARD_H
#include <stdint.h>

typedef enum {
    PipaStorageStart = 0,
    PipaStorageOff,             // native-source-storage is not 1: nothing to do
    PipaStorageRefusedRoot,     // native-ufs-root or native-ufs-root-noverify: a root from userdata
    PipaStorageRefusedStore,    // sheng-data-persist (1 reads the store's window, 2 writes it)
    PipaStorageRefusedLog,      // sheng-log: the UFS log writes userdata
} PipaStorageDecision;

// A boot argument as PE_parse_boot_argn gives it: present (nonzero `set`) with its value.
typedef struct {
    int set;
    uint32_t value;
} PipaBootArg;

typedef struct {
    PipaBootArg source_storage;   // native-source-storage
    PipaBootArg ufs_root;         // native-ufs-root
    PipaBootArg ufs_root_noverify;
    PipaBootArg data_persist;     // sheng-data-persist
    PipaBootArg log;              // sheng-log
} PipaStorageArgs;

static inline PipaStorageDecision pipa_storage_decide(const PipaStorageArgs *a) {
    if (!a->source_storage.set || a->source_storage.value != 1)
        return PipaStorageOff;
    if ((a->ufs_root.set && a->ufs_root.value) || a->ufs_root_noverify.set)
        return PipaStorageRefusedRoot;
    if (a->data_persist.set && a->data_persist.value)
        return PipaStorageRefusedStore;
    if (a->log.set && a->log.value)
        return PipaStorageRefusedLog;
    return PipaStorageStart;
}

static inline const char *pipa_storage_reason(PipaStorageDecision d) {
    switch (d) {
    case PipaStorageStart: return "start (read only: no root, no store, no log)";
    case PipaStorageOff: return "off (native-source-storage is not 1)";
    case PipaStorageRefusedRoot: return "refused: pipa mounts no root from userdata (native-ufs-root*)";
    case PipaStorageRefusedStore: return "refused: pipa keeps no Data store in userdata (sheng-data-persist)";
    case PipaStorageRefusedLog: return "refused: pipa writes no log to UFS (sheng-log)";
    }
    return "?";
}

#endif
