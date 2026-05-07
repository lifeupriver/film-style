// views.js — DOM-building view functions. No innerHTML for any data path.

import {
  decileCurve,
  decileDiff,
  donut,
  formatTime,
  formatTimecode,
  pacingBars,
  toRoman,
} from "./charts.js";
import { renderMarkdown } from "./markdown.js";
import { TimelineGroup } from "./timeline.js";

// ------------ tiny DOM helper ----------------------------------------------

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(node.style, v);
    else if (k.startsWith("on") && typeof v === "function")
      node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") {
      // Reserved for trusted, programmatic strings only — never used with API data.
      node.appendChild(document.createTextNode(v));
    } else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null || c === false) continue;
    if (typeof c === "string" || typeof c === "number") {
      node.appendChild(document.createTextNode(String(c)));
    } else {
      node.appendChild(c);
    }
  }
  return node;
}

const fmtRuntime = (sec) => {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  if (m >= 60) {
    const h = Math.floor(m / 60);
    const mm = m % 60;
    return `${h}h ${String(mm).padStart(2, "0")}m`;
  }
  return `${m}m ${String(s).padStart(2, "0")}s`;
};

// ------------ corpus / archive overview ------------------------------------

export function renderCorpus(stats, films) {
  const page = el("div", { class: "page page--corpus" });

  // ----- HERO ------
  const filmCount = films.length;
  const totalRuntime = films.reduce((s, f) => s + (f.duration_sec || 0), 0);

  const hero = el("section", { class: "hero" }, [
    el("p", { class: "hero__kicker" }, [`Volume · ${toRoman(filmCount) || "—"}`]),
    (() => {
      const h1 = el("h1", { class: "hero__display" });
      h1.appendChild(document.createTextNode("The "));
      h1.appendChild(el("em", {}, ["Archive"]));
      h1.appendChild(document.createTextNode(", in numerals."));
      return h1;
    })(),
    el("p", { class: "hero__lede" }, [
      filmCount === 0
        ? "Nothing catalogued yet. Run "
        : `${filmCount === 1 ? "One film" : `${filmCount} films`} catalogued. ${fmtRuntime(totalRuntime)} of finished work, dissected to the frame.`,
      filmCount === 0 ? el("code", {}, ["film-style analyze <path>"]) : "",
      filmCount === 0 ? " in your terminal to begin." : "",
    ]),
  ]);
  page.appendChild(hero);

  if (filmCount === 0) {
    page.appendChild(emptyState());
    return page;
  }

  // ----- FIGURES (numbers strip) ------
  const pacing = stats?.pacing || {};
  const trans = stats?.transitions || {};
  const audio = stats?.audio || null;

  const figures = el("section", { class: "figures" }, [
    figure("I · Pacing", `${(pacing.avg_clip_sec ?? 0).toFixed(2)}s`, "average clip held",
           `σ ${(pacing.std_dev_sec ?? 0).toFixed(2)}s`),
    figure("II · Cuts", `${stats?.clip_counts?.avg ?? "—"}`, "cuts per film",
           `${stats?.clip_counts?.min}–${stats?.clip_counts?.max} range`),
    figure(
      "III · Transitions",
      `${Math.round(trans.hard_cut_pct ?? 0)}%`,
      "hard-cut dominant",
      `${(trans.dissolve_pct ?? 0).toFixed(0)}% dissolve · ${(trans.fade_pct ?? 0).toFixed(0)}% fade`
    ),
    audio
      ? figure(
          "IV · First Speech",
          `${(audio.first_speech_at_pct_avg ?? 0).toFixed(0)}%`,
          "into the film",
          audio.first_speech_at_sec_avg != null
            ? `~${formatTime(audio.first_speech_at_sec_avg)} avg`
            : ""
        )
      : figure("IV · Audio", "—", "not yet analysed", "run with audio extras"),
  ]);
  page.appendChild(figures);

  // ----- DECILE CURVE ------
  const deciles = pacing.avg_deciles || [];
  const sectionCurve = el("section", {}, [
    el("header", { class: "section-rule" }, [
      el("span", { class: "section-rule__plate" }, ["Plate V"]),
      el("span", { class: "section-rule__title" }, [
        "Tempo across the run-time",
      ]),
      el("span", { class: "section-rule__line" }),
    ]),
    decileCurve(deciles.length ? deciles : new Array(10).fill(0)),
    deciles.length
      ? el("p", { class: "chart__caption" }, [
          "Mean clip duration sampled at every tenth of the film. Lower is tighter — peaks indicate held moments.",
        ])
      : null,
  ]);
  page.appendChild(sectionCurve);

  // ----- TRANSITIONS DONUT + AUDIO STRIP --------
  const right = el("div", {}, [
    el("p", { class: "chart__caption", style: { marginBottom: "1rem" } }, [
      `${trans.hard_cut_pct ?? 0}% hard cuts. The remainder breathes through dissolves and the occasional fade.`,
    ]),
    legendList([
      { label: "Hard cut", color: "var(--amber)" },
      { label: "Dissolve", color: "var(--dust)" },
      { label: "Fade", color: "var(--plum)" },
    ]),
  ]);

  const cols = el("div", { class: "cols", style: { marginTop: "2rem" } }, [
    el("div", {}, [
      el("header", { class: "section-rule", style: { marginTop: 0 } }, [
        el("span", { class: "section-rule__plate" }, ["Plate VI"]),
        el("span", { class: "section-rule__title" }, ["The transition mix"]),
        el("span", { class: "section-rule__line" }),
      ]),
      donut([
        { label: "Hard cut", value: trans.hard_cut_pct ?? 0, color: "var(--amber)" },
        { label: "Dissolve", value: trans.dissolve_pct ?? 0, color: "var(--dust)" },
        { label: "Fade", value: trans.fade_pct ?? 0, color: "var(--plum)" },
      ]),
    ]),
    right,
  ]);
  page.appendChild(cols);

  // ----- ARCHIVE GRID ------
  const sortedFilms = [...films].sort(
    (a, b) => (b.analyzed_at || "").localeCompare(a.analyzed_at || "")
  );
  const archive = el("section", {}, [
    el("header", { class: "section-rule" }, [
      el("span", { class: "section-rule__plate" }, ["Plate VII"]),
      el("span", { class: "section-rule__title" }, ["The reels"]),
      el("span", { class: "section-rule__line" }),
    ]),
    el(
      "div",
      { class: "archive-grid" },
      sortedFilms.map((f, i) => filmCard(f, i + 1))
    ),
  ]);
  page.appendChild(archive);

  return page;
}

function figure(plate, big, caption, detail) {
  return el("article", { class: "figure" }, [
    el("p", { class: "figure__plate" }, [plate]),
    el("p", { class: "figure__number" }, [big]),
    el("p", { class: "figure__caption" }, [caption]),
    detail ? el("p", { class: "figure__detail" }, [detail]) : null,
  ]);
}

function legendList(items) {
  return el(
    "ul",
    {
      style: {
        listStyle: "none",
        padding: 0,
        margin: 0,
        display: "flex",
        flexDirection: "column",
        gap: "0.6rem",
      },
    },
    items.map((it) =>
      el(
        "li",
        {
          style: {
            display: "flex",
            alignItems: "center",
            gap: "0.75rem",
            fontFamily: "var(--mono)",
            fontSize: "0.7rem",
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--ink-2)",
          },
        },
        [
          el("span", {
            style: {
              width: "18px",
              height: "2px",
              background: it.color,
              display: "inline-block",
            },
          }),
          it.label,
        ]
      )
    )
  );
}

function filmCard(f, index) {
  const stem = f.stem;
  const card = el(
    "a",
    {
      class: "card",
      href: `#/film/${stem}`,
      "aria-label": `View ${f.filename}`,
    },
    [
      el("div", { class: "card__cover" }, [
        f.cover_thumbnail
          ? el("img", { src: `/thumbs/${coverPath(f.cover_thumbnail)}`, alt: "" })
          : el("div", {
              style: {
                width: "100%",
                height: "100%",
                background:
                  "linear-gradient(135deg, var(--surface-2), var(--surface-3))",
              },
            }),
        el("span", { class: "card__plate" }, [
          `№ ${String(index).padStart(2, "0")}`,
        ]),
      ]),
      el("div", { class: "card__body" }, [
        el("h3", { class: "card__title" }, [prettyTitle(f.filename)]),
        el("div", { class: "card__meta" }, [
          el("span", {}, [
            el("strong", {}, [formatTime(f.duration_sec)]),
            " runtime",
          ]),
          el("span", {}, [el("strong", {}, [`${f.clip_count}`]), " cuts"]),
          el("span", {}, [
            el("strong", {}, [`${(f.avg_clip_sec ?? 0).toFixed(2)}s`]),
            " avg",
          ]),
          f.has_vision ? el("span", {}, [el("strong", {}, ["✦"]), " labelled"]) : null,
        ]),
      ]),
    ]
  );
  return card;
}

function coverPath(thumb) {
  // Stored thumbnail paths look like "thumbs/<stem>/clip_NNN.jpg".
  // The /thumbs/ route on the server is rooted at THUMBS_DIR, so strip the
  // leading "thumbs/" segment if present.
  return thumb.replace(/^thumbs\//, "");
}

function prettyTitle(filename) {
  const stem = filename.replace(/\.[^.]+$/, "");
  return stem
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ------------ per-film deep dive -------------------------------------------

export function renderFilm(analysis) {
  const page = el("div", { class: "page page--film" });

  const meta = analysis.film;
  const title = prettyTitle(meta.filename);
  const fps = meta.frame_rate || 24;

  const hero = el("section", { class: "film-hero" }, [
    el("p", { class: "film-hero__kicker" }, [
      `Reel · ${formatTime(meta.duration_sec)} · ${meta.resolution || "—"}`,
    ]),
    (() => {
      const h = el("h1", { class: "film-hero__title" });
      const parts = title.split(" ");
      if (parts.length > 1) {
        h.appendChild(document.createTextNode(parts.slice(0, -1).join(" ") + " "));
        h.appendChild(el("em", {}, [parts.at(-1)]));
      } else {
        h.appendChild(document.createTextNode(title));
      }
      return h;
    })(),
    el("div", { class: "film-hero__meta" }, [
      el("span", {}, [el("strong", {}, [`${analysis.cuts.total}`]), " cuts"]),
      el("span", {}, [
        el("strong", {}, [`${(analysis.pacing.avg_clip_duration_sec ?? 0).toFixed(2)}s`]),
        " avg clip",
      ]),
      el("span", {}, [
        el("strong", {}, [`${(analysis.pacing.median_clip_duration_sec ?? 0).toFixed(2)}s`]),
        " median",
      ]),
      el("span", {}, [el("strong", {}, [meta.codec || "—"]), " codec"]),
      el("span", {}, [
        el("strong", {}, [`${(meta.frame_rate ?? 0).toFixed(2)}`]),
        " fps",
      ]),
    ]),
  ]);
  page.appendChild(hero);

  // ----- filmstrip ------
  page.appendChild(
    el("header", { class: "section-rule", style: { marginTop: "3rem" } }, [
      el("span", { class: "section-rule__plate" }, ["Plate I"]),
      el("span", { class: "section-rule__title" }, [`Frame-by-frame, ${analysis.cuts.total} cells`]),
      el("span", { class: "section-rule__line" }),
    ])
  );
  page.appendChild(buildFilmstrip(analysis, fps));

  // ----- pacing bars ------
  page.appendChild(
    el("header", { class: "section-rule" }, [
      el("span", { class: "section-rule__plate" }, ["Plate II"]),
      el("span", { class: "section-rule__title" }, ["Clip duration over time"]),
      el("span", { class: "section-rule__line" }),
    ])
  );
  const pacingWrap = el("div", { class: "pacing-bars" }, [
    pacingBars(analysis.cuts.clips),
  ]);
  page.appendChild(pacingWrap);

  // ----- audio ribbon ------
  let audioWrap = null;
  if (analysis.audio?.segments?.length) {
    page.appendChild(
      el("header", { class: "section-rule" }, [
        el("span", { class: "section-rule__plate" }, ["Plate III"]),
        el("span", { class: "section-rule__title" }, ["The audio bed"]),
        el("span", { class: "section-rule__line" }),
      ])
    );
    audioWrap = buildAudioRibbon(analysis.audio, meta.duration_sec);
    page.appendChild(audioWrap);
  }

  // Synced timeline cursor across pacing bars + audio ribbon.
  setTimeout(() => {
    const group = new TimelineGroup(meta.duration_sec, fps);
    const pacingChart = pacingWrap.querySelector(".chart");
    if (pacingChart) group.attach(pacingChart);
    if (audioWrap) {
      const track = audioWrap.querySelector(".audio-ribbon__track");
      if (track) group.attach(track);
    }
  }, 0);

  // ----- chapters ------
  if (analysis.chapters?.length) {
    page.appendChild(
      el("header", { class: "section-rule" }, [
        el("span", { class: "section-rule__plate" }, [
          analysis.audio?.segments?.length ? "Plate IV" : "Plate III",
        ]),
        el("span", { class: "section-rule__title" }, [
          `Chapter divisions, ${analysis.chapters.length} marked`,
        ]),
        el("span", { class: "section-rule__line" }),
      ])
    );
    page.appendChild(buildChapters(analysis.chapters, fps,
                                    meta.filename.replace(/\.[^.]+$/, "")));
  }

  // ----- transcript ------
  if (analysis.transcript?.segments?.length) {
    page.appendChild(
      el("header", { class: "section-rule" }, [
        el("span", { class: "section-rule__plate" }, ["Plate V"]),
        el("span", { class: "section-rule__title" }, ["Heard, in their own words"]),
        el("span", { class: "section-rule__line" }),
      ])
    );
    page.appendChild(buildTranscript(analysis.transcript, fps));
  }

  // ----- metadata tags ------
  page.appendChild(
    el("header", { class: "section-rule" }, [
      el("span", { class: "section-rule__plate" }, ["Plate VI"]),
      el("span", { class: "section-rule__title" }, ["Tags & metadata"]),
      el("span", { class: "section-rule__line" }),
    ])
  );
  const tagsWrap = el("div", { "data-id": "tags-wrap" });
  page.appendChild(tagsWrap);
  setTimeout(() => bindMetadataEditor(tagsWrap, analysis), 0);

  // ----- similar films ------
  page.appendChild(
    el("header", { class: "section-rule" }, [
      el("span", { class: "section-rule__plate" }, ["Plate VII"]),
      el("span", { class: "section-rule__title" }, ["Stylistically nearest"]),
      el("span", { class: "section-rule__line" }),
    ])
  );
  const matchWrap = el("div", { "data-id": "match-wrap" }, [
    el("p", { class: "muted italic" }, ["Loading…"]),
  ]);
  page.appendChild(matchWrap);
  setTimeout(() => bindMatches(matchWrap, analysis), 0);

  return page;
}

// ------------ metadata editor ----------------------------------------------

async function bindMetadataEditor(wrap, analysis) {
  const stem = (analysis.film.filename.replace(/\.[^.]+$/, ""));
  let curatedKeys = {};
  try {
    const r = await fetch("/api/metadata-keys");
    if (r.ok) curatedKeys = await r.json();
  } catch {}

  const md = analysis.metadata || {};
  const root = el("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
      gap: "1rem 2rem",
      paddingTop: "1rem",
    },
  });

  for (const key of Object.keys(curatedKeys)) {
    const values = curatedKeys[key];
    const current = md[key] || "";
    const select = el("select", {
      "data-key": key,
      style: {
        background: "transparent",
        border: "none",
        borderBottom: "1px solid var(--line)",
        color: "var(--ink)",
        fontFamily: "var(--mono)",
        fontSize: "0.85rem",
        padding: "0.4rem 0",
        outline: "none",
        width: "100%",
        cursor: "pointer",
      },
    });
    select.appendChild(el("option", { value: "" }, ["—"]));
    for (const v of values) {
      const opt = el("option", { value: v }, [v.replace(/_/g, " ")]);
      if (v === current) opt.selected = true;
      select.appendChild(opt);
    }

    select.addEventListener("change", async () => {
      const payload = { [key]: select.value || null };
      try {
        await fetch(`/api/films/${encodeURIComponent(stem)}/metadata`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        flash(select);
      } catch {}
    });

    root.appendChild(
      el("label", { style: { display: "flex", flexDirection: "column", gap: "0.25rem" } }, [
        el("span", {
          style: {
            fontFamily: "var(--mono)",
            fontSize: "0.62rem",
            letterSpacing: "0.22em",
            textTransform: "uppercase",
            color: "var(--ink-mute)",
          },
        }, [key.replace(/_/g, " ")]),
        select,
      ])
    );
  }

  wrap.replaceChildren(root);
}

function flash(node) {
  const original = node.style.borderBottomColor;
  node.style.borderBottomColor = "var(--amber)";
  setTimeout(() => (node.style.borderBottomColor = original), 600);
}

// ------------ similar films ------------------------------------------------

async function bindMatches(wrap, analysis) {
  const stem = analysis.film.filename.replace(/\.[^.]+$/, "");
  try {
    const res = await fetch(`/api/match/${encodeURIComponent(stem)}`);
    if (!res.ok) throw new Error("match request failed");
    const data = await res.json();
    if (!data.matches?.length) {
      wrap.replaceChildren(
        el("p", { class: "muted italic" }, [
          "No other films in the archive yet to compare.",
        ])
      );
      return;
    }
    const grid = el("div", {
      style: {
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        gap: "1rem",
        paddingTop: "1rem",
      },
    });
    for (const m of data.matches) {
      const matchStem = m.stem;
      grid.appendChild(
        el("a", {
          href: `#/film/${encodeURIComponent(matchStem)}`,
          class: "card",
          style: { padding: "1rem 1.1rem", display: "block" },
        }, [
          el("p", { class: "card__title", style: { margin: "0 0 0.4rem" } }, [
            prettyTitle(m.filename),
          ]),
          el("p", {
            class: "mono",
            style: {
              fontSize: "0.65rem",
              letterSpacing: "0.18em",
              color: "var(--amber-soft)",
              textTransform: "uppercase",
            },
          }, [`similarity ${(m.similarity * 100).toFixed(1)}%`]),
        ])
      );
    }
    wrap.replaceChildren(grid);
  } catch (e) {
    wrap.replaceChildren(
      el("p", { class: "muted italic" }, ["Could not load similar films."])
    );
  }
}

function buildFilmstrip(analysis, fps) {
  // Detail panel sits below the rail; clicking a cell populates it.
  const detailPanel = el("div", {
    class: "clip-detail",
    style: { display: "none" },
  });

  function renderDetail(c) {
    const sd = c.shot_description || null;
    const pills = [];
    function addPill(label, val, cls) {
      if (!val) return;
      const arr = Array.isArray(val) ? val : [val];
      for (const v of arr) {
        pills.push(el("span", { class: `pill pill--${cls}` }, [
          el("span", { class: "pill__k" }, [label]),
          el("span", { class: "pill__v" }, [v.replace(/_/g, " ")]),
        ]));
      }
    }
    if (sd) {
      addPill("subjects", sd.subjects, "subjects");
      addPill("setting", sd.setting, "setting");
      addPill("lighting", sd.lighting, "lighting");
      addPill("mood", sd.mood, "mood");
      addPill("camera", sd.camera, "camera");
      addPill("action", sd.action, "action");
    }
    if (c.shot_size) {
      pills.push(el("span", { class: "pill pill--shot" }, [
        el("span", { class: "pill__k" }, ["shot"]),
        el("span", { class: "pill__v" }, [c.shot_size.replace(/_/g, " ")]),
      ]));
    }

    const left = c.thumbnail
      ? el("img", {
          class: "clip-detail__thumb",
          src: `/thumbs/${c.thumbnail.replace(/^thumbs\//, "")}`,
          alt: "",
        })
      : el("div", { class: "clip-detail__thumb clip-detail__thumb--missing" });

    const headline = `Clip ${String(c.index + 1).padStart(3, "0")} · ` +
      `${formatTimecode(c.start_sec, fps)} → ${formatTimecode(c.end_sec, fps)} · ` +
      `${c.duration_sec.toFixed(2)}s · ` +
      `${c.transition_in} → ${c.transition_out}`;

    const right = el("div", { class: "clip-detail__body" }, [
      el("div", { class: "clip-detail__headline" }, [headline]),
      pills.length
        ? el("div", { class: "clip-detail__pills" }, pills)
        : el("p", { class: "muted italic" }, [
            "No shot description yet — drive a describe pass via Claude Desktop " +
            "(get_clip_thumbnails_to_describe) or set claude_backend=cli " +
            "and re-run the vision pass.",
          ]),
      sd?.description
        ? el("p", { class: "clip-detail__desc" }, [sd.description])
        : null,
    ]);

    detailPanel.replaceChildren(left, right);
    detailPanel.style.display = "grid";
  }

  const rail = el(
    "div",
    { class: "filmstrip__rail" },
    analysis.cuts.clips.map((c) => {
      const sd = c.shot_description;
      const titleParts = [
        `Clip ${c.index + 1} · ${c.duration_sec.toFixed(2)}s`,
      ];
      if (c.shot_size) titleParts.push(c.shot_size.replace(/_/g, " "));
      if (sd?.subjects?.length) titleParts.push(sd.subjects.join("+"));
      if (sd?.action) titleParts.push(sd.action);
      const cell = el(
        "a",
        {
          class: "filmstrip__cell" + (sd ? " filmstrip__cell--described" : ""),
          href: `#`,
          title: titleParts.join(" · "),
          onclick: (e) => {
            e.preventDefault();
            renderDetail(c);
            detailPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
          },
        },
        [
          c.thumbnail
            ? el("img", {
                src: `/thumbs/${c.thumbnail.replace(/^thumbs\//, "")}`,
                alt: "",
                loading: "lazy",
              })
            : el("div", {
                style: {
                  width: "100%",
                  height: "100%",
                  background: "var(--surface-3)",
                },
              }),
          el("span", { class: "ix" }, [String(c.index + 1).padStart(3, "0")]),
          el("span", { class: "tc" }, [formatTimecode(c.start_sec, fps)]),
          // Mood corner-tag for fast visual scanning when descriptions exist.
          sd?.mood
            ? el("span", { class: `mood-tag mood-tag--${sd.mood}` }, [
                sd.mood.replace(/_/g, " "),
              ])
            : null,
        ]
      );
      return cell;
    })
  );

  // Coverage hint above the rail.
  const total = analysis.cuts.clips.length;
  const described = analysis.cuts.clips.filter((c) => c.shot_description).length;
  const sized = analysis.cuts.clips.filter((c) => c.shot_size).length;
  const coverage = el("div", { class: "filmstrip__coverage" }, [
    el("span", {}, [
      `${described}/${total} clips described`,
      described < total ? " · " : "",
      described < total
        ? el("span", { class: "muted" }, [
            "click any cell to inspect; missing descriptions show in italic.",
          ])
        : "",
    ]),
    el("span", { class: "muted" }, [
      ` · ${sized}/${total} shot-sized`,
    ]),
  ]);

  return el("div", { class: "filmstrip" }, [coverage, rail, detailPanel]);
}

function buildAudioRibbon(audio, totalSec) {
  const root = el("div", { class: "audio-ribbon" });

  root.appendChild(
    el("div", { class: "audio-ribbon__legend" }, [
      legendDot("Music", "music"),
      legendDot("Speech over music", "speech_over_music"),
      legendDot("Speech", "speech"),
      legendDot("Ambient", "noise"),
    ])
  );

  const track = el("div", { class: "audio-ribbon__track" });
  const total = totalSec || 1;
  for (const seg of audio.segments) {
    const widthPct = ((seg.duration_sec || (seg.end_sec - seg.start_sec)) / total) * 100;
    track.appendChild(
      el(
        "span",
        {
          class: `audio-ribbon__band audio-ribbon__band--${seg.type}`,
          style: { width: `${widthPct}%` },
          title: `${seg.type} · ${formatTime(seg.start_sec)}–${formatTime(seg.end_sec)}`,
        },
        []
      )
    );
  }
  root.appendChild(track);

  root.appendChild(
    el("div", { class: "audio-ribbon__scale" }, [
      "0:00",
      formatTime(total / 4),
      formatTime(total / 2),
      formatTime((total * 3) / 4),
      formatTime(total),
    ])
  );

  if (audio.summary) {
    root.appendChild(
      el(
        "div",
        {
          style: {
            marginTop: "1.25rem",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
            gap: "0.5rem 1.5rem",
            fontFamily: "var(--mono)",
            fontSize: "0.72rem",
            color: "var(--ink-mute)",
            letterSpacing: "0.06em",
          },
        },
        [
          summaryStat("Music alone", `${(audio.summary.music_only_pct ?? 0).toFixed(0)}%`),
          summaryStat(
            "Speech ↑ music",
            `${(audio.summary.speech_over_music_pct ?? 0).toFixed(0)}%`
          ),
          summaryStat(
            "First speech",
            audio.summary.first_speech_at_sec != null
              ? formatTime(audio.summary.first_speech_at_sec)
              : "—"
          ),
          summaryStat(
            "Longest excerpt",
            `${(audio.summary.longest_speech_segment_sec ?? 0).toFixed(0)}s`
          ),
        ]
      )
    );
  }

  return root;
}

function legendDot(label, kind) {
  return el("span", {}, [
    el("i", { class: `audio-ribbon__band audio-ribbon__band--${kind}` }),
    label,
  ]);
}

function summaryStat(label, value) {
  return el("div", {}, [
    el(
      "span",
      { style: { color: "var(--amber-soft)", fontWeight: 500 } },
      [value]
    ),
    el(
      "span",
      { style: { display: "block", fontSize: "0.65rem", marginTop: "0.15rem" } },
      [label.toUpperCase()]
    ),
  ]);
}

function buildChapters(chapters, fps, filmStem) {
  return el(
    "div",
    { class: "chapters" },
    chapters.map((ch) =>
      el("div", { class: "chapter" }, [
        el("span", { class: "chapter__num" }, [
          `Ch ${String(ch.index + 1).padStart(2, "0")}`,
        ]),
        buildChapterLabelEditor(ch, filmStem),
        el("span", { class: "chapter__meta" }, [
          `${formatTimecode(ch.start_sec, fps)} → ${formatTimecode(ch.end_sec, fps)}`,
        ]),
        el("span", { class: "chapter__meta" }, [
          `${ch.clip_count} cuts · ${(ch.avg_clip_sec ?? 0).toFixed(2)}s avg`,
        ]),
      ])
    )
  );
}

const SCENE_LABELS = [
  "getting_ready", "details", "first_look", "portraits", "ceremony",
  "ceremony_processional", "ceremony_vows", "ceremony_recessional",
  "cocktail_hour", "reception_entrance", "first_dance",
  "speeches", "toasts", "cake_cutting", "dancing", "send_off",
  "establishing", "transition", "other",
];

function buildChapterLabelEditor(chapter, filmStem) {
  const span = el("span", {
    class: "chapter__label" + (chapter.label ? "" : " is-unlabeled"),
    role: "button",
    tabindex: "0",
    title: "Click to change label",
    style: { cursor: "pointer", borderBottom: "1px dotted var(--ink-dim)" },
  }, [chapter.label ? chapter.label.replace(/_/g, " ") : "(set label)"]);

  const enterEdit = () => {
    const select = document.createElement("select");
    select.style.cssText =
      "background: var(--surface); border: 1px solid var(--amber-deep); " +
      "color: var(--ink); font-family: var(--serif); font-style: italic; " +
      "font-size: 1rem; padding: 0.25rem 0.5rem; outline: none;";
    const blank = document.createElement("option");
    blank.value = "";
    blank.textContent = "(unset)";
    select.appendChild(blank);
    for (const lbl of SCENE_LABELS) {
      const opt = document.createElement("option");
      opt.value = lbl;
      opt.textContent = lbl.replace(/_/g, " ");
      if (lbl === chapter.label) opt.selected = true;
      select.appendChild(opt);
    }
    span.replaceWith(select);
    select.focus();

    const commit = async () => {
      const newLabel = select.value || null;
      try {
        const res = await fetch(
          `/api/films/${encodeURIComponent(filmStem)}/chapters/${chapter.index}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ label: newLabel }),
          }
        );
        if (res.ok) {
          const data = await res.json();
          chapter.label = data.label;
        }
      } catch {}
      const next = buildChapterLabelEditor(chapter, filmStem);
      next.style.transition = "opacity 200ms ease";
      next.style.opacity = "0";
      select.replaceWith(next);
      requestAnimationFrame(() => (next.style.opacity = "1"));
    };

    select.addEventListener("blur", commit, { once: true });
    select.addEventListener("change", () => select.blur());
  };

  span.addEventListener("click", enterEdit);
  span.addEventListener("keypress", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      enterEdit();
    }
  });
  return span;
}

function buildTranscript(transcript, fps) {
  // Pick a few representative excerpts: the longest 4.
  const top = [...transcript.segments]
    .sort((a, b) => (b.end_sec - b.start_sec) - (a.end_sec - a.start_sec))
    .slice(0, 4)
    .sort((a, b) => a.start_sec - b.start_sec);

  return el(
    "div",
    { class: "transcript" },
    top.map((s) =>
      el("blockquote", { class: "transcript__excerpt" }, [
        el("p", { class: "transcript__time" }, [
          `${formatTimecode(s.start_sec, fps)} — ${formatTimecode(s.end_sec, fps)}`,
        ]),
        el("p", { class: "transcript__text" }, [`“${(s.text || "").trim()}”`]),
        s.speaker
          ? el("p", { class: "transcript__speaker" }, [s.speaker])
          : null,
      ])
    )
  );
}

// ------------ guide --------------------------------------------------------

export function renderGuide(payload) {
  const page = el("div", { class: "page page--guide" });

  page.appendChild(
    el("section", { class: "hero" }, [
      el("p", { class: "hero__kicker" }, ["The Guide"]),
      (() => {
        const h = el("h1", { class: "hero__display" });
        h.appendChild(document.createTextNode("Notes for the "));
        h.appendChild(el("em", {}, ["assembling editor"]));
        h.appendChild(document.createTextNode("."));
        return h;
      })(),
      el("p", { class: "hero__lede" }, [
        "Compiled from ",
        el("em", {}, ["the Archive"]),
        ". A working manual: pacing, transitions, audio, opening and closing formulas.",
      ]),
    ])
  );

  if (!payload?.exists) {
    page.appendChild(
      el("section", { class: "state" }, [
        el("p", { class: "state__kicker" }, ["No guide on file"]),
        el("p", { class: "state__title" }, ["Awaiting compilation."]),
        el("p", { class: "state__lede" }, [
          "Generate it with the CLI, then return.",
        ]),
        el("p", { class: "state__cmd" }, ["film-style guide --vision"]),
      ])
    );
    return page;
  }

  const { node, toc } = renderMarkdown(payload.markdown || "");
  node.classList.add("guide-prose");

  const tocEl = el(
    "aside",
    { class: "guide-toc", "aria-label": "Table of contents" },
    [
      el("p", { class: "guide-toc__heading" }, ["Plates"]),
      ...toc.map((entry) =>
        el(
          "a",
          {
            href: `#${entry.id}`,
            "data-toc-target": entry.id,
            style: {
              paddingLeft: `${(entry.level - 1) * 0.75}rem`,
            },
          },
          [entry.text]
        )
      ),
    ]
  );

  const shell = el("div", { class: "guide-shell" }, [tocEl, node]);
  page.appendChild(shell);

  // Smooth scrolling + active TOC highlight on scroll.
  setTimeout(() => {
    const sections = toc
      .map((t) => document.getElementById(t.id))
      .filter(Boolean);
    const links = Array.from(tocEl.querySelectorAll("[data-toc-target]"));
    function update() {
      let active = sections[0];
      for (const sec of sections) {
        if (sec.getBoundingClientRect().top - 120 < 0) active = sec;
      }
      links.forEach((a) =>
        a.classList.toggle(
          "is-active",
          a.dataset.tocTarget === (active?.id || "")
        )
      );
    }
    window.addEventListener("scroll", update, { passive: true });
    update();
  }, 60);

  return page;
}

// ------------ compare ------------------------------------------------------

export function renderCompareIntro() {
  const page = el("div", { class: "page page--compare" });
  page.appendChild(
    el("section", { class: "hero" }, [
      el("p", { class: "hero__kicker" }, ["Compare"]),
      (() => {
        const h = el("h1", { class: "hero__display" });
        h.appendChild(document.createTextNode("Hold a "));
        h.appendChild(el("em", {}, ["rough cut"]));
        h.appendChild(document.createTextNode(" to the light."));
        return h;
      })(),
      el("p", { class: "hero__lede" }, [
        "Drop an FCPXML and see where it drifts from your established profile — decile by decile.",
      ]),
    ])
  );

  const dz = el(
    "label",
    {
      class: "dropzone",
      role: "button",
      tabindex: "0",
      "data-id": "dropzone",
    },
    [
      el("p", { class: "dropzone__sub" }, ["Plate XII · Drop FCPXML"]),
      el("p", { class: "dropzone__title" }, [
        "Drop a .fcpxml here, or click to browse.",
      ]),
      el("p", { class: "dropzone__hint" }, [
        "Nothing leaves this machine. Files are parsed locally and discarded.",
      ]),
      el("input", {
        type: "file",
        accept: ".fcpxml,.xml",
        style: { display: "none" },
        "data-id": "file-input",
      }),
    ]
  );
  page.appendChild(dz);
  page.appendChild(el("div", { "data-id": "compare-result" }));
  return page;
}

export function renderCompareResult(report) {
  const root = el("div", { class: "page page--compare-result" });

  if (report.empty_profile) {
    root.appendChild(
      el("section", { class: "state" }, [
        el("p", { class: "state__kicker" }, ["No profile to compare against"]),
        el("p", { class: "state__title" }, ["Catalogue some films first."]),
        el("p", { class: "state__lede" }, [
          "Run analyze + guide so the dashboard has a baseline.",
        ]),
      ])
    );
    return root;
  }

  const cut = report.cut;
  const deltas = report.deltas;
  const profile = report.profile;

  root.appendChild(
    el("header", { class: "section-rule", style: { marginTop: "2.5rem" } }, [
      el("span", { class: "section-rule__plate" }, ["Plate XIII"]),
      el("span", { class: "section-rule__title" }, [
        `Compared against ${profile.film_count} reel${profile.film_count === 1 ? "" : "s"}`,
      ]),
      el("span", { class: "section-rule__line" }),
    ])
  );

  root.appendChild(
    el("div", { class: "diff-grid" }, [
      diffCell(
        "I · Runtime",
        formatTime(cut.total_duration_sec),
        deltas.duration_in_range
          ? "Within profile"
          : "Outside profile range",
        deltas.duration_in_range
      ),
      diffCell(
        "II · Total cuts",
        cut.clip_count,
        `${deltas.clip_count_pct >= 0 ? "+" : ""}${deltas.clip_count_pct}% vs. avg`,
        Math.abs(deltas.clip_count_pct) <= 20
      ),
      diffCell(
        "III · Avg clip",
        `${(cut.avg_clip_sec ?? 0).toFixed(2)}s`,
        `${deltas.avg_clip_pct >= 0 ? "+" : ""}${deltas.avg_clip_pct}% vs. avg`,
        Math.abs(deltas.avg_clip_pct) <= 15
      ),
      diffCell(
        "IV · Dissolves",
        cut.dissolves,
        `profile avg ${profile.transitions?.avg_dissolves_per_film ?? "—"}`,
        true
      ),
    ])
  );

  root.appendChild(
    el("header", { class: "section-rule" }, [
      el("span", { class: "section-rule__plate" }, ["Plate XIV"]),
      el("span", { class: "section-rule__title" }, ["Decile drift"]),
      el("span", { class: "section-rule__line" }),
    ])
  );

  const chartWrap = el("div", { class: "pacing-bars" }, [
    decileDiff(
      report.pacing_diff.map((d) => d.actual),
      report.pacing_diff.map((d) => d.expected)
    ),
  ]);
  root.appendChild(chartWrap);

  if (report.suggestions?.length) {
    root.appendChild(
      el("header", { class: "section-rule" }, [
        el("span", { class: "section-rule__plate" }, ["Plate XV"]),
        el("span", { class: "section-rule__title" }, [
          "Suggestions, in order of weight",
        ]),
        el("span", { class: "section-rule__line" }),
      ])
    );
    root.appendChild(
      el(
        "ol",
        { class: "suggestions" },
        report.suggestions.map((s) => el("li", {}, [s]))
      )
    );
  } else {
    root.appendChild(
      el(
        "p",
        {
          style: {
            marginTop: "2rem",
            fontFamily: "var(--serif)",
            fontStyle: "italic",
            color: "var(--sage)",
            fontSize: "1.1rem",
          },
        },
        ["No significant deviations. Hands and eye are in agreement."]
      )
    );
  }

  return root;
}

function diffCell(plate, big, deltaText, ok) {
  return el("div", { class: "diff-cell" }, [
    el("p", { class: "diff-cell__plate" }, [plate]),
    el("p", { class: "diff-cell__num" }, [String(big)]),
    el(
      "p",
      { class: `diff-cell__delta ${ok ? "is-ok" : "is-warn"}` },
      [deltaText]
    ),
  ]);
}

// ------------ settings -----------------------------------------------------

export function renderSettings(cfg) {
  const page = el("div", { class: "page page--settings" });
  page.appendChild(
    el("section", { class: "hero" }, [
      el("p", { class: "hero__kicker" }, ["Settings"]),
      (() => {
        const h = el("h1", { class: "hero__display" });
        h.appendChild(document.createTextNode("The "));
        h.appendChild(el("em", {}, ["preferences"]));
        h.appendChild(document.createTextNode(", on file."));
        return h;
      })(),
      el("p", { class: "hero__lede" }, [
        "Persisted to ",
        el("code", {}, ["~/.film-style-analyzer/config.json"]),
        ". Picked up by the CLI on next run.",
      ]),
    ])
  );

  const fields = [
    {
      key: "whisper_model",
      label: "Whisper model",
      hint: "WhisperX checkpoint. Larger is more accurate, slower.",
      type: "text",
    },
    {
      key: "language",
      label: "Language",
      hint: "ISO code for transcription.",
      type: "text",
    },
    {
      key: "scene_detect_threshold",
      label: "Scene detect threshold",
      hint: "Override adaptive sensitivity. Blank = automatic.",
      type: "number",
    },
    {
      key: "min_scene_length_sec",
      label: "Min scene length (sec)",
      hint: "Floor for clip duration during detection.",
      type: "number",
    },
    {
      key: "anthropic_model",
      label: "Anthropic model",
      hint: "Used by guide and vision passes.",
      type: "text",
    },
    {
      key: "gemini_model",
      label: "Gemini model",
      hint: "Used by --gemini narrative pass.",
      type: "text",
    },
    {
      key: "thumbnail_quality",
      label: "Thumbnail quality",
      hint: "ffmpeg q:v. 1 best, 31 worst.",
      type: "number",
    },
    {
      key: "cleanup_audio_after_analysis",
      label: "Cleanup audio after analysis",
      hint: "Delete extracted WAVs once transcription is done.",
      type: "checkbox",
    },
  ];

  const form = el("form", {
    class: "form-grid",
    "data-id": "settings-form",
    onsubmit: (e) => e.preventDefault(),
  });

  for (const f of fields) {
    const labelCell = el("label", { class: "form-row__label" }, [
      f.label,
      el("small", {}, [f.hint]),
    ]);
    const fieldCell = el("div", { class: "form-row__field" });
    let input;
    if (f.type === "checkbox") {
      input = el("input", { type: "checkbox", "data-key": f.key });
      if (cfg[f.key]) input.checked = true;
    } else {
      input = el("input", {
        type: f.type,
        "data-key": f.key,
        step: f.type === "number" ? "0.01" : undefined,
      });
      input.value = cfg[f.key] == null ? "" : cfg[f.key];
    }
    fieldCell.appendChild(input);
    form.appendChild(labelCell);
    form.appendChild(fieldCell);
  }

  page.appendChild(form);

  page.appendChild(
    el("div", { class: "form-actions" }, [
      el(
        "button",
        {
          class: "btn",
          type: "button",
          "data-id": "save-config",
        },
        ["Save"]
      ),
      el(
        "span",
        {
          class: "muted mono",
          style: { fontSize: "0.7rem", letterSpacing: "0.16em" },
          "data-id": "save-status",
        },
        [""]
      ),
    ])
  );

  return page;
}

// ------------ empty state --------------------------------------------------

function emptyState() {
  return el("section", { class: "state" }, [
    el("p", { class: "state__kicker" }, ["The vault is empty"]),
    el("p", { class: "state__title" }, ["Catalogue your first reel."]),
    el("p", { class: "state__lede" }, [
      "Point the analyser at a folder of finished films. Come back here when it has finished its work.",
    ]),
    el("p", { class: "state__cmd" }, [
      "film-style analyze ~/films/finished/",
    ]),
  ]);
}
