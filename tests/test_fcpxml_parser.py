from pathlib import Path

import pytest

from film_style_analyzer.fcpxml_parser import _parse_rational, parse


def test_parse_rational_fraction():
    assert _parse_rational("12000/24000s") == 0.5
    assert _parse_rational("5s") == 5.0
    assert _parse_rational("") == 0.0


def test_parse_fcpxml_basic(tmp_path: Path):
    fcpxml = tmp_path / "cut.fcpxml"
    fcpxml.write_text("""<?xml version="1.0"?>
<fcpxml version="1.10">
  <resources>
    <asset id="a1" hasVideo="1" hasAudio="1"/>
    <asset id="a2" hasVideo="0" hasAudio="1"/>
  </resources>
  <library>
    <event>
      <project>
        <sequence>
          <spine>
            <asset-clip ref="a1" duration="48000/24000s" offset="0s"/>
            <asset-clip ref="a1" duration="72000/24000s" offset="48000/24000s"/>
            <transition name="Cross Dissolve" duration="12/24s"/>
            <asset-clip ref="a1" duration="120000/24000s" offset="120000/24000s"/>
            <asset-clip ref="a2" lane="-1" duration="240000/24000s" offset="0s" audioRole="music"/>
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
""")
    result = parse(fcpxml)
    assert result["clip_count"] == 3
    assert result["transitions_total"] == 1
    assert result["dissolves"] == 1
    assert result["audio"]["has_audio"] is True
    assert result["audio"]["audio_clip_count"] == 1
    assert "music" in result["audio"]["audio_roles"]


def test_parse_fcpxml_empty(tmp_path: Path):
    fcpxml = tmp_path / "empty.fcpxml"
    fcpxml.write_text('<?xml version="1.0"?><fcpxml version="1.10"/>')
    result = parse(fcpxml)
    assert result["clip_count"] == 0
    assert result["audio"]["has_audio"] is False


def test_parse_invalid_xml(tmp_path: Path):
    bad = tmp_path / "bad.fcpxml"
    bad.write_text("not xml at all")
    with pytest.raises(Exception):
        parse(bad)
