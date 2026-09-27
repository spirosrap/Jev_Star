#!/bin/sh
# Build the two campaign map tools into .tools/ (needs git, cmake and a C++ compiler).
set -e
root=$(cd "$(dirname "$0")/../.." && pwd)
src="$root/.tools/src"
mkdir -p "$src"
[ -d "$src/CascLib" ] || git clone -q --depth 1 https://github.com/ladislav-zezula/CascLib.git "$src/CascLib"
[ -d "$src/StormLib" ] || git clone -q --depth 1 https://github.com/ladislav-zezula/StormLib.git "$src/StormLib"
# CascLib uses the Windows-only LPDWORD type in one place; PDWORD is its portable equivalent.
sed -i 's/\bLPDWORD\b/PDWORD/g' "$src/CascLib/src/CascFiles.cpp"
cmake -S "$src/CascLib" -B "$src/CascLib/build" -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=Release \
      -DCASC_BUILD_SHARED_LIB=OFF -DCASC_BUILD_STATIC_LIB=ON >/dev/null
cmake --build "$src/CascLib/build" -j4 >/dev/null
cmake -S "$src/StormLib" -B "$src/StormLib/build" -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_SHARED_LIBS=OFF -DSTORM_USE_BUNDLED_LIBRARIES=ON >/dev/null
cmake --build "$src/StormLib/build" -j4 >/dev/null
here=$(dirname "$0")
g++ -O2 -o "$root/.tools/casc_tool" "$here/casc_tool.cpp" -I"$src/CascLib/src" "$src/CascLib/build/libcasc.a" -lz -lpthread
g++ -O2 -std=c++17 -o "$root/.tools/mpq_pack" "$here/mpq_pack.cpp" -I"$src/StormLib/src" "$src/StormLib/build/libstorm.a" -lz -lbz2 -lpthread
echo "Built $root/.tools/casc_tool and $root/.tools/mpq_pack"
