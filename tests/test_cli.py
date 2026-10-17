"""Validation CLI output and exit-status regressions."""

import json
from types import SimpleNamespace

import pytest

from rubricon.cli import main


def test_validate_json_comparisons(capsys):
    assert main(["validate", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["passed"] is True
    comparisons = output["comparisons"]
    assert [row["coefficient"] for row in comparisons] == [
        "nominal", "ordinal", "interval", "ratio"
    ]
    assert [row["published"] for row in comparisons] == [0.743, 0.815, 0.849, 0.797]
    assert [row["computed"] for row in comparisons] == pytest.approx(
        [0.7434, 0.8154, 0.8491, 0.7974], abs=0.00005
    )
    for row in comparisons:
        assert row["absolute_error"] == pytest.approx(
            abs(row["computed"] - row["published"])
        )
        assert row["absolute_error"] < 0.002


@pytest.mark.parametrize("json_output", [False, True])
def test_validate_mismatch_preserves_failure_status(monkeypatch, capsys, json_output):
    monkeypatch.setattr(
        "rubricon.stats.agreement.krippendorff_alpha",
        lambda data, metric: SimpleNamespace(value=0.0),
    )
    assert main(["validate"] + (["--json"] if json_output else [])) == 1
    output = capsys.readouterr().out
    if json_output:
        assert json.loads(output)["passed"] is False
    else:
        assert "MISMATCH" in output
        assert output.endswith("\nFAIL\n")


def test_validate_default_remains_text(capsys):
    assert main(["validate"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("Krippendorff (2011) reference dataset")
    assert output.endswith("\nPASS\n")
    for row in (
        "nominal   computed=0.7434  published=0.743  OK",
        "ordinal   computed=0.8154  published=0.815  OK",
        "interval  computed=0.8491  published=0.849  OK",
        "ratio     computed=0.7974  published=0.797  OK",
    ):
        assert row in output
