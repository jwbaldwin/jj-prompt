# Local performance investigation

2026-11-01, Apple M4 Mac mini, macOS 25.6.0 arm64. Source baseline `d1d0cc28`; rustc 1.99.1 (`58cf8f9c3`), jj 0.46.0, Starship 1.27.0, Python 3.9

## Binaries

Built the untouched source first with `mise exec rust@stable -- cargo build --release --locked`. Cargo.lock, dependencies and release profile stayed unchanged

- Baseline: `target/perf/jj-prompt-baseline`, SHA-256 `ac54ddba9884fc804a0941162da3d19c57f58ff6eda7ea2d35d14e305060304a`
- Candidate: `target/perf/jj-prompt-candidate` (also `target/release/jj-prompt`), SHA-256 `2cf0130b063afb355cc6dc7e5cd36ea84454968ba4f37ef2b9312c1e31481717`
- Installed v0.1.1 release: `/Users/jbaldwin/.local/bin/jj-prompt`, SHA-256 `9e68f5ab4640f646f280e509c6862b3850d1eb1255e318d369936bdab3a306a1`. It reports version 0.1.0, as does Cargo.toml. Left untouched

The investigation did not edit shell config, replace the installed binary or publish a release

## Method

`measure.py` times fresh processes with `perf_counter_ns` and captures/checks output. Each warm case gets one separately recorded first observation, 10 warmups, then 200 samples. All binary/repo/mode combinations are shuffled each round with seed 0. p95 is the nearest-rank percentile. No builds or other benchmark jobs ran during timing

Modes: prompt, `--no-file-count`, `detect`, and `starship module custom.jj`. Starship uses the real unchanged config, including the detect command and `shell = ["sh"]`. A temporary PATH shim selects each binary for both calls. Its timings include shells, detection and rendering

Repos:

- **mmentum**, read-only: `/Users/jbaldwin/repos/projects/mmentum`, stored change `tmzqpzrmsmuuqpsruqlqowymosvxusts`, empty stored diff. All jj commands there used `--ignore-working-copy`; no snapshot or other mutating command ran there
- **empty**, **small**, **large**: disposable repos, removed after measurement. Respectively 0, 8, and 1,000 changed files. Small files replace one line; large files replace 200 lines each. Changed commits have a bookmark and two-line description. `fixtures.py` recreates them

Every sample includes process startup. “Warm” means warmed executable/filesystem caches, not a resident plugin or cached prompt result

## Results

All pairs below are **median / p95, milliseconds**, baseline → candidate. [results.csv](results.csv) records every mode/repo/binary combination, including the installed release, repeat sweep and first-exec sweep. Raw samples, output and ordinary first observations remain in ignored `target/perf/*.json`

- **mmentum prompt:** 13.743 / 14.391 → **3.632 / 4.118**
- **mmentum Starship:** 25.344 / 26.147 → **15.132 / 15.855**
- **empty prompt:** 13.307 / 14.006 → **3.522 / 3.879**; Starship 24.792 / 25.788 → **14.872 / 15.637**
- **small prompt:** 13.616 / 14.246 → 13.523 / 14.237; Starship 25.234 / 26.146 → 25.113 / 26.555. No clear win
- **large prompt:** 41.999 / 43.263 → **13.897 / 14.482**
- **large Starship:** 55.780 / 57.193 → **27.378 / 28.656**
- **mmentum controls:** no-file-count 3.647 / 4.087 → 3.609 / 4.023; detect 2.953 / 3.372 → 2.943 / 3.309. No improvement claimed in these modes on any repo
- **installed control:** mmentum prompt 13.701 / 14.377, Starship 25.365 / 26.203; large prompt 41.831 / 43.194, Starship 55.776 / 57.354. Tracks the source baseline

An independent 100-sample sweep reproduced the gains: mmentum prompt 14.015 / 15.049 → 3.720 / 4.219; Starship 25.839 / 26.797 → 15.493 / 16.410. Large prompt 42.324 / 43.577 → 14.151 / 15.157; Starship 56.436 / 58.550 → 27.890 / 29.452

That supports roughly **74% lower warm prompt median and 40% lower Starship median in mmentum**, and **67% / 51% lower medians in the large fixture**

### First execution is different

`--fresh-executable` makes a new executable copy/inode per sample, outside the timed region, then times its first exec. Starship's detect is the first exec; its prompt uses the same copy. This tests fresh-executable launch overhead with warm OS caches, **not disk-cold startup after reboot/cache eviction**

50 samples after five protocol warmups on mmentum: baseline prompt 169.216 / 220.538 → candidate 148.739 / 211.593; Starship 196.307 / 262.342 → 178.913 / 258.998. Candidate detect alone is 144.886 / 220.522. Fresh-executable overhead and variance dominate; **no cold-start speedup claim**

An earlier exploratory fresh-copy sweep aborted because Starship output changed. The recorded 50-sample rerun was stable, but that earlier event was not diagnosed. Cold-launch reliability remains inconclusive; no source change hides the event. True disk-cold behavior was not measured

## Iterations

1. **Keep: skip the count subprocess for empty stored commits.** `Commit::is_empty()` uses the loaded repo; errors fall through to the existing subprocess. Unsnapshotted edits stay excluded. Paired mmentum prompt 13.898 / 14.411 → 3.628 / 4.070; nonempty cases unchanged (`empty-fast.json`)
2. **Reject: count `diff --summary` / `--name-only` lines.** Reproduced literal newlines inside filenames, including `line\nM file`. Lines are not diff entries. Rejected before changing source
3. **Keep: `jj log -r @ --no-graph -T 'self.diff().files().len()' --ignore-working-copy`.** jj still handles merged parents and rename/copy rules, without calculating insertion/deletion statistics or rendering paths. Paired large prompt 41.417 / 42.314 → 13.822 / 14.306 (`template.json`). Explicit `self.diff()` avoids a user alias shadowing the bare `diff` keyword
4. **Reject: overlap the count child with field rendering.** Small prompt 13.506 / 13.832 → 13.419 / 13.889; large 13.719 / 14.129 → 13.769 / 14.357. Under 0.1 ms, no consistent p95 win; reverted (`overlap.json`). Stop rather than add process-lifecycle complexity for noise

The remaining ~10 ms on small changed commits is largely the jj subprocess. Removing it needs a separate compatibility decision. No daemon, cache, new stored state or architecture change

## Compatibility and limits

`verify.py` made 223 exact baseline/candidate comparisons of exit code, stdout bytes including ANSI, and stderr. It separately checks expected fields against jj's actual stored state and `diff --stat`

Covered clean/changed commits, unsnapshotted tracked/untracked edits, bookmarks, first-line descriptions, root/nested cwd, `--cwd`, conflict merges with zero/nonzero diffs, resolved merges, divergence, renames, executable/type changes, symlinks, binary/Unicode/newline/tab filenames, CLI options/ID lengths/errors, outside-repo and malformed `.jj`, missing/failing jj, and real Starship at root/nested/outside cwd. Output also matched in mmentum and both changed benchmark fixtures

Runtime coverage is jj 0.46.0 only. The count-template methods exist in jj-cli 0.36.0's locally inspected source/docs, but older runtimes were not run. Counts remain best-effort as before. Merge-heavy histories, corrupt object stores, and concurrent mutations were not performance-tested. The existing subprocess can still observe a different operation if another process changes the repo; no new cache or consistency model was added

## Reproduce

Preserve the untouched source baseline binary before editing. Local baseline/candidate binaries and raw results remain in ignored `target/perf/`. Scratch repos, throwaway binaries, redundant text logs and build intermediates were removed after measurement

```sh
mise exec rust@stable -- cargo build --release --locked
python3 benchmarks/fixtures.py /tmp/jj-prompt-new-fixtures
python3 benchmarks/verify.py target/perf/jj-prompt-baseline target/perf/jj-prompt-candidate
python3 benchmarks/measure.py --runs 200 \
  --binary baseline="$PWD/target/perf/jj-prompt-baseline" \
  --binary installed=/Users/jbaldwin/.local/bin/jj-prompt \
  --binary candidate="$PWD/target/perf/jj-prompt-candidate" \
  --repo mmentum=/Users/jbaldwin/repos/projects/mmentum \
  --repo empty=/tmp/jj-prompt-new-fixtures/empty \
  --repo small=/tmp/jj-prompt-new-fixtures/small \
  --repo large=/tmp/jj-prompt-new-fixtures/large \
  --out target/perf/rerun.json
# First-exec sweep: same command, only mmentum, --fresh-executable --runs 50 --warmup 5
```
