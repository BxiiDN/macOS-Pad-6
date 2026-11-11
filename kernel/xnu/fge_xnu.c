/*
 * XNU glue for FGE. See fge_xnu.h and docs/architecture.md.
 *
 * Requirements this file checks or relies on:
 *  - The kernel collection was rewritten by tools/pacstrip and verified by
 *    tools/isa_audit (no non-hint PAC instruction left in kernel or kexts).
 *    Otherwise every kernel function return traps, including this file's.
 *  - No signed thread state (HAS_APPLE_PAC off, as in UniXNU's BCM2837
 *    machine configuration): registers are written straight into the saved
 *    state.
 *
 * Copyright (c) 2026, macOS-Pad-6 contributors.
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 */
#include <arm64/fge.h>
#include <arm64/fge_xnu.h>

#include <arm/misc_protos.h>
#include <arm64/proc_reg.h>
#include <kern/misc_protos.h>
#include <machine/atomic.h>
#include <mach/arm/thread_status.h>
#include <pexpert/pexpert.h>

#if HAS_APPLE_PAC
#error "FGE writes the saved state directly; a signed thread state (HAS_APPLE_PAC) needs MANIPULATE_SIGNED_THREAD_STATE here"
#endif

uint64_t fge_xnu_counts[16];

static int      fge_mode = -1;          /* -1 unread, 0 off, 1 on, 2 on + log */
static uint64_t fge_key;

static void
fge_xnu_init(void)
{
	int mode = 1;

	if (!PE_parse_boot_argn("fge", &mode, sizeof(mode))) {
		mode = 1;
	}
	fge_key = early_random();
	fge_mode = mode;                    /* benign race: every reader computes the same */
}

static int
fge_read_user(void *cookie __unused, fge_u64 addr, void *dst, unsigned size)
{
	return copyin((user_addr_t)addr, (char *)dst, size);
}

static int
fge_write_user(void *cookie __unused, fge_u64 addr, const void *src, unsigned size)
{
	return copyout((const char *)src, (user_addr_t)addr, size);
}

static int
fge_read_kern(void *cookie __unused, fge_u64 addr, void *dst, unsigned size)
{
	return copyin_kern((user_addr_t)addr, (char *)dst, size);
}

static int
fge_write_kern(void *cookie __unused, fge_u64 addr, const void *src, unsigned size)
{
	return copyout_kern((const char *)src, (user_addr_t)addr, size);
}

static void
fge_barrier(void *cookie __unused)
{
	__builtin_arm_dmb(DMB_ISH);
}

bool
fge_xnu_handle(arm_context_t *context)
{
	arm_saved_state_t *state = &context->ss;
	arm_saved_state64_t *ss;
	fge_ctx_t ctx;
	fge_class_t cls = FGE_CLASS_NONE;
	fge_result_t res;
	uint32_t insn = 0;
	bool kernel;
	unsigned r;

	if (__improbable(fge_mode < 0)) {
		fge_xnu_init();
	}
	if (fge_mode == 0 || !is_saved_state64(state)) {
		return false;
	}
	ss = saved_state64(state);
	kernel = PSR64_IS_KERNEL(ss->cpsr);
	if (!kernel && !PSR64_IS_USER64(ss->cpsr)) {
		return false;
	}

	if (kernel) {
		insn = *(volatile uint32_t *)ss->pc;
	} else if (copyin((user_addr_t)ss->pc, (char *)&insn, sizeof(insn)) != 0) {
		return false;
	}

	for (r = 0; r < 29; r++) {
		ctx.x[r] = ss->x[r];
	}
	ctx.x[29] = ss->fp;
	ctx.x[30] = ss->lr;
	ctx.sp = ss->sp;
	ctx.pc = ss->pc;
	ctx.nzcv = ss->cpsr;
	ctx.el = kernel ? 1 : 0;
	if (context->ns.nsh.flavor == ARM_NEON_SAVED_STATE64 &&
	    context->ns.nsh.count == ARM_NEON_SAVED_STATE64_COUNT) {
		ctx.v = (fge_vreg_t *)(void *)&context->ns.ns_64.v.q[0];
		ctx.fpsr = &context->ns.ns_64.fpsr;
		ctx.fpcr = context->ns.ns_64.fpcr;
	} else {
		ctx.v = NULL;
		ctx.fpsr = NULL;
		ctx.fpcr = 0;
	}
	ctx.read_mem = kernel ? fge_read_kern : fge_read_user;
	ctx.write_mem = kernel ? fge_write_kern : fge_write_user;
	ctx.barrier = fge_barrier;
	ctx.cookie = NULL;
	ctx.pacga_key = fge_key;

	res = fge_emulate(&ctx, insn, &cls);
	if (res != FGE_HANDLED) {
		/* FGE_MEM_FAULT: the original instruction would have faulted; the
		 * caller's undefined-instruction path reports it. A precise data
		 * abort is a later refinement (docs/roadmap.md). */
		return false;
	}

	for (r = 0; r < 29; r++) {
		ss->x[r] = ctx.x[r];
	}
	ss->fp = ctx.x[29];
	ss->lr = ctx.x[30];
	ss->sp = ctx.sp;
	ss->pc = ctx.pc;
	ss->cpsr = (ss->cpsr & 0x0FFFFFFFu) | (ctx.nzcv & 0xF0000000u);

	if ((unsigned)cls < 16) {
		uint64_t n = os_atomic_inc(&fge_xnu_counts[cls], relaxed);
		if (fge_mode == 2 && (n & 0xFFFFF) == 0) {
			kprintf("fge: %s %llu (pc 0x%llx)\n", fge_class_name(cls), n, ss->pc);
		}
	}
	return true;
}
