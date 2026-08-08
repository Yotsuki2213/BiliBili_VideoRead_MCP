"""Support ``python -m videoread_mcp [login|status|logout|server]``."""

import sys


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("login", "status", "logout"):
        from videoread_mcp import cli

        sys.exit(cli.main(sys.argv[1:]))
    from videoread_mcp import server

    server.main()


if __name__ == "__main__":
    main()
