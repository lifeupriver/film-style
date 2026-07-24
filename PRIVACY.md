# Privacy

film-style-analyzer is a **local-first** desktop tool. By default, all analysis
artifacts stay on your machine under `~/.film-style-analyzer/`.

## What stays local

Unless you explicitly enable optional cloud features:

- Video files you analyze (never uploaded by the core pipeline)
- Analysis JSON, thumbnails, transcripts, and style profiles
- The local dashboard (`film-style serve` on `127.0.0.1` by default)
- MCP stdio transport (launched by Claude Desktop on your machine)

## Optional cloud data flows

| Feature | Data sent | Provider |
|---------|-----------|----------|
| `film-style guide` | Aggregated stats + optional vision thumbnails | Anthropic API |
| `--vision` / `--shot-sizes` | Thumbnail images (base64) | Anthropic API |
| `--gemini` / YouTube via Gemini | Full video or URL | Google Gemini API |
| `--skip-audio` off + diarization | Audio for transcription; optional speaker model download | WhisperX / Hugging Face |
| `film-style import` | Video URL to download | yt-dlp (target host) |

Enabling these features sends data to the respective providers under their terms.
API keys are read from environment variables (`ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`,
`HF_TOKEN`) and are not stored in config files.

## Sensitive content

Wedding and event footage often contains:

- Identifiable faces (emotion detection via DeepFace when `[shots]` is installed)
- Speech transcripts (names, vows, private conversations)
- Absolute filesystem paths in analysis JSON

Review exports (`/api/handoff.zip`, `style-guide.md`) before sharing.

## Retention and deletion

The tool does not implement automatic retention limits. To remove a corpus:

```bash
rm -rf ~/.film-style-analyzer/<genre>/
```

To remove everything:

```bash
rm -rf ~/.film-style-analyzer/
```

Extracted WAV files can be deleted automatically via `cleanup_audio_after_analysis`
(default: true). Transcripts and thumbnails persist until you delete them.

## Network exposure

The dashboard binds to loopback by default. Binding to `0.0.0.0` or another interface
requires `--insecure-public` and exposes an unauthenticated local API — do not do this
on untrusted networks without a reverse proxy and authentication.

## Questions

For security concerns, open an issue at
https://github.com/lifeupriver/film-style/issues
