"""Hospital-At-Home Agent — CLI entry point.

Usage:
  # Run a patient check-in session
  python main.py checkin --patient patient_001

  # Generate a clinician summary for today's check-in
  python main.py summary --patient patient_001

  # Load a patient record from a JSON file
  python main.py load-patient --file sample_data/patient_001.json

  # List all registered patients
  python main.py list-patients
"""

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from data.models import PatientRecord
from data.store import load_patient_record, save_patient_record, list_patients
from agents.patient_agent import PatientAgent
from agents.summary_agent import SummaryAgent

console = Console()


def cmd_load_patient(args: argparse.Namespace) -> None:
    path = Path(args.file)
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        sys.exit(1)
    record = PatientRecord.model_validate(json.loads(path.read_text()))
    save_patient_record(record)
    console.print(f"[green]Patient record saved: {record.name} ({record.patient_id})[/green]")


def cmd_list_patients(_: argparse.Namespace) -> None:
    patients = list_patients()
    if not patients:
        console.print("[yellow]No patients registered yet.[/yellow]")
        return
    for p in patients:
        console.print(f"  • {p}")


def cmd_checkin(args: argparse.Namespace) -> None:
    try:
        record = load_patient_record(args.patient)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    console.print(Panel(
        f"[bold]Hospital-At-Home Daily Check-In[/bold]\n"
        f"Patient: {record.name}  |  ID: {record.patient_id}\n"
        "─────────────────────────────────────────\n"
        "[dim]This session is for information collection only.\n"
        "The agent will NOT provide medical advice.[/dim]",
        border_style="blue",
    ))

    agent = PatientAgent(record)
    opening = agent.start_session()
    console.print(f"\n[bold cyan]Agent:[/bold cyan] {opening}\n")

    while True:
        patient_input = Prompt.ask("[bold green]You[/bold green]").strip()
        if not patient_input:
            continue

        reply, done = agent.respond(patient_input)
        console.print(f"\n[bold cyan]Agent:[/bold cyan] {reply}\n")

        if done:
            console.print("[dim]Check-in complete. Responses saved.[/dim]")
            break

    # Offer to generate summary immediately
    if Prompt.ask(
        "Generate clinician summary now?", choices=["y", "n"], default="y"
    ) == "y":
        cmd_summary_for_record(record)


def cmd_summary(args: argparse.Namespace) -> None:
    try:
        record = load_patient_record(args.patient)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    cmd_summary_for_record(record, getattr(args, "date", None))


def cmd_summary_for_record(record: PatientRecord, checkin_date: str | None = None) -> None:
    console.print("\n[dim]Generating clinical summary...[/dim]")
    agent = SummaryAgent(record)

    try:
        summary = agent.generate(checkin_date)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return

    console.print(Panel(
        f"[bold]Clinical Summary — {summary.date}[/bold]\n"
        f"Patient: {record.name}  |  ID: {record.patient_id}\n"
        f"Recommended action: [bold yellow]{summary.recommended_action}[/bold yellow]",
        border_style="magenta",
    ))
    console.print(Markdown(summary.summary_markdown))

    if summary.flagged_items:
        console.print("\n[bold red]FLAGGED ITEMS:[/bold red]")
        for item in summary.flagged_items:
            console.print(f"  ⚠  {item}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Hospital-At-Home Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p_load = sub.add_parser("load-patient", help="Register a patient from a JSON file")
    p_load.add_argument("--file", required=True)

    sub.add_parser("list-patients", help="List registered patients")

    p_checkin = sub.add_parser("checkin", help="Run a daily check-in for a patient")
    p_checkin.add_argument("--patient", required=True, help="Patient ID")

    p_summary = sub.add_parser("summary", help="Generate a clinician summary")
    p_summary.add_argument("--patient", required=True, help="Patient ID")
    p_summary.add_argument("--date", default=None, help="Date (YYYY-MM-DD), default=today")

    args = parser.parse_args()

    dispatch = {
        "load-patient": cmd_load_patient,
        "list-patients": cmd_list_patients,
        "checkin": cmd_checkin,
        "summary": cmd_summary,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
