#!/usr/bin/env python3
"""Create disposable stored-state benchmark fixtures in a new directory."""
import argparse
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path, help='must not already exist')
args = parser.parse_args()
args.directory.mkdir(parents=True)

for name, count in [('empty', 0), ('small', 8), ('large', 1000)]:
    repo = args.directory / name
    subprocess.run(['jj', 'git', 'init', str(repo)], check=True, capture_output=True)
    (repo / 'nested' / 'deep').mkdir(parents=True)
    if count:
        for index in range(count):
            (repo / f'file-{index:04}.txt').write_text('before\n' * (200 if name == 'large' else 1))
        subprocess.run(['jj', 'describe', '-m', 'parent'], cwd=repo, check=True, capture_output=True)
        subprocess.run(['jj', 'new', '-m', f'{name} benchmark\nsecond line'], cwd=repo, check=True, capture_output=True)
        for index in range(count):
            (repo / f'file-{index:04}.txt').write_text('after\n' * (200 if name == 'large' else 1))
        subprocess.run(['jj', 'describe', '-m', f'{name} benchmark\nsecond line'], cwd=repo, check=True, capture_output=True)
        subprocess.run(['jj', 'bookmark', 'create', 'bench'], cwd=repo, check=True, capture_output=True)
    summary = subprocess.run(['jj', 'diff', '--stat', '--ignore-working-copy'], cwd=repo,
                             check=True, capture_output=True, text=True).stdout.splitlines()[-1]
    assert int(summary.split()[0]) == count, summary
    print(f'{repo}: {summary}')
