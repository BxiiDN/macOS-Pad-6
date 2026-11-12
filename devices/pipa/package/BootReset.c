// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa: the reset entry points of the source storage, refusing. UniXNU-sheng's package/BootReset.c probes PSCI and the
// PMIC arbiter and can write the reboot reason so the next boot enters fastboot (its benchmark and autoreset use it).
// pipa does not change the bootloader's path or write PMIC cells from the kernel: both calls do nothing, write their
// reason into `text` and return -1 (the value build-sheng-source-storage.py's weak defaults give an absent call).
// New in macOS-Pad-6; compiled only on the macOS runner.
#include <stddef.h>

static int refuse(char *text, unsigned size, const char *why)
{
    if (text && size) {
        unsigned i = 0;
        for (; why[i] && i + 1 < size; ++i)
            text[i] = why[i];
        text[i] = 0;
    }
    return -1;
}

int boot_reset_probe(char *text, unsigned size)
{
    return refuse(text, size, "pipa: no reset probe (no PSCI or PMIC access from the storage path)");
}

int boot_reset_bootloader(char *text, unsigned size)
{
    return refuse(text, size, "pipa: no restart into fastboot (the reboot reason is not written)");
}
