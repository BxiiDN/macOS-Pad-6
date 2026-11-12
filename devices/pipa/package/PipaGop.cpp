// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa (macOS): GopFramebuffer's NativeGOPPresenter on the firmware frame buffer, so the GPU hand-off that Adreno650's
// user client forwards (native_gop_handoff_call / native_gop_handoff_memory) has a presenter to reach. On iPadOS the
// display driver (NativeLegacyDisplay) creates the presenter on the display node; macOS 26.5 has no such driver here, so
// this attaches it to a nub of its own under the platform expert. The nub's one memory range is the frame buffer that
// PE_current_console reports (the GOP buffer UEFI left, the one the kernel console draws to); the presenter checks the
// mapping against it again, so a mismatch stops it instead of publishing the wrong memory.
//
// Off unless pipa-gop=1. It writes no register: it maps memory the console already maps. GPU mode (a client that waits
// for frames and lets the GPU copy them) also needs sheng-fb-gpu=1, the presenter's own switch; without it a privileged
// client can only copy pixels in (NGP_METHOD_PRESENT). Nothing here has run on a tablet.
#include <IOKit/IOService.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOLib.h>
#include <libkern/c++/OSArray.h>
#include <pexpert/pexpert.h>

extern "C" {
IOService *native_gop_presenter_create(void);
void native_gop_presenter_set_source(IOService *presenter, IOService *nub);
extern volatile uint32_t native_gop_ready;
// 0 not asked, 1 running, 2 the presenter started, negative: the step that stopped it.
volatile int32_t pipa_gop_state;
void pipa_gop_start(void);
}

static int32_t gop_stop(int32_t step, const char *why)
{
    pipa_gop_state = step;
    IOLog("pipa-gop: not started (%s)\n", why);
    return step;
}

void pipa_gop_start(void)
{
    unsigned on = 0;
    if (pipa_gop_state || !PE_parse_boot_argn("pipa-gop", &on, sizeof on) || on != 1)
        return;
    pipa_gop_state = 1;
    PE_Video video = {};
    if (PE_current_console(&video) || !video.v_baseAddr || !video.v_width || !video.v_height || video.v_depth != 32 ||
        video.v_rowBytes < video.v_width * 4 || video.v_height > 16384) {
        gop_stop(-1, "no 32-bit firmware frame buffer");
        return;
    }
    const uint64_t bytes = uint64_t(video.v_rowBytes) * video.v_height;
    IOService *platform = IOService::getPlatform();
    if (!platform) {
        gop_stop(-2, "no platform expert");
        return;
    }
    IOService *nub = new IOService;
    IODeviceMemory *range = IODeviceMemory::withRange(video.v_baseAddr, bytes);
    OSArray *ranges = range ? OSArray::withObjects((const OSObject **)&range, 1) : nullptr;
    if (!nub || !nub->init() || !ranges) {
        OSSafeReleaseNULL(nub);
        OSSafeReleaseNULL(range);
        OSSafeReleaseNULL(ranges);
        gop_stop(-3, "no memory for the frame buffer nub");
        return;
    }
    nub->setName("pipa-gop-framebuffer");
    nub->setDeviceMemory(ranges);
    ranges->release();
    range->release();
    if (!nub->attach(platform)) {
        nub->release();
        gop_stop(-4, "cannot attach the nub");
        return;
    }
    nub->registerService();
    IOService *presenter = native_gop_presenter_create();
    if (!presenter || !presenter->init()) {
        OSSafeReleaseNULL(presenter);
        nub->release();
        gop_stop(-5, "no presenter");
        return;
    }
    native_gop_presenter_set_source(presenter, nub);
    if (!presenter->attach(nub)) {
        presenter->release();
        nub->release();
        gop_stop(-6, "cannot attach the presenter");
        return;
    }
    if (!presenter->start(nub)) {
        presenter->detach(nub);
        presenter->release();
        nub->release();
        gop_stop(-7, "the presenter refused the frame buffer");
        return;
    }
    presenter->release();   // the registry holds it now, as it holds the nub
    nub->release();
    pipa_gop_state = 2;
    IOLog("pipa-gop: presenter on %ux%u, %u bytes a row, %llu bytes at 0x%llx (ready %u)\n", video.v_width,
          video.v_height, video.v_rowBytes, (unsigned long long)bytes, (unsigned long long)video.v_baseAddr,
          native_gop_ready);
}
