"""
sensitivity_analysis.py — Profile differentiation / sensitivity analysis.

Measures how differently the 4 playing-style profiles rank players. If profiles
are too similar, the Spearman rank correlation between their player impact
scores will be ~1.0 (bad). Good differentiation -> lower correlations and
different Top-N lists.

Usage:
    python sensitivity_analysis.py            # prints summary, writes JSON
    python sensitivity_analysis.py --tag v1   # tags the saved JSON snapshot

The script always derives profile weights from metrics.build_profile_weights()
so it reflects the CURRENT state of metrics.py (no DB profile staleness).
Player stats are read from the seeded SQLite DB.
"""

import argparse
import itertools
import json
import os

from scipy.stats import spearmanr

import database as db
import impact_engine as IE
import metrics as M

PROFILES = list(M.DEFAULT_PROFILES.keys())
SNAP_DIR = os.path.dirname(os.path.abspath(__file__))


def profile_weight_map():
    """{profile_name: {metric_key: weight}} from metrics.py."""
    out = {}
    for name in PROFILES:
        out[name] = {k: w for (k, w, _c) in M.build_profile_weights(name)}
    return out


def match_impact_table(conn, match_id, weights_by_profile):
    """Return {profile: {player_name: total_impact}} for one match."""
    player_stats = db.get_match_player_stats(conn, match_id)
    table = {p: {} for p in weights_by_profile}
    for prof, w in weights_by_profile.items():
        rows = IE.compute_player_match_rows(player_stats, w)
        for r in rows:
            table[prof][r["player_name"]] = r["impact"]["total_impact"]
    return table


def ranked(impact_dict):
    """player->impact dict to ordered list of (player, impact) desc."""
    return sorted(impact_dict.items(), key=lambda kv: kv[1], reverse=True)


def pairwise_correlations(impact_table):
    """Spearman rank correlation between each profile pair for one match."""
    players = sorted({pl for d in impact_table.values() for pl in d})
    vectors = {
        prof: [impact_table[prof].get(pl, 0.0) for pl in players]
        for prof in impact_table
    }
    corrs = {}
    for a, b in itertools.combinations(impact_table.keys(), 2):
        if len(players) < 2:
            rho = float("nan")
        else:
            rho, _ = spearmanr(vectors[a], vectors[b])
        corrs[f"{a} vs {b}"] = None if rho != rho else round(float(rho), 3)
    return corrs


def topn_overlap(table_a, table_b, n=5):
    """Fraction of shared players in the Top-N of two profiles."""
    top_a = {p for p, _ in ranked(table_a)[:n]}
    top_b = {p for p, _ in ranked(table_b)[:n]}
    if not top_a:
        return 0.0
    return round(len(top_a & top_b) / len(top_a), 3)


def run_analysis():
    conn = db.get_connection()
    matches = db.list_matches(conn)
    weights = profile_weight_map()

    results = {"matches": [], "profiles": PROFILES}
    all_pair_corrs = {f"{a} vs {b}": []
                      for a, b in itertools.combinations(PROFILES, 2)}
    all_top5_overlap = {f"{a} vs {b}": []
                        for a, b in itertools.combinations(PROFILES, 2)}

    for m in matches:
        table = match_impact_table(conn, m["id"], weights)
        corrs = pairwise_correlations(table)
        for k, v in corrs.items():
            if v is not None:
                all_pair_corrs[k].append(v)

        overlaps = {}
        for a, b in itertools.combinations(PROFILES, 2):
            ov = topn_overlap(table[a], table[b], 5)
            overlaps[f"{a} vs {b}"] = ov
            all_top5_overlap[f"{a} vs {b}"].append(ov)

        rankings = {prof: ranked(table[prof]) for prof in PROFILES}
        results["matches"].append({
            "match_id": m["id"],
            "label": f"{m['team_name']} vs {m['opponent']}",
            "date": m["match_date"],
            "opponent": m["opponent"],
            "score": f"{m['home_score']} : {m['away_score']}",
            "correlations": corrs,
            "top5_overlap": overlaps,
            "rankings": {p: [(name, round(val, 2)) for name, val in r]
                         for p, r in rankings.items()},
        })

    def _avg(lst):
        vals = [x for x in lst if x is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    results["avg_correlations"] = {k: _avg(v) for k, v in all_pair_corrs.items()}
    overall = [x for v in all_pair_corrs.values() for x in v]
    results["overall_avg_correlation"] = round(sum(overall) / len(overall), 3) if overall else None
    results["avg_top5_overlap"] = {k: _avg(v) for k, v in all_top5_overlap.items()}
    ov_all = [x for v in all_top5_overlap.values() for x in v]
    results["overall_avg_top5_overlap"] = round(sum(ov_all) / len(ov_all), 3) if ov_all else None
    return results


def print_summary(results):
    print("=" * 70)
    print("PROFILE SENSITIVITY ANALYSIS")
    print("=" * 70)
    print(f"Matches analysed: {len(results['matches'])}")
    print(f"\nOverall avg pairwise Spearman correlation: "
          f"{results['overall_avg_correlation']}")
    print(f"Overall avg Top-5 overlap: {results['overall_avg_top5_overlap']}")
    print("\nAverage correlation per profile pair:")
    for k, v in results["avg_correlations"].items():
        print(f"  {k:<48} rho={v}")
    print("\nPer-match Top-3 by profile:")
    for m in results["matches"]:
        print(f"\n  {m['date']}  vs {m['opponent']}  ({m['score']})")
        for prof in results["profiles"]:
            top3 = ", ".join(f"{i+1}.{name}" for i, (name, _v)
                             in enumerate(m["rankings"][prof][:3]))
            print(f"    {prof:<24} {top3}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="current", help="snapshot tag (e.g. v1, v2)")
    args = ap.parse_args()
    results = run_analysis()
    results["tag"] = args.tag
    print_summary(results)
    out = os.path.join(SNAP_DIR, f"sensitivity_{args.tag}.json")
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSnapshot written: {out}")


if __name__ == "__main__":
    main()
