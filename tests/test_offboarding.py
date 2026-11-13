import json
import os

import pytest

from src.documents.offboarding import offboarding_report
from src.documents.registry import Registry
from test_document_registry import make_pdf


def test_verified_remaining_copy_needs_hashes_and_continued_access(tmp_path):
    source, remaining = tmp_path / "source.pdf", tmp_path / "team.pdf"
    make_pdf(source, ["Original"])
    remaining.write_bytes(source.read_bytes())
    original = source.read_bytes()
    with Registry(tmp_path / "db.sqlite") as registry:
        first = registry.ingest(source, owner_id="leaving")["copy"]
        second = registry.ingest(remaining, owner_id="team")["copy"]
        report = offboarding_report(registry, first["copy_id"], verified_by="reviewer")
        assert report["status"] == "no_verified_remaining_copy"
        assert report["candidates"][0]["hashes_verified"]
        assert report["candidates"][0]["status"] == "candidate_access_unconfirmed"
        confirmed = offboarding_report(
            registry, first["copy_id"], verified_by="reviewer",
            access_confirmations={second["copy_id"]: "Team-owned folder remains accessible after account removal"},
        )
        assert confirmed["status"] == "verified_remaining_copy"
        assert confirmed["evidence"][0]["verified_sha256"] == registry.document(first["doc_id"])["sha256"]
        assert confirmed["evidence"][0]["remaining_copy_id"] == second["copy_id"]
        assert confirmed["evidence"][0]["survives_offboarding"] is True
        stored = registry.connection.execute(
            "SELECT report FROM offboarding_reports WHERE report_id=?", (confirmed["report_id"],)
        ).fetchone()[0]
        assert json.loads(stored) == confirmed
        assert source.read_bytes() == remaining.read_bytes() == original
        with pytest.raises(ValueError, match="confirmations"):
            offboarding_report(registry, first["copy_id"], verified_by="reviewer", access_confirmations=[])


def test_inaccessible_changed_and_same_physical_file_do_not_verify(tmp_path, monkeypatch):
    import src.documents.offboarding as module

    source, offline, modified, alias = [tmp_path / name for name in
                                         ("source.pdf", "offline.pdf", "modified.pdf", "alias.pdf")]
    make_pdf(source, ["Original"])
    offline.write_bytes(source.read_bytes())
    modified.write_bytes(source.read_bytes())
    os.link(source, alias)
    with Registry(tmp_path / "db.sqlite") as registry:
        first = registry.ingest(source, owner_id="leaving")["copy"]
        copies = [registry.ingest(path, owner_id="team")["copy"] for path in (offline, modified, alias)]
        modified.write_bytes(b"changed after import")
        original_hash = module.hash_file

        def inaccessible(path):
            if path == offline:
                raise PermissionError("Synthetic access denied")
            return original_hash(path)

        monkeypatch.setattr(module, "hash_file", inaccessible)
        report = offboarding_report(
            registry, first["copy_id"], verified_by="reviewer",
            access_confirmations={copy["copy_id"]: "Team attested access" for copy in copies},
        )
        statuses = {item["remaining_copy_id"]: item["status"] for item in report["candidates"]}
        assert statuses[copies[0]["copy_id"]] == "inaccessible_or_changed"
        assert statuses[copies[1]["copy_id"]] == "bytes_differ"
        assert statuses[copies[2]["copy_id"]] == "same_physical_file"
        assert report["evidence"] == []
        assert report["status"] == "no_verified_remaining_copy"
        source.write_bytes(b"source changed too")
        assert offboarding_report(registry, first["copy_id"], verified_by="reviewer")["status"] == "source_unverified"


def test_missing_remaining_copy_and_revised_version_are_not_proof(tmp_path):
    source, remaining, revised = [tmp_path / name for name in ("source.pdf", "team.pdf", "rev.pdf")]
    make_pdf(source, ["Original"])
    remaining.write_bytes(source.read_bytes())
    make_pdf(revised, ["Revised"])
    with Registry(tmp_path / "db.sqlite") as registry:
        first = registry.ingest(source, owner_id="leaving")["copy"]
        second = registry.ingest(remaining, owner_id="team")["copy"]
        third = registry.ingest(revised, owner_id="team")["copy"]
        remaining.rename(tmp_path / "unavailable.pdf")
        report = offboarding_report(registry, first["copy_id"], verified_by="reviewer",
                                    access_confirmations={second["copy_id"]: "Team access"})
        assert report["status"] == "no_verified_remaining_copy"
        assert report["candidates"][0]["status"] == "inaccessible_or_changed"
        different = offboarding_report(registry, first["copy_id"], verified_by="reviewer",
                                       remaining_copy_id=third["copy_id"])
        assert different["candidates"][0]["status"] == "not_a_distinct_copy_of_this_version"


def test_source_changes_during_remaining_read_prevent_evidence(tmp_path, monkeypatch):
    import src.documents.offboarding as module

    source, remaining = tmp_path / "source.pdf", tmp_path / "team.pdf"
    make_pdf(source, ["Source"])
    remaining.write_bytes(source.read_bytes())
    with Registry(tmp_path / "db.sqlite") as registry:
        first = registry.ingest(source, owner_id="leaving")["copy"]
        second = registry.ingest(remaining, owner_id="team")["copy"]
        original = module.hash_file

        def concurrent_change(path):
            digest = original(path)
            if path == remaining:
                source.write_bytes(b"Changed during verification")
            return digest

        monkeypatch.setattr(module, "hash_file", concurrent_change)
        report = offboarding_report(registry, first["copy_id"], verified_by="reviewer",
                                    access_confirmations={second["copy_id"]: "Team-owned"})
        assert report["evidence"] == []
        assert report["candidates"][0]["status"] == "inaccessible_or_changed"
