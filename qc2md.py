#!/usr/bin/env python

"""
Name: qc2md.py
Description: A simple utility for converting mpvQC reports to markdown
Authors: 9volt, petzku
"""

import re
import ass
import git
import argparse
from typing import Dict
from pathlib import Path
from datetime import timedelta
from dataclasses import dataclass

# mpvQC output line format. sample:
# [00:02:18] [Phrasing] unsure of "comprises"
LINE_PATTERN = r"\[(.+?)\] \[(.+?)\] (.+)"

# When using --chrono, keep these categories separate
STANDALONE_CATEGORIES = ("Typeset", "Timing", "Encode")

# When using --refs, do not add a reference line for these categories
NON_DIALOGUE_CATEGORIES = ("Typeset", "Encode")


@dataclass
class QCEntry:
    """An entry in a mpvQC report"""
    time: str
    category: str
    text: str


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments

    Returns:
        argparse.Namespace: The parsed arguments
    """
    parser = argparse.ArgumentParser(
        prog="qc2md", description="Convert mpvQC reports to markdown")
    parser.add_argument("filename", help="mpvQC report")
    parser.add_argument(
        "-r",
        "--refs",
        action="store_true",
        help="Add quotation blocks for line references above report entries"
    )
    parser.add_argument(
        "-c",
        "--chrono",
        action="store_true",
        help="Group most notes together in chronological order"
    )
    parser.add_argument(
        "-d",
        "--dialogue",
        help="Dialogue file to source references from, where appropriate",
    )
    parser.add_argument(
        "--ref-format",
        default="full",
        choices=("full", "text"),
        help="How to format imported dialogue lines (default: %(default)s)"
    )

    return parser.parse_args()


def load_report(filename: str) -> tuple[str, list[str]]:
    """Load the mpvQC report file

    Args:
        filename (str): mpvQC report filename

    Returns:
        tuple[str, list[str]]: Artifact filename and list of raw lines
    """
    lines: list[str] = []
    with open(filename, mode="r", encoding="utf-8") as file:
        lines = file.readlines()
        artifact = next(
            line.split("/")[-1].strip() for line in lines if line.startswith("path")
        )
    lines = lines[lines.index("[DATA]\n") + 1:]

    return (artifact, lines)


def parse_report(lines: list[str]) -> list[QCEntry]:
    """Read the mpvQC report, generating a list of entries

    Args:
        lines (list[str]): Raw lines from the mpvQC report file

    Returns:
        list[QCEntry]: List of QCEntry objects
    """
    entries: list[QCEntry] = []

    for line in lines:
        if line.startswith("#"):
            continue
        if not (match := re.match(LINE_PATTERN, line)):
            continue

        time, category, text = match.groups()
        entries.append(QCEntry(time, category, text))

    return entries


def categorize_entries(
    entries: list[QCEntry],
    *,
    group_script_entries: bool = False
) -> Dict[str, list[QCEntry]]:
    """Organize report entries into buckets based on their category

    Args:
        entries (list[QCEntry]): Uncategorized list of report entries
        group_script_entries (bool): Groups most categories under "Script". Defaults to False

    Returns:
        Dict[str, list[QCEntry]]: Map between categories and entries
    """
    data: Dict[str, list[QCEntry]] = {}

    for entry in entries:
        if group_script_entries:
            group = entry.category if entry.category in STANDALONE_CATEGORIES else "Script"
        else:
            group = entry.category

        if group not in data:
            data[group] = []
        data[group].append(entry)

    return data


def load_dialogue_file(filename: str) -> list[ass.Dialogue]:
    """Load a dialogue subtitle file

    Args:
        filename (str): Filename

    Returns:
        list[ass.Dialogue]: List of dialogue events
    """
    with open(filename, encoding="utf-8-sig") as file:
        doc = ass.parse(file)
        return [
            line for line in doc.events
            if isinstance(line, ass.line.Dialogue)
            # Sanity check exclude shenanigans and stuff. Should be mostly accurate
            and not "\\pos" in line.text
        ]


def get_dialogue_lines_at_time(doc: list[ass.Dialogue], timestamp: str) -> list[ass.Dialogue]:
    """Get the dialogue events present at the given timestamp

    Args:
        doc (list[ass.Dialogue]): List of subtitle events
        timestamp (str): mpvQC timestamp. Format: HH:MM:SS

    Returns:
        list[ass.Dialogue]: List of dialogue events that overlap with the timestamp
    """
    h, m, s = [int(x) for x in timestamp.split(":")]
    start = timedelta(hours=h, minutes=m, seconds=s)
    end = timedelta(seconds=start.seconds + 1)
    return [
        line for line in doc if (line.start < end) and (line.end > start)
    ]


def write_markdown(
    output_filename: str,
    entries: Dict[str, list[QCEntry]],
    artifact_filename: str = None,
    githash: str = None,
    *,
    dialogue_events: list[ass.Dialogue] = None,
    include_references: bool = False,
    ref_format: str = "full"
) -> None:
    """Create and write the markdown file

    Args:
        output_filename (str): Output filename for the markdown file
        entries (Dict[str, list[QCEntry]]): Map between categories and entries
        artifact_filename (str, optional): Artifact filename. Defaults to None.
        githash (str, optional): Current git hash. Defaults to None.
        dialogue_events (list[ass.Dialogue], optional): Dialogue events. Defaults to None.
        include_references (bool, optional): Should references be added?. Defaults to False.
        ref_format (str, optional): Dialogue file reference formatting. Defaults to "full".
    """
    with open(output_filename, mode="w", encoding="utf-8") as md:
        # Write the header if values are supplied
        if artifact_filename:
            md.write(f"Using artifact `{artifact_filename}`\n")
        if githash:
            md.write(f"Repo at commit `{githash}`\n")
        if artifact_filename or githash:
            md.write("\n")

        ordered_map = sorted(entries.items(), key=lambda item: item[0])

        for group, notes in ordered_map:
            md.write(f"## {group}\n")
            for entry in notes:
                if include_references and group not in NON_DIALOGUE_CATEGORIES:
                    if dialogue_events:
                        matches = get_dialogue_lines_at_time(
                            dialogue_events, entry.time)
                        for reference in matches:
                            md.write(
                                f"> {reference.dump() if ref_format == "full" else reference.text}\n")
                    else:
                        md.write("> \n")

                # Group != category when --chrono is supplied
                if group != entry.category:
                    md.write(
                        f"- [ ] [`{entry.time}` - **{entry.category}]: {entry.text}\n")
                else:
                    md.write(f"- [ ] [`{entry.time}`]: {entry.text}\n")
            md.write("\n")


def main():
    args = parse_args()
    report_filename = args.filename
    output_filename = Path(args.filename).with_suffix(".md")

    dialogue_events = load_dialogue_file(Path(args.dialogue)) if (
        args.dialogue and Path(args.dialogue).exists() and args.refs
    ) else None

    repo = git.Repo(path=Path(args.filename).parent,
                    search_parent_directories=True)
    githash = repo.head.object.hexsha

    (artifact_filename, lines) = load_report(report_filename)
    entries = categorize_entries(parse_report(
        lines), group_script_entries=args.chrono)

    write_markdown(
        output_filename=output_filename,
        entries=entries,
        artifact_filename=artifact_filename,
        githash=githash,
        dialogue_events=dialogue_events,
        include_references=args.refs,
        ref_format=args.ref_format
    )


if __name__ == "__main__":
    main()
