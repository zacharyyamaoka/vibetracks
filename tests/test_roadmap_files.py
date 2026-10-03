"""Evidence and art file serving (``vibetracks.roadmap.files``), each against real files in a temporary directory.

``read_evidence`` serves only the files its allowlist cites, verbatim, as regular files read without following a
symlink; ``read_art`` and ``art_entries`` serve only lowercase ``.png`` regular files inside the art directory.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from vibetracks.roadmap import files
from vibetracks.roadmap.citations import cited_paths
from vibetracks.roadmap.files import (
    ART_READ_LIMIT,
    EVIDENCE_CONTEXT_LINES,
    EVIDENCE_READ_LIMIT,
    RoadmapForbidden,
    RoadmapNotFound,
    art_entries,
    evidence_snapshot,
    evidence_text,
    evidence_window,
    line_count,
    open_without_symlinks,
    read_art,
    read_evidence,
)

#: The smallest valid PNG header: what is served is compared byte for byte, so any bytes would do.
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(64))


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # realpath: the cited spelling must be the file's own, and the temp dir may sit under a symlinked directory.
        self.tmp = Path(os.path.realpath(temporary.name))


class EvidenceTestCase(TempDirTestCase):
    def setUp(self):
        super().setUp()
        root = self.tmp / "evidence"
        root.mkdir()
        self.cited = {
            "log": root / "acc_b1_log_v2.log",
            "test": root / "test_scorecard_acceptance.py",
            "second": root / "acc_l1_loop_tools.log",
            "directory": root / "a_directory.log",
            "missing": root / "never_written.log",
            "big": root / "big.log",
            "target": root / "target.txt",
            "link": root / "link.txt",
        }
        files_ = self.cited
        files_["log"].write_text("82 passed\nall green\n", encoding="utf-8")
        files_["test"].write_text("def test_x():\n    assert True", encoding="utf-8")
        files_["second"].write_text("10 passed\n", encoding="utf-8")
        files_["directory"].mkdir()
        files_["target"].write_text("the link's target\n", encoding="utf-8")
        files_["link"].symlink_to(files_["target"])
        self.texts = [
            f"bam_eval -m acceptance: 82 passed ({files_['log']})",
            f"two logs ({files_['test']}, {files_['second']}); a dir {files_['directory']}.",
            f"missing '{files_['missing']}'; big \"{files_['big']}\"; target {files_['target']}; link {files_['link']}",
        ]

    def allowlist(self, *extra: str) -> frozenset[str]:
        return cited_paths(self.texts + list(extra))


class CitedEvidenceTest(EvidenceTestCase):
    def test_a_cited_file_is_served_with_its_fields(self):
        allowlist = self.allowlist()
        log = self.cited["log"]
        info = os.stat(log)
        self.assertEqual(read_evidence(str(log), allowlist), {
            "path": str(log), "size": info.st_size, "mtime": info.st_mtime, "lines": 2,
            "first_line": 1, "truncated": False, "text": "82 passed\nall green\n"})
        body = read_evidence(str(self.cited["test"]), allowlist)  # cited inside "(... , ...)", unterminated
        self.assertEqual(body["lines"], 2)
        self.assertTrue(body["text"].endswith("assert True"))

    def test_an_uncited_spelling_is_forbidden(self):
        allowlist = self.allowlist()
        root = self.cited["log"].parent
        for spelling in (
            "/etc/passwd",                                  # absolute, never cited
            "acc_b1_log_v2.log",                            # relative
            "evidence/acc_b1_log_v2.log",                   # relative
            f"{root}/../evidence/acc_b1_log_v2.log",        # a `..` spelling of a cited file
            f"{root}/./acc_b1_log_v2.log",                  # a `.` spelling of a cited file
            f"{root}/acc_b1_log_v2.log)",                   # the punctuation the allowlist stripped
            "",                                             # blank
        ):
            with self.subTest(spelling=spelling):
                with self.assertRaisesRegex(RoadmapForbidden, "cites"):
                    read_evidence(spelling, allowlist)

    def test_a_symlink_a_directory_and_a_fifo_are_forbidden_even_when_cited(self):
        fifo = self.cited["log"].parent / "a_fifo.log"
        os.mkfifo(fifo)
        swapped = self.cited["second"]
        swapped.unlink()
        swapped.symlink_to(self.cited["log"])  # a cited name replaced by a link to another cited file
        allowlist = self.allowlist(f"fifo {fifo}")
        for path in (self.cited["link"], swapped, self.cited["directory"], fifo):
            with self.subTest(path=path):
                with self.assertRaises(RoadmapForbidden):
                    read_evidence(str(path), allowlist)
        self.assertEqual(read_evidence(str(self.cited["target"]), allowlist)["text"], "the link's target\n")

    def test_a_cited_path_under_a_symlinked_directory_is_forbidden(self):
        linked_dir = self.tmp / "linked"
        linked_dir.symlink_to(self.cited["log"].parent)
        through = linked_dir / self.cited["log"].name
        with self.assertRaisesRegex(RoadmapForbidden, "resolves to"):
            read_evidence(str(through), self.allowlist(f"via a link {through}"))

    def test_a_cited_file_that_does_not_exist_is_not_found(self):
        with self.assertRaises(RoadmapNotFound):
            read_evidence(str(self.cited["missing"]), self.allowlist())

    def test_the_allowlist_is_whatever_the_caller_passes_as_it_grows(self):
        late = self.cited["log"].parent / "late_acceptance.log"
        late.write_text("late\n", encoding="utf-8")
        with self.assertRaises(RoadmapForbidden):
            read_evidence(str(late), self.allowlist())
        self.assertEqual(read_evidence(str(late), self.allowlist(f"landed later ({late})"))["text"], "late\n")


class WalkTest(TempDirTestCase):
    def test_the_walk_refuses_a_symlinked_ancestor_and_opens_a_plain_path(self):
        """A09, the walk on its own: a directory link anywhere above the leaf is ELOOP/ENOTDIR, not followed."""

        root = self.tmp
        (root / "real" / "deeper").mkdir(parents=True)
        (root / "real" / "deeper" / "x.log").write_text("plain\n", encoding="utf-8")
        (root / "linked").symlink_to(root / "real")
        descriptor = open_without_symlinks(str(root / "real" / "deeper" / "x.log"))
        try:
            self.assertEqual(os.read(descriptor, 100), b"plain\n")
        finally:
            os.close(descriptor)
        for through in (root / "linked" / "deeper" / "x.log", root / "real" / "deeper" / "x.log" / "below.log"):
            with self.subTest(through=through):
                with self.assertRaises(OSError) as raised:
                    open_without_symlinks(str(through))
                self.assertIn(raised.exception.errno, (errno.ELOOP, errno.ENOTDIR))
        with self.assertRaises(FileNotFoundError):
            open_without_symlinks(str(root / "real" / "absent" / "x.log"))


class SwappedAncestorTest(EvidenceTestCase):
    def test_an_ancestor_swapped_for_a_symlink_after_the_realpath_check_is_forbidden(self):
        """A09, the race itself, made deterministic: the cited file's directory is replaced by a symlink to a directory
        holding a same-named secret AFTER the realpath pre-check passed and BEFORE the open. A plain ``O_NOFOLLOW`` open
        (the old code) then reads the secret, which the test asserts so the swap is known to be real;
        ``read_evidence`` refuses it. What this does not prove: a swap at a moment other than this one seam (each walk
        step is ``O_NOFOLLOW`` from the step before, so there is no other name resolution to race, but that is argued,
        not timed).
        """

        log = self.cited["log"]
        allowlist = self.allowlist()
        secret_dir = self.tmp / "secret"
        secret_dir.mkdir()
        (secret_dir / log.name).write_text("the secret\n", encoding="utf-8")
        evidence_dir = log.parent
        walk = files.open_without_symlinks

        def swap_then_open(path: str) -> int:
            evidence_dir.rename(evidence_dir.with_name("evidence_aside"))
            evidence_dir.symlink_to(secret_dir)
            plain = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                self.assertEqual(os.read(plain, 100), b"the secret\n", "the swap must redirect a plain O_NOFOLLOW open")
            finally:
                os.close(plain)
            return walk(path)

        self.assertEqual(read_evidence(str(log), allowlist)["text"], "82 passed\nall green\n")
        with mock.patch.object(files, "open_without_symlinks", swap_then_open):
            with self.assertRaisesRegex(RoadmapForbidden, "symlink"):
                read_evidence(str(log), allowlist)


class EvidenceWindowTest(EvidenceTestCase):
    def test_a_truncated_window_starts_at_a_line_boundary(self):
        self.assertEqual(evidence_text(b"xpartial\nkept\n", truncated=True), "kept\n")
        self.assertEqual(evidence_text(b"\nwhole line\n", truncated=True), "whole line\n")
        self.assertEqual(evidence_text(b"xno newline", truncated=True), "no newline")
        self.assertEqual(evidence_text(b"a\n\xffb", truncated=False), "a\n�b")
        self.assertEqual([line_count(text) for text in ("", "a", "a\n", "a\nb")], [0, 1, 1, 2])

    def test_a_file_over_512_kib_is_its_tail_from_a_line_boundary(self):
        line = "0123456789abcdef" * 4 + "\n"  # 74-byte lines with the index, so 512 KiB falls mid-line
        lines = [f"{index:08d} {line}" for index in range(10_000)]
        data = "".join(lines).encode("utf-8")
        self.assertGreater(len(data), EVIDENCE_READ_LIMIT)
        self.assertNotEqual((len(data) - EVIDENCE_READ_LIMIT) % len(lines[0]), 0)
        self.cited["big"].write_bytes(data)
        body = read_evidence(str(self.cited["big"]), self.allowlist())
        self.assertIs(body["truncated"], True)
        self.assertEqual(body["size"], len(data))
        text = body["text"]
        self.assertLessEqual(len(text.encode("utf-8")), EVIDENCE_READ_LIMIT)
        self.assertIn(text, data.decode("utf-8"))
        self.assertTrue(data.decode("utf-8").endswith(text))
        self.assertTrue(text.startswith(lines[-body["lines"]]), "the text starts at the first whole line of the window")
        self.assertLess(len(data) - len(text.encode("utf-8")), EVIDENCE_READ_LIMIT)  # it kept all but the partial line
        self.assertGreater(len(text.encode("utf-8")), EVIDENCE_READ_LIMIT - len(lines[0]))

    def test_a_big_files_window_says_which_source_line_it_starts_at(self):
        """Codex audit B09: a tail numbered from 1 highlighted line 188 of the TAIL for a ``:188`` citation."""

        lines = [f"{index + 1:08d} {'0123456789abcdef' * 4}\n" for index in range(10_000)]
        self.cited["big"].write_bytes("".join(lines).encode("utf-8"))
        big, allowlist = str(self.cited["big"]), self.allowlist()
        tail = read_evidence(big, allowlist)
        self.assertIs(tail["truncated"], True)
        self.assertTrue(tail["text"].startswith(lines[tail["first_line"] - 1]))
        self.assertGreater(tail["first_line"], 1)
        self.assertEqual(tail["first_line"] + tail["lines"] - 1, len(lines))
        around = read_evidence(big, allowlist, line=188)
        self.assertEqual(around["first_line"], 188 - EVIDENCE_CONTEXT_LINES)
        self.assertTrue(around["text"].startswith(lines[around["first_line"] - 1]))
        self.assertIn(lines[187], around["text"])
        self.assertTrue(around["text"].endswith("\n"))
        self.assertLessEqual(len(around["text"].encode()), EVIDENCE_READ_LIMIT)
        past = read_evidence(big, allowlist, line=99999)
        self.assertEqual(past["first_line"], tail["first_line"], "a line past the end falls back to the tail")

    def test_the_window_counts_lines_by_bytes_not_by_decoded_text(self):
        data = b"ok\n" * 300_000 + b"bad \xff byte\n" + b"end\n" * 10
        text, first_line, truncated = evidence_window(lambda count, at: data[at:at + count], len(data))
        self.assertTrue(truncated)
        self.assertTrue(text.endswith("end\n"))
        start = len(data) - (len(text.encode()) - text.count("�") * 2)  # U+FFFD is 3 bytes for the 1 it replaced
        self.assertEqual(first_line, data[:start].count(b"\n") + 1)
        small = b"one\ntwo\n"
        self.assertEqual(evidence_window(lambda count, at: small[at:at + count], len(small), line=2),
                         ("one\ntwo\n", 1, False))

    def test_a_cited_line_is_always_inside_its_own_window(self):
        """Codex audit C04: context above the cited line used to fill the window and push the line out of it."""

        def reader(data):
            return lambda count, at: data[at:at + count]

        edge = b"x" * 524287 + b"\nTARGET\nEND\n"
        text, first_line, truncated = evidence_window(reader(edge), len(edge), line=2)
        self.assertTrue(truncated)
        self.assertEqual(first_line, 2)
        self.assertTrue(text.startswith("TARGET\n"))
        wide = b"".join(f"{index + 1:05d}".encode() + b"y" * 15995 + b"\n" for index in range(100))
        text, first_line, _ = evidence_window(reader(wide), len(wide), line=50)
        shown = range(first_line, first_line + line_count(text))
        self.assertIn(50, shown)
        self.assertTrue(text.splitlines()[50 - first_line].startswith("00050"))
        huge = b"a\n" + b"z" * (EVIDENCE_READ_LIMIT + 10) + b"\nafter\n"
        text, first_line, _ = evidence_window(reader(huge), len(huge), line=2)
        self.assertEqual(first_line, 2)
        self.assertTrue(text.startswith("zzz"))
        self.assertEqual(len(text), EVIDENCE_READ_LIMIT)

    def test_a_file_that_changes_while_read_never_gets_wrong_line_numbers(self):
        """Codex audit C05: a log truncated between reading its tail and counting lines paired old text with new numbers."""

        lines = [f"{index + 1:08d} {'0123456789abcdef' * 4}\n" for index in range(10_000)]
        data = {"bytes": "".join(lines).encode(), "reads": 0}

        def read(count, at):
            chunk = data["bytes"][at:at + count]
            data["reads"] += 1
            if data["reads"] == 1:  # the tail is read, then the file is truncated to its first 100 lines
                data["bytes"] = "".join(lines[:100]).encode()
            return chunk

        def stat():
            return len(data["bytes"]), len(data["bytes"])

        size, text, first_line, _truncated = evidence_snapshot(stat, read)
        self.assertEqual(size, len("".join(lines[:100]).encode()))
        self.assertEqual(first_line, 1, "re-read once stable")
        self.assertTrue(text.startswith(lines[0]))
        flicker = {"n": 0}

        def always_changing():
            flicker["n"] += 1
            return len(data["bytes"]), flicker["n"]

        _size, _text, first_line, _ = evidence_snapshot(always_changing, lambda count, at: data["bytes"][at:at + count])
        self.assertIsNone(first_line, "a file that never holds still gets no line numbers")


class ArtTest(TempDirTestCase):
    def art_dir_with_pngs(self, root: Path) -> Path:
        root.mkdir()
        (root / "belt_sweep.png").write_bytes(PNG)
        (root / "a-0.overview.png").write_bytes(PNG[::-1])
        (root / "Upper.png").write_bytes(PNG)
        (root / "notes.txt").write_text("not art", encoding="utf-8")
        (root / "folder.png").mkdir()
        (root / "linked.png").symlink_to(root / "belt_sweep.png")
        return root

    def test_art_lists_and_serves_the_art_dir(self):
        art = self.art_dir_with_pngs(self.tmp / "art")
        self.assertEqual(art_entries(art), {"entries": ["a-0.overview.png", "belt_sweep.png"]})
        self.assertEqual(read_art(art, "belt_sweep.png"), PNG)
        self.assertEqual(read_art(art, "a-0.overview.png"), PNG[::-1])

    def test_bad_art_names_and_non_files_are_not_found(self):
        art = self.art_dir_with_pngs(self.tmp / "art")
        (self.tmp / "outside.png").write_bytes(PNG)
        for name in ("Upper.png", "notes.txt", "belt_sweep.PNG", "../outside.png", "..", "a/b.png", ".hidden.png",
                     "folder.png", "linked.png", "no_such.png", "belt_sweep.png\x00", "../../outside.png"):
            with self.subTest(name=name):
                with self.assertRaises(RoadmapNotFound):
                    read_art(art, name)

    def test_art_over_the_size_limit_is_not_found_unread_and_unlisted(self):
        """A11: a PNG bigger than ``ART_READ_LIMIT`` is refused from its fstat size (a sparse file: nothing is
        written, so a read of it would be seen only as a slow 4 MiB of zeros); one at the limit and a small one are served."""

        art = self.art_dir_with_pngs(self.tmp / "art")
        with (art / "huge.png").open("wb") as handle:
            handle.truncate(ART_READ_LIMIT + 1)
        with (art / "at_limit.png").open("wb") as handle:
            handle.write(PNG)
            handle.truncate(ART_READ_LIMIT)
        with self.assertRaisesRegex(RoadmapNotFound, "limit"):
            read_art(art, "huge.png")
        body = read_art(art, "at_limit.png")
        self.assertEqual(len(body), ART_READ_LIMIT)
        self.assertTrue(body.startswith(PNG))
        self.assertEqual(read_art(art, "belt_sweep.png"), PNG)
        self.assertEqual(art_entries(art), {"entries": ["a-0.overview.png", "at_limit.png", "belt_sweep.png"]})

    def test_the_art_dir_may_be_missing(self):
        missing = self.tmp / "no_art_here"
        self.assertEqual(art_entries(missing), {"entries": [], "missing": str(missing)})
        with self.assertRaises(RoadmapNotFound):
            read_art(missing, "belt_sweep.png")


class ErrorTypesTest(unittest.TestCase):
    def test_the_refusals_are_vibe_tracks_errors(self):
        from vibetracks import VibeTracksError

        self.assertTrue(issubclass(RoadmapForbidden, VibeTracksError))
        self.assertTrue(issubclass(RoadmapNotFound, VibeTracksError))


if __name__ == "__main__":
    unittest.main()
