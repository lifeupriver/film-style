// timeline.js — synced playhead cursor across multiple time-aligned tracks.
//
// Wrap any DOM node that displays a horizontal timeline (pacing-bars chart,
// audio-ribbon, etc.) in a TimelineTrack. The TimelineGroup binds them
// together so that hovering over one moves a vertical cursor line + timecode
// flag at the same proportional X position on every other track in the group.

import { formatTime, formatTimecode } from "./charts.js";

export class TimelineGroup {
  constructor(durationSec, fps = 24) {
    this.duration = Math.max(0.1, durationSec || 0);
    this.fps = fps;
    this.tracks = [];
  }

  attach(node) {
    if (!node) return null;
    node.classList.add("timeline-track");
    const cursor = document.createElement("div");
    cursor.className = "cursor-line";
    const flag = document.createElement("div");
    flag.className = "cursor-flag";
    node.appendChild(cursor);
    node.appendChild(flag);

    const track = { node, cursor, flag };
    this.tracks.push(track);

    node.addEventListener("mousemove", (e) => this._onMove(track, e));
    node.addEventListener("mouseenter", () => this._setHovered(true));
    node.addEventListener("mouseleave", () => this._setHovered(false));

    return track;
  }

  _onMove(track, event) {
    const rect = track.node.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const ratio = Math.max(0, Math.min(1, x / rect.width));
    const t = ratio * this.duration;
    this._setCursorAt(ratio, t);
  }

  _setCursorAt(ratio, t) {
    const tc = formatTimecode(t, this.fps);
    const wall = formatTime(t);
    for (const tr of this.tracks) {
      const rect = tr.node.getBoundingClientRect();
      const px = ratio * rect.width;
      tr.cursor.style.left = `${px}px`;
      tr.flag.style.left = `${px}px`;
      tr.flag.textContent = `${wall}  ·  ${tc}`;
    }
  }

  _setHovered(active) {
    for (const tr of this.tracks) {
      tr.node.classList.toggle("is-hovered", active);
    }
  }
}
