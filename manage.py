#!/usr/bin/env python3
"""Utilitário de linha de comando estilo Django para gerenciamento do NFSe Manager Pro.

Comandos disponíveis:
    python manage.py makemigrations [--name NOME]
    python manage.py migrate
    python manage.py showmigrations
    python manage.py create_admin [--username USER] [--email EMAIL] [--password PASS]
"""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import load_dotenv_if_present  # noqa: E402
from app.core.migrations import (  # noqa: E402
    create_admin_user,
    makemigrations,
    migrate,
    showmigrations,
)

load_dotenv_if_present()


def cmd_makemigrations(args: argparse.Namespace) -> int:
    created = makemigrations(name=getattr(args, "name", None))
    if created:
        print(f"Migrations for 'app':\n  {created.relative_to(ROOT_DIR)}")
    else:
        print("No changes detected")
    return 0


def cmd_migrate(_args: argparse.Namespace) -> int:
    print("Operations to perform:")
    print("  Apply all migrations: app")
    print("Running migrations:")
    applied = migrate()
    if applied:
        for item in applied:
            print(f"  Applying app.{item}... OK")
    else:
        print("  No migrations to apply.")
    return 0


def cmd_showmigrations(_args: argparse.Namespace) -> int:
    print("app")
    items = showmigrations()
    if not items:
        print(" (no migrations)")
        return 0
    for ver, nm, is_applied in items:
        mark = "X" if is_applied else " "
        print(f" [{mark}] {ver}_{nm}")
    return 0


def cmd_create_admin(args: argparse.Namespace) -> int:
    username = getattr(args, "username", None)
    email = getattr(args, "email", None)
    password = getattr(args, "password", None)

    if not username:
        username = input("Username: ").strip()
    if email is None:
        email = input("Email address: ").strip()
    if not password:
        pwd1 = getpass.getpass("Password: ")
        pwd2 = getpass.getpass("Password (again): ")
        if pwd1 != pwd2:
            print("Error: Your passwords didn't match.", file=sys.stderr)
            return 1
        password = pwd1

    try:
        user = create_admin_user(username=username, email=email, password=password)
        print(f"Superuser '{user.username}' created/updated successfully.")
        return 0
    except Exception as exc:
        print(f"Error creating superuser: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="manage.py",
        description="CLI de gerenciamento de migrações e administração do NFSe Manager Pro.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_make = subparsers.add_parser("makemigrations", help="Detecta alterações nos models e gera nova migração.")
    p_make.add_argument("-n", "--name", help="Nome descritivo opcional para a migração", default=None)
    p_make.set_defaults(func=cmd_makemigrations)

    p_mig = subparsers.add_parser("migrate", help="Aplica as migrações pendentes no banco de dados.")
    p_mig.set_defaults(func=cmd_migrate)

    p_show = subparsers.add_parser("showmigrations", help="Exibe o status das migrações (aplicadas/pendentes).")
    p_show.set_defaults(func=cmd_showmigrations)

    for alias in ("create_admin", "createsuperuser"):
        p_adm = subparsers.add_parser(alias, help="Cria ou atualiza um usuário administrador (superuser).")
        p_adm.add_argument("--username", help="Username do administrador", default=None)
        p_adm.add_argument("--email", help="E-mail do administrador", default=None)
        p_adm.add_argument("--password", help="Senha do administrador", default=None)
        p_adm.set_defaults(func=cmd_create_admin)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
