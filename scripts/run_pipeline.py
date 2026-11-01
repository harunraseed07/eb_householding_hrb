"""Run the full pipeline locally and print what came out.

    python scripts/run_pipeline.py                 # build everything
    python scripts/run_pipeline.py --reset         # clear data first
    python scripts/run_pipeline.py --rule NAME_AND_ADDRESS

This writes parquet into ./data and is the only step needed before
`streamlit run app/app.py`.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, evaluate, pipeline              # noqa: E402
from src.datastore import LocalStore                    # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Eastern Bank householding POC pipeline")
    parser.add_argument("--reset", action="store_true", help="delete existing parquet first")
    parser.add_argument("--seed", type=int, default=config.DATA_SPEC.seed)
    parser.add_argument("--identities", type=int, default=config.DATA_SPEC.n_identities)
    parser.add_argument("--rule", default=config.HOUSEHOLD_RULE,
                        choices=["ADDRESS_ONLY", "NAME_AND_ADDRESS"])
    parser.add_argument("--auto", type=float, default=config.AUTO_MATCH_THRESHOLD)
    parser.add_argument("--review", type=float, default=config.REVIEW_THRESHOLD)
    args = parser.parse_args()

    store = LocalStore()
    if args.reset:
        store.reset_dir()
        print("Cleared", store.data_dir)

    spec = config.DataSpec(**{
        **config.DATA_SPEC.as_dict(),
        "seed": args.seed,
        "n_identities": args.identities,
    })

    started = time.time()
    print("\n== Stage 0: generate Bronze ==")
    for name, count in pipeline.generate_bronze(store, spec).items():
        print(f"   {name:34s} {count:>7,}")

    print("\n== Stage 1: standardize and score ==")
    for name, count in pipeline.standardize_and_score(
        store, auto_threshold=args.auto, review_threshold=args.review
    ).items():
        print(f"   {name:34s} {count:>7,}")

    print("\n== Stage 2: resolve, household, publish Gold ==")
    for name, count in pipeline.apply_decisions_and_publish(store, rule=args.rule).items():
        print(f"   {name:34s} {count:>7,}")

    # ---- accuracy, the panel the client will ask about ----
    truth = store.read("ground_truth_identity")
    party_map = store.read("bridge_party_source_record")
    candidates = store.read("match_candidate")
    bridge = store.read("bridge_household_party")

    print("\n== Match quality vs synthetic ground truth ==")
    for name, value in evaluate.evaluate_matching(party_map, truth, candidates).items():
        print(f"   {name:34s} {value}")
    print("\n== Household quality ==")
    for name, value in evaluate.evaluate_households(bridge, party_map, truth).items():
        print(f"   {name:34s} {value}")

    summary = store.read("fact_household_summary")
    print("\n== Business value ==")
    print(f"   households                         {len(summary):>7,}")
    print(f"   cross-sell flagged                 {int(summary['cross_sell_flag'].sum()):>7,}")
    print(f"   cross-sell value          ${summary['cross_sell_opportunity_value'].sum():>14,.0f}")
    print(f"   total deposits            ${summary['deposit_balance'].sum():>14,.0f}")

    print(f"\nDone in {time.time() - started:.1f}s. Data in {store.data_dir}")
    print("Next: streamlit run app/app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
