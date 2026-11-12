// SPDX-License-Identifier: BSD-2-Clause-Patent
// pipa (macOS): what zzzzd-pipa-board-start.patch calls from bsd_init, after the source storage. Each part reads its own
// boot argument and returns at once without it (board.toml passes none of them):
//   pipa_gop_start     pipa-gop=1: GopFramebuffer's presenter on the firmware frame buffer (PipaGop.cpp)
//   native_gpu_probe   pipa-gpu=<1..11>: the staged Adreno 650 bring-up in a thread of its own (GpuProbe.cpp, macOS build);
//                      modes that write registers also need pipa-gpu-writes=1
// The presenter goes first, so the hand-off has a presenter before the GPU publishes its user client.
// Compiled into libPipaGpu.a (build-pipa-gpu.py). Not run anywhere yet.
void pipa_gop_start(void);
void native_gpu_probe(void);
void pipa_board_start(void);

void pipa_board_start(void)
{
    pipa_gop_start();
    native_gpu_probe();
}
