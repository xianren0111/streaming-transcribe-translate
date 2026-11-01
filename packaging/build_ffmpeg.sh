#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS="$ROOT/build/ffmpeg-toolchain"
export TMPDIR="$TOOLS/scratch"
export revision=8.1
mkdir -p "$TMPDIR"
export PATH="$TOOLS/llvm-mingw-20261020-ucrt-x86_64/bin:$TOOLS/make/bin:$PATH"
SOURCE="$TOOLS/FFmpeg-n8.1"
PREFIX="$ROOT/build/ffmpeg-lgpl"
cd "$SOURCE"

./configure \
  --target-os=mingw32 --arch=x86_64 \
  --cc=x86_64-w64-mingw32-clang --cxx=x86_64-w64-mingw32-clang++ \
  --ar=llvm-ar --nm=llvm-nm --ranlib=llvm-ranlib --strip=llvm-strip \
  --prefix=/ffmpeg \
  --disable-autodetect --disable-x86asm --disable-debug --disable-doc \
  --disable-ffplay --disable-gpl --disable-nonfree --disable-version3 \
  --disable-cuda --disable-cuvid --disable-nvenc --disable-nvdec \
  --enable-schannel --enable-network --enable-shared --enable-static \
  --disable-vulkan --disable-d3d11va --disable-d3d12va --disable-dxva2 \
  --disable-amf --disable-mediafoundation \
  --disable-decoders \
  --enable-decoder=aac,aac_fixed,mp3,mp3float,opus,vorbis,flac,alac \
  --enable-decoder='pcm*' \
  --disable-demuxers \
  --enable-demuxer=aac,mp3,mov,flv,matroska,ogg,wav,flac,mpegts,hls \
  --disable-parsers --enable-parser=aac,aac_latm,mpegaudio,opus,vorbis,flac \
  --disable-encoders --enable-encoder=pcm_s16le \
  --disable-muxers --enable-muxer=pcm_s16le --enable-muxer=wav \
  --disable-bsfs \
  --disable-filters --enable-filter=anullsrc --enable-filter=aresample \
  --enable-filter=aformat --enable-filter=anull \
  --disable-indevs --enable-indev=lavfi --disable-outdevs

./ffbuild/version.sh . libavutil/ffversion.h
make -j4
make install prefix="$PREFIX"
cp config.h config_components.h ffbuild/config.mak "$PREFIX/"
"$PREFIX/bin/ffmpeg.exe" -version > "$PREFIX/BUILD-VERSION.txt"
"$PREFIX/bin/ffmpeg.exe" -L > "$PREFIX/LICENSE-REPORT.txt"
