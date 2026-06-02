#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 <program.S>" >&2
    exit 2
fi

src=$1
if [ ! -f "$src" ]; then
    echo "error: source not found: $src" >&2
    exit 2
fi

if [ -n "${CROSS_PREFIX:-}" ]; then
    prefix=$CROSS_PREFIX
elif command -v riscv32-unknown-elf-gcc >/dev/null 2>&1; then
    prefix=riscv32-unknown-elf-
elif command -v riscv64-unknown-elf-gcc >/dev/null 2>&1; then
    prefix=riscv64-unknown-elf-
else
    echo "error: no RISC-V GCC found; set CROSS_PREFIX, for example CROSS_PREFIX=riscv32-unknown-elf-" >&2
    exit 1
fi

base=$(basename "$src" .S)
mkdir -p build

elf=build/$base.elf
bin=build/$base.bin
mem=build/$base.mem
map=build/$base.map

"${prefix}gcc" \
    -march=rv32im -mabi=ilp32 \
    -nostdlib -nostartfiles -ffreestanding \
    -Wl,-T,linker.ld,-Map,"$map",--build-id=none,--no-relax \
    -o "$elf" "$src"

"${prefix}objcopy" -O binary "$elf" "$bin"

size=$(wc -c < "$bin" | tr -d ' ')
if [ "$size" -gt 512 ]; then
    echo "error: $bin is $size bytes, larger than 512-byte boot image" >&2
    exit 1
fi

{
    echo "@000000"
    od -An -v -tx1 "$bin" | tr ' ' '\n' | awk -v limit=512 '
        NF {
            print toupper($0)
            count++
        }
        END {
            for (; count < limit; count++) {
                print "00"
            }
        }
    '
} > "$mem"

echo "wrote $elf"
echo "wrote $bin ($size bytes)"
echo "wrote $mem"
