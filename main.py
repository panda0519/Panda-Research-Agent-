"""Main CLI entrypoint for the Panda Research Agent."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import webbrowser
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from agents.coordinator_agent import CoordinatorAgent
from live_trace.server import start_in_background_thread

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("research_agent")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Panda Research Agent with Multi-Engine Search & 3-Layer Verification"
    )
    parser.add_argument(
        "--topic",
        "-t",
        type=str,
        help="The technical research topic or inquiry (e.g. 'On-device real-time speech diarization')",
    )
    parser.add_argument(
        "--context",
        "-c",
        type=str,
        default="",
        help="Project constraints, intended application, or background context",
    )
    parser.add_argument(
        "--rubric",
        "-r",
        type=str,
        help="Path to evaluation rubric file (YAML, JSON, or Markdown checklist)",
    )
    parser.add_argument(
        "--live-trace",
        action="store_true",
        help="Launch the live trace WebSocket server and open the real-time UI panel",
    )
    parser.add_argument(
        "--trace-port",
        type=int,
        default=8765,
        help="WebSocket port for live trace server (default: 8765)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Path to save the generated markdown research report",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="research_runs.db",
        help="SQLite database path for run persistence (default: research_runs.db)",
    )
    return parser.parse_args()


async def run_pipeline(
    topic: str,
    context: str = "",
    rubric_path: Optional[str] = None,
    output_path: Optional[str] = None,
    db_path: str = "research_runs.db",
    enable_trace: bool = False,
    trace_port: int = 8765,
) -> Dict[str, Any]:
    trace_thread = None
    if enable_trace:
        trace_thread = start_in_background_thread(port=trace_port)
        panel_path = Path(__file__).parent / "live_trace" / "panel.html"
        print(f"\n[LIVE TRACE] Server started on ws://localhost:{trace_port}")
        print(f"[LIVE TRACE] Opening panel: {panel_path.resolve()}")
        webbrowser.open(f"file://{panel_path.resolve()}")

    try:
        coordinator = CoordinatorAgent(
            topic=topic,
            project_context=context,
            db_path=db_path,
        )

        print(f"\n==================================================")
        print(f"  Starting Research Run: {coordinator.run_id}")
        print(f"  Topic: {topic}")
        if context:
            print(f"  Context: {context}")
        print(f"==================================================\n")

        blackboard = await coordinator.run(rubric_path=rubric_path)

        print(f"\n==================================================")
        print(f"  Research Run Complete!")
        print(f"  Verified Sources: {len(blackboard.sources)}")
        print(f"  Academic Papers: {len(blackboard.paper_notes)}")
        print(f"  Identified Gaps: {len(blackboard.gaps)}")
        print(f"  Proposed Features: {len(blackboard.proposed_features)}")
        print(f"  Evaluations: {len(blackboard.evaluations)}")
        print(f"  Claim Verifications: {len(blackboard.claim_verifications)}")
        print(f"==================================================\n")

        # Save markdown report to disk
        out_file = output_path or f"reports/{coordinator.run_id}_report.md"
        Path(out_file).parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(blackboard.report_markdown)
        print(f"Final Report saved to: {Path(out_file).resolve()}\n")

        return blackboard.to_dict()

    finally:
        # trace_thread is daemon, so it dies with the process
        pass


def main() -> None:
    args = parse_args()
    topic = args.topic
    if not topic:
        topic = input("Enter research topic: ").strip()
        if not topic:
            print("Error: Topic is required.")
            sys.exit(1)

    asyncio.run(
        run_pipeline(
            topic=topic,
            context=args.context,
            rubric_path=args.rubric,
            output_path=args.output,
            db_path=args.db,
            enable_trace=args.live_trace,
            trace_port=args.trace_port,
        )
    )


if __name__ == "__main__":
    main()
