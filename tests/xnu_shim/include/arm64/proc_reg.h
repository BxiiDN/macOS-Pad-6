/* Shim of the xnu-12377.121.6 macros fge_xnu.c uses. SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#define PSR64_MODE_EL_MASK 0x0000000C
#define PSR64_MODE_EL0 0x00000000
#define PSR64_MODE_RW_32 0x00000010
#define PSR64_IS_KERNEL(x) ((x & PSR64_MODE_EL_MASK) != PSR64_MODE_EL0)
#define PSR64_IS_USER(x) ((x & PSR64_MODE_EL_MASK) == PSR64_MODE_EL0)
#define PSR64_IS_USER64(x) (PSR64_IS_USER(x) && !(x & PSR64_MODE_RW_32))
#define DMB_ISH 0xb
#ifdef FGE_HOST_TEST
/* Host test only: no ARM barrier instruction on the build machine. */
#define __builtin_arm_dmb(x) __atomic_thread_fence(__ATOMIC_SEQ_CST)
#endif
