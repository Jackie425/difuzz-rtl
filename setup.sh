#!/bin/bash

# Install elf2hex
cd "$(dirname "${BASH_SOURCE[0]}")"
ELF2HEX_PREFIX=${PWD}/../env/elf2hex

# Fetch elf2hex source via submodule
git submodule update --init elf2hex

pushd elf2hex > /dev/null
autoreconf -i
./configure --target=riscv64-unknown-elf --prefix=${ELF2HEX_PREFIX}
make -j"$(nproc)"
make install
popd > /dev/null

# Make elf2hex visible in the current shell session.
export PATH=${ELF2HEX_PREFIX}/bin:$PATH

# Build riscv-isa-sim
pushd Fuzzer/ISASim/riscv-isa-sim > /dev/null
mkdir build
pushd build > /dev/null
echo $PWD
../configure --prefix=$PWD
make -j4
popd > /dev/null
popd > /dev/null

source env.sh
