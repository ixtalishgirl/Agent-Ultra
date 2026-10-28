"""Head agent.

The head collects copy reports and runs Arena-style elimination:
copies are ranked, the bottom half drops each round, until one
remains (100 -> 50 -> 25 -> 13 -> 7 -> 4 -> 2 -> 1 in Arena).

HONEST LIMIT: ranking here is MECHANICAL only — it scores report
facts (status ok, evidence present). It is NOT quality judging: a
model judging solution quality is UNTESTED and needs owner-approved
criteria first. No prompt content is used anywhere in this module.
"""

from .report_protocol import read_reports


def mechanical_score(report):
    score = 10 if report.get("status") == "ok" else 0
    score += min(len(report.get("evidence") or []), 5)
    return score


class HeadAgent:
    def __init__(self, log_path):
        self.log_path = log_path

    def collect(self):
        return read_reports(self.log_path)

    def rank(self, reports):
        return sorted(reports, key=mechanical_score, reverse=True)

    def eliminate_round(self, reports):
        """One Arena-style round: keep the top half (min 1)."""
        ranked = self.rank(reports)
        keep = max(1, len(ranked) // 2) if len(ranked) > 1 else 1
        return ranked[:keep]

    def run_bracket(self, reports):
        """Full bracket. Returns (rounds, winner_or_None)."""
        rounds = []
        current = list(reports)
        while len(current) > 1:
            current = self.eliminate_round(current)
            rounds.append([r["copy_id"] for r in current])
        winner = current[0] if current else None
        return rounds, winner
