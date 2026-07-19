import csv
import hashlib
import json
from pathlib import Path

from app.regional_human_judgment import (
    REVIEWER_CONFIDENCE_VALUES,
    REVIEWER_PREFERENCE_VALUES,
    REVIEWER_REASON_CODES,
    STATUS_INSUFFICIENT,
    build_regional_judgment_cases,
    evaluate_regional_weight_configurations,
    import_reviewed_regional_judgments,
    weight_grid,
)
from app.regional_shadow_evaluation import evaluate_regional_shadow_ranking
from tests.test_regional_shadow_evaluation import build_shadow_fixture


def build_evaluation_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    run_dir, shadow_dir = build_shadow_fixture(tmp_path)
    evaluation_dir = tmp_path / "evaluation"
    evaluate_regional_shadow_ranking(shadow_dir=shadow_dir, output_dir=evaluation_dir)
    return run_dir, shadow_dir, evaluation_dir


def fill_review_csv(source_csv: Path, output_csv: Path, *, unicode_notes: bool = False) -> None:
    with source_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames
    assert fieldnames is not None
    for index, row in enumerate(rows):
        row["reviewer_preference"] = REVIEWER_PREFERENCE_VALUES[index % len(REVIEWER_PREFERENCE_VALUES)]
        row["reviewer_confidence"] = REVIEWER_CONFIDENCE_VALUES[index % len(REVIEWER_CONFIDENCE_VALUES)]
        row["reviewer_reason_code"] = REVIEWER_REASON_CODES[index % len(REVIEWER_REASON_CODES)]
        row["reviewer_notes"] = "टीप" if unicode_notes else f"note-{index}"
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_build_judgment_cases_is_balanced_blinded_and_deterministic(tmp_path):
    _run_dir, _shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    first_dir = tmp_path / "judgment-a"
    second_dir = tmp_path / "judgment-b"

    first = build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=first_dir)
    second = build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=second_dir)

    assert first["record_count"] > 0
    assert set(first["language_counts"]) == {"ml", "mr", "ta"}
    csv_text = (first_dir / "judgment_cases.csv").read_text(encoding="utf-8")
    assert "v1_rank" not in csv_text
    assert "v2_rank" not in csv_text
    assert "v1_score" not in csv_text
    assert "v2_score" not in csv_text
    assert hashlib.sha256((first_dir / "judgment_cases.csv").read_bytes()).hexdigest() == hashlib.sha256((second_dir / "judgment_cases.csv").read_bytes()).hexdigest()
    assert hashlib.sha256((first_dir / "judgment_case_mapping.jsonl").read_bytes()).hexdigest() == hashlib.sha256((second_dir / "judgment_case_mapping.jsonl").read_bytes()).hexdigest()


def test_import_rejects_immutable_column_tampering(tmp_path):
    _run_dir, _shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    judgment_dir = tmp_path / "judgment"
    build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=judgment_dir)
    reviewed_csv = tmp_path / "reviewed.csv"
    fill_review_csv(judgment_dir / "judgment_cases.csv", reviewed_csv)

    with reviewed_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames
    assert fieldnames is not None
    rows[0]["language"] = "zz"
    with reviewed_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    try:
        import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "reviewed")
    except ValueError as exc:
        assert "immutable column mismatch" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_import_rejects_duplicate_case_and_formula_like_editable_cells(tmp_path):
    _run_dir, _shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    judgment_dir = tmp_path / "judgment"
    build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=judgment_dir)
    reviewed_csv = tmp_path / "reviewed.csv"
    fill_review_csv(judgment_dir / "judgment_cases.csv", reviewed_csv)

    with reviewed_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames
    assert fieldnames is not None
    rows[0]["reviewer_notes"] = "=bad"
    rows.append(dict(rows[0]))
    with reviewed_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    try:
        import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "reviewed")
    except ValueError as exc:
        assert "formula-like content rejected" in str(exc) or "duplicate judgment_case_id" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_import_preserves_unicode_and_emits_hashed_snapshot(tmp_path):
    _run_dir, _shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    judgment_dir = tmp_path / "judgment"
    build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=judgment_dir)
    reviewed_csv = tmp_path / "reviewed.csv"
    fill_review_csv(judgment_dir / "judgment_cases.csv", reviewed_csv, unicode_notes=True)

    result = import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "reviewed")

    assert result["summary"]["activation_eligible"] is False
    reviewed_text = (tmp_path / "reviewed" / "reviewed_judgments.jsonl").read_text(encoding="utf-8")
    assert "टीप" in reviewed_text
    assert (tmp_path / "reviewed" / "reviewed_judgment_summary.json").exists()
    assert (tmp_path / "reviewed" / "evaluation_manifest.json").exists()


def test_weight_grid_is_bounded_and_includes_control():
    configs = weight_grid()

    assert [config["config_id"] for config in configs][0] == "control"
    assert len(configs) == 5
    for config in configs:
        assert abs(sum(config["weights_dict"].values()) - 1.0) < 1e-9


def test_weight_evaluation_is_deterministic_and_offline(tmp_path):
    _run_dir, shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    judgment_dir = tmp_path / "judgment"
    build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=judgment_dir)
    reviewed_csv = tmp_path / "reviewed.csv"
    fill_review_csv(judgment_dir / "judgment_cases.csv", reviewed_csv)
    reviewed_dir = tmp_path / "reviewed"
    import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=reviewed_dir)

    first_dir = tmp_path / "weights-a"
    second_dir = tmp_path / "weights-b"
    first = evaluate_regional_weight_configurations(
        judgment_dir=judgment_dir,
        reviewed_dir=reviewed_dir,
        shadow_dir=shadow_dir,
        evaluation_dir=evaluation_dir,
        output_dir=first_dir,
    )
    second = evaluate_regional_weight_configurations(
        judgment_dir=judgment_dir,
        reviewed_dir=reviewed_dir,
        shadow_dir=shadow_dir,
        evaluation_dir=evaluation_dir,
        output_dir=second_dir,
    )

    assert first["recommendation"]["activation_eligible"] is False
    assert hashlib.sha256((first_dir / "weight_evaluation_summary.json").read_bytes()).hexdigest() == hashlib.sha256((second_dir / "weight_evaluation_summary.json").read_bytes()).hexdigest()
    assert hashlib.sha256((first_dir / "weight_evaluation_cases.jsonl").read_bytes()).hexdigest() == hashlib.sha256((second_dir / "weight_evaluation_cases.jsonl").read_bytes()).hexdigest()
    assert hashlib.sha256((first_dir / "language_weight_comparison.json").read_bytes()).hexdigest() == hashlib.sha256((second_dir / "language_weight_comparison.json").read_bytes()).hexdigest()
    assert hashlib.sha256((first_dir / "evaluation_recommendation.json").read_bytes()).hexdigest() == hashlib.sha256((second_dir / "evaluation_recommendation.json").read_bytes()).hexdigest()


def test_weight_evaluation_reports_insufficient_review_gate(tmp_path):
    _run_dir, shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    judgment_dir = tmp_path / "judgment"
    build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=judgment_dir)
    reviewed_csv = tmp_path / "reviewed.csv"

    with (judgment_dir / "judgment_cases.csv").open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)[:2]
        fieldnames = reader.fieldnames
    assert fieldnames is not None
    for row in rows:
        row["reviewer_preference"] = "A_HIGHER"
        row["reviewer_confidence"] = "HIGH"
        row["reviewer_reason_code"] = "EXECUTION_AND_CRAFT"
        row["reviewer_notes"] = "small"
    with reviewed_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    try:
        import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "reviewed")
    except ValueError as exc:
        assert "missing reviewed judgment_case_id values" in str(exc)
    else:
        raise AssertionError("expected ValueError before weight evaluation")

    fill_review_csv(judgment_dir / "judgment_cases.csv", reviewed_csv)
    with reviewed_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames
    assert fieldnames is not None
    rows = rows[:6]
    with reviewed_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    try:
        import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "reviewed-short")
    except ValueError as exc:
        assert "missing reviewed judgment_case_id values" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_review_snapshot_and_weight_eval_require_matching_artifacts(tmp_path):
    _run_dir, shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    judgment_dir = tmp_path / "judgment"
    build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=judgment_dir)
    reviewed_csv = tmp_path / "reviewed.csv"
    fill_review_csv(judgment_dir / "judgment_cases.csv", reviewed_csv)
    reviewed_dir = tmp_path / "reviewed"
    import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=reviewed_dir)

    summary_path = reviewed_dir / "reviewed_judgment_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["source_judgment_case_file_hash"] = "broken"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    try:
        evaluate_regional_weight_configurations(
            judgment_dir=judgment_dir,
            reviewed_dir=reviewed_dir,
            shadow_dir=shadow_dir,
            evaluation_dir=evaluation_dir,
            output_dir=tmp_path / "weights",
        )
    except ValueError as exc:
        assert "do not match the supplied judgment case file" in str(exc)
    else:
        raise AssertionError("expected ValueError")
