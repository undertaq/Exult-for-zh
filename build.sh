#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Exult Build Script ==="

PKG_CONFIG_PATH_EXTRA=""

# --- Autotools ---
if ! command -v autoreconf &>/dev/null; then
    echo "Installing autoconf, automake, and libtool..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -qq && sudo apt-get install -y -qq autoconf automake libtool autoconf-archive pkg-config
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y autoconf automake libtool autoconf-archive pkg-config
    elif command -v brew &>/dev/null; then
        brew install autoconf automake libtool autoconf-archive pkg-config
    else
        echo "ERROR: No known package manager found. Install autoconf, automake, libtool, and pkg-config manually."
        exit 1
    fi
fi

# --- SDL3 ---
SDL3_PREFIX="/tmp/sdl3-install"
SDL3_PC="$SDL3_PREFIX/lib/pkgconfig/sdl3.pc"
if ! PKG_CONFIG_PATH="$PKG_CONFIG_PATH_EXTRA" pkg-config --exists sdl3 2>/dev/null; then
    if [ -f "$SDL3_PC" ] && grep -q "^prefix=$SDL3_PREFIX$" "$SDL3_PC"; then
        PKG_CONFIG_PATH_EXTRA="$SDL3_PREFIX/lib/pkgconfig:$PKG_CONFIG_PATH_EXTRA"
        echo "Using SDL3 from $SDL3_PREFIX"
    else
        echo "Building SDL3 from source..."
        SDL3_SRC="/tmp/sdl3-src"
        if [ ! -d "$SDL3_SRC" ]; then
            git clone --depth 1 --branch main https://github.com/libsdl-org/SDL.git "$SDL3_SRC"
        fi
        cmake -S "$SDL3_SRC" -B "$SDL3_SRC/build" \
            -DCMAKE_BUILD_TYPE=Release \
            -DCMAKE_INSTALL_PREFIX="$SDL3_PREFIX" \
            -DSDL_STATIC=OFF -DSDL_UNIX_CONSOLE_BUILD=ON -DSDL_X11_XTEST=OFF
        cmake --build "$SDL3_SRC/build" -j"$(nproc)"
        cmake --install "$SDL3_SRC/build" --prefix "$SDL3_PREFIX"
        PKG_CONFIG_PATH_EXTRA="$SDL3_PREFIX/lib/pkgconfig:$PKG_CONFIG_PATH_EXTRA"
    fi
fi

# --- Local dev dependencies (for systems without -dev packages) ---
LOCAL_ROOT="/tmp/local-root"
LOCAL_PC="$LOCAL_ROOT/usr/lib/x86_64-linux-gnu/pkgconfig"
if [ -d "$LOCAL_PC" ]; then
    PKG_CONFIG_PATH_EXTRA="$LOCAL_PC:$PKG_CONFIG_PATH_EXTRA"
fi

export PKG_CONFIG_PATH="$PKG_CONFIG_PATH_EXTRA"
LOCAL_INCLUDE_FLAGS="-I$LOCAL_ROOT/usr/include"
for include_dir in freetype2 libpng16; do
    if [ -d "$LOCAL_ROOT/usr/include/$include_dir" ]; then
        LOCAL_INCLUDE_FLAGS="$LOCAL_INCLUDE_FLAGS -I$LOCAL_ROOT/usr/include/$include_dir"
    fi
done
export CFLAGS="$LOCAL_INCLUDE_FLAGS ${CFLAGS:-}"
export CXXFLAGS="$LOCAL_INCLUDE_FLAGS ${CXXFLAGS:-}"
LOCAL_LIB_DIR="$LOCAL_ROOT/usr/lib/x86_64-linux-gnu"
if [ -f "$LOCAL_LIB_DIR/libfreetype.a" ]; then
    # The staged FreeType archive has Brotli and BZip2 dependencies that are
    # normally supplied by freetype2.pc's private dependencies.
    export LDFLAGS="-L$LOCAL_LIB_DIR ${LDFLAGS:-}"
    export LIBS="-lbrotlidec -lbrotlicommon -lbz2 ${LIBS:-}"
fi

# --- Regenerate configure if needed ---
if [ ! -f configure ] || [ configure.ac -nt configure ]; then
    echo "Running autoreconf -v -i ..."
    autoreconf -v -i
fi

# --- Configure ---
# SDL3 may have been installed by this invocation, and an existing
# config.status can contain empty/stale SDL_CFLAGS and SDL_LIBS. Re-run
# configure after establishing PKG_CONFIG_PATH so the generated Makefiles
# always use the SDL3 installation selected above.
echo "Running ./configure ..."
./configure

# --- Build ---
echo "Running make -j$(nproc) ..."
make -j"$(nproc)"

echo "=== Build complete ==="
echo "Binary: $SCRIPT_DIR/exult"
