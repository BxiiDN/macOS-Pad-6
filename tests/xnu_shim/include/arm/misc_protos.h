/* Shim. SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <mach/arm/thread_status.h>
typedef unsigned long vm_size_t;
extern int copyin_kern(const user_addr_t user_addr, char *kernel_addr, vm_size_t nbytes);
extern int copyout_kern(const char *kernel_addr, user_addr_t user_addr, vm_size_t nbytes);
