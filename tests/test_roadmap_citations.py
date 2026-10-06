"""The shared citation rule (``vibetracks.roadmap.citations``) against ``citation_corpus.json`` and its own cases.

Codex audits A02/A10/B03/B13: the page, the API and ``bam_roadmap`` cite by one token rule; the corpus is its cases.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from vibetracks.roadmap.citations import cited_paths, cited_tokens, load_corpus

#: The kinsim dashboard's corpus, the rule's origin: this package's copy must be it, byte for byte, when it is there.
SOURCE_CORPUS = Path("/home/bam/bam_ws/.claude/worktrees/roadmap-dashboard-api/src/dev/bam_kinsim_dashboard"
                     "/tests/api/citation_corpus.json")
PACKAGE_CORPUS = Path(__file__).resolve().parents[1] / "vibetracks" / "roadmap" / "citation_corpus.json"


class CitedPathsTest(unittest.TestCase):
    def test_cited_paths_are_the_absolute_text_paths_written_in_the_texts(self):
        texts = [
            "test_kinematic_pick_run_log.py: 12 passed (/r/report-verify/acc_l2_producer.log)",
            "(/a/x.log, /a/y.jsonl); see /a/z.md.",
            "relative tests/test_q.py and http://h/u.json",
            "a dir /a/dir/ and an archive /a/log.json.gz and '/a/q.yaml'",
        ]
        self.assertEqual(cited_paths(texts), frozenset({
            "/r/report-verify/acc_l2_producer.log", "/a/x.log", "/a/y.jsonl", "/a/z.md", "/a/q.yaml"}))

    def test_a_citation_is_one_whitespace_token_by_the_shared_rule(self):
        """Codex audit A02/A10: the API and the page cite by the same token rule (``cited_paths``' docstring)."""

        cases = [
            ("rows in /a/runs.jsonl", {"/a/runs.jsonl"}),                       # .jsonl is itself, never cut to .json
            ("an archive /a/b.json.gz", set()),                                # a text suffix must end the path
            ("see /a/x.py:188", {"/a/x.py"}),                                  # :LINE is a line reference, not the path
            ("see /a/x.py:12:3.", {"/a/x.py"}),                                # :LINE:COL too, before a sentence's end
            ("https://example.test/?next=/a/secret.json", set()),              # a path must be a whole token
            ("logs (/a/log.txt), then", {"/a/log.txt"}),                       # the wrapping punctuation is stripped
            ("relative tests/test_x.py", set()),                               # must start with /
            ("/a/../b.txt and /a/./c.txt", set()),                             # a `..` or `.` segment is never cited
            ("[`/a/q.yaml`] <'/a/r.md'>", {"/a/q.yaml", "/a/r.md"}),           # leading and trailing sets, repeatedly
            ("/a/x.py:", {"/a/x.py"}),                                         # a bare trailing colon is punctuation
            ("/a/x.py:L12 /a/y.log:1:2:3", set()),                             # anything else after the suffix: no match
            ("/a/dir with space/z.log", set()),                                # residual: a path with a space is uncitable
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(cited_paths([text]), expected)

    def test_a_stray_closing_quote_is_not_a_citation(self):
        """Codex audit B03: a quote closed with none opened is stray, and a token with a stray quote cites nothing.
        The shared corpus never reaches this alone (its stray cases also leave a quote open), so it is pinned here."""

        for text, expected in (('/a/x.log"', set()), ("/a/x.log'", set()), ("/a/x.log` and /a/y.log", {"/a/y.log"})):
            with self.subTest(text=text):
                self.assertEqual(cited_paths([text]), expected)

    def test_quotes_never_span_two_texts(self):
        self.assertEqual(cited_paths(['"/a/x.log', "/a/y.log"]), frozenset({"/a/y.log"}))


class CorpusTest(unittest.TestCase):
    def test_the_shared_citation_corpus(self):
        """Codex audits B03/B13: the page, the API and bam_roadmap run this one corpus; here, the allowlist side."""

        corpus = load_corpus()
        self.assertTrue(corpus["cases"])
        for case in corpus["cases"]:
            with self.subTest(case=case["why"][:60]):
                self.assertEqual(cited_paths([case["text"]]), frozenset(case["cited"]))
                lines: dict[str, int | None] = {}
                for path, line in cited_tokens(case["text"]):
                    lines.setdefault(path, line)
                self.assertEqual({path: line for path, line in lines.items() if line is not None}, case["lines"])

    @unittest.skipUnless(SOURCE_CORPUS.exists(), "the kinsim dashboard's corpus is not on this machine")
    def test_the_corpus_file_is_byte_identical_to_the_dashboards(self):
        self.assertEqual(PACKAGE_CORPUS.read_bytes(), SOURCE_CORPUS.read_bytes())


if __name__ == "__main__":
    unittest.main()
