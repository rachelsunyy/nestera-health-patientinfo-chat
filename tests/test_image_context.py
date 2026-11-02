"""Files that must never ship stay out of the Docker build context and the Cloud Build upload.

.dockerignore follows Docker's rules: every pattern is relative to the context root, `*` and `?`
stay inside one path segment, `**` spans segments, `!` re-includes, and the last match wins.
.gcloudignore follows gitignore rules: a pattern without a slash matches at any depth and a
trailing slash matches directories only. A path is excluded when it or a parent directory is.
"""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCKERIGNORE = ROOT / ".dockerignore"
GCLOUDIGNORE = ROOT / ".gcloudignore"

MUST_EXCLUDE = [
    ".env",
    ".env.local",
    "prod.env",
    "agents/sub.env",
    "patient_data/x/record.json",
    "external_data/a.csv",
    ".git/config",
    ".claude/x",
    ".venv/lib/x.py",
]
MUST_INCLUDE = [
    "streamlit_app.py",
    "views/patient.py",
    "ui_theme.py",
    "assets/nestera-mark.svg",
    "sample_data/patient_001.json",
    ".streamlit/config.toml",
    "requirements.lock",
]
SECRETS = [".env", ".env.local", "prod.env", "agents/sub.env", "a/b/.env", "a/b/.env.prod", "a/b/x.env"]
UNSUPPORTED = ("[", "\\")
RELATIVE_PATH = re.compile(r"[\w.-]+(?:/[\w.-]+)+")


def glob_to_regex(glob: str) -> str:
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        elif glob[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif glob[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(glob[i]), i + 1
    return out


def parse(text: str, dialect: str) -> list[tuple[bool, re.Pattern, bool]]:
    rules = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#!"):
            raise ValueError(f"unsupported directive: {line}")
        if not line or line.startswith("#"):
            continue
        if any(c in line for c in UNSUPPORTED):
            raise ValueError(f"unsupported pattern syntax: {line}")
        negated = line.startswith("!")
        pattern = line.lstrip("!")
        if dialect == "docker":
            regex, dir_only = glob_to_regex(pattern.strip("/")), False
        elif dialect == "gitignore":
            if negated or "**" in pattern:
                raise ValueError(f"unsupported gitignore pattern: {line}")
            dir_only = pattern.endswith("/")
            body = pattern.rstrip("/")
            anchored = "/" in body
            regex = ("" if anchored else "(?:.*/)?") + glob_to_regex(body.lstrip("/"))
        else:
            raise ValueError(f"unknown dialect: {dialect}")
        rules.append((negated, re.compile(regex + "$"), dir_only))
    return rules


def is_excluded(path: str, rules) -> bool:
    parts = path.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    excluded = False
    for negated, regex, dir_only in rules:
        candidates = prefixes[:-1] if dir_only else prefixes
        if any(regex.match(p) for p in candidates):
            excluded = not negated
    return excluded


def docker_rules(text: str | None = None):
    return parse(DOCKERIGNORE.read_text() if text is None else text, "docker")


def gcloud_rules():
    return parse(GCLOUDIGNORE.read_text(), "gitignore")


def leaks(rules) -> list[str]:
    return [p for p in MUST_EXCLUDE if not is_excluded(p, rules)]


def local_module(name: str) -> Path | None:
    base = ROOT.joinpath(*name.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def imported_modules(tree: ast.Module, package: str) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - node.level])
                module = ".".join(p for p in (base, node.module) if p)
            else:
                module = node.module
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def file_dunder_paths(tree: ast.Module, source: Path) -> set[Path]:
    """Paths built as Path(__file__)...parent / "a" / "b" in the source."""
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        parts, left = [], node
        while isinstance(left, ast.BinOp) and isinstance(left.op, ast.Div):
            if not isinstance(left.right, ast.Constant) or not isinstance(left.right.value, str):
                break
            parts.insert(0, left.right.value)
            left = left.left
        else:
            if "__file__" in ast.unparse(left):
                found.add(source.parent.joinpath(*parts).resolve())
    return found


def runtime_paths() -> set[str]:
    """Modules the app imports, files it opens next to its code, and the dirs it reads at runtime."""
    needed: set[Path] = set()
    queue = [ROOT / "streamlit_app.py"]
    while queue:
        source = queue.pop()
        if source in needed:
            continue
        needed.add(source)
        tree = ast.parse(source.read_text())
        package = ".".join(source.relative_to(ROOT).with_suffix("").parts)
        for name in imported_modules(tree, package):
            segments = name.split(".")
            for i in range(1, len(segments) + 1):
                module = local_module(".".join(segments[:i]))
                if module:
                    queue.append(module)
        needed |= file_dunder_paths(tree, source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and RELATIVE_PATH.fullmatch(node.value):
                if (ROOT / node.value).is_file():
                    needed.add(ROOT / node.value)
    needed |= {ROOT / "assets", ROOT / "sample_data", ROOT / ".streamlit" / "config.toml"}
    files = set()
    for path in needed:
        files |= {p for p in path.rglob("*") if p.is_file()} if path.is_dir() else {path}
    return {f.relative_to(ROOT).as_posix() for f in files if "__pycache__" not in f.parts}


@pytest.mark.parametrize("rules_for", [docker_rules, gcloud_rules], ids=["dockerignore", "gcloudignore"])
def test_secrets_data_and_tooling_are_excluded(rules_for):
    assert leaks(rules_for()) == []


@pytest.mark.parametrize("rules_for", [docker_rules, gcloud_rules], ids=["dockerignore", "gcloudignore"])
def test_app_files_and_lock_are_included(rules_for):
    rules = rules_for()
    assert [p for p in MUST_INCLUDE if is_excluded(p, rules)] == []


def test_runtime_paths_scan_finds_the_app_and_its_assets():
    paths = runtime_paths()
    for expected in ["streamlit_app.py", "ui_theme.py", "config.py", "data/models.py",
                     "assets/nestera-mark.svg", "sample_data/patient_001.json", ".streamlit/config.toml"]:
        assert expected in paths


@pytest.mark.parametrize("rules_for", [docker_rules, gcloud_rules], ids=["dockerignore", "gcloudignore"])
def test_runtime_paths_are_never_excluded(rules_for):
    rules = rules_for()
    assert sorted(p for p in runtime_paths() if is_excluded(p, rules)) == []


def test_gcloudignore_excludes_every_secret_dockerignore_excludes():
    docker, gcloud = docker_rules(), gcloud_rules()
    assert [p for p in SECRETS if is_excluded(p, docker) != is_excluded(p, gcloud)] == []
    assert all(is_excluded(p, docker) for p in SECRETS)


def secret_section(path: Path) -> set[str]:
    section = path.read_text().split("# Secrets\n", 1)[1].split("\n\n", 1)[0]
    return {line.removeprefix("**/") for line in section.splitlines()}


def test_secret_sections_list_the_same_patterns():
    assert secret_section(DOCKERIGNORE) == secret_section(GCLOUDIGNORE)


def test_guard_reports_a_leak_when_the_env_patterns_are_removed():
    lines = DOCKERIGNORE.read_text().splitlines()
    mutated = "\n".join(l for l in lines if l not in ("**/.env", "**/*.env"))
    assert leaks(docker_rules(mutated)) == [".env", "prod.env", "agents/sub.env"]


@pytest.mark.parametrize("line", ["secret[0-9].env", "\\#notacomment", "#!include:.gitignore"])
def test_unsupported_syntax_fails_loudly(line):
    with pytest.raises(ValueError):
        parse(line, "docker")
    with pytest.raises(ValueError):
        parse(line, "gitignore")


def test_docker_patterns_anchor_at_the_root_and_negation_wins_last():
    rules = parse("*.md\n!README.md\nlogs/**/*.log", "docker")
    assert is_excluded("DEPLOY.md", rules)
    assert not is_excluded("README.md", rules)
    assert not is_excluded("docs/guide.md", rules)
    assert is_excluded("logs/a/b/x.log", rules)
    assert is_excluded("logs/x.log", rules)
    assert not is_excluded("logs/x.txt", rules)


def test_gitignore_patterns_match_at_any_depth_and_dir_only_rules_skip_files():
    rules = parse("*.md\ncache/\n/build", "gitignore")
    assert is_excluded("docs/guide.md", rules)
    assert is_excluded("a/cache/x", rules)
    assert not is_excluded("a/cache", rules)
    assert is_excluded("build/x", rules)
    assert not is_excluded("src/build/x", rules)
