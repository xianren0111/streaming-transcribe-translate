# Environment configuration

The browser and Tk applications read the project-root `.env` at startup.
Restart the application after editing it. Do not put credentials in a shared
template. API keys saved through the UI are protected with Windows DPAPI.

## Precedence

For subtitle and interface options, saved JSON fields override environment
defaults. Environment values fill only missing fields; built-in defaults fill
the rest. Saving through the UI persists the current options, so later changes
to their environment defaults do not override those saved values.

Saved `overlay_window.json` coordinates override `OVERLAY_X` and `OVERLAY_Y`.
Coordinates are constrained to the visible screen when opening the overlay.
Environment defaults do not create settings files until the user saves changes.
Invalid active defaults produce a configuration error/notification.

Room, audio, chat mode, source language and translation credentials are already
saved directly in `.env`; changes to these entries affect the next startup.
Platform cookies/logins, current session, pause/lock state, pending messages,
device discovery and export-session selection are not environment configuration.

## Service, audio and room options

| Variable | Values | Default / behavior |
|---|---|---|
| `WEB_PORT` | Integer 0..65535 | 8765; 0 selects a free port; bind failure logs a warning and uses a free port |
| `OPENAI_API_BASE` | OpenAI-compatible API base URL | Configure your provider, e.g. `https://api.openai.com/v1` |
| `OPENAI_MODEL` | Provider-supported model ID | Backend default `gpt-4o-mini`; configure explicitly |
| `OPENAI_API_KEY` | Your API key or empty | Empty for providers requiring no key |
| `JEV_API_KEY` | Optional assistance API key or empty | Current free OpenCode Zen service requires no key |
| `AUDIO_INPUT` | `stream`, `microphone`, `system` | `stream`; Chinese values remain supported |
| `CHAT_MODE` | `manual`, `automatic` | `manual`; Chinese values remain supported |
| `SOURCE_LANGUAGE` | `ja`, `en`, `zh`, empty | Empty/missing uses automatic detection in the UI |
| `TARGET_LANGUAGE` | `zh-CN`, `zh-TW`, `en`, `ja`, `ko` | `zh-CN`; saved/explicit reading languages take precedence |
| `WHISPER_MODEL` | Backend model name/path | `base`; does not change installed desktop ASR models |
| `LIVE_PLATFORM` | `Bilibili`/`哔哩哔哩`, `YouTube`, `MissEvan`/`猫耳FM` | `Bilibili`; optional for full URLs |
| `LIVE_ROOM_URL` | Full live URL, or Bilibili/MissEvan numeric room ID | A URL identifies the platform; IDs require the platform |

Only one `LIVE_ROOM_URL` is needed. The application connects to one platform at
a time and detects it from a full URL. Switching sites changes that one URL;
this is not simultaneous multi-platform streaming. `LIVE_PLATFORM` is needed
only to disambiguate a numeric ID. Old `BILIBILI_ROOM_URL`, `YOUTUBE_ROOM_URL`,
and `MISSEVAN_ROOM_URL` entries remain readable for compatibility when no
`LIVE_ROOM_URL` is present, but the UI no longer writes them.
UI names are 哔哩哔哩 and 猫耳FM; stable English platform identifiers remain
accepted in existing configuration.
No separate room-ID variable is needed. English audio/chat aliases ignore case
and surrounding whitespace. Do not manually populate `*_API_KEY_DPAPI`.

## Subtitle defaults

All `SubtitleSettings` fields use `SUBTITLE_` plus the uppercase field name.
Booleans accept `true` or `false` (case-insensitive). Lists and dictionaries use
JSON, preferably enclosed in single dotenv quotes. Strings are UTF-8.

| Variable | Values | Built-in default |
|---|---|---|
| `SUBTITLE_PRESET` | Name present in `SUBTITLE_PRESETS` | `主播模式` |
| `SUBTITLE_PRESETS` | JSON object of named `{background, glossary}` string pairs | Built-in streamer/conversation presets |
| `SUBTITLE_USE_CONTEXT` | Boolean | false |
| `SUBTITLE_PREVIOUS_SENTENCES` | Integer 0..8 | 2 |
| `SUBTITLE_DISPLAY_MODE` | `边听边出`, `说完再出` | `边听边出` |
| `SUBTITLE_DEDUPLICATE` | Boolean | false |
| `SUBTITLE_IGNORE_ONOMATOPOEIA` | Boolean | true |
| `SUBTITLE_SMART_SEGMENTATION` | Boolean | false |
| `SUBTITLE_CHECK_TRANSLATION` | Boolean | false |
| `SUBTITLE_PALETTE` | `黑白`, `经典白`, `影院黄`, `薄荷绿`, `天空蓝`, `樱花粉`, `白底黑字` | `黑白` |
| `SUBTITLE_READING_LANGUAGES` | JSON array of unique `zh-CN`, `zh-TW`, `en`, `ja`, `ko` codes | `[]` falls back to `TARGET_LANGUAGE` |
| `SUBTITLE_CHAT_LANGUAGE` | One selected reading-language code, or empty | Empty selects first reading language |
| `SUBTITLE_CHAT_TEMPLATE` | Exactly one `{translation}`; optional `{original}`, `{language}` | Default follows UI language |
| `SUBTITLE_CHAT_TEMPLATE_CUSTOM` | Boolean | false; inferred true for a nonstandard template if not explicitly specified |
| `SUBTITLE_FONT_SIZE` | Integer 10..40 | 15 |
| `SUBTITLE_OPACITY` | Number 0.1..1 | 0.48 |
| `SUBTITLE_SHOW_ORIGINAL` | Boolean | true |
| `SUBTITLE_SHOW_STATS` | Boolean | true |
| `SUBTITLE_WIDTH_PERCENT` | Number 1..100 | 28 |
| `SUBTITLE_HEIGHT_PERCENT` | Number 1..80 | 10 |
| `SUBTITLE_RETAINED_SENTENCES` | Integer 1..200 | 50 |
| `SUBTITLE_SAVE_RECORDS` | Boolean | false |
| `SUBTITLE_RECORDS_FOLDER` | Absolute folder path, or empty for project `records` | Empty |
| `SUBTITLE_SAVE_CAPTIONS` | Boolean | true |
| `SUBTITLE_DIAGNOSTICS` | Boolean | false |
| `SUBTITLE_RECORDING_START` | Legacy string field | Empty; actual export clock is automatic at session start |
| `SUBTITLE_JEV_PROVIDER` | Legacy field; normalized to fixed free service | `OpenCode Zen（免费，不用 key）` |
| `SUBTITLE_JEV_URL` | Legacy field; normalized to empty | Empty; cannot override current fixed service |
| `SUBTITLE_JEV_MODEL` | Legacy field; normalized to empty | Empty; cannot override current fixed service |

Custom content names follow the existing loader's migration to streamer or
conversation mode. Include `主播模式` and/or `对话模式` to avoid that migration.
For a fixed chat template, explicitly set `SUBTITLE_CHAT_TEMPLATE_CUSTOM=true`.
With false, UI-language defaults are Chinese `【{translation}】`, English/Korean
`[{translation}]`, and Japanese `「{translation}」`.

## Interface and floating position

`SUBTITLE_IGNORE_ONOMATOPOEIA=true` (also available in subtitle behavior
settings) skips whole recognized utterances consisting only of known laughter,
animal calls or common sound words before translation, subtitle display and
chat delivery. It is enabled by default, including when older saved settings
omit the field. Mixed sentences and unknown or ambiguous sounds are preserved;
this is a conservative built-in vocabulary, not a semantic classifier.
Standalone Japanese interjections `ふん`, `うん`, `あっ` and `えっ` are also
skipped when enabled, as requested; this can omit a short affirmative response
such as `うん`. Sentences such as `うん、わかった` remain unchanged.
Set it to `false` to translate these utterances as before. Saved settings still
take precedence over this env default.

| Variable | Values | Built-in default |
|---|---|---|
| `UI_LANGUAGE` | `system`, `zh`, `en`, `ja`, `ko` | `system` |
| `UI_THEME` | `light`, `dark` | `light` |
| `OVERLAY_X` | Integer screen coordinate | Automatic position |
| `OVERLAY_Y` | Integer screen coordinate | Automatic position |

Specify both coordinates or omit both. Floating position applies to the browser
app's native subtitle window; the Tk fallback has its own basic subtitle window.

## Credential-free example

```dotenv
WEB_PORT=8765
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_API_KEY=
JEV_API_KEY=
SOURCE_LANGUAGE=
TARGET_LANGUAGE=zh-CN
AUDIO_INPUT=stream
CHAT_MODE=manual
LIVE_PLATFORM=Bilibili
LIVE_ROOM_URL=https://live.bilibili.com/25760587

UI_LANGUAGE=zh
UI_THEME=light
SUBTITLE_READING_LANGUAGES='["zh-CN", "en"]'
SUBTITLE_CHAT_LANGUAGE=zh-CN
SUBTITLE_CHAT_TEMPLATE='【{translation}】'
SUBTITLE_CHAT_TEMPLATE_CUSTOM=true
SUBTITLE_RETAINED_SENTENCES=50
SUBTITLE_SHOW_ORIGINAL=true
SUBTITLE_IGNORE_ONOMATOPOEIA=true
SUBTITLE_SAVE_RECORDS=false
SUBTITLE_RECORDS_FOLDER=
SUBTITLE_PRESETS='{"主播模式":{"background":"Live streamer speech.","glossary":"ASR: speech recognition"},"对话模式":{"background":"Everyday conversation.","glossary":""}}'
```
