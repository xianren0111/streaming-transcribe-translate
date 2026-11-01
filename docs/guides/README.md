# Public guide pack / 使用指南 / 操作ガイド

## Word documents

The Chinese, Japanese and English Word documents are local deliverables for
manual publication, not repository files. They remain on the author's computer
as `User-Guide-zh.docx`, `User-Guide-ja.docx` and `User-Guide-en.docx` and are
excluded from future commits.

The documents explain first-time setup, translation services, audio/languages,
chat review, floating subtitles/OBS, reviewed-record exports, troubleshooting,
privacy and env-default precedence. Screenshots use synthetic captions, a
placeholder room/model, blank API keys and an isolated local demo session.
They do not contain the user's real captions, cookies or configuration.

## Twitter / X and Bilibili 动态

Each language has four local numbered PNG cards, sized 1080 x 1350.
These publication images are excluded from Git, like the Word documents.
Upload the four cards of one language in numerical order. Only the editable
caption text in [social](social/) is tracked.

| Language | Cards | Ready-to-edit captions |
|---|---|---|
| 中文 | `zh-01.png` .. `zh-04.png` | [posts-zh.txt](social/posts-zh.txt) |
| 日本語 | `ja-01.png` .. `ja-04.png` | [posts-ja.txt](social/posts-ja.txt) |
| English | `en-01.png` .. `en-04.png` | [posts-en.txt](social/posts-en.txt) |

Project branding and download links are intentionally not invented. Add the
real public project name and GitHub URL before announcing a release.
Twitter/X copy is designed for a standard-length post before adding a link;
check the platform's composer after editing.

## Editing and publication checklist

- [guide-content.json](guide-content.json) retains the localized written content.
- The local `images` folder contains the source screenshots; it is excluded
  from Git because no application or other project document uses these images.
- Open each Word document and review your preferred editor's layout before
  publishing; fonts and pagination can vary between Word/WPS/LibreOffice.
  All three documents have been rendered and checked as nine-page guides in
  LibreOffice, with embedded screenshots and no blank overflow pages.
- Do not replace demo screenshots with unredacted personal sessions.
- Do not upload private settings, model files, records, logs or credentials.
- This is a Windows Python base version, not a bundled standalone EXE.
- Platform functionality still uses the sibling `Streaming` project.
- Audio recognition is local; translation text goes to the selected API.
- Optional Decisions sends text to OpenCode Zen.
- One platform at a time; multiple reading languages, one review/send language.
- Records are off by default and export reviewed sent/skipped text, not an
  automatic archive of all speech.

See [the project README](../../README.md) and
[environment configuration](../ENV_CONFIGURATION.md) for installation details
and the complete parameter reference.
