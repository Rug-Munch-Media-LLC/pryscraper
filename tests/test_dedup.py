"""Tests for dedup.py — SimHash fingerprinting, dedup, clustering, diffing."""

from pry.engine.dedup import Deduplicator, SimHash


class TestSimHashHash:
    def test_empty_text_returns_zero(self):
        assert SimHash.hash("") == 0
        assert SimHash.hash("!!! ???") == 0  # punctuation-only: no \w tokens

    def test_deterministic(self):
        assert SimHash.hash("hello world foo") == SimHash.hash("hello world foo")

    def test_identical_texts_same_hash(self):
        t = "The quick brown fox jumps over the lazy dog"
        assert SimHash.hash(t) == SimHash.hash(t.lower())

    def test_different_texts_differ(self):
        assert SimHash.hash("alpha beta gamma") != SimHash.hash("delta epsilon zeta")

    def test_case_insensitive_tokens(self):
        assert SimHash.hash("Alpha BETA") == SimHash.hash("alpha beta")

    def test_n_features_respected(self):
        h = SimHash.hash("some content here", n_features=32)
        assert 0 <= h < 2**32


class TestHammingDistance:
    def test_identical_zero(self):
        assert SimHash.hamming_distance(0b1010, 0b1010) == 0

    def test_known_small_values(self):
        assert SimHash.hamming_distance(0b1010, 0b1001) == 2
        assert SimHash.hamming_distance(0b1, 0b0) == 1

    def test_max_distance_for_width(self):
        assert SimHash.hamming_distance(0, 2**128 - 1) == 128


class TestSimilarity:
    def test_identical_full_similarity(self):
        assert SimHash.similarity(12345, 12345) == 1.0

    def test_formula_exact(self):
        # dist(0b1100, 0b0011) = 4 bits over 8 features
        assert SimHash.similarity(0b1100, 0b0011, n_features=8) == 1.0 - 4 / 8

    def test_opposite_hashes_zero_similarity(self):
        assert SimHash.similarity(0, 2**128 - 1) == 0.0


class TestDeduplicatorAdd:
    def test_add_returns_hash_and_stores(self):
        d = Deduplicator()
        h = d.add("doc1", "unique content alpha")
        assert d._hashes["doc1"] == h

    def test_same_id_overwrites(self):
        d = Deduplicator()
        d.add("doc1", "first version text")
        h2 = d.add("doc1", "second version text")
        assert d._hashes["doc1"] == h2
        assert len(d._hashes) == 1


class TestFindDuplicates:
    def test_near_duplicate_detected_sorted(self):
        d = Deduplicator(threshold=0.7)
        base = "the quick brown fox jumps over the lazy dog near the river bank today"
        d.add("orig", base)
        near = base.replace("dog", "cat")  # one-token change -> high similarity
        dupes = d.find_duplicates(near)
        assert len(dupes) >= 1
        assert dupes[0]["doc_id"] == "orig"
        assert dupes[0]["similarity"] >= 0.7
        assert isinstance(dupes[0]["distance"], int)

    def test_disjoint_content_not_flagged(self):
        d = Deduplicator(threshold=0.9)
        d.add("a", "alpha beta gamma delta")
        assert d.find_duplicates("completely different words entirely here") == []

    def test_results_sorted_desc_by_similarity(self):
        d = Deduplicator(threshold=0.5)
        d.add("close", "alpha beta gamma delta epsilon zeta eta theta")
        d.add("closer", "alpha beta gamma delta epsilon zeta eta theta iota")
        dupes = d.find_duplicates("alpha beta gamma delta epsilon zeta eta theta")
        sims = [x["similarity"] for x in dupes]
        assert sims == sorted(sims, reverse=True)


class TestCluster:
    def test_similar_docs_cluster_together(self):
        d = Deduplicator(threshold=0.6)
        base = "breaking news about crypto market regulation today with many details"
        texts = {
            "a": base,
            "b": base.replace("today", "yesterday"),
            "z": "totally unrelated recipe for chocolate cake with sugar flour eggs",
        }
        clusters = d.cluster(texts)
        assert len(clusters) == 2
        members = [set(c) for c in clusters.values()]
        assert {"a", "b"} in members
        assert {"z"} in members

    def test_all_unique_singletons(self):
        d = Deduplicator(threshold=0.99)
        clusters = d.cluster({"x": "foo bar baz", "y": "quux quux quux"})
        assert len(clusters) == 2


class TestDiff:
    def test_identical_minimal(self):
        d = Deduplicator(threshold=0.85)
        out = d.diff("same words repeated here now", "same words repeated here now")
        assert out["changed"] is False
        assert out["change_severity"] == "minimal"
        assert out["hamming_distance"] == 0

    def test_disjoint_is_high_and_changed(self):
        d = Deduplicator(threshold=0.85)
        out = d.diff("alpha beta gamma", "delta epsilon zeta")
        assert out["changed"] is True
        assert out["change_severity"] == "high"

    def test_severity_ordering_consistent_with_distance(self):
        d = Deduplicator(threshold=0.85)
        small = d.diff(
            "one two three four five six seven eight", "one two three four five six seven nine"
        )
        big = d.diff(
            "one two three four five six seven eight",
            "alpha beta gamma delta epsilon zeta eta theta",
        )
        order = {"minimal": 0, "low": 1, "medium": 2, "high": 3}
        assert order[big["change_severity"]] >= order[small["change_severity"]]
