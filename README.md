# jj-prompt

Fast JJ prompt for [Starship](https://starship.rs).

## Output Format

```
 {change_id} {bookmarks} {status} {~file_count} {description}
```

- `change_id` - 4 chars with jj's native coloring (bold magenta prefix, gray rest)
- `bookmarks` - bold magenta
- `status` - `>` for conflict, `\` for divergent
- `~file_count` - dimmed, number of changed files
- `description` - first line, dimmed

## Install

```bash
cargo build --release
cp target/release/jj-prompt ~/.local/bin/
```

## Starship Config

Add to `~/.config/starship.toml`:

```toml
[custom.jj]
command = "jj-prompt"
when = "jj-prompt detect"
format = "$output "
```

## Options

| Option | Description |
|--------|-------------|
| `--cwd <PATH>` | Override working directory |
| `--id-length <N>` | Change ID length (default: 4) |
| `--symbol <S>` | Symbol prefix (default: ` `) |
| `--no-color` | Disable colors |
| `--no-file-count` | Skip file count |

## Development

```bash
cd ~/repos/_projects/jj-prompt && cargo build --release && cp target/release/jj-prompt ~/.local/bin/
```

## Performance

Times depend on the repository and host. See the [local benchmark note](benchmarks/README.md)
for measured baseline/candidate results, retained and rejected experiments, and reproduction steps.
