# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Rug Munch Media LLC
#
# Part of Pry — https://git.rugmunch.io/RugMunchMedia/pryscraper
# Licensed under MIT. See LICENSE.
"""Hardened tests for engine/dedup.py — untested branches.

Complements tests/test_dedup.py and tests/test_dedup_mutation.py by
targeting branches those suites do not reach:

* ``SimHash.hash`` with ``n_features=0`` and ``n_features=1``.
* ``Deduplicator.add`` with empty text.
* ``find_duplicates`` with no documents added and with empty text.
* ``find_duplicates`` result ordering / exact keys.
* ``cluster`` with an empty dict and with a single document.
* ``diff`` with empty strings and with identical-but-empty inputs.
* ``diff`` ``changed`` semantics at the threshold boundary.
* ``Deduplicator`` custom threshold propagation.

Every assertion pins a concrete value / type / outcome — no tautologies.
"""

from __future__ import annotations

from pry.engine.dedup import Deduplicator, SimHash

# ── SimHash.hash feature-width edge cases ───────────────────────────────────


class TestSimHashFeatureWidth:
    def test_n_features_zero_returns_zero(self) -> None:
        # No feature bits -> result stays 0 regardless of tokens.
        assert SimHash.hash("hello world", n_features=0) == 0

    def test_n_features_one_is_single_bit(self) -> None:
        h = SimHash.hash("hello", n_features=1)
        assert h in (0, 1)

    def test_n_features_one_deterministic(self) -> None:
        assert SimHash.hash("hello", n_features=1) == SimHash.hash("hello", n_features=1)

    def test_empty_text_any_width_is_zero(self) -> None:
        assert SimHash.hash("", n_features=64) == 0
        assert SimHash.hash("", n_features=0) == 0


# ── Deduplicator.add edge cases ─────────────────────────────────────────────


class TestDeduplicatorAddEdgeCases:
    def test_add_empty_text_stores_zero_hash(self) -> None:
        d = Deduplicator()
        h = d.add("doc", "")
        assert h == 0
        assert d._hashes["doc"] == 0

    def test_add_returns_int_hash(self) -> None:
        d = Deduplicator()
        h = d.add("doc", "some real content here")
        assert isinstance(h, int)
        assert h != 0


# ── find_duplicates edge cases ──────────────────────────────────────────────


class TestFindDuplicatesEdgeCases:
    def test_no_documents_returns_empty(self) -> None:
        d = Deduplicator()
        assert d.find_duplicates("any text") == []

    def test_empty_text_against_stored_docs(self) -> None:
        d = Deduplicator(threshold=0.0)  # threshold 0 matches everything
        d.add("doc", "some content")
        hits = d.find_duplicates("")
        # Empty text hashes to 0; similarity to a stored hash is
        # 1 - hamming_distance(0, doc_hash)/128 (>= 0, so threshold 0 matches).
        assert len(hits) == 1
        assert hits[0]["doc_id"] == "doc"
        expected_sim = 1.0 - SimHash.hamming_distance(0, d._hashes["doc"]) / 128
        assert hits[0]["similarity"] == round(expected_sim, 3)
        assert hits[0]["distance"] == SimHash.hamming_distance(0, d._hashes["doc"])

    def test_result_keys_are_exact(self) -> None:
        d = Deduplicator(threshold=0.0)
        d.add("doc", "content")
        hits = d.find_duplicates("content")
        assert set(hits[0].keys()) == {"doc_id", "similarity", "distance"}

    def test_similarity_is_float_and_distance_is_int(self) -> None:
        d = Deduplicator(threshold=0.0)
        d.add("doc", "content")
        hits = d.find_duplicates("content")
        assert isinstance(hits[0]["similarity"], float)
        assert isinstance(hits[0]["distance"], int)

    def test_identical_text_returns_full_similarity(self) -> None:
        d = Deduplicator(threshold=1.0)
        d.add("doc", "identical words here")
        hits = d.find_duplicates("identical words here")
        assert hits[0]["similarity"] == 1.0
        assert hits[0]["distance"] == 0


# ── cluster edge cases ──────────────────────────────────────────────────────


class TestClusterEdgeCases:
    def test_empty_texts_returns_empty(self) -> None:
        d = Deduplicator()
        assert d.cluster({}) == {}

    def test_single_document_forms_one_cluster(self) -> None:
        d = Deduplicator()
        clusters = d.cluster({"only": "some text"})
        assert clusters == {"cluster_0": ["only"]}

    def test_all_identical_docs_form_single_cluster(self) -> None:
        d = Deduplicator(threshold=1.0)
        clusters = d.cluster({"a": "same", "b": "same", "c": "same"})
        assert len(clusters) == 1
        assert sorted(clusters["cluster_0"]) == ["a", "b", "c"]

    def test_cluster_members_are_lists_of_strings(self) -> None:
        d = Deduplicator(threshold=0.0)
        clusters = d.cluster({"a": "x", "b": "y"})
        for members in clusters.values():
            assert isinstance(members, list)
            assert all(isinstance(m, str) for m in members)


# ── diff edge cases ─────────────────────────────────────────────────────────


class TestDiffEdgeCases:
    def test_both_empty_strings(self) -> None:
        d = Deduplicator()
        out = d.diff("", "")
        assert out["similarity"] == 1.0
        assert out["hamming_distance"] == 0
        assert out["changed"] is False
        assert out["change_severity"] == "minimal"

    def test_one_empty_one_nonempty(self) -> None:
        d = Deduplicator()
        out = d.diff("", "some real content here")
        assert out["changed"] is True
        assert out["hamming_distance"] > 0
        assert out["similarity"] < 1.0

    def test_diff_returns_exact_keys(self) -> None:
        d = Deduplicator()
        out = d.diff("a b c", "a b d")
        assert set(out.keys()) == {
            "similarity",
            "hamming_distance",
            "changed",
            "change_severity",
        }

    def test_changed_false_when_similarity_at_threshold(self) -> None:
        # changed = sim < threshold (strict). At sim == threshold it's False.
        d = Deduplicator(threshold=1.0)
        out = d.diff("same text", "same text")
        assert out["similarity"] == 1.0
        assert out["changed"] is False


# ── Deduplicator threshold propagation ──────────────────────────────────────


class TestThresholdPropagation:
    def test_custom_threshold_stored(self) -> None:
        assert Deduplicator(threshold=0.5).threshold == 0.5
        assert Deduplicator(threshold=0.99).threshold == 0.99

    def test_default_threshold_is_085(self) -> None:
        assert Deduplicator().threshold == 0.85

    def test_threshold_controls_find_duplicates(self) -> None:
        # A low threshold catches a distant doc; a high one does not.
        d_low = Deduplicator(threshold=0.0)
        d_low.add("doc", "alpha beta gamma")
        assert len(d_low.find_duplicates("completely different words")) == 1

        d_high = Deduplicator(threshold=0.99)
        d_high.add("doc", "alpha beta gamma")
        assert d_high.find_duplicates("completely different words") == []
