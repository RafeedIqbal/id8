import json
from pathlib import Path

import pytest

from app.codegen.template_project import (
    IGNORED_DIRS,
    IGNORED_FILES,
    get_template_filepaths,
    infer_language,
    load_template_tree,
    merge_project,
    resolve_template_dir,
)
from app.schemas.code_snapshot import CodeFile


@pytest.fixture
def mock_template_dir(tmp_path: Path) -> str:
    # Create a mock template
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text("page content")
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"react": "19.0.0"},
                "devDependencies": {"typescript": "5.0.0"},
            }
        )
    )

    # Create ignored stuff
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "test.js").write_text("ignore me")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("ignore me")
    (tmp_path / "package-lock.json").write_text("ignore me")

    return str(tmp_path)


def test_infer_language():
    assert infer_language("page.tsx") == "typescript"
    assert infer_language("lib/utils.js") == "javascript"
    assert infer_language("package.json") == "json"
    assert infer_language("README.md") == "markdown"
    assert infer_language("unknown.xyz") == "plaintext"


def test_get_template_filepaths(mock_template_dir: str):
    paths = get_template_filepaths(mock_template_dir)
    assert len(paths) == 2
    assert "package.json" in paths
    assert "app/page.tsx" in paths

    # Check ignored
    assert "node_modules/test.js" not in paths
    assert ".git/config" not in paths
    assert "package-lock.json" not in paths


def test_resolve_template_dir_works_from_repo_root_and_backend_cwd(monkeypatch):
    repo_root = Path(__file__).resolve().parents[3]
    expected = (repo_root / "exampleApp" / "example").resolve()
    assert expected.is_dir()

    monkeypatch.chdir(repo_root)
    assert resolve_template_dir("exampleApp/example") == expected

    monkeypatch.chdir(repo_root / "backend")
    assert resolve_template_dir("exampleApp/example") == expected


def test_load_template_tree(mock_template_dir: str):
    files = load_template_tree(mock_template_dir)
    assert len(files) == 2

    pkg = next(f for f in files if f.path == "package.json")
    assert pkg.language == "json"
    assert "react" in pkg.content

    page = next(f for f in files if f.path == "app/page.tsx")
    assert page.language == "typescript"
    assert page.content == "page content"


def test_merge_project(mock_template_dir: str):
    ai_files = [
        CodeFile(path="app/page.tsx", content="new page", language="typescript"),
        CodeFile(path="components/ui/button.tsx", content="button", language="typescript"),
    ]

    merged = merge_project(mock_template_dir, ai_files)

    assert len(merged) == 3

    # Check AI page took effect
    page = next(f for f in merged if f.path == "app/page.tsx")
    assert page.content == "new page"

    # Check AI component was added
    btn = next(f for f in merged if f.path == "components/ui/button.tsx")
    assert btn.content == "button"

    # Check template package.json remains authoritative until server-side resolution.
    pkg = next(f for f in merged if f.path == "package.json")
    parsed_pkg = json.loads(pkg.content)
    assert parsed_pkg["dependencies"]["react"] == "19.0.0"
    assert "framer-motion" not in parsed_pkg["dependencies"]

    # Ensure they are sorted
    assert [f.path for f in merged] == ["app/page.tsx", "components/ui/button.tsx", "package.json"]
