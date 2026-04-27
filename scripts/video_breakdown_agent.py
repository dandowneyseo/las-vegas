#!/usr/bin/env python3
"""Transcript-to-vendor clip planner.

Supported input line formats:
1) [HH:MM:SS] Speaker: text
2) M:SS<free text possibly containing 'minutes, SS seconds'>Utterance
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from typing import List, Optional

VENDOR_HINTS = {
    "towing_service": ["towing", "tow", "roadside", "rescue"],
    "marketing": ["marketing", "social media", "leads", "ads", "website"],
    "insurance": ["insurance", "liability", "property", "casualty", "coverage"],
    "software": ["software", "platform", "api", "ai", "dispatch", "tracking"],
    "equipment": ["lift", "strap", "wire rope", "jumper", "battery", "camera", "radio", "equipment"],
    "legal_compliance": ["law", "compliance", "civil relief", "permit"],
    "auction_marketplace": ["auction", "sell", "abandoned vehicles", "surplus"],
    "payments": ["credit card", "processing", "rates", "chargeback"],
    "general": [],
}

BRACKET_TS_RE = re.compile(r"^\[(\d{1,2}:\d{2}:\d{2})\]\s*([^:]+):\s*(.*)$")
RAW_TS_RE = re.compile(r"^(\d{1,2}):(\d{2})(.*)$")
TIME_TEXT_RE = re.compile(r"^\d+\s*minutes?,\s*\d+\s*seconds")

HOST_MARKERS = [
    "you want to give a shout out",
    "tell us about your business",
    "what's your website",
    "we're live",
    "go ahead",
]


@dataclass
class Utterance:
    time: str
    speaker: str
    text: str


@dataclass
class Segment:
    start: str
    end: str
    speaker: str
    vendor_type: str
    key_topic: str
    suggested_title: str
    excerpt: str


def to_hhmmss(minutes: int, seconds: int) -> str:
    return f"00:{minutes:02d}:{seconds:02d}"


def parse_line(line: str) -> Optional[Utterance]:
    line = line.strip()
    if not line:
        return None

    m = BRACKET_TS_RE.match(line)
    if m:
        return Utterance(time=m.group(1), speaker=m.group(2).strip(), text=m.group(3).strip())

    m2 = RAW_TS_RE.match(line)
    if not m2:
        return None

    mm = int(m2.group(1))
    ss = int(m2.group(2))
    rest = m2.group(3).strip()
    rest = TIME_TEXT_RE.sub("", rest).strip()

    speaker = "Host" if any(k in rest.lower() for k in HOST_MARKERS) else "Guest"
    return Utterance(time=to_hhmmss(mm, ss), speaker=speaker, text=rest)


def detect_vendor_type(text: str) -> str:
    lower = text.lower()
    best_type = "general"
    best_score = 0
    for vendor_type, hints in VENDOR_HINTS.items():
        score = sum(1 for h in hints if h in lower)
        if score > best_score:
            best_score = score
            best_type = vendor_type
    return best_type


def infer_topic(text: str) -> str:
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]+", text)
    if not words:
        return "General pitch"
    return " ".join(words[:10])


def infer_title(vendor_type: str, topic: str) -> str:
    return f"{vendor_type.replace('_', ' ').title()} | {topic}"


def parse_segments(lines: List[str]) -> List[Segment]:
    rows = [u for line in lines if (u := parse_line(line))]

    segments: List[Segment] = []
    current: Optional[Segment] = None

    for row in rows:
        vtype = detect_vendor_type(row.text)
        speaker_changed = current is not None and row.speaker != current.speaker
        topic_changed = current is not None and vtype != current.vendor_type and row.speaker != "Host"

        if current is None or speaker_changed or topic_changed:
            if current is not None:
                segments.append(current)
            topic = infer_topic(row.text)
            current = Segment(
                start=row.time,
                end=row.time,
                speaker=row.speaker,
                vendor_type=vtype,
                key_topic=topic,
                suggested_title=infer_title(vtype, topic),
                excerpt=row.text,
            )
        else:
            current.end = row.time
            current.excerpt += " " + row.text

    if current is not None:
        segments.append(current)

    return segments


def recommend_clips(segments: List[Segment], max_per_vendor: int = 3) -> dict:
    grouped: dict[str, list[Segment]] = {}
    for seg in segments:
        if seg.speaker == "Host":
            continue
        grouped.setdefault(seg.vendor_type, []).append(seg)

    recs = {}
    for vendor_type, items in grouped.items():
        ranked = sorted(items, key=lambda s: len(s.excerpt), reverse=True)[:max_per_vendor]
        recs[vendor_type] = [
            {
                "start": s.start,
                "end": s.end,
                "title": s.suggested_title,
                "topic": s.key_topic,
            }
            for s in ranked
        ]
    return recs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Path to transcript text file")
    parser.add_argument("-o", "--output", default="outputs/video_breakdown.json")
    parser.add_argument("--max-clips-per-vendor", type=int, default=3)
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        lines = f.readlines()

    segments = parse_segments(lines)
    payload = {
        "sections": [asdict(s) for s in segments],
        "clip_recommendations": recommend_clips(segments, max_per_vendor=args.max_clips_per_vendor),
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    print(f"Wrote {len(segments)} sections to {args.output}")


if __name__ == "__main__":
    main()
