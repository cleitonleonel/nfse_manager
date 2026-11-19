#!/usr/bin/env python3
"""Utilitário de linha de comando estilo Django para gerenciamento do NFSe Manager Pro.

Comandos disponíveis:
    python manage.py makemigrations [--name NOME]
    python manage.py migrate
    python manage.py showmigrations
    python manage.py create_admin [--username USER] [--email EMAIL] [--password PASS]
    python manage.py release [patch|minor|major|X.Y.Z] [--notes "RESUMO"] [--push]
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


def cmd_release(args: argparse.Namespace) -> int:
    """Atualiza versão, sincroniza manifestos/changelog e opcionalmente realiza commit/push."""
    scripts_dir = ROOT_DIR / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import bump_version  # noqa: PLC0415

    cli_args: list[str] = [args.target]
    if args.notes:
        cli_args.extend(["--notes", args.notes])
    if args.message:
        cli_args.extend(["--message", args.message])
    if args.no_changelog:
        cli_args.append("--no-changelog")
    if args.no_fetch:
        cli_args.append("--no-fetch")
    if args.dry_run:
        cli_args.append("--dry-run")
    elif not args.no_commit:
        cli_args.append("--commit")
    if args.tag:
        cli_args.append("--tag")
    if args.push:
        cli_args.append("--push")
    return bump_version.main(cli_args)


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

    p_rel = subparsers.add_parser(
        "release",
        help="Incrementa a versão, gera changelog, cria commit e publica a release no GitHub.",
    )
    p_rel.add_argument(
        "target",
        nargs="?",
        default="patch",
        help="Versão alvo (X.Y.Z) ou incremento (patch | minor | major). Padrão: patch.",
    )
    p_rel.add_argument("--notes", default="", help="Resumo/destaques manuais para incluir no changelog.")
    p_rel.add_argument("-m", "--message", default="", help="Mensagem personalizada para o commit git da release.")
    p_rel.add_argument("--no-changelog", action="store_true", help="Não atualiza CHANGELOG.md e changelog.txt.")
    p_rel.add_argument("--no-fetch", action="store_true", help="Não busca tags remotas antes de calcular o diff.")
    p_rel.add_argument("--no-commit", action="store_true", help="Apenas altera os arquivos sem criar commit git.")
    p_rel.add_argument("--tag", action="store_true", help="Também cria tag local anotada vX.Y.Z (para release manual com --push).")
    p_rel.add_argument("--push", action="store_true", help="Envia o commit para origin/HEAD (disparando auto-release.yml e instaladores).")
    p_rel.add_argument("--dry-run", action="store_true", help="Simula a geração sem alterar arquivos.")
    p_rel.set_defaults(func=cmd_release)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
