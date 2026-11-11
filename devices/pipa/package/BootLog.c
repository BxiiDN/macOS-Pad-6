// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa: the boot log entry points the source storage expects, with no writer. UniXNU-sheng's package/BootLog.c keeps
// the kernel's message buffer in a log window at the end of userdata and writes it every round (sheng-log=1); pipa
// writes nothing to UFS, so here the log is off by construction: boot_log_tick records why and returns.
// build-sheng-source-storage.py also derives zero weak defaults from this file's weak imports; it has none.
// New in macOS-Pad-6; compiled only on the macOS runner.
#include <stdint.h>

// The state the board page and SourceStorage read in sheng: 0 not started, 1 opening, 2 writing, 3 off.
volatile uint32_t boot_log_state = 0;
volatile uint32_t boot_log_rounds = 0;
volatile uint32_t boot_log_errors = 0;
const char *volatile boot_log_open_refusal = 0;

void boot_log_tick(unsigned now)
{
    (void)now;
    boot_log_state = 3;
    boot_log_open_refusal = "pipa: no log on UFS (the board writes nothing to userdata)";
}
