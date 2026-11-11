# Host build of FGE (shared library for tests/fge) and an AArch64 object check.
#   cmake -S kernel/fge -B build/cmake -G Ninja && ninja -C build/cmake
# SPDX-License-Identifier: BSD-2-Clause-Patent
cmake_minimum_required(VERSION 3.20)
project(fge C)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

add_library(fge SHARED fge.c)
target_compile_options(fge PRIVATE -Wall -Wextra -Werror)

find_program(CLANG clang)
if(CLANG)
  add_custom_command(
    OUTPUT fge-aarch64.o
    COMMAND ${CLANG} --target=aarch64-none-elf -mcpu=cortex-a77 -std=c11 -O2 -ffreestanding
            -fno-builtin -mgeneral-regs-only -DFGE_FREESTANDING -Wall -Wextra -Werror
            -c ${CMAKE_CURRENT_SOURCE_DIR}/fge.c -o fge-aarch64.o
    DEPENDS fge.c fge.h)
  add_custom_target(fge_aarch64 ALL DEPENDS fge-aarch64.o)
endif()
