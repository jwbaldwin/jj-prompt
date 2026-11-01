#!/usr/bin/env python3
"""Compare exact CLI results and check stored state with the jj executable.

All mutations stay inside a fresh temporary directory. No existing repo is used.
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('baseline', type=Path)
parser.add_argument('candidate', type=Path)
args = parser.parse_args()
binaries = [str(args.baseline.resolve()), str(args.candidate.resolve())]
checks = 0


def run(command, cwd, executable=None):
    result = subprocess.run(command, executable=executable, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode, result.stdout, result.stderr


def jj(repo, *command):
    code, out, err = run(['jj', *command], repo)
    assert code == 0, (command, err)
    return out.decode()


def compare(cwd, *options):
    global checks
    before, after = [run(['jj-prompt', *options], cwd, executable=binary) for binary in binaries]
    assert before == after, (cwd, options, before, after)
    checks += 1
    return after


def check_state(repo, *, divergent=False):
    # jj, not the candidate's library, supplies the expected stored state.
    change_id = jj(repo, 'log', '--ignore-working-copy', '-r', '@', '--no-graph', '-T', 'change_id').strip()
    description = jj(repo, 'log', '--ignore-working-copy', '-r', '@', '--no-graph', '-T', 'description.first_line()').strip()
    conflict = jj(repo, 'log', '--ignore-working-copy', '-r', '@', '--no-graph', '-T', 'conflict').strip() == 'true'
    bookmarks = jj(repo, 'log', '--ignore-working-copy', '-r', '@', '--no-graph', '-T', 'local_bookmarks.map(|b| b.name()).join(" ")').strip()
    stat = jj(repo, 'diff', '--stat', '--ignore-working-copy').splitlines()[-1]
    count = int(stat.split()[0])
    expected = '  ' + change_id[:4]
    if bookmarks:
        expected += ' ' + bookmarks
    status = ('>' if conflict else '') + ('\\' if divergent else '')
    if status:
        expected += ' ' + status
    if count:
        expected += f' ~{count}'
    if description and description != '(no description set)':
        expected += ' ' + description
    code, out, err = compare(repo, '--no-color')
    assert (code, out.decode(), err) == (0, expected, b''), (out, expected)
    nested = repo / 'nested' / 'deep'
    nested.mkdir(parents=True, exist_ok=True)
    assert compare(nested) == compare(repo)
    assert compare(repo.parent, '--cwd', str(nested)) == compare(repo)
    for options in [[], ['prompt'], ['detect'], ['--no-file-count'], ['--no-color', '--no-file-count'],
                    ['--id-length', '0'], ['--id-length', '1'], ['--id-length', '32'],
                    ['--id-length', '999'], ['--symbol', 'custom '], ['--symbol', ''],
                    ['--no-color', '--symbol', 'X', '--id-length', '8'], ['--help'], ['--version']]:
        compare(repo, *options)
    print(f'{repo.name}: count={count}, conflict={conflict}, divergent={divergent}')


with tempfile.TemporaryDirectory(prefix='jj-prompt-verify-') as temporary:
    root = Path(temporary)
    assert compare(root) == (1, b'', b'')
    assert compare(root, 'detect') == (1, b'', b'')
    compare(root, '--not-an-option')
    compare(root, '--id-length', 'bad')
    compare(root, '--cwd', str(root / 'missing'))
    broken = root / 'broken'
    (broken / '.jj').mkdir(parents=True)
    assert compare(broken, 'detect') == (0, b'', b'')
    assert compare(broken) == (1, b'', b'')

    repo = root / 'states'
    jj(root, 'git', 'init', str(repo))
    check_state(repo)
    (repo / 'file').write_text('base\n')
    # Unsnapshotted edits must not enter the stored commit's count.
    check_state(repo)
    jj(repo, 'describe', '-m', '  first line  \nsecond line')
    jj(repo, 'bookmark', 'create', 'alpha', 'beta')
    check_state(repo)
    (repo / 'file').write_text('unsnapshotted\n')
    (repo / 'untracked').write_text('untracked\n')
    check_state(repo)
    jj(repo, 'describe', '-m', 'snapshot')
    check_state(repo)
    # Unusual filenames and file types exercise the file-count representation.
    for name in ['newline\nname', 'line\nM file', 'tab\tname', 'é.txt', ' leading', 'R prefixed']:
        (repo / name).write_text('text\n')
    (repo / 'link').symlink_to('file')
    (repo / 'binary').write_bytes(bytes(range(256)))
    jj(repo, 'describe', '-m', 'unusual paths')
    check_state(repo)
    jj(repo, 'new', '-m', 'types and renames')
    (repo / 'binary').unlink()
    (repo / 'link').unlink()
    (repo / 'file').rename(repo / 'renamed')
    (repo / 'renamed').chmod(0o755)
    (repo / 'link').write_text('now regular\n')
    jj(repo, 'describe', '-m', 'types and renames')
    check_state(repo)

    conflict_repo = root / 'conflict'
    jj(root, 'git', 'init', str(conflict_repo))
    (conflict_repo / 'file').write_text('base\n')
    jj(conflict_repo, 'describe', '-m', 'base')
    base = jj(conflict_repo, 'log', '-r', '@', '--no-graph', '-T', 'commit_id').strip()
    jj(conflict_repo, 'new', base, '-m', 'left')
    (conflict_repo / 'file').write_text('left\n')
    jj(conflict_repo, 'describe', '-m', 'left')
    left = jj(conflict_repo, 'log', '-r', '@', '--no-graph', '-T', 'commit_id').strip()
    jj(conflict_repo, 'new', base, '-m', 'right')
    (conflict_repo / 'file').write_text('right\n')
    jj(conflict_repo, 'describe', '-m', 'right')
    right = jj(conflict_repo, 'log', '-r', '@', '--no-graph', '-T', 'commit_id').strip()
    jj(conflict_repo, 'new', left, right, '-m', 'merge')
    check_state(conflict_repo)
    (conflict_repo / 'extra').write_text('changed while still conflicted\n')
    jj(conflict_repo, 'describe', '-m', 'changed conflict')
    check_state(conflict_repo)
    (conflict_repo / 'file').write_text('resolved\n')
    jj(conflict_repo, 'describe', '-m', 'resolved merge')
    check_state(conflict_repo)

    # Retain two rewrites of one change as visible parents.
    divergent_repo = root / 'divergent'
    jj(root, 'git', 'init', str(divergent_repo))
    jj(divergent_repo, 'describe', '-m', 'one')
    one = jj(divergent_repo, 'log', '-r', '@', '--no-graph', '-T', 'commit_id').strip()
    jj(divergent_repo, 'describe', '-m', 'two')
    two = jj(divergent_repo, 'log', '-r', '@', '--no-graph', '-T', 'commit_id').strip()
    jj(divergent_repo, 'new', one, two, '-m', 'keep both rewrites visible')
    jj(divergent_repo, 'edit', one)
    assert jj(divergent_repo, 'log', '--ignore-working-copy', '-r', '@', '--no-graph', '-T', 'divergent').strip() == 'true'
    check_state(divergent_repo, divergent=True)

    for cwd in [root, repo, repo / 'nested' / 'deep']:
        outputs = []
        for number, binary in enumerate(binaries):
            shim = root / f'starship-bin-{number}'
            shim.mkdir(exist_ok=True)
            if not (shim / 'jj-prompt').exists():
                (shim / 'jj-prompt').symlink_to(binary)
            env = dict(os.environ, PATH=f'{shim}:{os.environ["PATH"]}', STARSHIP_LOG='error')
            result = subprocess.run(['starship', 'module', 'custom.jj'], cwd=cwd, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            outputs.append((result.returncode, result.stdout, result.stderr))
        assert outputs[0] == outputs[1], outputs
        assert outputs[0][0] == 0 and not outputs[0][2], outputs
        assert bool(outputs[0][1]) == (cwd != root), outputs
        checks += 1

    # Missing/failing jj must keep the existing best-effort file-count behavior.
    fake_bin = root / 'bin'
    fake_bin.mkdir()
    (fake_bin / 'jj').write_text('#!/bin/sh\nexit 1\n')
    (fake_bin / 'jj').chmod(0o755)
    original_path = os.environ['PATH']
    for path in [str(fake_bin), str(root / 'missing-bin')]:
        os.environ['PATH'] = path
        compare(repo)
        compare(repo, '--no-file-count')
    os.environ['PATH'] = original_path

print(f'{checks} exact baseline/candidate comparisons passed')
