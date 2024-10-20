#!/usr/bin/env python

"""
Name: qc2md.py
Description: A simple utility for converting mpvQC reports to markdown
Authors: 9volt, petzku
"""

import re
import ass
import git
import sys
import argparse
import contextlib
from pathlib import Path
from datetime import timedelta
from dataclasses import dataclass
from enum import Enum

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


class RefFormat(Enum):
    FULL = "full"
    TEXT = "text"

    def __str__(self):
        return self.value


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments

    Returns:
        argparse.Namespace: The parsed arguments
    """
    parser = argparse.ArgumentParser(
        prog="qc2md", description="Convert mpvQC reports to markdown"
    )
    parser.add_argument("filename", help="Report generated by mpvQC")
    parser.add_argument(
        "-r",
        "--refs",
        action="store_true",
        help="Add quotation blocks for line references above report entries. Use --dialogue to include actual lines.",
    )
    parser.add_argument(
        "-c",
        "--chrono",
        action="store_true",
        help="Group most notes together in chronological order",
    )
    dialogue = parser.add_mutually_exclusive_group()
    dialogue.add_argument(
        "-d",
        "--dialogue",
        help="ASS subtitle file file to source references from, where appropriate. Implies --refs.",
    )
    dialogue.add_argument(
        "-D",
        "--auto-dialogue",
        action="store_true",
        help="Automatically try to detect dialogue file in same directory as report file. Implies --refs.",
    )
    parser.add_argument(
        "-f",
        "--ref-format",
        type=RefFormat,
        default=RefFormat.FULL,
        choices=tuple(RefFormat),
        help="How to references sourced from the dialogue file (default: %(default)s)",
    )
    parser.add_argument(
        "-F",
        action="store_const",
        const=RefFormat.FULL,
        dest="ref_format",
        help="Equivalent to --ref-format full",
    )
    parser.add_argument(
        "-T",
        action="store_const",
        const=RefFormat.TEXT,
        dest="ref_format",
        help="Equivalent to --ref-format text",
    )
    parser.add_argument(
        "--pick-refs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Display a picker interface if there are multiple matching reference lines (default: %(default)s)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Path to output generated Markdown to. Defaults to the input filename with a .md extension. Use '-' for stdout. Using stdout will disable the reference picker.",
    )

    return parser.parse_args()


def load_report(filename: str) -> tuple[str | None, list[str]]:
    """Load the mpvQC report file

    Args:
        filename (str): mpvQC report filename

    Returns:
        tuple[str | None, list[str]]: Artifact filename if present, and list of raw lines
    """
    lines: list[str] = []
    with open(filename, encoding="utf-8") as file:
        lines = file.readlines()
        # sample line in [FILE] section:
        # path      : /path/to/qc2md/test/blank.mkv
        artifact = next(
            (line.split("/")[-1].strip() for line in lines if line.startswith("path")),
            None,
        )
    # Somewhat hacky, but skips to the [DATA] section.
    # After this point, all lines will be notes (except final line, containing line count)
    lines = lines[lines.index("[DATA]\n") + 1 :]

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
    entries: list[QCEntry], *, group_script_entries: bool = False
) -> dict[str, list[QCEntry]]:
    """Organize report entries into buckets based on their category

    Args:
        entries (list[QCEntry]): Uncategorized list of report entries
        group_script_entries (bool, optional): Groups most categories under "Script". Defaults to False

    Returns:
        dict[str, list[QCEntry]]: Map between categories and entries
    """
    data: dict[str, list[QCEntry]] = {}

    for entry in entries:
        if group_script_entries:
            group = (
                entry.category if entry.category in STANDALONE_CATEGORIES else "Script"
            )
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
            line
            for line in doc.events
            if isinstance(line, ass.line.Dialogue)
            # Sanity check exclude shenanigans and stuff. Should be mostly accurate
            and not "\\pos" in line.text
        ]


def get_dialogue_lines_at_time(
    doc: list[ass.Dialogue], timestamp: str
) -> list[ass.Dialogue]:
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
    # mpvQC only has 1-second resolution => choose any lines that intersect with that second.
    # May result in false positives, but this is better than the alternative.
    return [line for line in doc if (line.start < end) and (line.end > start)]


def write_markdown(
    output_filename: str | None,
    entries: dict[str, list[QCEntry]],
    artifact_filename: str | None = None,
    githash: str | None = None,
    *,
    dialogue_events: list[ass.Dialogue] | None = None,
    include_references: bool = False,
    ref_format: RefFormat = RefFormat.FULL,
    pick_refs: bool = True,
) -> None:
    """Create and write the markdown file

    Args:
        output_filename (str | None): Output filename for the markdown file, or None for stdout
        entries (dict[str, list[QCEntry]]): Map between categories and entries
        artifact_filename (str, optional): Artifact filename. Defaults to None.
        githash (str, optional): Current git hash. Defaults to None.
        dialogue_events (list[ass.Dialogue], optional): Dialogue events. Defaults to None.
        include_references (bool, optional): Should references be added?. Defaults to False.
        ref_format (RefFormat, optional): Dialogue file reference formatting. Defaults to FULL.
        pick_refs (bool, optional): Display a picker interface if there are multiple matching refs. Defaults to True
    """
    with smart_open(output_filename) as md:
        # Write the header if values are supplied
        if artifact_filename:
            md.write(f"Using artifact `{artifact_filename}`\n")
        if githash:
            md.write(f"Repo at commit `{githash}`\n")
        if artifact_filename or githash:
            md.write("\n")

        # Sort sections alphabetically by section header
        ordered_map = sorted(entries.items(), key=lambda item: item[0])

        for group, notes in ordered_map:
            md.write(f"## {group}\n")
            for entry in notes:
                if include_references and group not in NON_DIALOGUE_CATEGORIES:
                    if not dialogue_events:
                        md.write("> \n")
                    else:  # Get references from dialogue file
                        matches = get_dialogue_lines_at_time(
                            dialogue_events, entry.time
                        )
                        # If outputting to stdout, we don't want to bring up interface
                        if pick_refs and len(matches) > 1 and md is not sys.stdout:
                            picks = pick_references(entry, matches)
                            if picks is None:
                                # User interrupted picker (ctrl-C). Assume they want no more interaction
                                pick_refs = False
                            else:
                                matches = picks
                        for ref in matches:
                            md.write(
                                f"> {ref.dump() if ref_format == RefFormat.FULL else ref.text}\n"
                            )

                # Group != category when --chrono is supplied
                if group != entry.category:
                    md.write(
                        f"- [ ] [`{entry.time}` - **{entry.category}**]: {entry.text}\n"
                    )
                else:
                    md.write(f"- [ ] [`{entry.time}`]: {entry.text}\n")
            md.write("\n")


@contextlib.contextmanager
def smart_open(filename: str | None):
    """Custom open method for supporting stdout as a write destination

    Based on https://stackoverflow.com/a/17603000/4611644, CC BY-SA 4.0

    Args:
        filename (str | None): Filename or '-' / None for stdout

    Yields:
        TextIOWrapper: Write destination
    """
    if filename and filename != "-":
        fh = open(filename, mode="w", encoding="utf-8")
        try:
            yield fh
        finally:
            fh.close()
    else:
        yield sys.stdout


def main():
    args = parse_args()
    report_filename = args.filename

    output_filename = (
        None
        if args.output == "-"
        else (
            Path(args.output)
            if args.output is not None
            else Path(args.filename).with_suffix(".md")
        )
    )

    if args.auto_dialogue:
        dialogue_path = next(
            Path(report_filename).parent.glob("*[Dd]ialogue*.ass"), None
        )
    else:
        dialogue_path = args.dialogue

    dialogue_events = (
        load_dialogue_file(Path(dialogue_path))
        if (dialogue_path and Path(dialogue_path).exists())
        else None
    )

    # Use git repo containing QC report rather than current working directory (these may be different)
    repo = git.Repo(path=Path(report_filename).parent, search_parent_directories=True)
    githash = repo.head.object.hexsha

    (artifact_filename, lines) = load_report(report_filename)
    entries = categorize_entries(parse_report(lines), group_script_entries=args.chrono)

    write_markdown(
        output_filename,
        entries,
        artifact_filename,
        githash,
        dialogue_events=dialogue_events,
        include_references=args.refs or (dialogue_events is not None),
        ref_format=args.ref_format,
        pick_refs=args.pick_refs,
    )


def pick_references(
    note: QCEntry, options: list[ass.Dialogue]
) -> list[ass.Dialogue] | None:
    """Display an interface for selecting the appropriate dialogue line(s)
    if there are multiple matches

    Args:
        note (QCEntry): The note to match for
        options (list[ass.Dialogue]): List of matching dialogue lines

    Returns:
        list[ass.Dialogue] | None: The selected line(s), or None if the user canceled the operation
    """
    from textual.app import App, ComposeResult
    from textual.widgets import Footer, Static
    from textual.binding import Binding

    class ReferencePickerApp(App):
        def __init__(self, note: QCEntry, options: list[ass.Dialogue], **kwargs):
            super().__init__(**kwargs)
            self.note = note
            self.options = options
            self.highlighted = 0
            self.selection: list[int] = []

        BINDINGS = [
            Binding("up", "up", "Move cursor up"),
            Binding("down", "down", "Move cursor down"),
            Binding("space", "select", "Select highlighted line"),
            Binding("enter", "accept", "Accept highlighted or selected line(s)"),
        ]

        def compose(self) -> ComposeResult:
            yield Static(
                f"Select the applicable reference(s):\n    [{self.note.category}]: {self.note.text}\n\n"
            )
            for i, option in enumerate(self.options):
                yield Static(
                    f"  {'*' if i in self.selection else ' '} {'>' if i == self.highlighted else ' '} {option.text}",
                    id=f"option-{i}",
                )
            yield Footer(show_command_palette=False)

        def on_mount(self):
            self.update_widgets()

        def update_widgets(self):
            for i, option in enumerate(self.options):
                widget = self.query_one(f"#option-{i}", Static)
                widget.update(
                    f"  {'*' if i in self.selection else ' '} {'>' if i == self.highlighted else ' '} {option.text}"
                )

        async def action_up(self):
            self.highlighted = (self.highlighted - 1) % len(self.options)
            self.update_widgets()

        async def action_down(self):
            self.highlighted = (self.highlighted + 1) % len(self.options)
            self.update_widgets()

        async def action_select(self):
            # Toggle selection of the highlighted item
            (
                self.selection.remove(self.highlighted)
                if (self.highlighted in self.selection)
                else self.selection.append(self.highlighted)
            )
            self.update_widgets()

        async def action_accept(self):
            self.exit(self.selection if len(self.selection) > 0 else [self.highlighted])

    app = ReferencePickerApp(note, options)
    result = app.run()
    return [options[i] for i in result] if result is not None else None


if __name__ == "__main__":
    main()
