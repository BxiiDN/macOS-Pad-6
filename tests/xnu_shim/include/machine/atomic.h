/* Shim of os_atomic_inc(p, relaxed): returns the new value, as XNU's does. SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#define os_atomic_inc(p, m) (__atomic_add_fetch((p), 1, __ATOMIC_RELAXED))
