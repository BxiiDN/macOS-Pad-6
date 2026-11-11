/* Shim (copyin/copyout from bsd/libkern/copyio.h via misc_protos.h). SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <mach/arm/thread_status.h>
int copyin(const user_addr_t uaddr, void *kaddr, size_t len) __attribute__((warn_unused_result));
int copyout(const void *kaddr, user_addr_t udaddr, size_t len);
extern uint64_t early_random(void);
