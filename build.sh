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
    if [ -f "$SDL3_PC" ]; then
        PKG_CONFIG_PATH_EXTRA="$SDL3_PREFIX/lib/pkgconfig:$PKG_CONFIG_PATH_EXTRA"
        echo "Using SDL3 from $SDL3_PREFIX"
    else
        echo "Building SDL3 from source..."
        SDL3_SRC="/tmp/sdl3-src"
        if [ ! -d "$SDL3_SRC" ]; then
            git clone --depth 1 --branch main https://github.com/libsdl-org/SDL.git "$SDL3_SRC"
        fi
        cmake -B "$SDL3_SRC/build" -DCMAKE_BUILD_TYPE=Release -DSDL_STATIC=OFF -DSDL_UNIX_CONSOLE_BUILD=ON -DSDL_X11_XTEST=OFF
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
export CFLAGS="-I$LOCAL_ROOT/usr/include"
export CXXFLAGS="-I$LOCAL_ROOT/usr/include"

# --- Regenerate configure if needed ---
if [ ! -f configure ] || [ configure.ac -nt configure ]; then
    echo "Running autoreconf -v -i ..."
    autoreconf -v -i
fi

# --- Configure if needed ---
if [ ! -f config.status ]; then
    echo "Running ./configure ..."
    ./configure
fi

# --- Build ---
echo "Running make -j$(nproc) ..."
make -j"$(nproc)"

echo "=== Build complete ==="
echo "Binary: $SCRIPT_DIR/exult"
