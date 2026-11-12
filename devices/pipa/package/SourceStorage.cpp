// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa: start the source-built UFS adapter (PipaUfs as ShengUfs, arm64e source storage) after the original storage
// family loads, read only. After UniXNU-sheng's package/SourceStorage.cpp (same class registration through the
// public IOStorageFamily interface), without what pipa must not do: no Data disk seeded into userdata, no UFS log
// writer, no benchmark, no restart into fastboot, no root. PipaStorageGuard.h decides from the boot arguments and
// refuses every mode in which NativeUfs would write or mount a root. New in macOS-Pad-6; compiled only by
// build-sheng-source-storage.py on the macOS runner; never run on the tablet.
#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/storage/IOBlockStorageDevice.h>
#include <libkern/OSKextLib.h>
#include <string.h>
#include <mach/kmod.h>
#include <pexpert/pexpert.h>
#include <IOKit/IOLib.h>
#include "PipaStorageGuard.h"

extern kmod_info_t g_kernel_kmod_info;
extern "C" void source_storage_base_init(void) __asm__("__GLOBAL__sub_I_IOBlockStorageDevice.cpp");
extern "C" void source_storage_ufs_init(void) __asm__("__GLOBAL__sub_I_NativeUfs.cpp");
extern "C" void source_storage_ram_init(void) __asm__("__GLOBAL__sub_I_NativeRamBlock.cpp");
extern "C" IOService *native_ufs_source_create(void);
extern "C" bool native_source_root_policies_load(void);
extern "C" volatile uint32_t native_ufs_root_step;
extern "C" const char *volatile native_ufs_root_failure;
extern "C" void boot_log_tick(unsigned now);

// NativeUfs polls the optional board diagnostic during window reads; pipa has none. Hidden: a weak definition the static
// kernel link can export would be bound at run time, which the linker writes as a chained-fixup import (XnuPrelink
// refuses any), as with native_exit_trace (zzzz-pipa-macos-absent-features.patch).
extern "C" __attribute__((weak, visibility("hidden"))) void boot_progress_poll(void) {}

// The decision, for the panic screen and a later read of the kernel's memory.
extern "C" {
volatile uint32_t pipa_storage_decision = PipaStorageOff;
}

static const OSMetaClass *storageParent;
static IOService *storageDriver;
static bool attempted;

// Used only by the deferred source IOBlockStorageDevice metaclass constructor.
extern "C" const OSMetaClass *native_source_storage_parent(void)
{
    if (!storageParent) panic("SourceStorage: metaclass initialized before original family");
    return storageParent;
}

static PipaBootArg arg(const char *name)
{
    PipaBootArg a = {0, 0};
    a.set = PE_parse_boot_argn(name, &a.value, sizeof(a.value)) ? 1 : 0;
    return a;
}

extern "C" void native_source_storage_start(void)
{
    if (attempted) return;
    PipaStorageArgs args = {arg("native-source-storage"), arg("native-ufs-root"), arg("native-ufs-root-noverify"),
                            arg("sheng-data-persist"), arg("sheng-log"), arg("native-ufs-probe")};
    const PipaStorageDecision decision = pipa_storage_decide(&args);
    pipa_storage_decision = decision;
    if (decision == PipaStorageOff) return;
    attempted = true;
    printf("SourceStorage: pipa %s\n", pipa_storage_reason(decision));
    if (decision != PipaStorageStart) return;      // refused: the boot goes on without UFS (and ends at the root mount)

    OSReturn status = OSKextLoadKextWithIdentifier("com.apple.iokit.IOStorageFamily");
    if (status != kOSReturnSuccess)
        panic("SourceStorage: IOStorageFamily load failed %x", status);
    const OSSymbol *name = OSSymbol::withCString("IOBlockStorageDevice");
    storageParent = name ? OSMetaClass::getMetaClassWithName(name) : nullptr;
    if (name) name->release();
    if (!storageParent || storageParent->getClassSize() != sizeof(IOBlockStorageDevice))
        panic("SourceStorage: original base layout %u differs from source %lu",
              storageParent ? storageParent->getClassSize() : 0, sizeof(IOBlockStorageDevice));
    // pipa ships no root policies (SourceRootPolicies.cpp): the load reports none, and NativeUfs publishes no verified
    // root window. That is the board's choice, not a failure.
    if (native_source_root_policies_load())
        panic("SourceStorage: root policies present on pipa, which mounts no UFS root");

    void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
    if (!handle) panic("SourceStorage: cannot begin class registration");
    source_storage_base_init();
    source_storage_ufs_init();
    source_storage_ram_init();
    status = OSMetaClass::postModLoad(handle);
    if (status != kOSReturnSuccess)
        panic("SourceStorage: class registration failed %x", status);

    OSDictionary *matching = IOService::serviceMatching("IOPlatformExpertDevice");
    IOService *provider = matching ? IOService::waitForMatchingService(matching, 5000000000ULL) : nullptr;
    if (!provider) panic("SourceStorage: platform root unavailable");
    storageDriver = native_ufs_source_create();
    if (!storageDriver) panic("SourceStorage: cannot allocate UFS service");
    if (!storageDriver->init() || !storageDriver->attach(provider))
        panic("SourceStorage: UFS service init or attach failed");
    // The guard admits only register inspections (native-ufs-probe 2, 6, 7, 8). NativeUfs::start runs the one asked
    // for, reports it (probe 2 on the panic screen, the others in the log) and returns false: it publishes nothing.
    // That is the expected outcome here, not a failure, so the service is detached and the boot goes on.
    if (!storageDriver->start(provider)) {
        printf("SourceStorage: UFS inspection done, nothing published (root step %u: %s)\n", native_ufs_root_step,
               native_ufs_root_failure ? native_ufs_root_failure : "none");
        storageDriver->detach(provider);
        storageDriver->release();
        storageDriver = nullptr;
        boot_log_tick(0);
        return;
    }
    // Not reached with the guard's inspections; kept so a start that does publish is reported, not silent.
    printf("SourceStorage: UFS started through public IOStorageFamily interface, read only\n");
    boot_log_tick(0);    // BootLog.c: records that pipa keeps no UFS log
}
