import sys

from main import main


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("serve")
    raise SystemExit(main())
