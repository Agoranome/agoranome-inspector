"""Canonical bytes, the Merkle tree, keys and the book."""

import hashlib
import json

import pytest

from agoranome_inspector.book import Book, check_chain, parse
from agoranome_inspector.canonical import canonical, digest
from agoranome_inspector.keys import Signer, thumbprint, verify_signature
from agoranome_inspector.merkle import leaf_hash, merkle_proof, merkle_root, receipt_leaf, verify_proof


def test_canonical_sorts_keys_and_refuses_floats():
    assert canonical({"b": 1, "a": [True, None, "é"]}) == '{"a":[true,null,"é"],"b":1}'.encode()
    with pytest.raises(TypeError):
        canonical({"price": 0.005})


def test_receipt_leaf_is_the_labs_construction():
    entry = {"receipt_id": "r1", "payer": "0xabc", "amount_atomic": 10000, "tx_hash": "0xdef", "ignored": 1}
    fields = {k: entry[k] for k in ("receipt_id", "payer", "amount_atomic", "tx_hash")}
    expected = hashlib.sha256(b"\x00" + json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert receipt_leaf(entry) == "0x" + expected


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 8, 9, 16, 33])
def test_every_leaf_proves_into_the_root(n):
    leaves = [leaf_hash({"i": i}) for i in range(n)]
    root = merkle_root(leaves)
    for leaf in leaves:
        assert verify_proof(leaf, merkle_proof(leaves, leaf), root)
    assert not verify_proof(leaf_hash({"i": n}), merkle_proof(leaves, leaves[0]), root)


def test_merkle_root_ignores_leaf_order_and_is_none_when_empty():
    leaves = [leaf_hash({"i": i}) for i in range(6)]
    assert merkle_root(leaves) == merkle_root(list(reversed(leaves)))
    assert merkle_root([]) is None


def test_keys_sign_verify_and_round_trip():
    signer = Signer.generate()
    assert signer.kid == thumbprint(signer.jwk)
    sig = signer.sign(b"message")
    assert verify_signature(signer.jwk, b"message", sig)
    assert not verify_signature(signer.jwk, b"other", sig)
    again = Signer.from_text(signer.pem())
    assert again.kid == signer.kid


def test_only_the_whole_pem_file_is_a_signing_key():
    signer = Signer.generate()
    pasted = '"\r\n' + signer.pem().replace("\n", "\r\n") + '  "\n'       # quotes, spaces and CRLF from a paste
    assert Signer.from_text(pasted).kid == signer.kid
    body = signer.pem().splitlines()[1]
    for wrong in (signer.kid, signer.jwk["x"], body, "inspector-key.pem", ""):   # a kid or public key is 32 bytes too
        with pytest.raises(ValueError, match="whole file keygen wrote"):
            Signer.from_text(wrong)
    with pytest.raises(ValueError, match="damaged"):
        Signer.from_text(signer.pem().replace(body, "!!!!" + body[4:]))


def _book(tmp_path, n=3):
    signer = Signer.generate()
    book = Book(str(tmp_path / "book.jsonl"))
    for i in range(n):
        book.append(signer, "note", {"text": f"note {i}"}, time=f"2026-11-1{i}T00:00:00Z")
    return signer, book


def test_book_opens_with_its_key_and_verifies(tmp_path):
    signer, book = _book(tmp_path)
    entries = book.entries()
    assert [e["kind"] for e in entries] == ["key", "note", "note", "note"]
    found = check_chain(entries, pinned_kid=signer.kid, since={"seq": 2, "hash": entries[2]["hash"]})
    assert found.ok, found.failures
    assert found.head["seq"] == 3


def test_book_catches_an_edited_entry(tmp_path):
    _, book = _book(tmp_path)
    entries = book.entries()
    entries[2]["body"]["text"] = "rewritten"
    assert "hash does not match" in " ".join(check_chain(entries).failures)


def test_book_catches_a_rehashed_entry_and_a_dropped_one(tmp_path):
    from agoranome_inspector.book import entry_hash

    _, book = _book(tmp_path)
    entries = book.entries()
    entries[2]["body"]["text"] = "rewritten"
    entries[2]["hash"] = entry_hash(entries[2])
    assert "signature does not verify" in " ".join(check_chain(entries).failures)
    entries = book.entries()
    del entries[1]
    assert not check_chain(entries).ok


def test_book_refuses_a_stranger_and_a_wrong_pin(tmp_path):
    signer, book = _book(tmp_path)
    with pytest.raises(RuntimeError):
        book.append(Signer.generate(), "note", {"text": "intruder"})
    assert not check_chain(book.entries(), pinned_kid=Signer.generate().kid).ok
    assert not check_chain(book.entries(), since={"seq": 1, "hash": "0x" + "ab" * 32}).ok


def test_a_pasted_pin_with_spaces_still_matches(tmp_path):
    signer, book = _book(tmp_path)
    assert check_chain(book.entries(), pinned_kid=f"  {signer.kid}\n").ok
    assert not check_chain(book.entries(), pinned_kid=f" {Signer.generate().kid} ").ok


def test_book_hands_over_to_a_new_key(tmp_path):
    signer, book = _book(tmp_path, n=1)
    new = Signer.generate()
    book.hand_over(signer, new)
    book.append(new, "note", {"text": "signed by the new key"})
    with pytest.raises(RuntimeError):
        book.append(signer, "note", {"text": "the old key is retired"})
    found = check_chain(book.entries(), pinned_kid=signer.kid)
    assert found.ok, found.failures
    assert [k["kid"] for k in found.keys] == [signer.kid, new.kid]


def test_book_lines_are_canonical(tmp_path):
    _, book = _book(tmp_path, n=1)
    for line in (tmp_path / "book.jsonl").read_text().splitlines():
        assert canonical(json.loads(line)).decode() == line
    assert len(parse((tmp_path / "book.jsonl").read_text())) == 2
    assert digest({"a": 1}).startswith("0x")
