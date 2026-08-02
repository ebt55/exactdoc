"""Hermetic tests for the installed Google Docs oracle surface."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

from exactdoc import gdocs
from exactdoc.errors import (OracleAuthenticationError, OracleCleanupError,
                             OracleExportError, OracleImportError,
                             OracleUnavailableError, OracleUploadError)


class _Request:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def execute(self):
        if self.error:
            raise self.error
        return self.value


class _Files:
    def __init__(self, create=None, export=None, delete=None):
        self.create_result = create if create is not None else {"id": "private-id"}
        self.export_result = export if export is not None else b"%PDF"
        self.delete_error = delete
        self.deleted = []

    def create(self, **_kwargs):
        if isinstance(self.create_result, Exception):
            return _Request(error=self.create_result)
        return _Request(self.create_result)

    def export(self, **_kwargs):
        if isinstance(self.export_result, Exception):
            return _Request(error=self.export_result)
        return _Request(self.export_result)

    def delete(self, fileId):
        self.deleted.append(fileId)
        return _Request(error=self.delete_error)


class _Service:
    def __init__(self, **kwargs):
        self.file_api = _Files(**kwargs)

    def files(self):
        return self.file_api


def _media(*_args, **_kwargs):
    return object()


class PackagedGdocsTests(unittest.TestCase):
    def test_offline_import_is_pure_and_does_not_need_testkit(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = ("import sys; import exactdoc.gdocs; "
                "assert not any(n == 'google' or n.startswith('google.') for n in sys.modules); "
                "assert 'gdocs_oracle' not in sys.modules")
        result = subprocess.run([sys.executable, "-c", code], cwd=root,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_noninteractive_missing_auth_is_typed(self):
        deps = (object(), object(), object(), object())
        with mock.patch.object(gdocs, "_google_dependencies", return_value=deps):
            with self.assertRaises(OracleAuthenticationError):
                gdocs.service(False, credentials_path="missing-credentials.json",
                              token_path="missing-token.json")

    def test_missing_optional_dependencies_are_typed(self):
        import builtins
        original_import = builtins.__import__

        def deny_google(name, *args, **kwargs):
            if name.startswith("google"):
                raise ImportError("optional dependency absent")
            return original_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=deny_google):
            with self.assertRaises(OracleUnavailableError):
                gdocs._google_dependencies()

    def test_roundtrip_maps_stages_and_always_deletes_after_export_failure(self):
        with tempfile.TemporaryDirectory() as work:
            docx, pdf = os.path.join(work, "in.docx"), os.path.join(work, "out.pdf")
            open(docx, "wb").close()
            upload = _Service(create=RuntimeError("no upload"))
            with self.assertRaises(OracleUploadError):
                gdocs.roundtrip(upload, docx, pdf, media_factory=_media)
            bad_import = _Service(create={})
            with self.assertRaises(OracleImportError):
                gdocs.roundtrip(bad_import, docx, pdf, media_factory=_media)
            exported = _Service(export=RuntimeError("no export"))
            with self.assertRaises(OracleExportError):
                gdocs.roundtrip(exported, docx, pdf, media_factory=_media)
            self.assertEqual(exported.file_api.deleted, ["private-id"])

    def test_cleanup_failure_writes_private_ledger_and_command_retries_without_ids(self):
        with tempfile.TemporaryDirectory() as work:
            ledger = os.path.join(work, "ledger.json")
            service = _Service(delete=RuntimeError("no delete"))
            with self.assertRaises(OracleCleanupError) as raised:
                gdocs.roundtrip(service, os.path.join(work, "in.docx"),
                                os.path.join(work, "out.pdf"), media_factory=_media,
                                orphan_ledger_path=ledger)
            self.assertNotIn("private-id", str(raised.exception))
            with open(ledger, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["file_ids"], ["private-id"])
            output = StringIO()
            with mock.patch.object(gdocs, "service", return_value=_Service()), redirect_stdout(output):
                self.assertEqual(gdocs.main(["cleanup-orphans", "--orphan-ledger", ledger]), 0)
            self.assertNotIn("private-id", output.getvalue())
            self.assertFalse(os.path.exists(ledger))

    def test_cleanup_retains_only_failed_ids(self):
        with tempfile.TemporaryDirectory() as work:
            ledger = os.path.join(work, "ledger.json")
            gdocs._write_private(ledger, json.dumps({"schema": gdocs.LEDGER_SCHEMA,
                                                       "file_ids": ["one", "two"]}))
            calls = []
            class _MixedFiles:
                def delete(self, fileId):
                    calls.append(fileId)
                    return _Request(error=RuntimeError() if fileId == "two" else None)
            class _MixedService:
                def files(self): return _MixedFiles()
            with self.assertRaises(OracleCleanupError):
                gdocs.cleanup_orphans(_MixedService(), ledger)
            with open(ledger, encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["file_ids"], ["two"])
            self.assertEqual(calls, ["one", "two"])

    @unittest.skipUnless(os.name != "nt", "POSIX modes are not portable on Windows")
    def test_private_write_does_not_change_existing_parent_permissions(self):
        with tempfile.TemporaryDirectory() as work:
            os.chmod(work, 0o755)
            before = os.stat(work).st_mode & 0o777
            gdocs._write_private(os.path.join(work, "token.json"), "token")
            self.assertEqual(os.stat(work).st_mode & 0o777, before)
            self.assertEqual(os.stat(os.path.join(work, "token.json")).st_mode & 0o777, 0o600)

    def test_targets_propagates_renderer_failure(self):
        from exactdoc import targets
        with mock.patch.object(gdocs, "service", return_value=object()), \
                mock.patch.object(gdocs, "roundtrip", side_effect=OracleExportError("failed")):
            renderer, name = targets.get_renderer("gdocs")
            self.assertEqual(name, "gdocs")
            with self.assertRaises(OracleExportError):
                renderer("input.docx", tempfile.gettempdir())

    def test_targets_passes_source_and_destination_to_roundtrip(self):
        from exactdoc import targets
        with tempfile.TemporaryDirectory() as work:
            source = os.path.join(work, "input.docx")
            with mock.patch.object(gdocs, "service", return_value="service"), \
                    mock.patch.object(gdocs, "roundtrip", return_value="rendered") as roundtrip:
                renderer, _ = targets.get_renderer("gdocs")
                self.assertEqual(renderer(source, work), "rendered")
            self.assertEqual(roundtrip.call_args.args,
                             ("service", source, os.path.join(work, "gd.pdf")))


if __name__ == "__main__":
    unittest.main()
