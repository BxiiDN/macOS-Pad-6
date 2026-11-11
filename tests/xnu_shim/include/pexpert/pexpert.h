/* Shim. SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
typedef int boolean_t;
extern boolean_t PE_parse_boot_argn(const char *arg_string, void *arg_ptr, int max_arg);
void kprintf(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
