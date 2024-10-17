# qc2md

A simple script for converting reports generated by mpvQC to markdown.

## Usage

    qc2md.py [OPTION...] TXT_FILE

Mandatory arguments to long options are mandatory for short options too.

- `-r`, `--refs`: Add quotation blocks for line references above report entries. (Use `--dialogue` to include actual lines.)
- `-c`, `--chrono`: Group most notes together in chronological order. The category will be added to each line. Some categories, like Typesetting, will remain separate.
- `-d`, `--dialogue DIALOGUE`: ASS subtitle file to source references from, where appropriate. Implies `--refs`.
  - `-D`, `--auto-dialogue`: Alternative to, and mutually exclusive with `-d`. Tries to detect a dialogue file in the same directory as the report file. Implies `--refs`.
- `-f`, `--ref-format {full,text}`: How to format references sourced from the dialogue file. `full` includes the entire event definition, `text` includes just the text. Default: `full`
  - `-F` and `-T` are provided as shorthand to set `full` and `text` respectively
- `--pick-refs`, `--no-pick-refs`: Enables or disables the reference picker. If there are multiple matches in the dialogue file, a picker is displayed to allow selection of the correct line(s). Default: enabled
- `-o`, `--output OUTPUT`: Path to output generated Markdown to. Defaults to the input filename with a .md extension. Use `-` for stdout. Using stdout will disable the reference picker.

### For Clarity

- `--ref-format` and `--pick-refs` only take effect if a `--dialogue` file is supplied
- `--output -` disables `--pick-refs`
