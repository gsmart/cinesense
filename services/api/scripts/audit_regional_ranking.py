from app.core.regional_ranking_audit import order_results_within_groups, run_regional_ranking_audit


def main() -> None:
    grouped = order_results_within_groups(run_regional_ranking_audit())
    for group_id, results in grouped.items():
        print(f"\n[{group_id}]")
        print("case | language/category | audience | evidence | popularity | critic | coverage | total | order")
        for position, result in enumerate(results, start=1):
            components = result.components
            print(
                " | ".join(
                    [
                        result.case.display_label,
                        result.case.language_or_category,
                        str(components["audience_reception"]),
                        str(components["evidence_confidence"]),
                        str(components["popularity"]),
                        result.critic_state,
                        str(components["data_coverage"]),
                        str(result.total),
                        str(position),
                    ]
                )
            )


if __name__ == "__main__":
    main()
