"""ShopAI CLI — command-line interface for the orchestrator."""

import argparse
import json
import sys

from core.orchestrator import MainOrchestrator
from engines.registry import engine_count, list_engines
from utils.logger import get_logger

logger = get_logger("cli")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ShopAI — AI-powered Shopify operator (111 engines)",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show system status")
    sub.add_parser("start", help="Start the orchestrator")
    sub.add_parser("stop", help="Stop the orchestrator")

    # Task execution
    run = sub.add_parser("run", help="Submit a task to an engine")
    run.add_argument("task_type", help="Engine name (e.g. product_selection)")
    run.add_argument("--params", type=str, default="{}", help="JSON params")

    # Engine commands
    sub.add_parser("engines", help="List all registered engines")
    eng_info = sub.add_parser("engine-info", help="Show engine details")
    eng_info.add_argument("engine_name", help="Engine name")

    # Pipeline commands
    pipeline = sub.add_parser("pipeline", help="Run a data pipeline")
    pipeline.add_argument("pipeline_name", choices=["product", "marketing", "analytics"])
    pipeline.add_argument("--input", type=str, required=True, help="Path to input JSON file")

    # Workflow commands
    workflow = sub.add_parser("workflow", help="Run a workflow")
    workflow.add_argument("workflow_name", help="Workflow name")
    workflow.add_argument("--params", type=str, default="{}", help="JSON params")

    # Module health check
    sub.add_parser("health", help="Check all module health")

    return parser


def _cmd_engines() -> None:
    engines = list_engines()
    print(f"Registered engines: {engine_count()}\n")
    for i, name in enumerate(engines, 1):
        print(f"  {i:3d}. {name}")


def _cmd_engine_info(engine_name: str) -> None:
    from engines.registry import get_engine
    try:
        engine = get_engine(engine_name)
        print(f"Engine: {engine.engine_name}")
        print(f"Class:  {engine.__class__.__name__}")
        print(f"Inputs: {engine.required_input_fields}")
        print(f"Outputs: {engine.required_output_fields}")
    except KeyError:
        print(f"Unknown engine: {engine_name}")
        sys.exit(1)


def _cmd_pipeline(pipeline_name: str, input_path: str) -> None:
    with open(input_path) as f:
        data = json.load(f)

    if pipeline_name == "product":
        from data_pipeline.pipelines.product_pipeline import ProductPipeline
        result = ProductPipeline().run(data)
    elif pipeline_name == "marketing":
        from data_pipeline.pipelines.marketing_pipeline import MarketingPipeline
        result = MarketingPipeline().run(data)
    elif pipeline_name == "analytics":
        from data_pipeline.pipelines.analytics_pipeline import AnalyticsPipeline
        result = AnalyticsPipeline().run(data)
    else:
        print(f"Unknown pipeline: {pipeline_name}")
        sys.exit(1)

    print(json.dumps(result, indent=2, default=str))


def _cmd_health() -> None:
    import importlib
    modules = [
        ("engines", "engines.registry"),
        ("data_pipeline", "data_pipeline"),
        ("execution", "execution"),
        ("agents", "agents"),
        ("knowledge", "knowledge"),
        ("memory", "memory"),
        ("testing", "testing"),
        ("monitoring", "monitoring"),
        ("infrastructure", "infrastructure"),
        ("workflows", "workflows"),
        ("models", "models.routing.model_router"),
        ("core", "core.orchestrator"),
    ]
    print("ShopAI Health Check\n")
    all_ok = True
    for name, path in modules:
        try:
            importlib.import_module(path)
            print(f"  [OK] {name}")
        except Exception as exc:
            print(f"  [FAIL] {name}: {exc}")
            all_ok = False
    print(f"\nEngines: {engine_count()}")
    print(f"Status: {'ALL OK' if all_ok else 'SOME FAILURES'}")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "engines":
        _cmd_engines()
        return

    if args.command == "engine-info":
        _cmd_engine_info(args.engine_name)
        return

    if args.command == "pipeline":
        _cmd_pipeline(args.pipeline_name, getattr(args, "input"))
        return

    if args.command == "health":
        _cmd_health()
        return

    orchestrator = MainOrchestrator()

    if args.command == "start":
        orchestrator.initialize()
        print(f"ShopAI orchestrator started. ({engine_count()} engines)")

    elif args.command == "stop":
        orchestrator.shutdown()
        print("ShopAI orchestrator stopped.")

    elif args.command == "status":
        orchestrator.initialize()
        status = orchestrator.get_status()
        status["engine_count"] = engine_count()
        print(json.dumps(status, indent=2, default=str))
        orchestrator.shutdown()

    elif args.command == "run":
        orchestrator.initialize()
        params = json.loads(args.params)
        result = orchestrator.submit_task(args.task_type, params)
        print(json.dumps(result, indent=2, default=str))
        orchestrator.shutdown()

    elif args.command == "workflow":
        orchestrator.initialize()
        params = json.loads(args.params)
        result = orchestrator.run_workflow(args.workflow_name, params)
        print(json.dumps(result, indent=2, default=str))
        orchestrator.shutdown()

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
