// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa: when the source UFS adapter (PipaUfs as ShengUfs, under arm64e) may start, as a pure function of the boot
// arguments. Used by SourceStorage.cpp; host-tested by PipaStorageGuardTests.c. New in macOS-Pad-6.
//
// The board does not use userdata as a root file system and does not write to UFS. NativeUfs.cpp writes in exactly
// two places, both inside userdata (its own header says so): the persistent Data store (sheng-data-persist=2) and the
// diagnostic log with its export region (sheng-log=1); it mounts a root from userdata windows with native-ufs-root
// (native-ufs-root-noverify skips the policy check). The guard refuses to start the adapter when any of those is
// asked for, and requires native-source-storage=1 as UniXNU-sheng's SourceStorage does.
//
// NativeUfs::start does nothing without native-ufs-probe (or a root mode). Of its probes only four are register reads
// that publish nothing and adopt nothing (NativeUfs.cpp's own comments: "Nothing is written"): 2 (GCC and host
// controller registers, read only while the GDSC and bus clocks are on), 6 (the request list the firmware left),
// 7 (apps SMMU global space and the UFS stream match), 8 (SMMU context banks). Every other value either brings the
// host up and issues commands (3-5, 9, 10, 11, 16 -> 10), publishes block devices (12, 13, 15: 15 publishes all of
// userdata, writable) or stops the boot for a memory report (14). The guard starts the adapter only for 2, 6, 7, 8.
// Whether even those read correctly has not been tried on the tablet.
#ifndef PIPA_STORAGE_GUARD_H
#define PIPA_STORAGE_GUARD_H
#include <stdint.h>

typedef enum {
    PipaStorageStart = 0,
    PipaStorageOff,             // native-source-storage is not 1: nothing to do
    PipaStorageRefusedRoot,     // native-ufs-root or native-ufs-root-noverify: a root from userdata
    PipaStorageRefusedStore,    // sheng-data-persist (1 reads the store's window, 2 writes it)
    PipaStorageRefusedLog,      // sheng-log: the UFS log writes userdata
    PipaStorageRefusedProbe,    // native-ufs-probe absent or not one of the read-only inspections 2, 6, 7, 8
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
    PipaBootArg probe;            // native-ufs-probe
} PipaStorageArgs;

// native-ufs-probe values that only read registers and publish nothing (see above).
static inline int pipa_storage_probe_read_only(uint32_t probe) {
    return probe == 2 || probe == 6 || probe == 7 || probe == 8;
}

static inline PipaStorageDecision pipa_storage_decide(const PipaStorageArgs *a) {
    if (!a->source_storage.set || a->source_storage.value != 1)
        return PipaStorageOff;
    if ((a->ufs_root.set && a->ufs_root.value) || a->ufs_root_noverify.set)
        return PipaStorageRefusedRoot;
    if (a->data_persist.set && a->data_persist.value)
        return PipaStorageRefusedStore;
    if (a->log.set && a->log.value)
        return PipaStorageRefusedLog;
    if (!a->probe.set || !pipa_storage_probe_read_only(a->probe.value))
        return PipaStorageRefusedProbe;
    return PipaStorageStart;
}

static inline const char *pipa_storage_reason(PipaStorageDecision d) {
    switch (d) {
    case PipaStorageStart: return "start (a read-only register inspection: no root, no store, no log, nothing published)";
    case PipaStorageOff: return "off (native-source-storage is not 1)";
    case PipaStorageRefusedRoot: return "refused: pipa mounts no root from userdata (native-ufs-root*)";
    case PipaStorageRefusedStore: return "refused: pipa keeps no Data store in userdata (sheng-data-persist)";
    case PipaStorageRefusedLog: return "refused: pipa writes no log to UFS (sheng-log)";
    case PipaStorageRefusedProbe: return "refused: native-ufs-probe must be a read-only inspection (2, 6, 7 or 8)";
    }
    return "?";
}

#endif
