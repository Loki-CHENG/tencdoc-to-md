"""Probe a docx file for structural metadata needed by the cleaner pipeline.

We deliberately parse the raw ZIP + XML instead of relying on python-docx,
because Tencent Doc exports use randomized style IDs that python-docx doesn't
map back to semantic names reliably. Direct XML parsing lets us work from the
``w:name`` attribute (which IS standardized) instead.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


@dataclass
class DocxProbe:
    docx_path: Path
    title: Optional[str] = None
    author: Optional[str] = None
    heading_levels_used: List[int] = field(default_factory=list)
    image_files: List[str] = field(default_factory=list)
    paragraph_style_map: Dict[str, str] = field(default_factory=dict)
    has_comments: bool = False
    has_vmerge: bool = False
    has_footnotes: bool = False
    raw_doc_length: int = 0
    is_tencent_doc: bool = False

    def summary(self) -> Dict:
        return {
            "title": self.title,
            "author": self.author,
            "heading_levels_used": sorted(set(self.heading_levels_used)),
            "image_count": len(self.image_files),
            "image_files": self.image_files,
            "has_comments": self.has_comments,
            "has_vmerge": self.has_vmerge,
            "has_footnotes": self.has_footnotes,
            "is_tencent_doc": self.is_tencent_doc,
        }


# Pre-compiled patterns used repeatedly.
_STYLE_PATTERN = re.compile(
    r'<w:style\s+([^>]*?)>(.*?)</w:style>',
    re.DOTALL,
)
_STYLE_ID_PATTERN = re.compile(r'w:styleId="([^"]+)"')
_STYLE_TYPE_PATTERN = re.compile(r'w:type="([^"]+)"')
_STYLE_NAME_PATTERN = re.compile(r'<w:name w:val="([^"]+)"')
_HEADING_NAME_PATTERN = re.compile(r"^heading\s+(\d+)$", re.IGNORECASE)
_PSTYLE_USE_PATTERN = re.compile(r'<w:pStyle w:val="([^"]+)"')
_TITLE_STYLE_ID_PATTERN = re.compile(r'<w:t[^>]*>([^<]*)</w:t>')


def probe_docx(path: Path) -> DocxProbe:
    """Read a docx file and return a populated DocxProbe.

    Never raises on a well-formed but unusual docx — just fills less info.
    """
    probe = DocxProbe(docx_path=path)

    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())

        # --- styles.xml: map style ID -> semantic name ---
        if "word/styles.xml" in names:
            styles_xml = zf.read("word/styles.xml").decode("utf-8", errors="replace")
            title_style_ids = set()
            for m in _STYLE_PATTERN.finditer(styles_xml):
                attrs = m.group(1)
                body = m.group(2)
                sid_m = _STYLE_ID_PATTERN.search(attrs)
                stype_m = _STYLE_TYPE_PATTERN.search(attrs)
                name_m = _STYLE_NAME_PATTERN.search(body)
                if not (sid_m and name_m):
                    continue
                sid = sid_m.group(1)
                stype = stype_m.group(1) if stype_m else ""
                name = name_m.group(1)
                if stype != "paragraph":
                    continue
                probe.paragraph_style_map[sid] = name
                if name.strip().lower() == "title":
                    title_style_ids.add(sid)

            # Tencent Doc fingerprint: 6-char lowercase-alnum random style IDs
            # AND paragraph names like "heading N" rather than "Heading N".
            rand_ids = [
                sid for sid in probe.paragraph_style_map
                if re.fullmatch(r"[a-z0-9]{6}", sid)
            ]
            name_has_lower_heading = any(
                n.startswith("heading ") for n in probe.paragraph_style_map.values()
            )
            probe.is_tencent_doc = len(rand_ids) >= 2 and name_has_lower_heading
        else:
            title_style_ids = set()

        # --- document.xml: heading levels actually used, title text ---
        if "word/document.xml" in names:
            doc_xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
            probe.raw_doc_length = len(doc_xml)

            for sid in _PSTYLE_USE_PATTERN.findall(doc_xml):
                name = probe.paragraph_style_map.get(sid, "")
                hm = _HEADING_NAME_PATTERN.match(name)
                if hm:
                    probe.heading_levels_used.append(int(hm.group(1)))

            # Extract first Title-styled paragraph's text.
            if title_style_ids:
                for sid in title_style_ids:
                    # Find first <w:p>...<w:pStyle w:val="sid"/>...</w:p>
                    pattern = re.compile(
                        r'<w:p\b[^>]*>(?:(?!</w:p>).)*?<w:pStyle\s+w:val="'
                        + re.escape(sid)
                        + r'"\s*/>(.*?)</w:p>',
                        re.DOTALL,
                    )
                    m = pattern.search(doc_xml)
                    if m:
                        text_parts = _TITLE_STYLE_ID_PATTERN.findall(m.group(1))
                        title = "".join(text_parts).strip()
                        if title:
                            probe.title = title
                            break

            probe.has_comments = "<w:commentReference" in doc_xml or "<w:comment" in doc_xml
            probe.has_vmerge = "<w:vMerge" in doc_xml
            probe.has_footnotes = "<w:footnoteReference" in doc_xml

        # --- media files ---
        media = sorted(
            n for n in names if n.startswith("word/media/") and not n.endswith("/")
        )
        probe.image_files = [Path(m).name for m in media]

        # --- core properties: author (dc:creator) ---
        if "docProps/core.xml" in names:
            core_xml = zf.read("docProps/core.xml").decode("utf-8", errors="replace")
            author_m = re.search(r"<dc:creator[^>]*>([^<]*)</dc:creator>", core_xml)
            if author_m:
                probe.author = author_m.group(1).strip() or None
            # Title sometimes present in core.xml even if body doesn't have one.
            if not probe.title:
                t_m = re.search(r"<dc:title[^>]*>([^<]*)</dc:title>", core_xml)
                if t_m and t_m.group(1).strip():
                    probe.title = t_m.group(1).strip()

        # Fallback: use filename stem as title.
        if not probe.title:
            probe.title = path.stem

    return probe
