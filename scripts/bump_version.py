"""Atualizador centralizado de versão e gerador detalhado de `changelog.txt` / `CHANGELOG.md`.

Uso:
    python scripts/bump_version.py 0.2.0
    python scripts/bump_version.py patch | minor | major
    python scripts/bump_version.py 0.2.0 --notes "Suporte multiusuário, WTS e instaladores desktop"
    python scripts/bump_version.py 0.2.0 --dry-run
    python scripts/bump_version.py 0.2.0 --commit --tag
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from sync_version import read_pyproject_version, sync_all_version_files  # noqa: E402

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?$")


def parse_next_version(current: str, target: str) -> str:
    """Resolve versão explícita (ex.: `0.2.0`) ou incremento semântico (`patch`, `minor`, `major`)."""
    cleaned = target.strip().removeprefix("v")
    if cleaned in {"patch", "minor", "major"}:
        match = SEMVER_RE.match(current.strip())
        if not match:
            raise ValueError(f"Versão atual '{current}' não segue semver X.Y.Z.")
        major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if cleaned == "major":
            return f"{major + 1}.0.0"
        if cleaned == "minor":
            return f"{major}.{minor + 1}.0"
        return f"{major}.{minor}.{patch + 1}"

    if not SEMVER_RE.match(cleaned):
        raise ValueError(f"Versão inválida '{target}'. Use X.Y.Z (ex.: 0.2.0) ou patch/minor/major.")
    return cleaned


def _run_git(args: List[str], root: Path = ROOT) -> str:
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return ""
        return res.stdout.strip()
    except Exception:
        return ""


def get_latest_git_tag(root: Path = ROOT) -> Optional[str]:
    tag = _run_git(["describe", "--tags", "--abbrev=0"], root=root)
    return tag or None


def _clean_commit_subject(subject: str) -> str:
    # Remove prefixos de emoji markdown (:art:, :white_check_mark:, etc.) para leitura limpa
    return re.sub(r"^:[a-z0-9_+-]+:\s*", "", subject.strip()).strip()


def _classify_commit(subject: str) -> str:
    lower = _clean_commit_subject(subject).lower()
    if lower.startswith("feat"):
        return "Novas Funcionalidades"
    if lower.startswith("docs"):
        return "Documentação"
    if lower.startswith("test") or "cobertura" in lower:
        return "Testes e Qualidade"
    if lower.startswith("fix") or "corrig" in lower:
        return "Correções e Estabilidade"
    if lower.startswith("refactor") or lower.startswith("perf"):
        return "Refatoração e Performance"
    if "docker" in lower or "workflow" in lower or "release" in lower or "ci" in lower or "build" in lower:
        return "Infraestrutura, Build e CI/CD"
    return "Melhorias Gerais"


def _classify_layer(rel_path: str) -> str:
    if rel_path.startswith("backend/"):
        return "Backend (API, Serviços & Banco)"
    if rel_path.startswith("frontend/"):
        return "Frontend SPA"
    if rel_path.startswith("ui/"):
        return "Desktop Tauri & Empacotamento"
    if rel_path.startswith("tests/"):
        return "Testes Automatizados"
    if rel_path.startswith(".github/") or rel_path.startswith("scripts/"):
        return "CI/CD & Automação"
    if rel_path.startswith("docs/"):
        return "Documentação"
    return "Raiz & Configuração"


def collect_release_analysis(
    new_version: str,
    previous_version: str,
    previous_tag: Optional[str],
    notes: Optional[str] = None,
    root: Path = ROOT,
) -> Dict[str, object]:
    """Coleta histórico de commits e alterações locais detalhadas para compor o changelog."""
    rev_range = f"{previous_tag}..HEAD" if previous_tag else "HEAD"
    raw_log = _run_git(
        ["log", rev_range, "--date=short", "--pretty=format:%h|%ad|%an|%s"],
        root=root,
    )

    commits: List[Dict[str, str]] = []
    commits_by_category: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    if raw_log:
        for line in raw_log.splitlines():
            parts = line.split("|", 3)
            if len(parts) != 4:
                continue
            sha, date_str, author, subject = parts
            clean_subj = _clean_commit_subject(subject)
            cat = _classify_commit(subject)
            entry = {"sha": sha, "date": date_str, "author": author, "subject": clean_subj, "category": cat}
            commits.append(entry)
            commits_by_category[cat].append(entry)

    # Arquivos alterados nos commits desde a última tag
    committed_files: Dict[str, str] = {}
    if previous_tag:
        raw_committed_status = _run_git(["diff", "--name-status", f"{previous_tag}..HEAD"], root=root)
        for line in raw_committed_status.splitlines():
            parts = line.split("\t", 1)
            if len(parts) == 2:
                committed_files[parts[1].strip()] = parts[0].strip()
        committed_shortstat = _run_git(["diff", "--shortstat", f"{previous_tag}..HEAD"], root=root)
    else:
        committed_shortstat = ""

    # Alterações pendentes na working tree (staged + unstaged + untracked)
    working_files: Dict[str, str] = {}
    raw_status = _run_git(["status", "--porcelain"], root=root)
    for line in raw_status.splitlines():
        if len(line) < 4:
            continue
        code = line[:2].strip() or "M"
        path_str = line[3:].strip()
        if " -> " in path_str:
            path_str = path_str.split(" -> ", 1)[1].strip()
        # Ignora artefatos locais de build, bancos SQLite dev e pastas temporárias
        if path_str.startswith(("dist/", "build/", "ui/src-tauri/target/", "ui/node_modules/", "skills/")):
            continue
        if path_str.endswith((".db", ".sqlite", ".sqlite3")):
            continue
        working_files[path_str] = code

    working_shortstat = _run_git(["diff", "--shortstat", "HEAD"], root=root)

    # Junta arquivos por camada para análise técnica
    all_files: Dict[str, str] = dict(committed_files)
    for path_str, code in working_files.items():
        if path_str in all_files and code != "??":
            all_files[path_str] = f"{all_files[path_str]}+{code}"
        else:
            all_files[path_str] = "A (novo)" if code == "??" else code

    files_by_layer: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for path_str in sorted(all_files):
        files_by_layer[_classify_layer(path_str)].append((path_str, all_files[path_str]))

    return {
        "new_version": new_version,
        "previous_version": previous_version,
        "previous_tag": previous_tag or "início",
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "notes": (notes or "").strip(),
        "commits": commits,
        "commits_by_category": dict(commits_by_category),
        "committed_shortstat": committed_shortstat,
        "working_files": working_files,
        "working_shortstat": working_shortstat,
        "files_by_layer": dict(files_by_layer),
    }


def format_changelog_txt_entry(analysis: Dict[str, object]) -> str:
    """Formata entrada completa e detalhada em texto puro para `changelog.txt`."""
    new_v = analysis["new_version"]
    prev_v = analysis["previous_version"]
    prev_tag = analysis["previous_tag"]
    generated_at = analysis["generated_at"]
    notes = str(analysis["notes"] or "")
    commits: List[Dict[str, str]] = analysis["commits"]  # type: ignore[assignment]
    commits_by_cat: Dict[str, List[Dict[str, str]]] = analysis["commits_by_category"]  # type: ignore[assignment]
    working_files: Dict[str, str] = analysis["working_files"]  # type: ignore[assignment]
    files_by_layer: Dict[str, List[Tuple[str, str]]] = analysis["files_by_layer"]  # type: ignore[assignment]

    lines: List[str] = [
        "=" * 80,
        f"VERSAO v{new_v}  (Data: {generated_at})",
        f"Base anterior: v{prev_v} (tag: {prev_tag})",
        f"Commits incluidos: {len(commits)} | Arquivos pendentes no workspace: {len(working_files)}",
        "=" * 80,
        "",
    ]

    if notes:
        lines.extend(["[RESUMO / DESTAQUES DA VERSAO]", notes, ""])

    if analysis["committed_shortstat"]:
        lines.append(f"Resumo git ({prev_tag}..HEAD): {analysis['committed_shortstat']}")
    if analysis["working_shortstat"]:
        lines.append(f"Resumo alteracoes locais (HEAD): {analysis['working_shortstat']}")
    if analysis["committed_shortstat"] or analysis["working_shortstat"]:
        lines.append("")

    ordered_categories = [
        "Novas Funcionalidades",
        "Correções e Estabilidade",
        "Refatoração e Performance",
        "Infraestrutura, Build e CI/CD",
        "Testes e Qualidade",
        "Documentação",
        "Melhorias Gerais",
    ]
    if commits:
        lines.append("[ALTERACOES POR CATEGORIA (COMMITS)]")
        for cat in ordered_categories:
            items = commits_by_cat.get(cat) or []
            if not items:
                continue
            lines.append(f"  * {cat} ({len(items)}):")
            for item in items:
                lines.append(f"      - [{item['sha']}] ({item['date']}) {item['subject']} — {item['author']}")
        lines.append("")

    if working_files:
        lines.append("[ALTERACOES LOCAIS DETECTADAS NO WORKSPACE]")
        for path_str in sorted(working_files):
            lines.append(f"  - [{working_files[path_str]:>2}] {path_str}")
        lines.append("")

    if files_by_layer:
        lines.append("[INVENTARIO DE ARQUIVOS MODIFICADOS POR CAMADA (PARA ANALISE)]")
        for layer, entries in files_by_layer.items():
            lines.append(f"  [{layer}] ({len(entries)} arquivos)")
            for path_str, status in entries:
                lines.append(f"      {status:<10} {path_str}")
        lines.append("")

    lines.append("")
    return "\n".join(lines)


def format_changelog_md_entry(analysis: Dict[str, object]) -> str:
    """Formata entrada estruturada em Markdown para `CHANGELOG.md` e GitHub Releases."""
    new_v = analysis["new_version"]
    prev_tag = analysis["previous_tag"]
    date_only = str(analysis["generated_at"]).split(" ", 1)[0]
    notes = str(analysis["notes"] or "")
    commits_by_cat: Dict[str, List[Dict[str, str]]] = analysis["commits_by_category"]  # type: ignore[assignment]
    files_by_layer: Dict[str, List[Tuple[str, str]]] = analysis["files_by_layer"]  # type: ignore[assignment]

    lines: List[str] = [
        f"## v{new_v} ({date_only})",
        "",
        f"Comparativo a partir de `{prev_tag}`.",
        "",
    ]

    if notes:
        lines.extend(["### Destaques", "", notes, ""])

    ordered_categories = [
        "Novas Funcionalidades",
        "Correções e Estabilidade",
        "Refatoração e Performance",
        "Infraestrutura, Build e CI/CD",
        "Testes e Qualidade",
        "Documentação",
        "Melhorias Gerais",
    ]
    for cat in ordered_categories:
        items = commits_by_cat.get(cat) or []
        if not items:
            continue
        lines.append(f"### {cat}")
        lines.append("")
        for item in items:
            lines.append(f"- `{item['sha']}` {item['subject']} ({item['author']})")
        lines.append("")

    if files_by_layer:
        lines.append("### Resumo por Camada")
        lines.append("")
        for layer, entries in files_by_layer.items():
            lines.append(f"- **{layer}**: {len(entries)} arquivo(s)")
        lines.append("")

    return "\n".join(lines)


def upsert_changelog_txt(path: Path, version: str, entry: str) -> None:
    """Insere ou substitui a seção da versão no topo de `changelog.txt`."""
    header = (
        "NFSe Manager Pro — Registro Detalhado de Alterações (Changelog para Análise)\n"
        "Gerado automaticamente por scripts/bump_version.py\n\n"
    )
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing.startswith("NFSe Manager Pro — Registro Detalhado"):
        parts = existing.split("\n\n", 1)
        body = parts[1] if len(parts) > 1 else ""
    else:
        body = existing

    # Remove bloco anterior da mesma versão, se já existir
    sep = "=" * 80
    pattern = re.compile(
        rf"{sep}\nVERSAO v{re.escape(version)}\b.*?(?=\n{sep}\nVERSAO v|\Z)",
        re.DOTALL,
    )
    body = pattern.sub("", body).lstrip("\n")
    new_content = header + entry.rstrip("\n") + ("\n\n" + body if body else "\n")
    path.write_text(new_content, encoding="utf-8")


def upsert_changelog_md(path: Path, version: str, entry: str) -> None:
    """Insere ou substitui a seção da versão no topo de `CHANGELOG.md`."""
    header = "# Changelog\n\n"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing.startswith("# Changelog"):
        body = existing[len("# Changelog") :].lstrip("\n")
    else:
        body = existing

    pattern = re.compile(
        rf"^## v{re.escape(version)}\b.*?(?=^## v|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    body = pattern.sub("", body).lstrip("\n")
    new_content = header + entry.rstrip("\n") + ("\n\n" + body if body else "\n")
    path.write_text(new_content, encoding="utf-8")


def update_pyproject_version(pyproject_path: Path, new_version: str) -> bool:
    """Atualiza `version = "..."` dentro de `[project]` (ou `[tool.poetry]`) em `pyproject.toml`."""
    text = pyproject_path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(?m)^(version\s*=\s*")([^"]+)(")',
        rf'\g<1>{new_version}\g<3>',
        text,
        count=1,
    )
    if count == 0:
        raise RuntimeError(f"Campo version não encontrado em {pyproject_path}")
    if updated != text:
        pyproject_path.write_text(updated, encoding="utf-8")
        return True
    return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Altera a versão do projeto em todos os arquivos e gera changelog.txt / CHANGELOG.md detalhados."
    )
    parser.add_argument(
        "target",
        help="Nova versão (ex.: 0.2.0 ou 1.0.0) ou incremento semântico (patch | minor | major).",
    )
    parser.add_argument("--notes", default="", help="Resumo/destaques manuais para incluir na entrada do changelog.")
    parser.add_argument("--no-changelog", action="store_true", help="Não gera nem atualiza changelog.txt / CHANGELOG.md.")
    parser.add_argument("--dry-run", action="store_true", help="Simula a operação sem alterar arquivos no disco.")
    parser.add_argument("--commit", action="store_true", help="Cria commit git após atualizar versão e changelog.")
    parser.add_argument("--tag", action="store_true", help="Cria tag git anotada vX.Y.Z após atualizar (implica --commit se houver alterações).")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    pyproject_path = ROOT / "pyproject.toml"
    current_version = read_pyproject_version(pyproject_path) or "0.0.0"
    new_version = parse_next_version(current_version, args.target)
    previous_tag = get_latest_git_tag(ROOT)

    print(f"Versão atual : {current_version} (última tag: {previous_tag or 'nenhuma'})")
    print(f"Nova versão  : {new_version}")

    analysis = collect_release_analysis(
        new_version=new_version,
        previous_version=current_version,
        previous_tag=previous_tag,
        notes=args.notes,
        root=ROOT,
    )
    txt_entry = format_changelog_txt_entry(analysis)
    md_entry = format_changelog_md_entry(analysis)

    if args.dry_run:
        print("\n[DRY-RUN] Prévia do changelog.txt:\n")
        print(txt_entry)
        return 0

    changed_files: List[str] = []
    if update_pyproject_version(pyproject_path, new_version):
        changed_files.append("pyproject.toml")

    synced = sync_all_version_files(ROOT, new_version)
    changed_files.extend(synced)

    if not args.no_changelog:
        txt_path = ROOT / "changelog.txt"
        md_path = ROOT / "CHANGELOG.md"
        upsert_changelog_txt(txt_path, new_version, txt_entry)
        upsert_changelog_md(md_path, new_version, md_entry)
        changed_files.extend(["changelog.txt", "CHANGELOG.md"])

    print("\nArquivos atualizados/sincronizados:")
    for item in sorted(set(changed_files)):
        print(f" - {item}")

    if args.commit or args.tag:
        subprocess.run(["git", "add", "-A"], cwd=str(ROOT), check=True)
        status_out = _run_git(["status", "--porcelain"], root=ROOT)
        if status_out:
            subprocess.run(
                ["git", "commit", "-m", f"chore(release): v{new_version}"],
                cwd=str(ROOT),
                check=True,
            )
            print(f"Commit criado: chore(release): v{new_version}")

    if args.tag:
        tag_name = f"v{new_version}"
        subprocess.run(
            ["git", "tag", "-a", tag_name, "-m", f"Release {tag_name}"],
            cwd=str(ROOT),
            check=True,
        )
        print(f"Tag criada: {tag_name}")

    print("\nPróximos passos sugeridos para publicar no GitHub:")
    print(f"  1. Revise o changelog em: {ROOT / 'changelog.txt'}")
    print("  2. Se ainda não criou commit/tag: ./scripts/release.sh (ou git push origin master --tags)")
    print(json.dumps({"previous_version": current_version, "new_version": new_version}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
