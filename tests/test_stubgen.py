"""P5 — mnemonica-stubgen: the Python analogue of tactica.

Golden-file comparison of the emitted .pyi for each definition form, plus
checker integration: mypy --strict and pyright strict run over fixture
packages USING `user.Admin(...)` through the generated stubs must report
zero errors, and a wrong argument type must be rejected (the stubs are
not vacuous).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mnemonica.stubgen import generate, main

FIXTURES = Path(__file__).parent / "fixtures" / "stubgen"
SRC = Path(__file__).parent.parent / "src"

CASES = {
    "form_a": ["__init__.pyi"],
    "form_b": ["app.pyi"],
    "form_c": ["app.pyi", "extra.pyi"],
    "edge": ["app.pyi"],
}


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    destination = tmp_path / name
    shutil.copytree(FIXTURES / name, destination)
    return destination


@pytest.mark.parametrize("name", sorted(CASES))
def test_golden_files(name: str, tmp_path: Path) -> None:
    package = _copy_fixture(name, tmp_path)
    written = generate(package)
    assert [p.name for p in written] == sorted(CASES[name])
    for relative in CASES[name]:
        generated = (package / relative).read_text(encoding="utf-8")
        golden = (FIXTURES / name / "expected" / relative).read_text(encoding="utf-8")
        assert generated == golden


@pytest.mark.parametrize("name", sorted(CASES))
def test_generation_is_idempotent(name: str, tmp_path: Path) -> None:
    package = _copy_fixture(name, tmp_path)
    first = {p.name: p.read_text(encoding="utf-8") for p in generate(package)}
    second = {p.name: p.read_text(encoding="utf-8") for p in generate(package)}
    assert first == second


def _run_checker(
    name: str, tmp_path: Path, checker: str, target: str
) -> subprocess.CompletedProcess[str]:
    package = _copy_fixture(name, tmp_path)
    generate(package)
    environment = dict(os.environ)
    environment["MYPYPATH"] = str(SRC)
    if checker == "mypy":
        command = [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "--cache-dir",
            str(tmp_path / ".mypy_cache"),
            target,
        ]
    else:
        (package / "pyrightconfig.json").write_text(
            "{"
            '"typeCheckingMode": "strict",'
            '"pythonVersion": "3.12",'
            '"executionEnvironments": [{'
            f'"root": ".", "extraPaths": ["..", "{SRC}"]'
            "}]}"
            "\n",
            encoding="utf-8",
        )
        command = [sys.executable, "-m", "pyright", "-p", ".", target]
    result = subprocess.run(
        command,
        cwd=package,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    return result


@pytest.mark.parametrize("name", ["form_a", "form_b", "form_c"])
@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_generated_stubs_type_check(name: str, checker: str, tmp_path: Path) -> None:
    result = _run_checker(name, tmp_path, checker, "usage.py")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("name", ["form_a", "form_b", "form_c"])
@pytest.mark.parametrize("checker", ["mypy", "pyright"])
def test_generated_stubs_reject_wrong_arguments(
    name: str, checker: str, tmp_path: Path
) -> None:
    result = _run_checker(name, tmp_path, checker, "usage_bad.py")
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "str" in output  # the expected parameter type is named


def test_cross_module_subtype_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = _copy_fixture("form_c", tmp_path)
    generate(package)
    captured = capsys.readouterr()
    assert "Sub extends User from another module" in captured.err


def test_out_dir_writes_elsewhere(name: str = "form_b") -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        package = Path(tmp) / "pkg"
        shutil.copytree(FIXTURES / name, package)
        out = Path(tmp) / "stubs"
        written = generate(package, out)
        assert written
        assert all(out in p.parents for p in written)
        assert not (package / "app.pyi").exists()


def test_cli_module_invocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # runpy executes the module as __main__, covering the sys.exit path
    import runpy

    package = _copy_fixture("form_a", tmp_path)
    monkeypatch.setattr("sys.argv", ["mnemonica.stubgen", str(package)])
    # the test module already imported stubgen as a library; drop it so
    # runpy executes it fresh in the __main__ role
    sys.modules.pop("mnemonica.stubgen", None)
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("mnemonica.stubgen", run_name="__main__")
    assert caught.value.code == 0
    assert (package / "__init__.pyi").exists()


def test_main_returns_zero_and_prints(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package = _copy_fixture("edge", tmp_path)
    exit_code = main([str(package)])
    assert exit_code == 0
    printed = capsys.readouterr().out
    assert "app.pyi" in printed


def test_modules_without_types_get_no_stub(tmp_path: Path) -> None:
    package = tmp_path / "plain"
    package.mkdir()
    (package / "ordinary.py").write_text("X = 1\n", encoding="utf-8")
    assert generate(package) == []
