"""CLI entry point for KP v2 unpacking."""

import argparse

from .pack import unpack


def main() -> None:
    parser = argparse.ArgumentParser(description="Unpack a KP v2 archive into a recording package.")
    parser.add_argument("kp_path")
    parser.add_argument("out_dir")
    args = parser.parse_args()
    print(unpack(args.kp_path, args.out_dir))


if __name__ == "__main__":
    main()
