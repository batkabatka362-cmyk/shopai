"""Search index tests."""
from __future__ import annotations

import unittest

from core.memory import search_index as si


class TestTokenise(unittest.TestCase):
    def test_stopwords_stripped(self) -> None:
        toks = si._tokenise("the quick brown fox")
        self.assertNotIn("the", toks)
        self.assertIn("quick", toks)

    def test_stemming_normalises(self) -> None:
        self.assertEqual(si._stem("running"), "runn")  # Porter-lite
        self.assertEqual(si._stem("runs"), "run")


class TestAddAndSearch(unittest.TestCase):
    def setUp(self) -> None:
        self.idx = si.SearchIndex()
        self.idx.add("doc1", "wireless bluetooth speaker")
        self.idx.add("doc2", "wired headphones with noise cancel")
        self.idx.add("doc3", "speaker stand aluminium")

    def test_search_returns_matches(self) -> None:
        hits = self.idx.search("speaker")
        ids = [h.doc_id for h in hits]
        self.assertIn("doc1", ids)
        self.assertIn("doc3", ids)
        self.assertNotIn("doc2", ids)

    def test_empty_query_empty(self) -> None:
        self.assertEqual(self.idx.search(""), [])

    def test_empty_index_empty(self) -> None:
        empty = si.SearchIndex()
        self.assertEqual(empty.search("x"), [])

    def test_scores_descending(self) -> None:
        # doc1 has both 'wireless' and 'speaker'; doc3 only 'speaker'
        hits = self.idx.search("wireless speaker")
        self.assertEqual(hits[0].doc_id, "doc1")
        if len(hits) >= 2:
            self.assertGreaterEqual(hits[0].score, hits[1].score)

    def test_top_k_honoured(self) -> None:
        hits = self.idx.search("speaker", top_k=1)
        self.assertLessEqual(len(hits), 1)


class TestMetadata(unittest.TestCase):
    def test_metadata_surfaces(self) -> None:
        idx = si.SearchIndex()
        idx.add(
            "doc1", "premium audio",
            metadata={"niche": "audio", "price": 99},
        )
        hits = idx.search("premium")
        self.assertEqual(hits[0].metadata["niche"], "audio")

    def test_blank_doc_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            si.SearchIndex().add("", "text")

    def test_empty_text_noop(self) -> None:
        idx = si.SearchIndex()
        idx.add("d", "")
        self.assertEqual(idx.search("x"), [])


class TestRemove(unittest.TestCase):
    def test_remove_drops_from_results(self) -> None:
        idx = si.SearchIndex()
        idx.add("d1", "speaker")
        idx.add("d2", "speaker")
        self.assertTrue(idx.remove("d1"))
        hits = idx.search("speaker")
        self.assertEqual([h.doc_id for h in hits], ["d2"])

    def test_remove_unknown_false(self) -> None:
        self.assertFalse(si.SearchIndex().remove("nope"))

    def test_readd_replaces_old_version(self) -> None:
        idx = si.SearchIndex()
        idx.add("d", "old text")
        idx.add("d", "new content")
        # Searching "old" should not hit anymore.
        self.assertEqual(idx.search("old"), [])
        hits = idx.search("content")
        self.assertEqual([h.doc_id for h in hits], ["d"])


class TestSuggest(unittest.TestCase):
    def test_prefix_matches(self) -> None:
        idx = si.SearchIndex()
        idx.add("d1", "wireless speaker")
        idx.add("d2", "wired headphones")
        idx.add("d3", "waterproof case")
        suggestions = idx.suggest("wir")
        self.assertIn("d1", suggestions)
        self.assertIn("d2", suggestions)
        self.assertNotIn("d3", suggestions)

    def test_empty_prefix_empty(self) -> None:
        self.assertEqual(si.SearchIndex().suggest(""), [])


class TestSnippet(unittest.TestCase):
    def test_snippet_contains_match(self) -> None:
        idx = si.SearchIndex()
        idx.add(
            "d", "prefix padding text with wireless speaker in it",
        )
        hits = idx.search("wireless")
        self.assertIn("wireless", hits[0].snippet.lower())


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        idx = si.SearchIndex()
        idx.add("d1", "one two three")
        idx.add("d2", "four five six")
        stats = idx.stats()
        self.assertEqual(stats["doc_count"], 2)
        self.assertGreaterEqual(stats["term_count"], 2)


if __name__ == "__main__":
    unittest.main()
