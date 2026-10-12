import argparse
import signal
import sys

from .server import LocalServer


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve the local Capstone video website and generation API.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        server = LocalServer(("127.0.0.1", args.port))
    except OSError as exc:
        print(f"Could not start the local server: {exc}", file=sys.stderr)
        return 1

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    print(f"Capstone is available at http://127.0.0.1:{args.port}", flush=True)
    print("Generation runs on this computer. Keep this terminal open; press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
