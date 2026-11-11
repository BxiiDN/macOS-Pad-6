// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa: the owner-root queries the kernel asks after a mount. UniXNU-sheng's package/SourceRootBinding.cpp answers 1
// when the mounted device is the one IOMedia above a NativeUfs window that verified its volume UUID. pipa verifies
// no UFS root (it mounts none from userdata), so every query answers "not authorized" and gives no digest or device:
// a UFS-backed root is refused by the kernel's owner-root checks. New in macOS-Pad-6; compiled only on the macOS runner.
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <sys/types.h>

extern "C" {
int native_verified_block_root_authorized(dev_t device);
int native_verified_block_manifest_sha384(dev_t device, const char *uuid, uint8_t digest[48]);
int native_verified_block_volume_device(const char *uuid, dev_t *device, char *path, size_t size);
}

extern "C" int native_verified_block_root_authorized(dev_t)
{
    return 0;
}

extern "C" int native_verified_block_manifest_sha384(dev_t, const char *, uint8_t digest[48])
{
    if (digest) memset(digest, 0, 48);
    return 0;
}

extern "C" int native_verified_block_volume_device(const char *, dev_t *device, char *path, size_t size)
{
    if (device) *device = 0;
    if (path && size) path[0] = 0;
    return 0;
}
