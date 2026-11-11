/*
 * XNU glue for FGE (kernel/fge): emulate trapped ARMv8.3-8.5 instructions on
 * ARMv8.2 CPUs. Called from sleh_synchronous() for ESR_EC_UNCATEGORIZED.
 *
 * Copyright (c) 2026, macOS-Pad-6 contributors.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 */
#ifndef _ARM64_FGE_XNU_H_
#define _ARM64_FGE_XNU_H_

#include <stdbool.h>
#include <stdint.h>
#include <mach/arm/thread_status.h>

/*
 * Returns true when the instruction at the saved PC was emulated and the
 * saved state now points past it (or at the branch target). Returns false to
 * let the caller take its normal path (SIGILL for user code, panic for the
 * kernel). Boot argument fge=0 disables it, fge=2 also logs every 2^20 traps.
 */
bool fge_xnu_handle(arm_context_t *context);

/* Per-class counters, readable by board log probes. */
extern uint64_t fge_xnu_counts[16];

#endif /* _ARM64_FGE_XNU_H_ */
