# qc2md

A simple script for converting reports generated by mpvQC to markdown.

## Features

- `-r`, `--refs`: Add quotation blocks for line references above report entries. (Use `--dialogue` to include actual lines.)
- `-c`, `--chrono`:  Group most notes together in chronological order. The category will be added to each line. Some categories, like Typesetting, will remain separate.
`-d`, `--dialogue`: ASS subtitle file to source references from, where appropriate.
- `--ref-format {full,text}`: How to format references sourced from the dialogue file. `full` includes the entire event definition, `text` includes just the text. Default: `full`
- `--pick-refs`, `--no-pick-refs`: Enables or disables the reference picker. If there are multiple matches in the dialogue file, a picker is displayed to allow selection of the correct line(s). Default: enabled
- `-o`, `--output`:  Path to output generated Markdown to. Defaults to the input filename with a .md extension. Use `-` for stdout. Using stdout will disable the reference picker.

### For Clarity

- The `--dialogue` file only takes effect if the `--refs` flag is enabled
- `--ref-format` and `--pick-refs` only take effect if a `--dialogue` file is supplied
- `--output -` disables `--pick-refs`
