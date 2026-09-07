"""Canonical serialization tests."""

import pytest

from memory_brain import canonical, normalize


# --- determinism ---------------------------------------------------------
def test_canonical_json_deterministic_key_order():
    assert canonical.canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_canonical_json_nested_sorting():
    assert canonical.canonical_json({"z": {"y": 1, "x": 2}, "a": 1}) == \
        '{"a":1,"z":{"x":2,"y":1}}'


def test_digest_domain_separation():
    a = canonical.digest({"x": 1}, "mem")
    b = canonical.digest({"x": 1}, "other")
    assert a != b
    assert canonical.digest({"x": 1}, "mem") == a  # deterministic


def test_digest_order_independent_for_equivalent_structs():
    assert canonical.digest({"a": 1, "b": 2}, "t") == \
        canonical.digest({"b": 2, "a": 1}, "t")


def test_list_and_tuple_digest_same():
    assert canonical.digest([1, 2, 3], "t") == canonical.digest((1, 2, 3), "t")


def test_string_escaping_minimal():
    assert canonical.canonical_json({"s": 'a"b\\c\n'}) == '{"s":"a\\"b\\\\c\\n"}'


def test_bool_vs_int_distinct():
    assert canonical.canonical_json(True) == "true"
    assert canonical.canonical_json(1) == "1"
    assert canonical.canonical_json(True) != canonical.canonical_json(1)


# --- number formatting ---------------------------------------------------
def test_integer_serialization():
    assert canonical.canonical_json(42) == "42"
    assert canonical.canonical_json(-3) == "-3"
    assert canonical.canonical_json(0) == "0"


def test_float_integer_like_serializes_as_int():
    assert canonical.canonical_json(4.0) == "4"


def test_float_non_integer_deterministic():
    a = canonical.canonical_json(3.14)
    b = canonical.canonical_json(3.14)
    assert a == b
    assert "." in a


# --- normalization -------------------------------------------------------
def test_normalization_casefold_and_whitespace():
    assert normalize.normalize_text("  Hello  WORLD \n") == \
        normalize.normalize_text("hello world")


def test_normalization_accent_insensitive():
    assert normalize.normalize_text("café") == normalize.normalize_text("cafe")


def test_normalized_hash_deterministic():
    assert normalize.normalized_hash("PostgreSQL DB") == \
        normalize.normalized_hash("PostgreSQL DB")


def test_content_hash_differs_from_normalized_hash():
    assert normalize.content_hash("X") != normalize.normalized_hash("X")


def test_normalized_hash_catches_near_dupes():
    assert normalize.normalized_hash("The Service uses PostgreSQL.") == \
        normalize.normalized_hash("the service uses postgresql")
