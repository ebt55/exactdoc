"""Optional Google Docs renderer.

This module is deliberately safe to import in the offline product.  Google
libraries are imported only when a service or upload is actually requested;
installing ``exactdoc`` therefore does not make conversion depend on Google.
"""
import argparse
import json
import os
import sys
import uuid

from .errors import (OracleAuthenticationError, OracleCleanupError,
                     OracleExportError, OracleImportError,
                     OracleUnavailableError, OracleUploadError)


SCOPES = ("https://www.googleapis.com/auth/drive.file",)
GDOC_MIME = "application/vnd.google-apps.document"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Drive's simple (multipart) upload carries at most 5 MB; a larger DOCX (one
# with many page images: y06's is 9.9 MB) is refused or cut off mid-body, so it
# goes up through a resumable session instead.
SIMPLE_UPLOAD_MAX = 5 * 1024 * 1024
# Google converts the DOCX while the create request is still open, so a large
# one answers late: y06 (9.9 MB) outlived httplib2's default socket timeout in
# mid-conversion (2026-10-04).
HTTP_TIMEOUT_S = 600
LEDGER_SCHEMA = "exactdoc.gdocs-orphan-ledger.v1"


def _config_dir():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "exactdoc")


def _project_root():
    """Source-tree compatibility only; installed users use their config dir."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _first_existing(candidates, default):
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return default


def credential_paths(credentials_path=None, token_path=None):
    """Resolve local OAuth paths without reading their contents.

    Explicit arguments win, followed by narrowly scoped path variables, then
    the per-user config directory.  The repository files remain a last-resort
    convenience for developers running from a checkout.
    """
    config = _config_dir()
    repo = _project_root()
    credentials_default = os.path.join(config, "credentials.json")
    token_default = os.path.join(config, "token.json")
    credentials = credentials_path or os.environ.get("EXACTDOC_GDOCS_CREDENTIALS") or _first_existing(
        (credentials_default, os.path.join(repo, "credentials.json")), credentials_default)
    token = token_path or os.environ.get("EXACTDOC_GDOCS_TOKEN") or _first_existing(
        (token_default, os.path.join(repo, "token.json")), token_default)
    return os.fspath(credentials), os.fspath(token)


def default_orphan_ledger_path():
    return os.path.join(_config_dir(), "gdocs-orphans.json")


def _private_mode(path):
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_private(path, data):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        _private_mode(path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _google_dependencies():
    """Return third-party pieces lazily, with one typed missing-extra error."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise OracleUnavailableError(
            "the Google Docs oracle needs the optional [gdocs] dependencies") from exc
    return Credentials, InstalledAppFlow, Request, build


def service(interactive=False, credentials_path=None, token_path=None):
    """Create a Drive client, refreshing or acquiring desktop OAuth as needed."""
    Credentials, InstalledAppFlow, Request, build = _google_dependencies()
    credentials_path, token_path = credential_paths(credentials_path, token_path)
    creds = None
    if os.path.isfile(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as exc:
            raise OracleAuthenticationError("the Google Docs token is unreadable or invalid") from exc
    if not creds or not creds.valid:
        refreshed = False
        if creds and getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
            try:
                creds.refresh(Request())
                refreshed = True
            except Exception as exc:
                # A refresh token from an OAuth app in testing status expires
                # after about seven days (invalid_grant). Non-interactively that
                # is an error; interactively it is the case a fresh consent
                # repairs, so fall through to the browser instead of failing.
                if not interactive:
                    raise OracleAuthenticationError(
                        "the Google Docs token could not be refreshed; "
                        "run exactdoc-gdocs auth") from exc
        if not refreshed:
            if not interactive:
                raise OracleAuthenticationError(
                    "Google Docs authentication is required; run exactdoc-gdocs auth")
            if not os.path.isfile(credentials_path):
                raise OracleAuthenticationError("Google OAuth desktop credentials are not configured")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(
                    port=0, authorization_prompt_message="Opening a browser for Google consent...",
                    success_message="Authorised. You can close this tab.")
            except Exception as exc:
                raise OracleAuthenticationError("Google OAuth authorisation did not complete") from exc
        try:
            _write_private(token_path, creds.to_json())
        except (OSError, TypeError, ValueError) as exc:
            raise OracleAuthenticationError("the Google Docs token could not be saved securely") from exc
    try:
        try:
            import httplib2
            from google_auth_httplib2 import AuthorizedHttp
        except ImportError:
            return build("drive", "v3", credentials=creds, cache_discovery=False)
        return build("drive", "v3", cache_discovery=False,
                     http=AuthorizedHttp(creds, http=httplib2.Http(timeout=HTTP_TIMEOUT_S)))
    except Exception as exc:
        raise OracleUnavailableError("the Google Drive service could not be initialised") from exc


def _record_orphan(file_id, ledger_path=None):
    """Persist a recovery ID locally without ever exposing it in an error."""
    if not isinstance(file_id, str) or not file_id:
        raise ValueError("Drive delete did not return a recoverable document")
    ledger_path = ledger_path or default_orphan_ledger_path()
    existing = []
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, encoding="utf-8") as fh:
                payload = json.load(fh)
            existing = payload.get("file_ids", []) if isinstance(payload, dict) else []
            if (not isinstance(payload, dict) or payload.get("schema") != LEDGER_SCHEMA or
                    not isinstance(existing, list) or
                    not all(isinstance(item, str) and item for item in existing)):
                raise ValueError("unsafe orphan ledger")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise OracleCleanupError("the Google Docs recovery ledger is unusable") from exc
    if file_id not in existing:
        existing.append(file_id)
    try:
        _write_private(ledger_path, json.dumps(
            {"schema": LEDGER_SCHEMA, "file_ids": existing}, sort_keys=True) + "\n")
    except OSError as exc:
        raise OracleCleanupError("the Google Docs recovery ledger could not be saved") from exc


def _read_orphans(ledger_path):
    if not os.path.exists(ledger_path):
        return []
    try:
        with open(ledger_path, encoding="utf-8") as fh:
            payload = json.load(fh)
        ids = payload.get("file_ids", []) if isinstance(payload, dict) else []
        if (not isinstance(payload, dict) or payload.get("schema") != LEDGER_SCHEMA or
                not isinstance(ids, list) or
                not all(isinstance(item, str) and item for item in ids)):
            raise ValueError("unsafe orphan ledger")
        return ids
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise OracleCleanupError("the Google Docs recovery ledger is unusable") from exc


def _export_pdf(svc, file_id):
    """Google's PDF of the Doc. `files.export` refuses a Doc whose export
    passes 10 MB (403, "This file is too large to be exported": y06, 9.9 MB of
    page images, 2026-10-04); the file's own export link has no such cap, so
    that refusal, and only that one, is retried through it."""
    try:
        return svc.files().export(fileId=file_id, mimeType="application/pdf").execute()
    except Exception as exc:
        if "too large to be exported" not in str(exc) and \
                "exportSizeLimitExceeded" not in str(exc):
            raise
    link = svc.files().get(fileId=file_id, fields="exportLinks").execute() \
        .get("exportLinks", {}).get("application/pdf")
    if not link:
        raise ValueError("the Doc offers no PDF export link")
    resp, content = svc._http.request(link)
    if getattr(resp, "status", None) != 200:
        raise ValueError("the PDF export link answered %s" % getattr(resp, "status", None))
    return content


def _sweep_upload(svc, name, orphan_ledger_path=None):
    """After a failed create, delete any Doc carrying this upload's name.

    A create the client gave up on can still finish on the server and leave a
    document nobody holds an id for. The name is unique to the upload, so a
    match is ours. Best effort: a listing that fails leaves nothing to act on,
    and a delete that fails is recorded for `cleanup_orphans`.
    """
    try:
        q = "name = '%s' and trashed = false" % name.replace("\\", "\\\\").replace("'", "\\'")
        found = svc.files().list(q=q, fields="files(id)").execute().get("files", [])
    except Exception:
        return
    for item in found:
        try:
            svc.files().delete(fileId=item["id"]).execute()
        except Exception:
            try:
                _record_orphan(item["id"], orphan_ledger_path)
            except Exception:
                pass


def roundtrip(svc, docx_path, out_pdf, media_factory=None, orphan_ledger_path=None):
    """Upload a DOCX, export its Docs rendering as PDF, and delete it once."""
    if media_factory is None:
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            raise OracleUnavailableError(
                "the Google Docs oracle needs the optional [gdocs] dependencies") from exc
        media_factory = MediaFileUpload
    name = "%s.%s" % (os.path.basename(docx_path), uuid.uuid4().hex[:12])
    try:
        size = os.path.getsize(docx_path) if os.path.exists(docx_path) else 0
        media = media_factory(docx_path, mimetype=DOCX_MIME,
                              resumable=size > SIMPLE_UPLOAD_MAX)
        created = svc.files().create(
            body={"name": name, "mimeType": GDOC_MIME},
            media_body=media, fields="id").execute()
    except Exception as exc:
        _sweep_upload(svc, name, orphan_ledger_path)
        raise OracleUploadError("the document could not be uploaded to Google Drive") from exc
    file_id = created.get("id") if isinstance(created, dict) else None
    if not isinstance(file_id, str) or not file_id:
        raise OracleImportError("Google Drive did not create a readable Google Doc")

    export_error = None
    try:
        data = _export_pdf(svc, file_id)
        if not isinstance(data, bytes) or not data:
            raise ValueError("empty or non-binary PDF export")
        with open(out_pdf, "wb") as fh:
            fh.write(data)
    except Exception as exc:
        export_error = exc

    try:
        svc.files().delete(fileId=file_id).execute()
    except Exception as exc:
        try:
            _record_orphan(file_id, orphan_ledger_path)
        except Exception as ledger_exc:
            raise OracleCleanupError("the temporary Google Doc could not be deleted or recorded for recovery") from ledger_exc
        raise OracleCleanupError("the temporary Google Doc could not be deleted") from exc
    if export_error is not None:
        raise OracleExportError("Google Docs did not return a usable PDF export") from export_error
    return out_pdf


def cleanup_orphans(svc=None, ledger_path=None, credentials_path=None, token_path=None):
    """Retry all private recovery IDs; retain the ledger if any delete fails."""
    ledger_path = ledger_path or default_orphan_ledger_path()
    ids = _read_orphans(ledger_path)
    if not ids:
        if os.path.isfile(ledger_path):
            try:
                os.remove(ledger_path)
            except OSError as exc:
                raise OracleCleanupError("the resolved Google Docs recovery ledger could not be removed") from exc
        return 0
    if svc is None:
        svc = service(False, credentials_path, token_path)
    failed = []
    last_failure = None
    for file_id in ids:
        try:
            svc.files().delete(fileId=file_id).execute()
        except Exception as exc:
            failed.append(file_id)
            last_failure = exc
    if failed:
        try:
            _write_private(ledger_path, json.dumps(
                {"schema": LEDGER_SCHEMA, "file_ids": failed}, sort_keys=True) + "\n")
        except OSError as exc:
            raise OracleCleanupError("Google Docs orphan cleanup failed and its ledger could not be updated") from exc
        raise OracleCleanupError("one or more temporary Google Docs could not be deleted") from last_failure
    try:
        os.remove(ledger_path)
    except OSError as exc:
        raise OracleCleanupError("the resolved Google Docs recovery ledger could not be removed") from exc
    return len(ids)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="exactdoc-gdocs")
    parser.add_argument("command", choices=("auth", "cleanup-orphans"))
    parser.add_argument("--credentials")
    parser.add_argument("--token")
    parser.add_argument("--orphan-ledger")
    args = parser.parse_args(argv)
    try:
        if args.command == "auth":
            service(True, args.credentials, args.token)
            print("Google Docs authentication completed.")
        else:
            cleanup_orphans(ledger_path=args.orphan_ledger,
                            credentials_path=args.credentials, token_path=args.token)
            print("Google Docs orphan cleanup completed.")
        return 0
    except (OracleAuthenticationError, OracleUnavailableError, OracleUploadError,
            OracleImportError, OracleExportError, OracleCleanupError) as exc:
        print("error: %s" % exc.message, file=sys.stderr)
        return {"oracle-unavailable": 11, "oracle-auth": 12,
                "oracle-upload": 13, "oracle-import": 14,
                "oracle-export": 15, "oracle-cleanup": 16}[exc.code]


if __name__ == "__main__":
    sys.exit(main())
