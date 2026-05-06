// charts.js — hand-rolled SVG chart helpers. Drawn for the page; not Recharts.
//
// Decile curve: a smooth cardinal-spline polyline with marker dots and a
// hover loupe. Donut: thin-stroke arcs (transition mix). Histogram bars and
// pacing-over-time bars are written inline by views.js — these helpers cover
// the shared geometry.

export function svgEl(tag, attrs = {}, children = []) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    el.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    if (typeof c === "string") el.appendChild(document.createTextNode(c));
    else el.appendChild(c);
  }
  return el;
}

function makeTip() {
  const tip = document.createElement("div");
  tip.className = "tip";
  tip.style.display = "none";
  const strong = document.createElement("strong");
  const muted = document.createElement("span");
  muted.className = "muted";
  muted.style.marginLeft = "0.5em";
  tip.appendChild(strong);
  tip.appendChild(muted);
  return { tip, strong, muted };
}

function setTip({ strong, muted }, primary, secondary) {
  strong.textContent = primary;
  muted.textContent = secondary || "";
}

// Cardinal spline through points → smooth path string.
function cardinalPath(points, tension = 0.5) {
  if (points.length < 2) return "";
  const t = tension;
  const out = [`M ${points[0][0]} ${points[0][1]}`];
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] || points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || p2;
    const cp1x = p1[0] + ((p2[0] - p0[0]) / 6) * t * 2;
    const cp1y = p1[1] + ((p2[1] - p0[1]) / 6) * t * 2;
    const cp2x = p2[0] - ((p3[0] - p1[0]) / 6) * t * 2;
    const cp2y = p2[1] - ((p3[1] - p1[1]) / 6) * t * 2;
    out.push(`C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2[0]} ${p2[1]}`);
  }
  return out.join(" ");
}

/**
 * Draw a decile curve as the hero chart.
 * @param values number[] of 10 values (avg clip duration per decile)
 */
export function decileCurve(values, opts = {}) {
  const w = opts.width || 900;
  const h = opts.height || 280;
  const padL = 32;
  const padR = 24;
  const padT = 28;
  const padB = 38;

  const nonZero = values.filter((v) => v > 0);
  if (!nonZero.length) {
    return placeholder("No pacing data yet.", w, h);
  }
  const max = Math.max(...values) * 1.15;
  const min = 0;
  const xStep = (w - padL - padR) / (values.length - 1);
  const yScale = (v) => padT + (h - padT - padB) * (1 - (v - min) / (max - min));
  const points = values.map((v, i) => [padL + xStep * i, yScale(v)]);

  const svg = svgEl("svg", {
    viewBox: `0 0 ${w} ${h}`,
    role: "img",
    "aria-label": "Pacing curve across film deciles",
  });

  // grid horizontals
  const gridLines = 4;
  for (let i = 0; i <= gridLines; i++) {
    const y = padT + ((h - padT - padB) / gridLines) * i;
    svg.appendChild(
      svgEl("line", {
        x1: padL,
        y1: y,
        x2: w - padR,
        y2: y,
        stroke: "var(--line-soft)",
        "stroke-width": 1,
        "stroke-dasharray": i === gridLines ? "0" : "1 3",
      })
    );
  }

  // y-axis labels (sec)
  for (let i = 0; i <= gridLines; i++) {
    const v = max - (max / gridLines) * i;
    const y = padT + ((h - padT - padB) / gridLines) * i;
    svg.appendChild(
      svgEl(
        "text",
        {
          x: padL - 8,
          y: y + 3,
          "text-anchor": "end",
          class: "chart__axis",
        },
        [`${v.toFixed(1)}s`]
      )
    );
  }

  // x-axis labels (decile)
  for (let i = 0; i < values.length; i++) {
    const x = padL + xStep * i;
    svg.appendChild(
      svgEl(
        "text",
        {
          x,
          y: h - padB + 18,
          "text-anchor": "middle",
          class: "chart__axis",
        },
        [`${i * 10}%`]
      )
    );
  }

  // gradient defs (declared before fill so referenced id exists)
  const defs = svgEl("defs");
  const lg = svgEl("linearGradient", {
    id: "amber-fade",
    x1: 0,
    y1: 0,
    x2: 0,
    y2: 1,
  });
  lg.appendChild(svgEl("stop", { offset: "0%", "stop-color": "#C9974C", "stop-opacity": 0.6 }));
  lg.appendChild(svgEl("stop", { offset: "100%", "stop-color": "#C9974C", "stop-opacity": 0 }));
  defs.appendChild(lg);
  svg.appendChild(defs);

  // soft area fill under curve
  const area =
    cardinalPath(points) +
    ` L ${points.at(-1)[0]} ${h - padB} L ${points[0][0]} ${h - padB} Z`;
  svg.appendChild(
    svgEl("path", {
      d: area,
      fill: "url(#amber-fade)",
      opacity: 0.35,
    })
  );

  // curve line
  svg.appendChild(
    svgEl("path", {
      d: cardinalPath(points),
      fill: "none",
      stroke: "var(--amber-soft)",
      "stroke-width": 1.5,
      "stroke-linecap": "round",
    })
  );

  // dots + invisible hover targets
  const tipBits = makeTip();
  const tip = tipBits.tip;

  points.forEach((p, i) => {
    svg.appendChild(
      svgEl("circle", {
        cx: p[0],
        cy: p[1],
        r: 2.5,
        fill: "var(--amber)",
        stroke: "var(--bg)",
        "stroke-width": 1.5,
      })
    );
    const hot = svgEl("circle", {
      cx: p[0],
      cy: p[1],
      r: 14,
      fill: "transparent",
      style: "cursor: crosshair",
    });
    hot.addEventListener("mouseenter", () => {
      setTip(tipBits, `${(values[i] || 0).toFixed(2)}s`, `at ${i * 10}–${(i + 1) * 10}%`);
      tip.style.display = "block";
    });
    hot.addEventListener("mousemove", (e) => {
      const wrap = svg.parentElement.getBoundingClientRect();
      tip.style.left = `${e.clientX - wrap.left}px`;
      tip.style.top = `${e.clientY - wrap.top}px`;
    });
    hot.addEventListener("mouseleave", () => {
      tip.style.display = "none";
    });
    svg.appendChild(hot);
  });

  const wrap = document.createElement("div");
  wrap.className = "chart";
  wrap.style.position = "relative";
  wrap.appendChild(svg);
  wrap.appendChild(tip);
  return wrap;
}

/**
 * Donut: transition mix.
 * @param parts [{label, value, color}]
 */
export function donut(parts) {
  const w = 240;
  const h = 240;
  const r = 90;
  const cx = w / 2;
  const cy = h / 2;
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${w} ${h}`,
    role: "img",
    "aria-label": "Transition mix",
  });

  // background ring
  svg.appendChild(
    svgEl("circle", {
      cx,
      cy,
      r,
      fill: "none",
      stroke: "var(--line)",
      "stroke-width": 0.6,
    })
  );

  // arcs
  let angle = -Math.PI / 2;
  parts.forEach((p) => {
    const span = (p.value / total) * Math.PI * 2;
    if (span <= 0) return;
    const x1 = cx + r * Math.cos(angle);
    const y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(angle + span);
    const y2 = cy + r * Math.sin(angle + span);
    const large = span > Math.PI ? 1 : 0;
    const d = `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
    svg.appendChild(
      svgEl("path", {
        d,
        fill: "none",
        stroke: p.color,
        "stroke-width": 8,
        "stroke-linecap": "butt",
      })
    );
    angle += span;
  });

  // center text
  const dom = parts.reduce((a, b) => (a.value > b.value ? a : b), { value: 0 });
  const dominantPct = total ? Math.round((dom.value / total) * 100) : 0;
  svg.appendChild(
    svgEl(
      "text",
      {
        x: cx,
        y: cy - 4,
        "text-anchor": "middle",
        "font-family": "var(--serif)",
        "font-style": "italic",
        "font-size": "2.5rem",
        "font-variation-settings": '"opsz" 144',
        fill: "var(--ink)",
      },
      [`${dominantPct}%`]
    )
  );
  svg.appendChild(
    svgEl(
      "text",
      {
        x: cx,
        y: cy + 22,
        "text-anchor": "middle",
        "font-family": "var(--mono)",
        "font-size": "0.65rem",
        "letter-spacing": "0.18em",
        fill: "var(--ink-mute)",
      },
      [(dom.label || "").toUpperCase()]
    )
  );

  return svg;
}

/**
 * Pacing-bars: per-clip duration as bars across film time.
 */
export function pacingBars(clips, opts = {}) {
  const w = opts.width || 900;
  const h = opts.height || 200;
  const padL = 32;
  const padR = 16;
  const padT = 16;
  const padB = 32;

  if (!clips.length) return placeholder("No clips detected.", w, h);
  const totalSec = clips[clips.length - 1].end_sec || 1;
  const maxDur = Math.max(...clips.map((c) => c.duration_sec)) * 1.05;
  const avg =
    clips.reduce((s, c) => s + c.duration_sec, 0) / clips.length;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${w} ${h}`,
    role: "img",
    "aria-label": "Per-clip duration over time",
  });

  // baseline
  svg.appendChild(
    svgEl("line", {
      x1: padL,
      y1: h - padB,
      x2: w - padR,
      y2: h - padB,
      stroke: "var(--line)",
      "stroke-width": 1,
    })
  );

  // average line
  const avgY = padT + (h - padT - padB) * (1 - avg / maxDur);
  svg.appendChild(
    svgEl("line", {
      x1: padL,
      y1: avgY,
      x2: w - padR,
      y2: avgY,
      stroke: "var(--ink-2)",
      "stroke-width": 0.7,
      "stroke-dasharray": "2 3",
      opacity: 0.5,
    })
  );
  svg.appendChild(
    svgEl(
      "text",
      {
        x: w - padR,
        y: avgY - 4,
        "text-anchor": "end",
        class: "chart__axis",
      },
      [`avg ${avg.toFixed(2)}s`]
    )
  );

  // bars
  const tipBits = makeTip();
  const tip = tipBits.tip;

  clips.forEach((c) => {
    const x = padL + ((c.start_sec / totalSec) * (w - padL - padR));
    const barW = Math.max(
      1.2,
      ((c.duration_sec / totalSec) * (w - padL - padR)) - 0.5
    );
    const barH = (c.duration_sec / maxDur) * (h - padT - padB);
    const y = h - padB - barH;
    const rect = svgEl("rect", {
      x,
      y,
      width: barW,
      height: barH,
      class: "pacing-bars__bar",
      rx: 0.5,
    });
    rect.addEventListener("mouseenter", () => {
      setTip(tipBits, `${c.duration_sec.toFixed(2)}s`, `clip ${c.index + 1}`);
      tip.style.display = "block";
    });
    rect.addEventListener("mousemove", (e) => {
      const wrap = svg.parentElement.getBoundingClientRect();
      tip.style.left = `${e.clientX - wrap.left}px`;
      tip.style.top = `${e.clientY - wrap.top}px`;
    });
    rect.addEventListener("mouseleave", () => {
      tip.style.display = "none";
    });
    svg.appendChild(rect);
  });

  // x-axis time labels
  for (let i = 0; i <= 4; i++) {
    const t = (totalSec / 4) * i;
    const x = padL + (i / 4) * (w - padL - padR);
    svg.appendChild(
      svgEl(
        "text",
        {
          x,
          y: h - padB + 18,
          "text-anchor": "middle",
          class: "chart__axis",
        },
        [formatTime(t)]
      )
    );
  }

  const wrap = document.createElement("div");
  wrap.className = "chart";
  wrap.style.position = "relative";
  wrap.appendChild(svg);
  wrap.appendChild(tip);
  return wrap;
}

export function decileDiff(actual, expected) {
  const w = 900;
  const h = 240;
  const padL = 32;
  const padR = 16;
  const padT = 28;
  const padB = 38;

  if (!expected?.length) return placeholder("No profile data yet.", w, h);

  const max = Math.max(...actual, ...expected) * 1.15;
  const xStep = (w - padL - padR) / (expected.length - 1);
  const yScale = (v) => padT + (h - padT - padB) * (1 - v / max);

  const ePts = expected.map((v, i) => [padL + xStep * i, yScale(v)]);
  const aPts = actual.map((v, i) => [padL + xStep * i, yScale(v)]);

  const svg = svgEl("svg", {
    viewBox: `0 0 ${w} ${h}`,
    role: "img",
  });

  // grid
  for (let i = 0; i <= 4; i++) {
    const y = padT + ((h - padT - padB) / 4) * i;
    svg.appendChild(
      svgEl("line", {
        x1: padL,
        y1: y,
        x2: w - padR,
        y2: y,
        stroke: "var(--line-soft)",
        "stroke-width": 1,
        "stroke-dasharray": i === 4 ? "0" : "1 3",
      })
    );
  }

  // expected (profile) — dashed
  svg.appendChild(
    svgEl("path", {
      d: cardinalPath(ePts),
      fill: "none",
      stroke: "var(--ink-mute)",
      "stroke-width": 1,
      "stroke-dasharray": "3 4",
    })
  );

  // actual — solid amber
  svg.appendChild(
    svgEl("path", {
      d: cardinalPath(aPts),
      fill: "none",
      stroke: "var(--amber)",
      "stroke-width": 1.6,
    })
  );

  // dots on actual + warning highlights
  aPts.forEach((p, i) => {
    const pct =
      expected[i] && expected[i] > 0
        ? Math.abs(((actual[i] - expected[i]) / expected[i]) * 100)
        : 0;
    const warn = pct > 25;
    svg.appendChild(
      svgEl("circle", {
        cx: p[0],
        cy: p[1],
        r: warn ? 4 : 2.5,
        fill: warn ? "var(--oxblood)" : "var(--amber)",
        stroke: "var(--bg)",
        "stroke-width": 1.5,
      })
    );
  });

  for (let i = 0; i < expected.length; i++) {
    const x = padL + xStep * i;
    svg.appendChild(
      svgEl(
        "text",
        {
          x,
          y: h - padB + 18,
          "text-anchor": "middle",
          class: "chart__axis",
        },
        [`${i * 10}%`]
      )
    );
  }

  // legend
  const legend = svgEl("g", { transform: `translate(${w - padR - 220}, 10)` });
  legend.appendChild(
    svgEl("line", {
      x1: 0,
      y1: 6,
      x2: 18,
      y2: 6,
      stroke: "var(--ink-mute)",
      "stroke-dasharray": "3 4",
    })
  );
  legend.appendChild(
    svgEl(
      "text",
      { x: 24, y: 9, class: "chart__axis", fill: "var(--ink-mute)" },
      ["YOUR PROFILE"]
    )
  );
  legend.appendChild(
    svgEl("line", {
      x1: 110,
      y1: 6,
      x2: 128,
      y2: 6,
      stroke: "var(--amber)",
      "stroke-width": 1.5,
    })
  );
  legend.appendChild(
    svgEl(
      "text",
      { x: 134, y: 9, class: "chart__axis", fill: "var(--amber-soft)" },
      ["THIS CUT"]
    )
  );
  svg.appendChild(legend);

  return svg;
}

function placeholder(text, w, h) {
  const svg = svgEl("svg", { viewBox: `0 0 ${w} ${h}` });
  svg.appendChild(
    svgEl(
      "text",
      {
        x: w / 2,
        y: h / 2,
        "text-anchor": "middle",
        "font-family": "var(--serif)",
        "font-style": "italic",
        "font-size": "1rem",
        fill: "var(--ink-mute)",
      },
      [text]
    )
  );
  return svg;
}

export function formatTime(sec) {
  if (!isFinite(sec)) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function formatTimecode(sec, fps = 24) {
  if (!isFinite(sec)) return "00:00:00:00";
  const total = Math.floor(sec * fps);
  const ff = total % fps;
  const totalS = Math.floor(total / fps);
  const ss = totalS % 60;
  const mm = Math.floor(totalS / 60) % 60;
  const hh = Math.floor(totalS / 3600);
  const z = (n) => String(n).padStart(2, "0");
  return `${z(hh)}:${z(mm)}:${z(ss)}:${z(ff)}`;
}

export function toRoman(num) {
  if (!num || num < 1) return "";
  const map = [
    [1000, "M"],
    [900, "CM"],
    [500, "D"],
    [400, "CD"],
    [100, "C"],
    [90, "XC"],
    [50, "L"],
    [40, "XL"],
    [10, "X"],
    [9, "IX"],
    [5, "V"],
    [4, "IV"],
    [1, "I"],
  ];
  let n = num;
  let out = "";
  for (const [v, s] of map) {
    while (n >= v) {
      out += s;
      n -= v;
    }
  }
  return out;
}
