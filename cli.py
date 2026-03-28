"""ShopAI CLI — command-line interface for the orchestrator."""

import argparse
import json
import sys

from core.orchestrator import MainOrchestrator
from utils.logger import get_logger

logger = get_logger("cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ShopAI CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show system status")
    sub.add_parser("start", help="Start the orchestrator")
    sub.add_parser("stop", help="Stop the orchestrator")

    run = sub.add_parser("run", help="Submit a task")
    run.add_argument("task_type", help="Type of task to run")
    run.add_argument("--params", type=str, default="{}", help="JSON params")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    orchestrator = MainOrchestrator()

    if args.command == "start":
        orchestrator.initialize()
        print("ShopAI orchestrator started.")

    elif args.command == "stop":
        orchestrator.shutdown()
        print("ShopAI orchestrator stopped.")

    elif args.command == "status":
        orchestrator.initialize()
        status = orchestrator.get_status()
        print(json.dumps(status, indent=2, default=str))
        orchestrator.shutdown()

    elif args.command == "run":
        orchestrator.initialize()
        params = json.loads(args.params)
        result = orchestrator.submit_task(args.task_type, params)
        print(json.dumps(result, indent=2, default=str))
        orchestrator.shutdown()

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
