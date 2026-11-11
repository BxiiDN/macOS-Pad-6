/*
 * FGE - Feature Gap Emulation for running arm64e (Apple ARMv8.3+) code on
 * ARMv8.2 cores (Qualcomm Kryo 585 = Cortex-A77 + Cortex-A55, SM8250).
 *
 * The library decodes one trapped instruction and emulates it against a
 * register snapshot. It has no dependency on libc, XNU or the host OS: memory
 * access, barriers and FP state go through the context, so the same file is
 * unit-tested on the build host and linked into the kernel by the XNU patch.
 *
 * Pointer authentication is emulated as "null PAC": signing and
 * authentication are the identity function. This is coherent only when every
 * signature in the system is produced on the device (UniXNU's arm64e profile
 * already relies on that: "No signature is computed off the device"). It
 * removes the protection PAC gives. See docs/feasibility.md.
 *
 * Copyright (c) 2026, macOS-Pad-6 contributors.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 */
#ifndef FGE_H
#define FGE_H

#ifdef __cplusplus
extern "C" {
#endif

#if defined(KERNEL) || defined(FGE_FREESTANDING)
typedef unsigned char      fge_u8;
typedef unsigned short     fge_u16;
typedef unsigned int       fge_u32;
typedef unsigned long long fge_u64;
typedef long long          fge_s64;
#else
#include <stdint.h>
typedef uint8_t  fge_u8;
typedef uint16_t fge_u16;
typedef uint32_t fge_u32;
typedef uint64_t fge_u64;
typedef int64_t  fge_s64;
#endif

/* PSTATE.NZCV bits as they sit in SPSR/CPSR. */
#define FGE_N (1u << 31)
#define FGE_Z (1u << 30)
#define FGE_C (1u << 29)
#define FGE_V (1u << 28)

/* FPSR cumulative exception bits. */
#define FGE_FPSR_IOC (1u << 0)
#define FGE_FPSR_IXC (1u << 4)
#define FGE_FPSR_IDC (1u << 7)
/* FPCR.FZ */
#define FGE_FPCR_FZ  (1u << 24)

typedef struct fge_vreg {
	fge_u64 lo;
	fge_u64 hi;
} fge_vreg_t;

typedef enum fge_class {
	FGE_CLASS_NONE = 0,
	FGE_CLASS_PAC_DP1,      /* PACIA..XPACD, AUTIA..AUTDZB (data processing, 1 source) */
	FGE_CLASS_PACGA,        /* PACGA */
	FGE_CLASS_PAC_BRANCH,   /* BRAA/BRAB(Z), BLRAA/BLRAB(Z), RETAA/RETAB */
	FGE_CLASS_PAC_LOAD,     /* LDRAA/LDRAB */
	FGE_CLASS_PAC_KEYREG,   /* MSR/MRS AP*Key*_EL1 (EL1 only) */
	FGE_CLASS_JSCVT,        /* FJCVTZS */
	FGE_CLASS_FLAGM,        /* CFINV, RMIF, SETF8, SETF16 (v8.4) */
	FGE_CLASS_FLAGM2,       /* AXFLAG, XAFLAG (v8.5) */
	FGE_CLASS_SB,           /* SB (v8.5) */
	FGE_CLASS_RCPC2,        /* LDAPUR*, STLUR* (v8.4) */
	FGE_CLASS_PSTATE,       /* MSR DIT/SSBS, #imm; MRS/MSR DIT */
	FGE_CLASS_SHA3,         /* EOR3, BCAX, RAX1, XAR (FEAT_SHA3) */
	FGE_CLASS_SHA512,       /* SHA512H, SHA512H2, SHA512SU0, SHA512SU1 (FEAT_SHA512) */
	FGE_CLASS_COUNT
} fge_class_t;

typedef enum fge_result {
	FGE_NOT_HANDLED = 0,   /* not an instruction FGE knows: deliver SIGILL / panic as before */
	FGE_HANDLED     = 1,   /* state updated, PC advanced or redirected */
	FGE_MEM_FAULT   = 2    /* a memory access failed: deliver the fault as before */
} fge_result_t;

typedef struct fge_ctx {
	fge_u64 x[31];          /* X0..X30 */
	fge_u64 sp;             /* SP of the trapping EL */
	fge_u64 pc;             /* address of the trapping instruction */
	fge_u32 nzcv;           /* only bits 31..28 are read and written */
	int     el;             /* 0 = user, 1 = kernel */

	fge_vreg_t *v;          /* V0..V31, or NULL when FP state is not available */
	fge_u32    *fpsr;       /* may be NULL */
	fge_u32     fpcr;

	/* Return 0 on success. size is 1, 2, 4 or 8; addr may be unaligned.
	 * A naturally aligned access must be single-copy atomic, as the
	 * emulated instruction was (LDAPUR/STLUR implement C11 atomics). */
	int  (*read_mem)(void *cookie, fge_u64 addr, void *dst, unsigned size);
	int  (*write_mem)(void *cookie, fge_u64 addr, const void *src, unsigned size);
	void (*barrier)(void *cookie);   /* full DMB ISH; may be NULL */
	void *cookie;

	fge_u64 pacga_key;      /* per-boot value mixed into PACGA results */
} fge_ctx_t;

typedef struct fge_stats {
	fge_u64 count[FGE_CLASS_COUNT];
	fge_u64 not_handled;
	fge_u64 faults;
} fge_stats_t;

/*
 * Emulate one instruction. On FGE_HANDLED the context holds the new state
 * (ctx->pc is the next instruction). On the other results the context is
 * unchanged. cls, when not NULL, receives the instruction class.
 */
fge_result_t fge_emulate(fge_ctx_t *ctx, fge_u32 insn, fge_class_t *cls);

/* Classify without emulating (used by the static audit tests). */
fge_class_t fge_classify(fge_u32 insn, int el);

const char *fge_class_name(fge_class_t cls);

void fge_stats_record(fge_stats_t *stats, fge_result_t res, fge_class_t cls);

/* FJCVTZS on raw IEEE-754 binary64 bits; exposed for tests. */
fge_u32 fge_fjcvtzs(fge_u64 bits, fge_u32 fpcr, int *z, fge_u32 *fpsr_bits);

#ifdef __cplusplus
}
#endif

#endif /* FGE_H */
