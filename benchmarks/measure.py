#!/usr/bin/env python3
"""Interleave fresh processes; keep raw wall times and outputs for review."""
import argparse
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', action='append', required=True, help='label=/absolute/path')
parser.add_argument('--repo', action='append', required=True, help='label=/absolute/path')
parser.add_argument('--runs', type=int, default=100)
parser.add_argument('--warmup', type=int, default=10)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--fresh-executable', action='store_true',
                    help='time the first exec of a new copy per sample; does not evict OS caches')
args = parser.parse_args()
rng = random.Random(0)
results = []
with tempfile.TemporaryDirectory(prefix='jj-prompt-bench-') as temporary:
    for binary_spec in args.binary:
        binary_label, binary = binary_spec.split('=', 1)
        shim = Path(temporary) / binary_label
        shim.mkdir()
        (shim / 'jj-prompt').symlink_to(Path(binary).resolve())
        env = dict(os.environ, PATH=f'{shim}:{os.environ["PATH"]}', STARSHIP_LOG='error')
        for repo_spec in args.repo:
            repo_label, repo = repo_spec.split('=', 1)
            for mode, command in [
                ('prompt', [binary]),
                ('no-file-count', [binary, '--no-file-count']),
                ('detect', [binary, 'detect']),
                ('starship', ['starship', 'module', 'custom.jj']),
            ]:
                results.append(dict(binary=binary_label, executable=binary, repo=repo_label, cwd=repo,
                                    mode=mode, command=command, env=env, samples_ms=[]))

    def measure(case):
        fresh = tempfile.TemporaryDirectory(dir=temporary) if args.fresh_executable else None
        try:
            command, env = case['command'], case['env']
            if fresh:
                executable = Path(fresh.name) / 'jj-prompt'
                shutil.copyfile(case['executable'], executable)
                executable.chmod(0o755)
                env = dict(env, PATH=f'{fresh.name}:{env["PATH"]}')
                if case['mode'] != 'starship':
                    command = [str(executable), *command[1:]]
            start = time.perf_counter_ns()
            completed = subprocess.run(command, cwd=case['cwd'], env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            elapsed = (time.perf_counter_ns() - start) / 1e6
        finally:
            if fresh:
                fresh.cleanup()
        if completed.returncode:
            raise RuntimeError((case['command'], completed.returncode, completed.stderr))
        output = completed.stdout.decode()
        if 'output' in case and output != case['output']:
            raise RuntimeError(f'Output changed during timings: {case["binary"]} {case["repo"]} '
                               f'{case["mode"]}: {case["output"]!r} -> {output!r}; '
                               f'{elapsed:.3f} ms; stderr={completed.stderr!r}')
        case['output'] = output
        if case['mode'] == 'starship' and not output:
            raise RuntimeError('Starship did not run the custom module')
        return elapsed

    order = list(results)
    rng.shuffle(order)
    for case in order:
        case['first_observed_ms'] = measure(case)
    for iteration in range(args.warmup + args.runs):
        rng.shuffle(order)
        for case in order:
            elapsed = measure(case)
            if iteration >= args.warmup:
                case['samples_ms'].append(elapsed)
    for case in results:
        del case['env']
        case['median_ms'] = statistics.median(case['samples_ms'])
        case['p95_ms'] = sorted(case['samples_ms'])[math.ceil(args.runs * .95) - 1]
        print(f'{case["binary"]:12} {case["repo"]:10} {case["mode"]:14} '
              f'{case["median_ms"]:8.3f} {case["p95_ms"]:8.3f}')
    args.out.write_text(json.dumps(dict(runs=args.runs, warmup=args.warmup,
                                        fresh_executable=args.fresh_executable, results=results), indent=2) + '\n')
