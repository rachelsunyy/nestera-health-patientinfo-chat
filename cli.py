"""Interactive CLI for local development and testing.

Usage:
  python cli.py load-patient --file sample_data/patient_001.json
  python cli.py add-questions --patient patient_001 --questions "How is your cough?" "Any fever?"
  python cli.py checkin --patient patient_001
  python cli.py summary --patient patient_001
  python cli.py list-patients
"""

import argparse, json, sys
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from data.models import PatientRecord, DoctorQuestions
from database.patient_db import MockPatientDatabase
from agents.patient_agent import PatientAgent
from agents.summary_agent import SummaryAgent

console = Console()
db = MockPatientDatabase()


def cmd_load_patient(args):
    path = Path(args.file)
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]"); sys.exit(1)
    record = PatientRecord.model_validate(json.loads(path.read_text()))
    db.save_patient(record)
    console.print(f"[green]Registered: {record.name} ({record.patient_id})[/green]")


def cmd_list_patients(_):
    ids = db.list_patient_ids()
    if not ids:
        console.print("[yellow]No patients registered yet.[/yellow]"); return
    for pid in ids:
        console.print(f"  • {pid}")


def cmd_add_questions(args):
    from datetime import date
    dq = DoctorQuestions(
        patient_id=args.patient,
        questions=args.questions,
        added_by=args.added_by or "CLI",
    )
    db.save_doctor_questions(dq)
    console.print(f"[green]{len(args.questions)} question(s) saved for {args.patient} on {dq.date}[/green]")
    for q in args.questions:
        console.print(f"  → {q}")


def cmd_checkin(args):
    try:
        record = db.get_patient(args.patient)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]"); sys.exit(1)

    console.print(Panel(
        f"[bold]Hospital-At-Home Daily Check-In[/bold]\n"
        f"Patient: {record.name}  |  ID: {record.patient_id}\n"
        "[dim]Information collection only — no medical advice.[/dim]",
        border_style="blue",
    ))

    agent = PatientAgent(args.patient, db)
    console.print("\n[dim]Loading patient record and generating questions...[/dim]")
    opening = agent.start_session()
    console.print(f"\n[bold cyan]Agent:[/bold cyan] {opening}\n")

    while True:
        patient_input = Prompt.ask("[bold green]You[/bold green]").strip()
        if not patient_input:
            continue
        reply, done = agent.respond(patient_input)
        console.print(f"\n[bold cyan]Agent:[/bold cyan] {reply}\n")
        if done:
            console.print("[dim]Check-in saved.[/dim]")
            break

    if Prompt.ask("Generate clinician summary now?", choices=["y", "n"], default="y") == "y":
        _run_summary(args.patient)


def cmd_summary(args):
    _run_summary(args.patient, getattr(args, "date", None))


def _run_summary(patient_id: str, checkin_date: str | None = None):
    console.print("\n[dim]Generating clinical summary...[/dim]")
    try:
        record = db.get_patient(patient_id)
        summary = SummaryAgent(patient_id, db).generate(checkin_date)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]{e}[/red]"); return

    console.print(Panel(
        f"[bold]Clinical Summary — {summary.date}[/bold]\n"
        f"Patient: {record.name}\n"
        f"Action: [bold yellow]{summary.recommended_action}[/bold yellow]",
        border_style="magenta",
    ))
    console.print(Markdown(summary.summary_markdown))
    if summary.flagged_items:
        console.print("\n[bold red]FLAGGED:[/bold red]")
        for item in summary.flagged_items:
            console.print(f"  ⚠  {item}")


def main():
    parser = argparse.ArgumentParser(description="Hospital-At-Home Agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("load-patient"); p.add_argument("--file", required=True)
    sub.add_parser("list-patients")

    p = sub.add_parser("add-questions")
    p.add_argument("--patient", required=True)
    p.add_argument("--questions", nargs="+", required=True)
    p.add_argument("--added-by", default="")

    p = sub.add_parser("checkin"); p.add_argument("--patient", required=True)

    p = sub.add_parser("summary")
    p.add_argument("--patient", required=True)
    p.add_argument("--date", default=None)

    args = parser.parse_args()
    {
        "load-patient": cmd_load_patient,
        "list-patients": cmd_list_patients,
        "add-questions": cmd_add_questions,
        "checkin": cmd_checkin,
        "summary": cmd_summary,
    }[args.command](args)


if __name__ == "__main__":
    main()
