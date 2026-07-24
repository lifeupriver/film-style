# Changelog

All notable changes to this project are documented in this file.

## [1.0.0] - 2026-07-24

### Added

- Per-command `--genre` flag and `film-style genre use` for switching workspaces
- Legacy layout migration prompt on CLI startup; MCP refuses legacy layouts
- Genre-pack-driven emotion weights and genre-neutral `peak_emotion_score` fields
- Genre-scoped MCP resources (`film-style://{genre}/profile`, etc.)
- Dashboard genre badge, complete settings form, and dynamic masthead subtitle
- GitHub Actions CI (test matrix + ruff) and PyPI release workflow
- `PRIVACY.md` documenting local vs cloud data flows
- HTTP hardening: POST body limits, atomic config writes, chapter label validation
- Non-loopback bind requires `--insecure-public` on `film-style serve`

### Changed

- Version bumped to 1.0.0 (production/stable)
- Dynamic `data_root()` and `config_path()` for correct test isolation
- MCP clip description schema hints derive from active genre pack

### Fixed

- Settings persistence uses live config path (not import-time HOME)
- Dashboard and MCP no longer hardcode wedding-only vocabulary

[1.0.0]: https://github.com/lifeupriver/film-style/releases/tag/v1.0.0
