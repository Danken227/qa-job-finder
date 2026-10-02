"""Wysyłka raportów mailem (Gmail SMTP).

Ustawienia (adresy) są w lokalnym, ignorowanym przez Git pliku
``config/notify.json``. Hasło aplikacji Gmail jest w Menedżerze poświadczeń
Windows (pakiet ``keyring``) - zapisuje je ``python setup_email.py``.
Zapasowo można podać hasło w zmiennej środowiskowej ``QA_JOB_FINDER_SMTP_PASSWORD``.
"""

from __future__ import annotations

import json
import mimetypes
import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import date
from email.message import EmailMessage
from html import escape
from pathlib import Path

from pipeline import ReportResult

NOTIFY_PATH = Path(__file__).parent / "config" / "notify.json"
KEYRING_SERVICE = "qa-job-finder-smtp"
PASSWORD_ENV = "QA_JOB_FINDER_SMTP_PASSWORD"


@dataclass(frozen=True, slots=True)
class NotifySettings:
    sender: str
    recipients: tuple[str, ...]
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    attach_reports: bool = True


def load_settings(path: Path = NOTIFY_PATH) -> NotifySettings:
    if not path.exists():
        raise RuntimeError(
            "Brakuje config/notify.json. Skopiuj config/notify.example.json jako notify.json "
            "i uruchom: python setup_email.py"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    recipients = raw.get("recipients") or [raw["sender"]]
    return NotifySettings(
        sender=str(raw["sender"]),
        recipients=tuple(str(item) for item in recipients),
        smtp_host=str(raw.get("smtp_host", "smtp.gmail.com")),
        smtp_port=int(raw.get("smtp_port", 465)),
        attach_reports=bool(raw.get("attach_reports", True)),
    )


def get_password(settings: NotifySettings) -> str:
    password = os.environ.get(PASSWORD_ENV, "")
    if password:
        return password
    try:
        import keyring

        password = keyring.get_password(KEYRING_SERVICE, settings.sender) or ""
    except Exception:  # noqa: BLE001 - brak keyring = brak hasła, komunikat niżej
        password = ""
    if not password:
        raise RuntimeError("Brak hasła aplikacji Gmail. Uruchom: python setup_email.py")
    return password


def build_message(
    settings: NotifySettings,
    results: list[ReportResult],
    errors: list[str],
) -> EmailMessage:
    new_total = sum(len(result.new_rows) for result in results)
    message = EmailMessage()
    message["Subject"] = f"QA Job Finder {date.today().isoformat()}: {new_total} nowych ofert"
    message["From"] = settings.sender
    message["To"] = ", ".join(settings.recipients)

    text_lines = [f"Raport z {date.today().isoformat()}.", ""]
    html_parts = [f"<p>Raport z {date.today().isoformat()}.</p>"]
    sheet_url = next((result.sheet_url for result in results if result.sheet_url), "")
    if sheet_url:
        text_lines += [f"Arkusz ze statusami: {sheet_url}", ""]
        html_parts.append(f'<p><b><a href="{escape(sheet_url, quote=True)}">Otwórz arkusz ze statusami</a></b></p>')
    for result in results:
        text_lines.append(
            f"{result.name}: nowe {len(result.new_rows)}, do przejrzenia {result.active} "
            f"(znaleziono {result.found}, po filtrach {result.saved})"
        )
        html_parts.append(
            f"<h3>{escape(result.name)}: {len(result.new_rows)} nowych</h3>"
            f"<p>Do przejrzenia {result.active}; znaleziono {result.found}, po filtrach {result.saved}.</p>"
        )
        if result.new_rows:
            items = []
            for row in result.new_rows:
                label = f"{row.get('Firma', '')} – {row.get('Stanowisko', '')} ({row.get('Lokalizacja', '')}, {row.get('Model pracy', '')})"
                text_lines.append(f"  - {label}: {row.get('Link', '')}")
                items.append(f'<li><a href="{escape(row.get("Link", ""), quote=True)}">{escape(label)}</a></li>')
            html_parts.append(f"<ul>{''.join(items)}</ul>")
        text_lines.append("")
    problems = [*errors, *(f"{result.name}: {problem}" for result in results for problem in result.problems)]
    if problems:
        text_lines += ["Problemy ze źródłami (do sprawdzenia):", *(f"  - {problem}" for problem in problems), ""]
        html_parts.append(
            "<h3>Problemy ze źródłami (do sprawdzenia)</h3><ul>"
            + "".join(f"<li>{escape(problem)}</li>" for problem in problems) + "</ul>"
        )
    hint = ("Statusy (obejrzana / CV wysłane) zmieniaj w arkuszu Google"
            if sheet_url else "Statusy (obejrzana / CV wysłane) zmieniaj w plikach Excel na komputerze")
    if settings.attach_reports:
        hint += " - załączniki to tylko kopie do podglądu."
    text_lines.append(hint)
    html_parts.append(f"<p><small>{escape(hint)}</small></p>")

    message.set_content("\n".join(text_lines))
    message.add_alternative("".join(html_parts), subtype="html")
    for result in results if settings.attach_reports else ():
        path = Path(result.excel_path)
        if path.exists():
            maintype, subtype = (mimetypes.guess_type(path.name)[0] or "application/octet-stream").split("/")
            message.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
    return message


def send(message: EmailMessage, settings: NotifySettings) -> None:
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=60) as server:
        server.login(settings.sender, get_password(settings))
        server.send_message(message)


def send_reports(results: list[ReportResult], errors: list[str]) -> None:
    settings = load_settings()
    send(build_message(settings, results, errors), settings)
    print(f"Wysłano raport na: {', '.join(settings.recipients)}")
