"""CLI for the KP v2 savings benchmark."""

import argparse

from .benchmark import benchmark_packages


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark compact KP packages.")
    parser.add_argument("--samples-root", default="data/sample")
    parser.add_argument("--output", default="docs/savings.md")
    args = parser.parse_args()
    print(benchmark_packages(args.samples_root, args.output))


if __name__ == "__main__":
    main()
