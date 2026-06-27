"""
Parallel Launcher — opens N terminals, each running a batch slice.

Usage:
    # Launch 3 parallel extraction terminals
    python pipeline/parallel_launch.py --terminals 3

    # Launch 5 terminals for specific companies
    python pipeline/parallel_launch.py --terminals 5

Each terminal runs: python pipeline/batch_extract.py --batch N/TOTAL
"""

import subprocess
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(r"C:/Users/VinothRajapandian/Personal Claude/Stock Monitor")


def launch_terminals(n_terminals):
    print(f"Launching {n_terminals} parallel extraction terminals...\n")

    for i in range(1, n_terminals + 1):
        cmd = (
            f'start "Batch {i}/{n_terminals}" cmd /k '
            f'"cd /d {PROJECT_ROOT} && python pipeline/batch_extract.py --batch {i}/{n_terminals}"'
        )
        print(f"  Terminal {i}: --batch {i}/{n_terminals}")
        subprocess.Popen(cmd, shell=True)

    print(f"\n{n_terminals} terminals launched.")
    print(f"Monitor progress: python pipeline/batch_extract.py --status")


def main():
    parser = argparse.ArgumentParser(description="Launch parallel extraction terminals")
    parser.add_argument("--terminals", type=int, default=3, help="Number of parallel terminals")
    args = parser.parse_args()

    if args.terminals < 1 or args.terminals > 10:
        print("Keep terminals between 1 and 10")
        sys.exit(1)

    launch_terminals(args.terminals)


if __name__ == "__main__":
    main()
