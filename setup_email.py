"""Jednorazowa konfiguracja wysyłki maili: hasło aplikacji Gmail + mail testowy.

Hasło trafia do Menedżera poświadczeń Windows (nie do pliku ani repozytorium).
Hasło aplikacji tworzysz na https://myaccount.google.com/apppasswords
(wymaga włączonej weryfikacji dwuetapowej).
"""

from __future__ import annotations

import getpass

import keyring

from notify import KEYRING_SERVICE, load_settings, send
from pipeline import configure_console


def main() -> None:
    configure_console()
    settings = load_settings()
    print(f"Konto nadawcy: {settings.sender}")
    password = getpass.getpass("Hasło aplikacji Gmail (16 znaków, nie hasło do konta): ").replace(" ", "")
    if not password:
        print("Nie podano hasła - przerwano.")
        return
    keyring.set_password(KEYRING_SERVICE, settings.sender, password)
    print("Zapisano hasło w Menedżerze poświadczeń Windows.")

    from email.message import EmailMessage

    message = EmailMessage()
    message["Subject"] = "QA Job Finder - test wysyłki"
    message["From"] = settings.sender
    message["To"] = ", ".join(settings.recipients)
    message.set_content("Konfiguracja działa. Raporty będą przychodzić na ten adres.")
    send(message, settings)
    print(f"Wysłano mail testowy na: {', '.join(settings.recipients)}")


if __name__ == "__main__":
    main()
