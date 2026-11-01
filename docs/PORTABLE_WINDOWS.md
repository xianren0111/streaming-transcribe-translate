# Windows portable edition

Release: `v1.0.1`, Windows x64.

## For users

1. Download `LiveSubtitles-1.0.1-windows-x64.zip` from
   [GitHub Releases](https://github.com/xianren0111/streaming-transcribe-translate/releases).
2. Extract the entire ZIP into a writable folder, for example
   `Documents\LiveSubtitles`. Do not run the EXE from inside the ZIP or move the
   EXE away from its accompanying files.
3. Double-click `LiveSubtitles.exe`. No separate Python, FFmpeg or sibling
   Streaming project installation is required in the portable edition.
4. On first use, click the model download button. This downloads approximately
   230 MB from the model providers. Wait for completion; on network failure,
   the dialog explains the error and allows retry. Cancellation exits without
   starting the subtitle session.
5. The browser interface opens locally. In Settings > Translation, enter your
   own OpenAI-compatible service address, supported model and API key; save and
   test the connection.
6. Paste one full live URL, or choose microphone/computer audio, select reading
   languages and start subtitles. One platform at a time; review/send uses one
   selected language.

首次使用：完整解压 → 双击 `LiveSubtitles.exe` → 下载本机模型 →
设置翻译服务并测试 → 选择声音和语言 → 开始字幕。

初回使用：ZIP全体を展開 → `LiveSubtitles.exe` →
音声モデルをダウンロード → 翻訳APIを設定・テスト → 音声と言語を選択。

## Privacy and portability

The EXE's folder is the portable data directory. Models, settings, API keys,
records and logs are created there, not inside the temporary extraction folder.
Keep this directory private. Do not put it in Program Files or another location
without write permission. Do not publish the generated `.env`, settings,
records, logs, cookies or live session URL.

API keys saved on Windows are encrypted for the current Windows user. Moving
the portable folder to a different Windows account or PC may require entering
the key again. Platform logins are temporary and are not bundled.

Speech recognition runs locally after model setup. Translation text is sent
to your chosen API; optional Decisions assistance sends text to OpenCode Zen.
API charges, rate limits and platform restrictions still apply.

## Troubleshooting

- Keep `_internal` and all other ZIP contents beside the EXE.
- Model downloads need access to Hugging Face and GitHub. Retry after fixing
  network/firewall/proxy issues.
- Startup diagnostics are in `logs\portable-startup.log`. Inspect/redact logs
  before sharing them.
- If Windows warns about an unsigned application, verify its source and ZIP
  SHA-256 before deciding whether to run it. The release is not code-signed.
- No models are included in the ZIP; an internet connection is needed for the
  first model setup and for online translation/live streams.
- Close using the application's Quit button, not just the browser tab.
- The source-code launchers and source installation instructions still apply
  to developers; they are not required for portable users.

## Build and verification

The packaging configuration/build script is maintained under `packaging`.
Build dependencies are separate from ordinary application dependencies.
Portable archives include runtime dependencies, bundled platform components,
FFmpeg and third-party license notices; local user data and downloaded models
must never be collected.

Publish `LiveSubtitles-1.0.1-corresponding-source.zip` alongside the Windows
archive and `LiveSubtitles-1.0.1-SHA256SUMS.txt`. The source archive contains the
corresponding sources and build configuration for the bundled LGPL-only FFmpeg.
Third-party notices and the Streaming components' MIT redistribution
authorization are included with the bundle. The source archive is for license
compliance and rebuilding; ordinary users only need the Windows ZIP.

The portable entry point accepts `--setup-models` for model setup only and
`--self-test-report <absolute-path.json>` for a non-network runtime smoke test.
The smoke test exercises native imports, platform components, Tk, FFmpeg PCM
conversion and the real localhost browser server. It does not read personal
configuration, send chat or contact translation APIs.

Add `--self-test-models` to also load the installed Japanese ReazonSpeech and
Chinese Whisper models and recognize a short silence sample. This requires
models in the validation copy; do not include them in release archives.

## Updating from v1.0.0

Quit the old application normally before updating. Extract v1.0.1 into a new
writable folder. If desired, copy your private `models` folder and saved
configuration files from the old folder; do not share them. Keys may require
re-entry on a different Windows account or PC.

v1.0.1 adds a default-enabled **Ignore sound words** checkbox in subtitle
behavior settings. Whole utterances consisting only of known laughter, calls
or common onomatopoeia are skipped before translation, display and chat
delivery. Mixed sentences and ambiguous or unknown words remain unchanged.
Older settings without this field use the new enabled default. Uncheck it to
restore translation of these sounds.
