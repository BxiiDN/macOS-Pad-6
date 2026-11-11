/* Shim: the declarations of xnu-12377.121.6 osfmk/mach/arm/thread_status.h that
 * kernel/xnu/fge_xnu.c uses, copied with the same layouts (HAS_APPLE_PAC off).
 * Only for a syntax and type check; the real build uses XNU's headers.
 * SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
typedef __uint128_t uint128_t;
typedef uint64_t user_addr_t;
typedef unsigned int mach_msg_type_number_t;
#define __unused __attribute__((unused))
#define __improbable(x) __builtin_expect(!!(x), 0)
#define ARM_SAVED_STATE64 21
#define ARM_NEON_SAVED_STATE64 23
typedef struct arm_state_hdr { uint32_t flavor; uint32_t count; } arm_state_hdr_t;
struct arm_saved_state64 {
	uint64_t x[29]; uint64_t fp; uint64_t lr; uint64_t sp; uint64_t pc;
	uint32_t cpsr; uint32_t reserved; uint64_t far; uint64_t esr;
};
typedef struct arm_saved_state64 arm_saved_state64_t;
struct arm_saved_state32 { uint32_t r[13]; uint32_t sp, lr, pc, cpsr, far, esr, exception; };
struct arm_saved_state {
	arm_state_hdr_t ash;
	union { struct arm_saved_state32 ss_32; struct arm_saved_state64 ss_64; } uss;
} __attribute__((aligned(16)));
typedef struct arm_saved_state arm_saved_state_t;
struct arm_neon_saved_state64 {
	union { uint128_t q[32]; } v;
	uint32_t fpsr; uint32_t fpcr;
};
struct arm_neon_saved_state32 { union { uint128_t q[16]; } v; uint32_t fpscr; };
struct arm_neon_saved_state {
	arm_state_hdr_t nsh;
	union { struct arm_neon_saved_state32 ns_32; struct arm_neon_saved_state64 ns_64; } uns;
};
#define ns_64 uns.ns_64
#define ARM_NEON_SAVED_STATE64_COUNT ((mach_msg_type_number_t) \
	(sizeof (struct arm_neon_saved_state64)/sizeof(unsigned int)))
struct arm_context { struct arm_saved_state ss; struct arm_neon_saved_state ns; };
typedef struct arm_context arm_context_t;
static inline bool is_saved_state64(const arm_saved_state_t *iss) { return iss->ash.flavor == ARM_SAVED_STATE64; }
static inline arm_saved_state64_t *saved_state64(arm_saved_state_t *iss) { return &iss->uss.ss_64; }
