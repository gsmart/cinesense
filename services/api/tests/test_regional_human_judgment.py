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


def test_import_type_aware_immutable_columns(tmp_path):
    _run_dir, _shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    judgment_dir = tmp_path / "judgment"
    build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=judgment_dir)

    # 1. Base clean review file
    reviewed_csv = tmp_path / "reviewed.csv"
    fill_review_csv(judgment_dir / "judgment_cases.csv", reviewed_csv)

    # Let's verify clean import passes
    import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "reviewed_clean")

    # Helper to modify columns and attempt import
    def check_import_with_modified_column(col_name: str, new_val: str, expected_err: str = ""):
        reviewed_csv_mod = tmp_path / f"reviewed_mod_{col_name}.csv"
        with reviewed_csv.open("r", encoding="utf-8", newline="") as h:
            reader = csv.DictReader(h)
            rows = list(reader)
            fieldnames = reader.fieldnames
        rows[0][col_name] = new_val
        with reviewed_csv_mod.open("w", encoding="utf-8", newline="") as h:
            writer = csv.DictWriter(h, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        try:
            import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv_mod, output_dir=tmp_path / f"reviewed_out_{col_name}")
            return True
        except ValueError as exc:
            if expected_err:
                assert expected_err in str(exc), f"Expected {expected_err!r} in {str(exc)!r}"
            return False

    # A. Test nullable_integer behavior
    with reviewed_csv.open("r", encoding="utf-8") as h:
        orig_row = next(csv.DictReader(h))
    orig_year = orig_row["movie_a_release_year"]
    if orig_year:
        assert check_import_with_modified_column("movie_a_release_year", f"{orig_year}.0")
        assert not check_import_with_modified_column("movie_a_release_year", f"{int(orig_year) + 1}", "immutable column mismatch")
        assert not check_import_with_modified_column("movie_a_release_year", "2008.5", "invalid integer format")
        assert not check_import_with_modified_column("movie_a_release_year", "abc", "invalid integer format")
        assert not check_import_with_modified_column("movie_a_release_year", "2,008", "invalid integer format")
        assert not check_import_with_modified_column("movie_a_release_year", "2e3", "invalid integer format")
        assert not check_import_with_modified_column("movie_a_release_year", "True", "invalid integer format")
        assert not check_import_with_modified_column("movie_a_release_year", "0" if orig_year != "0" else "1", "immutable column mismatch")

    # B. Test nullable_decimal behavior
    orig_rating = orig_row["movie_a_tmdb_rating"]
    if orig_rating:
        assert check_import_with_modified_column("movie_a_tmdb_rating", f"{orig_rating}000")
        assert not check_import_with_modified_column("movie_a_tmdb_rating", f"{float(orig_rating) + 1.0}", "immutable column mismatch")
        assert not check_import_with_modified_column("movie_a_tmdb_rating", "abc", "invalid decimal format")
        assert not check_import_with_modified_column("movie_a_tmdb_rating", "True", "invalid decimal format")

    # C. Title change rejected
    orig_title = orig_row["movie_a_title"]
    assert not check_import_with_modified_column("movie_a_title", orig_title + " modified", "immutable column mismatch")
    # Harmless outer whitespace accepted for normalized_text
    assert check_import_with_modified_column("movie_a_title", "  " + orig_title + "  ")

    # D. Exact text and exact identifier change rejected
    assert not check_import_with_modified_column("language", orig_row["language"] + " ", "immutable column mismatch")
    assert not check_import_with_modified_column("movie_a_tmdb_id", orig_row["movie_a_tmdb_id"] + "1", "immutable column mismatch")
    assert not check_import_with_modified_column("judgment_case_id", orig_row["judgment_case_id"] + "1", "unknown judgment_case_id")

    # E. Warnings field tampering rejected
    orig_warnings = orig_row["evidence_warnings"]
    assert not check_import_with_modified_column("evidence_warnings", orig_warnings + "|some_new_warning", "immutable column mismatch")


def test_import_duplicate_columns_rejected(tmp_path):
    _run_dir, _shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    judgment_dir = tmp_path / "judgment"
    build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=judgment_dir)
    reviewed_csv = tmp_path / "reviewed.csv"
    fill_review_csv(judgment_dir / "judgment_cases.csv", reviewed_csv)

    content = reviewed_csv.read_text(encoding="utf-8")
    lines = content.splitlines()
    lines[0] = lines[0] + ",reviewer_notes"
    for i in range(1, len(lines)):
        lines[i] = lines[i] + ",duplicate_value"

    dup_csv = tmp_path / "dup.csv"
    dup_csv.write_text("\n".join(lines), encoding="utf-8")

    try:
        import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=dup_csv, output_dir=tmp_path / "reviewed_dup")
        raise AssertionError("Expected ValueError for duplicate columns")
    except ValueError as exc:
        assert "duplicate column detected" in str(exc)


def test_reviewer_notes_roundtrip_and_safety(tmp_path):
    _run_dir, _shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    judgment_dir = tmp_path / "judgment"
    build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=judgment_dir)
    reviewed_csv = tmp_path / "reviewed.csv"

    with (judgment_dir / "judgment_cases.csv").open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames
    assert fieldnames is not None

    rows[0]["reviewer_preference"] = "A_HIGHER"
    rows[0]["reviewer_confidence"] = "HIGH"
    rows[0]["reviewer_reason_code"] = "EXECUTION_AND_CRAFT"
    rows[0]["reviewer_notes"] = "This is a normal note."

    rows[1]["reviewer_preference"] = "B_HIGHER"
    rows[1]["reviewer_confidence"] = "MEDIUM"
    rows[1]["reviewer_reason_code"] = "CULTURAL_SIGNIFICANCE"
    rows[1]["reviewer_notes"] = "'- Stronger screenplay"

    rows[2]["reviewer_preference"] = "ROUGHLY_EQUAL"
    rows[2]["reviewer_confidence"] = "LOW"
    rows[2]["reviewer_reason_code"] = "AUDIENCE_RECEPTION"
    rows[2]["reviewer_notes"] = "- Benign note with dash"

    rows[3]["reviewer_preference"] = "CANNOT_JUDGE"
    rows[3]["reviewer_confidence"] = "HIGH"
    rows[3]["reviewer_reason_code"] = "NOT_COMPARABLE"
    rows[3]["reviewer_notes"] = "'=SUM(1,2)"

    rows[4]["reviewer_preference"] = "A_HIGHER"
    rows[4]["reviewer_confidence"] = "HIGH"
    rows[4]["reviewer_reason_code"] = "CULTURAL_SIGNIFICANCE"
    rows[4]["reviewer_notes"] = "मराठी टीप\nLine 2"

    for index in range(5, len(rows)):
        rows[index]["reviewer_preference"] = "ROUGHLY_EQUAL"
        rows[index]["reviewer_confidence"] = "MEDIUM"
        rows[index]["reviewer_reason_code"] = "OTHER"
        rows[index]["reviewer_notes"] = "Note"

    with reviewed_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    result = import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "reviewed")
    assert result["reviewed_count"] == len(rows)

    imported_rows = []
    with (tmp_path / "reviewed" / "reviewed_judgments.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                imported_rows.append(json.loads(line))

    imported_by_id = {row["judgment_case_id"]: row for row in imported_rows}

    assert imported_by_id[rows[0]["judgment_case_id"]]["reviewer_notes"] == "This is a normal note."
    assert imported_by_id[rows[1]["judgment_case_id"]]["reviewer_notes"] == "- Stronger screenplay"
    assert imported_by_id[rows[2]["judgment_case_id"]]["reviewer_notes"] == "- Benign note with dash"
    assert imported_by_id[rows[3]["judgment_case_id"]]["reviewer_notes"] == "=SUM(1,2)"
    assert imported_by_id[rows[4]["judgment_case_id"]]["reviewer_notes"] == "मराठी टीप\nLine 2"

    rows[0]["reviewer_notes"] = "=1+2"
    with reviewed_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    try:
        import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "reviewed_dangerous")
        raise AssertionError("Expected ValueError for dangerous formula note")
    except ValueError as exc:
        assert "must be escaped with a leading apostrophe" in str(exc)


def test_decimal_strict_parsing_and_handling():
    from app.regional_human_judgment import parse_decimal_strict, parse_int_strict
    from decimal import Decimal

    # NaN / Infinity / -Infinity
    for val in ("nan", "NaN", "NAN", "inf", "Infinity", "-inf", "-Infinity"):
        try:
            parse_decimal_strict(val)
            raise AssertionError(f"Expected ValueError for NaN/Infinity: {val}")
        except ValueError:
            pass

    # Scientific notation
    for val in ("1e3", "1E-3", "2e0", "2.5e2"):
        try:
            parse_decimal_strict(val)
            raise AssertionError(f"Expected ValueError for scientific notation: {val}")
        except ValueError:
            pass

    # Comma-formatted
    for val in ("2,008", "7,500.0", "123,456"):
        try:
            parse_decimal_strict(val)
            raise AssertionError(f"Expected ValueError for commas: {val}")
        except ValueError:
            pass

    # Boolean values
    for val in ("True", "False", "true", "false", "TRUE", "FALSE"):
        try:
            parse_decimal_strict(val)
            raise AssertionError(f"Expected ValueError for booleans: {val}")
        except ValueError:
            pass

    # Whitespace/Signs inside
    for val in ("- 2008", "+-2008", "--2008", "+ 2008"):
        try:
            parse_decimal_strict(val)
            raise AssertionError(f"Expected ValueError for internal spaces/signs: {val}")
        except ValueError:
            pass

    # Decimal Trailing Zeros
    d1 = parse_decimal_strict("7.5000")
    d2 = parse_decimal_strict("7.5")
    assert d1 == d2
    assert d1 == Decimal("7.5")

    # Long decimal precision
    d3 = parse_decimal_strict("0.12345678901234567890")
    assert d3 == Decimal("0.12345678901234567890")

    # Large integer precision
    d4 = parse_int_strict("12345678901234567890")
    assert d4 == 12345678901234567890

    # Integer represented with trailing zeros
    d5 = parse_int_strict("2008.000")
    assert d5 == 2008

    # 2008.5 is rejected as integer
    try:
        parse_int_strict("2008.5")
        raise AssertionError("Expected ValueError for 2008.5 as integer")
    except ValueError:
        pass

    # Negative zero behavior
    d6 = parse_decimal_strict("-0")
    d7 = parse_decimal_strict("0")
    d8 = parse_decimal_strict("-0.00")
    d9 = parse_decimal_strict("0.0")
    assert d6 == d7
    assert d8 == d9
    assert d6 == d8
    assert parse_int_strict("-0") == 0
    assert parse_int_strict("-0.00") == 0


def test_structured_warning_canonicalization_strict(tmp_path):
    _run_dir, _shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    judgment_dir = tmp_path / "judgment"
    build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=judgment_dir)
    reviewed_csv = tmp_path / "reviewed.csv"
    fill_review_csv(judgment_dir / "judgment_cases.csv", reviewed_csv)

    def check_warnings(warnings_val, expected_err=""):
        reviewed_csv_mod = tmp_path / "reviewed_mod_warn.csv"
        with reviewed_csv.open("r", encoding="utf-8", newline="") as h:
            reader = csv.DictReader(h)
            rows = list(reader)
            fieldnames = reader.fieldnames
        rows[0]["evidence_warnings"] = warnings_val
        with reviewed_csv_mod.open("w", encoding="utf-8", newline="") as h:
            writer = csv.DictWriter(h, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        try:
            import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv_mod, output_dir=tmp_path / "reviewed_out_warn")
            return True
        except ValueError as exc:
            if expected_err:
                assert expected_err in str(exc)
            return False

    with reviewed_csv.open("r", encoding="utf-8") as h:
        orig_row = next(csv.DictReader(h))
    orig_warnings = orig_row["evidence_warnings"]

    # Duplicate warning tokens rejected
    assert not check_warnings("WARN|WARN", "duplicate warning tokens detected")

    # Blank warning tokens rejected
    assert not check_warnings("WARN||OTHER", "blank warning token detected")
    assert not check_warnings("|", "blank warning token detected")
    assert not check_warnings("WARN|", "blank warning token detected")

    # Changed casing rejected
    assert not check_warnings("missing_aliases" if "MISSING_ALIASES" in orig_warnings else "MISSING_ALIASES".lower(), "immutable column mismatch")

    # Whitespace inside warning identifiers rejected
    assert not check_warnings("MISSING ALIASES", "whitespace inside warning identifiers detected")
    assert not check_warnings("MISSING\tALIASES", "whitespace inside warning identifiers detected")


def test_note_escaping_unambiguous(tmp_path):
    _run_dir, _shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    judgment_dir = tmp_path / "judgment"
    build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=judgment_dir)
    reviewed_csv = tmp_path / "reviewed.csv"

    with (judgment_dir / "judgment_cases.csv").open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames

    rows[0]["reviewer_preference"] = "A_HIGHER"
    rows[0]["reviewer_confidence"] = "HIGH"
    rows[0]["reviewer_reason_code"] = "EXECUTION_AND_CRAFT"
    # Literal apostrophe note that does NOT start with a formula prefix
    rows[0]["reviewer_notes"] = "'This is a literal quote"

    # Escaped note that starts with formula prefix but we do not repeatedly strip apostrophes
    rows[1]["reviewer_preference"] = "B_HIGHER"
    rows[1]["reviewer_confidence"] = "MEDIUM"
    rows[1]["reviewer_reason_code"] = "CULTURAL_SIGNIFICANCE"
    rows[1]["reviewer_notes"] = "''- Escaped twice"

    for index in range(2, len(rows)):
        rows[index]["reviewer_preference"] = "ROUGHLY_EQUAL"
        rows[index]["reviewer_confidence"] = "MEDIUM"
        rows[index]["reviewer_reason_code"] = "OTHER"
        rows[index]["reviewer_notes"] = "Note"

    with reviewed_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    result = import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "reviewed")
    assert result["reviewed_count"] == len(rows)

    imported_rows = []
    with (tmp_path / "reviewed" / "reviewed_judgments.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                imported_rows.append(json.loads(line))

    imported_by_id = {row["judgment_case_id"]: row for row in imported_rows}

    # Assert literal quote note is not altered
    assert imported_by_id[rows[0]["judgment_case_id"]]["reviewer_notes"] == "'This is a literal quote"
    # Assert double escape removes only exactly one apostrophe
    assert imported_by_id[rows[1]["judgment_case_id"]]["reviewer_notes"] == "'- Escaped twice"


def test_complete_manual_smoke_verification_demonstration(tmp_path):
    _run_dir, _shadow_dir, evaluation_dir = build_evaluation_fixture(tmp_path)
    judgment_dir = tmp_path / "judgment"
    build_regional_judgment_cases(evaluation_dir=evaluation_dir, output_dir=judgment_dir)
    reviewed_csv = tmp_path / "reviewed.csv"
    fill_review_csv(judgment_dir / "judgment_cases.csv", reviewed_csv)

    def load_rows():
        with reviewed_csv.open("r", encoding="utf-8", newline="") as h:
            reader = csv.DictReader(h)
            return list(reader), reader.fieldnames

    def save_rows(rows, fieldnames):
        with reviewed_csv.open("w", encoding="utf-8", newline="") as h:
            writer = csv.DictWriter(h, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    clean_rows, fieldnames = load_rows()

    # 1. 2008 to 2008.0 imports successfully
    rows = [dict(r) for r in clean_rows]
    orig_year = rows[0]["movie_a_release_year"]
    rows[0]["movie_a_release_year"] = f"{orig_year}.0"
    save_rows(rows, fieldnames)
    import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "out_1")

    # 2. 2008 to 2009 fails
    rows = [dict(r) for r in clean_rows]
    rows[0]["movie_a_release_year"] = "2009"
    save_rows(rows, fieldnames)
    try:
        import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "out_2")
        raise AssertionError("expected failure for year mismatch")
    except ValueError as exc:
        assert "immutable column mismatch" in str(exc)

    # 3. 7.5 to 7.500 imports successfully
    rows = [dict(r) for r in clean_rows]
    orig_rating = rows[0]["movie_a_tmdb_rating"]
    rows[0]["movie_a_tmdb_rating"] = f"{orig_rating}00"
    save_rows(rows, fieldnames)
    import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "out_3")

    # 4. null to zero fails
    from app.regional_human_judgment import _compare_immutable_field
    try:
        _compare_immutable_field("case_1", "movie_a_release_year", "0", "")
        raise AssertionError("expected null to zero to fail")
    except ValueError as exc:
        assert "immutable column mismatch" in str(exc)

    try:
        _compare_immutable_field("case_1", "movie_a_release_year", "", "0")
        raise AssertionError("expected zero to null to fail")
    except ValueError as exc:
        assert "immutable column mismatch" in str(exc)

    # 5. dash-prefixed note round-trips
    rows = [dict(r) for r in clean_rows]
    rows[0]["reviewer_preference"] = "A_HIGHER"
    rows[0]["reviewer_confidence"] = "HIGH"
    rows[0]["reviewer_reason_code"] = "EXECUTION_AND_CRAFT"
    rows[0]["reviewer_notes"] = "- Benign dash-prefixed note"
    save_rows(rows, fieldnames)
    import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "out_5")

    # 6. formula-like unescaped note fails
    rows = [dict(r) for r in clean_rows]
    rows[0]["reviewer_notes"] = "=1+2"
    save_rows(rows, fieldnames)
    try:
        import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "out_6")
        raise AssertionError("expected unescaped formula to fail")
    except ValueError as exc:
        assert "must be escaped with a leading apostrophe" in str(exc)

    # 7. safely escaped formula-like note imports as human-readable text
    rows = [dict(r) for r in clean_rows]
    rows[0]["reviewer_preference"] = "A_HIGHER"
    rows[0]["reviewer_confidence"] = "HIGH"
    rows[0]["reviewer_reason_code"] = "EXECUTION_AND_CRAFT"
    rows[0]["reviewer_notes"] = "'=1+2"
    save_rows(rows, fieldnames)
    import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "out_7")
    imported_rows = []
    with (tmp_path / "out_7" / "reviewed_judgments.jsonl").open("r", encoding="utf-8") as h:
        for line in h:
            if line.strip():
                imported_rows.append(json.loads(line))
    assert imported_rows[0]["reviewer_notes"] == "=1+2"

    # 8. repeated processing produces identical reviewed snapshot hashes
    res_a = import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "out_8a")
    res_b = import_reviewed_regional_judgments(judgment_dir=judgment_dir, reviewed_csv_path=reviewed_csv, output_dir=tmp_path / "out_8b")
    assert res_a["output_hashes"]["reviewed_judgments.jsonl"] == res_b["output_hashes"]["reviewed_judgments.jsonl"]


def test_improved_benchmarks_generator_policies(tmp_path):
    from app.regional_human_judgment import _build_case_rows, JudgmentCaseBuilderConfig

    mock_cases = [
        {"tmdb_movie_id": "1", "title": "Movie 1", "language": "ml", "entity_status": "VALIDATED_EXACT_MATCH", "release_year": 2020, "v1_score": 7.0, "v2_rank": 1, "v1_rank": 2, "v2_score": 8.0, "rank_delta": 1, "warnings": [], "quality_group": "high", "reach_group": "low", "selected_cohort_level": "level_1"},
        {"tmdb_movie_id": "2", "title": "Movie 2", "language": "ml", "entity_status": "VALIDATED_EXACT_MATCH", "release_year": 2021, "v1_score": 7.5, "v2_rank": 2, "v1_rank": 3, "v2_score": 8.5, "rank_delta": 1, "warnings": [], "quality_group": "high", "reach_group": "low", "selected_cohort_level": "level_1"},
        {"tmdb_movie_id": "3", "title": "Movie 3", "language": "ml", "entity_status": "VALIDATED_EXACT_MATCH", "release_year": 2022, "v1_score": 8.0, "v2_rank": 3, "v1_rank": 4, "v2_score": 9.0, "rank_delta": 1, "warnings": [], "quality_group": "high", "reach_group": "low", "selected_cohort_level": "level_1"},
        {"tmdb_movie_id": "4", "title": "Movie 4", "language": "ml", "entity_status": "VALIDATED_EXACT_MATCH", "release_year": 2023, "v1_score": 8.5, "v2_rank": 4, "v1_rank": 5, "v2_score": 9.5, "rank_delta": 1, "warnings": [], "quality_group": "high", "reach_group": "low", "selected_cohort_level": "level_1"},

        # Future-release exclusions (should be excluded as release_year > 2026)
        {"tmdb_movie_id": "5", "title": "Future Movie", "language": "ml", "entity_status": "VALIDATED_EXACT_MATCH", "release_year": 2027, "v1_score": 8.0, "v2_rank": 5, "v1_rank": 6, "v2_score": 9.0, "rank_delta": 1, "warnings": [], "quality_group": "high", "reach_group": "low", "selected_cohort_level": "level_1"},

        # Ambiguous identity status (should be excluded)
        {"tmdb_movie_id": "6", "title": "Ambiguous Movie", "language": "ml", "entity_status": "AMBIGUOUS_REVIEW_REQUIRED", "release_year": 2022, "v1_score": 8.0, "v2_rank": 6, "v1_rank": 7, "v2_score": 9.0, "rank_delta": 1, "warnings": [], "quality_group": "high", "reach_group": "low", "selected_cohort_level": "level_1"},

        # Critical warning exclusion (should be excluded)
        {"tmdb_movie_id": "7", "title": "Critical Warning Movie", "language": "ml", "entity_status": "EXACT_MATCH_WITH_WARNINGS", "release_year": 2022, "v1_score": 8.0, "v2_rank": 7, "v1_rank": 8, "v2_score": 9.0, "rank_delta": 1, "warnings": ["YEAR_CONFLICT"], "quality_group": "high", "reach_group": "low", "selected_cohort_level": "level_1"},

        # TE cases (another language to check balanced sample)
        {"tmdb_movie_id": "11", "title": "Movie 11", "language": "te", "entity_status": "VALIDATED_EXACT_MATCH", "release_year": 2020, "v1_score": 7.0, "v2_rank": 1, "v1_rank": 2, "v2_score": 8.0, "rank_delta": 1, "warnings": [], "quality_group": "high", "reach_group": "low", "selected_cohort_level": "level_1"},
        {"tmdb_movie_id": "12", "title": "Movie 12", "language": "te", "entity_status": "VALIDATED_EXACT_MATCH", "release_year": 2021, "v1_score": 7.5, "v2_rank": 2, "v1_rank": 3, "v2_score": 8.5, "rank_delta": 1, "warnings": [], "quality_group": "high", "reach_group": "low", "selected_cohort_level": "level_1"},
    ]

    mock_context = {
        "cases": mock_cases,
        "source_paths": {
            "run_dir": str(tmp_path / "run_dir")
        }
    }

    run_dir = tmp_path / "run_dir"
    run_dir.mkdir(parents=True, exist_ok=True)
    movies_jsonl = run_dir / "movies.jsonl"

    movie_records = [
        {"source_record_id": "1", "release_date": "2020-01-01"},
        {"source_record_id": "2", "release_date": "2021-01-01"},
        {"source_record_id": "3", "release_date": "2022-01-01"},
        {"source_record_id": "4", "release_date": "2026-01-01"},  # Retained recent release
        {"source_record_id": "5", "release_date": "2027-01-01"},
        {"source_record_id": "11", "release_date": "2020-01-01"},
        {"source_record_id": "12", "release_date": "2020-01-01"},
    ]
    with movies_jsonl.open("w", encoding="utf-8") as f:
        for rec in movie_records:
            f.write(json.dumps(rec) + "\n")

    config = JudgmentCaseBuilderConfig(
        cases_per_language=5,
        max_total_cases=10,
    )

    blinded_rows, mapping_rows = _build_case_rows(context=mock_context, config=config)

    selected_ids = set()
    for row in blinded_rows:
        selected_ids.add(row["movie_a_tmdb_id"])
        selected_ids.add(row["movie_b_tmdb_id"])

    assert "5" not in selected_ids
    assert "6" not in selected_ids
    assert "7" not in selected_ids
    assert "4" in selected_ids

    pairs = []
    for row in blinded_rows:
        p = tuple(sorted((row["movie_a_tmdb_id"], row["movie_b_tmdb_id"])))
        pairs.append(p)
    assert len(pairs) == len(set(pairs))

    for row in blinded_rows:
        assert "v1_rank" not in row
        assert "v2_rank" not in row
        assert "v1_score" not in row
        assert "v2_score" not in row
        assert "rank_delta" not in row

    for m_row in mapping_rows:
        assert isinstance(m_row["selection_reasons"], list)
        assert len(m_row["selection_reasons"]) > 0

    blinded_rows2, mapping_rows2 = _build_case_rows(context=mock_context, config=config)
    assert blinded_rows == blinded_rows2
    assert mapping_rows == mapping_rows2

    te_cases = [r for r in blinded_rows if r["language"] == "te"]
    assert len(te_cases) == 1
