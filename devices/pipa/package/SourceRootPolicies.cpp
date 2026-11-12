// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa: the verified root policies NativeUfs reads, and their load. pipa mounts no root from userdata, so it ships no
// policy envelope: the table stays empty and the load reports none, whatever the firmware hands off. The symbols are
// UniXNU-sheng's (package/SourceRootPolicies.cpp), which authenticates a "RootPolicies" sidecar with the compiled-in
// owner key; pipa does not read it. New in macOS-Pad-6; compiled only on the macOS runner.
#include <stdint.h>
#include "VerifiedBlockPolicy.h"

extern "C" {
NativeVerifiedBlockPolicy verified_root_policies[16];
uint64_t verified_root_policy_count;
// 1 when a RootPolicies property was seen and ignored, for diagnostics.
volatile uint32_t pipa_root_policies_ignored;
}

#include <IOKit/IORegistryEntry.h>
#include <IOKit/IODeviceTreeSupport.h>

extern "C" bool native_source_root_policies_load(void)
{
    IORegistryEntry *entry = IORegistryEntry::fromPath("/chosen/memory-map", gIODTPlane);
    if (entry) {
        pipa_root_policies_ignored = entry->getProperty("RootPolicies") ? 1 : 0;
        entry->release();
    }
    verified_root_policy_count = 0;
    return false;
}
