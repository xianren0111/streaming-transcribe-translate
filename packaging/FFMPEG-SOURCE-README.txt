LiveSubtitles 1.0.0 corresponding source materials

The application invokes FFmpeg as a separate executable and PyAV dynamically
loads the same LGPL FFmpeg build. No original PyAV codec DLLs, x264, x265,
third-party codecs, CUDA, or GPL-enabled FFmpeg libraries are redistributed.
The only non-system runtime code in this FFmpeg build is FFmpeg itself and
the permissively licensed LLVM/MinGW runtime. All copyright/license notices
are included. FFmpeg source is unmodified n8.1, LGPL-2.1-or-later.

The complete unmodified FFmpeg source archive is ffmpeg-n8.1.tar.gz.
SOURCE-MANIFEST.json records its official source URL and SHA256, the compiler
and make download URLs/hashes, and built binary hashes.
ffmpeg-build-config contains the exact configure/build options.

To rebuild on Windows x64:
1. Install Git for Windows to obtain Bash.
2. Download the compiler and make archives identified in SOURCE-MANIFEST.json.
3. Create build/ffmpeg-toolchain relative to your working project folder.
4. Extract the compiler there (llvm-mingw-20261020-ucrt-x86_64).
5. Extract make to build/ffmpeg-toolchain/make.
6. Extract ffmpeg-n8.1.tar.gz to build/ffmpeg-toolchain/FFmpeg-n8.1.
7. Put build_ffmpeg.sh in packaging/ and run it with Git for Windows Bash.
8. The resulting executable and seven DLLs are in build/ffmpeg-lgpl/bin.

Source configure prefix is a build detail; output can be installed anywhere.
Users may replace the FFmpeg executable/DLLs, including the PyAV import-name
copies, with ABI-compatible builds of their choosing. No signature check or
restriction prevents library replacement or reverse engineering for debugging
modifications. Preserve FFmpeg LGPL notices when redistributing changes.

The same release must supply this source archive alongside the binary ZIP.
Do not publish the binary ZIP without these source materials.
The separate MIT application remains MIT; FFmpeg's LGPL terms are independent.

The QR terminal source archive preserves upstream MIT declaration and author's
available attribution. Streaming authorization is expressly from xianren0111
on 2026-11-01, not assumed from the historical Nyanko7 reference.
