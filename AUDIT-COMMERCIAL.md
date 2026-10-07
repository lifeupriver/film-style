# Commercial audit: film-style-analyzer

*Audit date: 2026-10-07. Code reviewed at commit `6b714e9` on `main`.*

Three parallel reviews fed this report: the product and code, the market, and launch readiness. The tests and the package build were run in this session. No product code was changed.

---

## 0. Urgent, before anything else

**A credential was committed in this public repository.** A handoff document under `docs/handoffs/` contained what appears to be a real `VIMEO_ACCESS_TOKEN`, along with client couple names, Vimeo video IDs and a local home-directory path.

**Status (2026-10-07):** the file has been removed from the history of every branch with `git filter-repo`, and all branches were force-pushed. Three things still remain:

1. **Revoke the token in Vimeo.** It was public for months, so treat it as compromised whether or not it is still in the history.
2. **GitHub still holds the old commits under pull-request refs and in its cache.** These are the read-only `refs/pull/1–5` refs, which cannot be force-pushed. Ask GitHub Support to purge cached views and run garbage collection on the old commits. Any existing forks or clones also keep the old history.
3. **Re-clone or hard-reset** every local checkout and agent worktree, so the old history is not pushed back.

This report deliberately does not repeat the token or any client names.

---

## 1. What it is

**In plain words:** a tool that watches a filmmaker's finished films and works out how they edit. It measures how long shots last and how pacing changes across a film, which transitions they use, their colour grade, shot sizes, how they mix music, speech and ambient sound, whether cuts land on the beat, how the film is structured into chapters, and the framing, exposure and emotion of the shots they keep. It then produces three things:

- a **plain-English style guide**, the brief you would give a new assistant editor;
- a **machine-readable style profile** (JSON) that an AI assistant such as Claude Desktop, connected over MCP, can follow when told "edit this in my style";
- a **local dashboard** for browsing the archive, viewing pacing curves and correcting labels.

On top of that it can:

- **score a rough cut** (Final Cut Pro FCPXML) against the profile and point out where it drifts;
- **score raw footage clips 0–100** against the shot preferences it has learned, so the edit starts from a shortlist.

**Who it is for:** working wedding filmmakers first. It also ships genre packs for commercial, brand content, social shorts, music video and documentary. In practice it fits editors who are comfortable in a terminal.

**The problem it solves:** an editor's personal style lives in their head. It is hard to put into words, hard to hand to an assistant or contractor, and impossible for AI tools to follow without some measured target. This is the video version of what Imagen AI's "Personal AI Profile" does for photographers.

It was built by and for the owner's own wedding-film business, and tuned on that archive.

---

## 2. How built it is

### Tech stack

| Layer | What is used |
|---|---|
| Language and packaging | Python 3.11+, setuptools, a `film-style` command built with click and rich |
| Core | pydantic v2, PySceneDetect with OpenCV, ffmpeg/ffprobe, the Anthropic SDK |
| Optional extras | librosa (music/beat), yt-dlp (Vimeo/YouTube import), google-generativeai (Gemini), MCP/FastMCP (Claude Desktop), WhisperX and inaSpeechSegmenter (audio), MediaPipe, DeepFace and TensorFlow (shot composition and emotion) |
| Dashboard | Python standard-library `http.server` on `127.0.0.1:7421`; vanilla JS single-page app with hand-drawn SVG charts; no build step |
| AI | Claude, used for the style guide and for vision labelling of chapters and shot sizes. Model ID `claude-sonnet-4-20250514` is hard-coded and out of date. A `claude` CLI backend can use the owner's own subscription instead. Gemini 2.5 Pro is used for whole-film analysis. Whisper runs locally |
| Storage | Local files under `~/.film-style-analyzer/` (per-genre analyses, thumbnails, aggregate statistics, `style-profile.json`, `style-guide.md`). No database |
| Deployment | Local only: a CLI, a local dashboard and an MCP stdio server. Nothing is hosted |

**Size:** about 15.3k lines in total. That is about 7.8k lines of Python and about 3.5k of JavaScript, plus CSS and 6 genre-pack TOML files. The git history has 32 commits over three days in May 2026.

### Feature status

| Status | Features |
|---|---|
| **Working** (tested or smoke-tested) | `analyze`, `list`, `stats`, `genre` (6 packs), `migrate`, `config`, `tag`, `match`, `compare` (FCPXML), `predict-cuts` (writes FCPXML markers), `export-notebooklm`, `import` (yt-dlp), `mcp-serve` (24 tools, 4 resources). Dashboard: Archive, Film detail, Guide, Shot Profile, Edit-Craft, Hand-off zip, Compare, Settings |
| **Partial** | `guide`: needs an API key and shows a raw traceback without one. `learn-shots` and `score-clips`: the code exists and the unit tests pass with stubs, but the `[shots]` dependency pins (mediapipe<0.10.21, tensorflow<2.19) **cannot be installed on Python 3.13**. Audio extra: Python 3.11–3.12 only. Edit-Craft view: reads a folder that no code writes. Gemini: uses an end-of-life SDK |
| **Planned or missing** | Premiere Pro, DaVinci Resolve, EDL, AAF and OTIO support (**FCPXML only**, while most of the market uses Premiere or Resolve). Installer or app bundle, PyPI release, Windows support |

### Tests and build (run in this session)

- **33 test files** with about 251 test functions; pytest collects 260 tests.
- **Fresh install as resolved today: 257 passed, 2 failed, 1 skipped.** Both failures are in `tests/test_composition.py::TestHorizonTilt`. The cause is that scenedetect now pulls in OpenCV 5, which changed the output shape of `HoughLinesP` (`composition.py:405`). Pinning `opencv-python<5` gives **259 passed, 1 skipped**. This is a real bug that appears on any new install.
- **The build passes:** `python -m build` produces a wheel and an sdist, with static assets and genre packs included. setuptools prints a deprecation warning about the licence metadata.
- **Not tested:** `server.py` (the dashboard API), most of `cli.py`, the full `analyze` path, and `guide_writer`. The real-media test is skipped by default.
- **Missing tooling:** no lint or type-check configuration and **no CI** (no `.github/`).

### Data model

`FilmAnalysis` (pydantic) holds clips, chapters, pacing, transitions, cuts, film metadata and structure. `style-profile.json` (schema 1.0) has sections for duration, the pacing decile curve, transitions, audio, colour, shot mix, music, scenes, structure, rules and source films. There is also `shot-profile.json` and a per-folder `clip-scores.json`.

### Auth, payments and operations

- **None of the following exist:** auth, multi-user support, payments or licence keys, telemetry, crash reporting, auto-update, installer, privacy policy or terms. Support is "open an issue".
- **Licence:** MIT.
- **Dashboard security:** binds to localhost by default, and file paths are checked against traversal. But it **does no Origin, Host or CSRF checking**. A cross-origin POST to `/api/config` succeeded in testing, and DNS rebinding could read data. `serve --host 0.0.0.0` exposes the dashboard with no authentication.
- **Data that leaves the machine:**
  - The `guide` command sends Anthropic aggregate statistics, including film filenames (which in practice are client names).
  - `--vision` and `--shot-sizes` send full-resolution frames, including guests' faces, to Anthropic.
  - `analyze --gemini` **uploads the whole film file to Google**.

### Percent complete toward a launchable product

| Area | % | Why |
|---|---|---|
| Core product | **55–60%** | The pipeline works and is well unit-tested. It is FCPXML-only, two extras can't be installed on current Python, dependencies aren't pinned, there are no end-to-end tests, and it is tuned on one editor's archive |
| Marketing site | **0–5%** | None exists. The README's pitch copy is the only usable material |
| Founder/admin dashboard | **0%** | The bundled dashboard is for end users. There is no customer, revenue or usage view |
| Payments | **0%** | No billing, licence keys or activation |
| Operations | **5–10%** | No installer, signing, updates, CI, telemetry, onboarding or support. `config --init` and the decent error messages are a start |
| **Overall, as a commercial product** | **~15–20%** | A strong personal tool or open-source project at about beta quality for its author; little of the commercial wrapper exists |

---

## 3. Commercial viability

### Target customer and how many

- **Primary:** owner-operator wedding filmmakers who edit their own films and have an established style and a back catalogue.
- **Secondary:** commercial and documentary editors, and small studios that hire contract editors and need to pass a house style on to them.

Sizing:

- **US film and video editors:** 39,400, of whom 35% are self-employed ([BLS](https://www.bls.gov/ooh/Media-and-Communication/Film-and-video-editors-and-camera-operators.htm)).
- **US weddings:** about 2.0M in 2025, and 37% of couples hire a videographer, with an average spend of about $2,300 ([The Knot](https://www.theknot.com/content/average-cost-wedding-videographer)). That is roughly 740k filmed weddings a year.
- **US wedding-video businesses (estimate):** about 21k–37k, assuming 20–35 weddings per operator per year.
- **Serviceable market today (estimate):** in its current form, only the technical minority will install a Python and ffmpeg tool and supply their own API key, about 3–5%. That gives roughly **700–1,800 users in the US and 2k–5k worldwide**.
- **Revenue ceiling (estimate):** at $100–150 a year each, roughly **$0.2M–0.7M ARR**. This is a niche or lifestyle business unless it becomes a polished app or plug-in for Premiere and Resolve, which would widen the market several times over.

### Willingness to pay and a plausible price

- **Photographers** already pay $12–165 a month for AI that learns their personal style: Imagen ([pricing](https://imagen-ai.com/pricing/): $0.05 per photo, or $129–165 a month unlimited) and Aftershoot ([pricing](https://aftershoot.com/pricing): $12–55 a month).
- **Wedding filmmakers** pay **$89–119 per film** for AI-cut edits ([Wedit.ai](https://wedit.ai/)) and **$400–2,500+** per film for outsourced human editing ([Fotober](https://fotober.com/wedding-video-editing-pricing)).
- Willingness to pay is real once the tool saves hours on each film. A tool that only provides insight ("here is your style") is a harder sell than one that saves time (culling, rough-cut checks, assistant hand-off).

**Plausible price:**

- **Recommended:** a **Pro desktop app at $99–149 one-time**, with a year of updates and the customer's own API key. This fits a buy-once culture (DaVinci Resolve Studio is a one-time $295).
- **Alternative:** a **subscription at $12–19 a month** that includes hosted AI calls. This only makes sense if the owner pays for the AI and meters it.

### Channels

1. **Communities:** r/videography (~445k), r/weddingvideography (~18k), r/filmmakers (~3M), and Facebook groups such as How To Film Weddings and Wedding Film School.
2. **The owner's own credibility** as a working wedding filmmaker: before/after case studies built from their own archive.
3. **YouTube educators** in wedding film, and affiliate deals with them.
4. **WPPI** (Las Vegas, March) and similar shows.
5. **Marketplaces:** Adobe Exchange (a Premiere panel), FxFactory (Final Cut), and MCP and Claude directories for the "edit in my style with Claude" angle.
6. **Open source as a funnel:** GitHub, Hacker News and Product Hunt.

Distribution is helped by tight, word-of-mouth communities where the owner is an insider. It is held back by install friction: a terminal-based install loses most of the audience at the first step.

### Competitors and alternatives

| Product | What it does | Price | Threat |
|---|---|---|---|
| **Wedit.ai** | AI cuts wedding highlights and full films and exports to Premiere, Resolve or FCP | $89/film, $119/highlight; $699/month unlimited ([site](https://wedit.ai/)) | **High.** Same buyer. Uses generic styles ("traditional/modern") rather than learned ones |
| **Eddie AI** | AI assistant editor, now an MCP server inside Claude and ChatGPT | Credits $10 per 1k up to $350 per 50k ([No Film School](https://nofilmschool.com/eddie-ai-updates-pricing)) | **High** for the Claude hand-off angle |
| **Selects (Cutback)** | Sync, transcription, highlights, bad-shot detection, rough cut for Premiere, FCP and Resolve | Free; $20 or $100 a month ([site](https://tryselects.com/)) | Medium. Clip culling overlaps `score-clips` |
| **Imagen AI** (photo) | Personal AI Profile learned from 3,000+ of your edited photos | $0.05 per photo; $129–165 a month ([pricing](https://imagen-ai.com/pricing/)) | Shows the model works. Could expand into video |
| **Aftershoot** (photo) | Culling plus personal-style editing | $12–55 a month ([pricing](https://aftershoot.com/pricing)) | Same as Imagen |
| Gling, FireCut, AutoCut, Descript, OpusClip | Talking-head and creator cutting | ~$7–65 a month ([Gling](https://www.gling.ai/pricing), [FireCut](https://firecut.ai/pricing), [AutoCut](https://www.autocut.com/en/pricing/), [Descript](https://www.descript.com/pricing), [Opus](https://www.opus.pro/pricing)) | Low. Different job |
| Built into Premiere Pro / DaVinci Resolve 20 | Media Intelligence search, Generative Extend, IntelliScript, scene-cut detection | Included (Resolve Studio is a one-time $295) | Medium. "Good enough" built-in AI keeps rising |
| Outsourced editors | A human edits in your style | $400–2,500+ per film | The real alternative for a busy studio |

**What would make it win:** no product found combines (a) learning a profile from your *finished films*, (b) scoring a rough cut against it, and (c) ranking raw clips by your own preferences. Imagen proved that "learns *your* style" is a winning pitch for photographers, and the video equivalent is open. To win it needs:

1. a one-click Mac app;
2. Premiere and Resolve support, not only FCPXML;
3. a visible time saving (shortlisted clips, rough-cut warnings);
4. a privacy-first, local-first story;
5. the owner's credibility as a working filmmaker.

### Regulatory, legal, privacy and safety risk

- **Biometric and emotion analysis of wedding guests.** Guests never consent.
  - Illinois BIPA allows up to $5,000 per violation, limited since 2024 to one recovery per person.
  - Texas CUBI was the basis of Meta's $1.4B settlement.
  - Under GDPR Article 9, biometric data is special-category data.
  - Under the EU AI Act, emotion recognition outside workplaces and education is classed as **high-risk**, which brings transparency obligations.

  **Mitigation:** face *detection* only; never store embeddings; turn emotion analysis off by default (or reframe it as non-biometric "shot energy"); and make the filmmaker, as data controller, responsible through the terms of service.
- **Client footage sent to third parties.** Full-resolution frames go to Anthropic, and the Gemini path uploads whole films to Google.
  - Anthropic API inputs are not used for training by default, but some newer model families require 30-day retention.
  - **Mitigation:** downscale frames and send derived metrics only by default; make uploads opt-in with clear disclosure; suggest contract wording filmmakers can give their clients.
- **Platform terms.** `import` uses yt-dlp, which can read browser cookies. Downloading even your own Vimeo videos this way may breach platform terms. Keep it as a power-user feature.
- **Security.** The leaked token (section 0) and the dashboard's missing CSRF and Origin checks.
- **Music copyright:** negligible, because the tool only analyses beats and redistributes nothing.

### Operating cost

- **Bring-your-own key (recommended):** close to $0 per user in variable cost. Fixed costs are about $100 a year for an Apple developer account (code signing), a $0–20 a month site, merchant-of-record fees of about 5% plus 50¢ (Lemon Squeezy or Paddle), and an optional $0–26 a month for Sentry. That is **under $100 a month in total**.
- **If the owner pays for the AI:** first-time profiling of a 20-film archive costs about **$12–18**, and each added film about **$0.60**, mostly from the vision shot-size pass on full-resolution frames. That is roughly 3–5 times what `ARCHITECTURE.md` estimates. Downscaling thumbnails would cut it sharply.

### Time and effort to reach launch

The estimate is about **25–40 build days**, plus 2–3 weeks of calendar time for a private beta with 5–10 editors. The hardest part is not code but **packaging**: shipping TensorFlow, MediaPipe, WhisperX and ffmpeg as a signed, notarized Mac app is brittle work that autonomous build loops handle poorly.

### Does it matter that the repository is public?

Yes, in three ways:

1. **Exposure.** The token and client names (section 0) are public now.
2. **Licensing.** The code is **MIT**, so anyone, including Wedit, Eddie or Selects, may legally fork and resell everything committed so far. The code is no moat. The owner can relicense *future* versions (for example as a closed Pro app or an open core under FSL or BSL), provided they own every contribution. The two author identities in git history should be confirmed as the owner and the owner's AI assistant.
3. **Upside.** With a serviceable market of a few thousand editors, an open-source CLI is a credible funnel and a trust signal ("your footage never leaves your machine"). **Recommendation:** clean the history, keep the core CLI open, and sell a closed Pro app (installer, NLE plug-ins, culling, updates).

---

## 4. Scores

| Dimension | Score | Reasoning |
|---|---|---|
| Market size | **3** | A few thousand reachable wedding editors today; a ceiling below $1M ARR unless it widens to Premiere/Resolve and other genres |
| Willingness to pay | **6** | Proven by Imagen and Aftershoot for photo, and Wedit at $89/film, but "insight" is worth less than "time saved" |
| Distribution ease | **5** | Tight communities and an insider founder, offset by a terminal install that loses most buyers |
| Competitive position | **5** | A unique "learns from your finished films" angle, but Wedit, Eddie and built-in NLE AI are close, and MIT code can be forked |
| Build progress | **4** | Core about 55–60% and solid; the commercial wrapper (app, payments, site, ops) about 0–10% |
| Effort to launch (10 = least) | **4** | 25–40 days, and packaging heavy ML dependencies into a signed app is hard |
| Risk (10 = least) | **4** | Biometric and emotion analysis of non-consenting guests, client footage sent to AI vendors, a live credential leak (fixable) |
| Founder fit (solo + autonomous AI loop) | **7** | The owner is the target customer and has credibility; the code is AI-loop friendly. Packaging, signing and community selling need hands-on human time |

**Overall commercial viability: 48 / 100.**

Weighting: market size 15%, willingness to pay 15%, distribution 15%, competitive position 15%, build progress 10%, effort 10%, risk 10%, founder fit 10%.

(3×15 + 6×15 + 5×15 + 5×15 + 4×10 + 4×10 + 4×10 + 7×10) / 10 = 475 / 10 = 47.5, rounded to **48**.

**Verdict:** a genuinely differentiated idea in a small market. It is viable as a lifestyle product or as a credibility asset for the owner's studio. It is not a venture-scale business unless it reaches Premiere and Resolve users through a polished app.

---

## 5. Recommended scope for a full launch build

| # | Milestone | Scope | Est. days |
|---|---|---|---|
| **M0** | Clean-up and decisions | Revoke the Vimeo token; purge it and client names from history (or make the repo private); decide the licence (MIT core plus closed Pro); confirm contributor ownership | 0.5–1 |
| **M1** | Product hardening | Add CI (macOS arm64 and x86); pin dependencies with a lock file; fix OpenCV 5 horizon detection; fix the `[shots]` pins for Python 3.12/3.13; update the Claude model ID; move to the `google-genai` SDK; downscale frames before vision calls; add Host, Origin and CSRF checks plus a session token to the dashboard; give friendly errors when no API key is set; add tests for `server.py` and the full `analyze` path | 5–8 |
| **M2** | Privacy-first defaults | Emotion and face analysis off by default; uploads to Anthropic and Gemini opt-in with in-app disclosure; filenames anonymised before AI calls; client-contract template wording | 2–3 |
| **M3** | NLE reach | Premiere (xmeml or OTIO) and DaVinci Resolve import/export for `compare`, `predict-cuts` and clip-score markers | 5–8 |
| **M4** | Desktop app packaging | A standalone Mac app (PyInstaller or Briefcase) bundling Python, ffmpeg and models, with downloads on first run; signed and notarized; Sparkle auto-update; a first-run wizard that checks prerequisites and API keys. Windows later | 6–10 |
| **M5** | Payments and licensing | Lemon Squeezy or Paddle as merchant of record; licence keys; in-app activation with an offline grace period; a 14-day trial; refunds | 3–4 |
| **M6** | Marketing site | Landing page led by "learns how *you* cut"; a demo video built on the owner's films; a sample style guide; pricing; docs and onboarding; privacy policy and terms (with lawyer review); download page; email capture | 4–6 |
| **M7** | Founder dashboard | Sales and revenue, active licence keys, version adoption, opt-in crash and usage metrics (Sentry or PostHog), support inbox summary | 3–5 |
| **M8** | Operations and beta | Support email or help desk; changelog and release process; status page; a private beta with 5–10 wedding filmmakers; case studies; then a public launch through Reddit, Facebook groups, YouTube educators and Product Hunt | 3–5 + 2–3 weeks of beta |

**Total:** about 32–50 build days. That is more than the 25–40 quoted in section 3 because NLE reach (M3) and privacy defaults (M2) are included, and it does not count the calendar time for the beta.

---

## 6. Top three things the owner must decide or provide

1. **The business model, the licence and the AI cost.** Choose between selling a closed Pro app on top of an open core, keeping everything MIT and selling services, or relicensing. Decide whether customers bring their own Anthropic/Google key (near-zero cost, more friction) or the owner pays and meters it (subscription pricing). Pricing, the payments setup and the privacy story all follow from this.
2. **The scope of the first release and its data policy.** Choose the platforms (Mac-only first?), the editing apps (adding Premiere and Resolve is the biggest lever on market size), and whether the face, emotion and full-film upload features ship at all, or ship off by default. Provide the disclosure and retention wording, ideally reviewed by a lawyer.
3. **Accounts, assets and beta users.** Revoke the Vimeo token and approve the history clean-up. Provide an Apple Developer account (for signing and notarization), a merchant-of-record account, a domain, brand and support email, the demo footage and the films they have rights to use, and 5–10 filmmaker contacts for the private beta.
