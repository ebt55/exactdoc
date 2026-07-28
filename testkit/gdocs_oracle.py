"""Google Docs oracle: measure fidelity in the renderer we actually target.

Every fidelity number in this project so far has been measured through
LibreOffice standing in for Google Docs. They are different renderers, and
they disagree exactly where the design is riskiest -- per-section page
geometry, fixed table layout, column normalisation. This closes that gap.

Round trip per document:
    upload .docx  --(Drive converts)-->  Google Doc
    export        --(Docs renders)   -->  .pdf
    delete the temp file
then score that PDF against the source with the same harness metrics.

Auth: needs `credentials.json` (Desktop-app OAuth client) in the project root.
The first run opens a browser once; the resulting `token.json` is cached and
reused. Scope is `drive.file`, which grants access ONLY to files this script
creates -- it cannot read anything already in your Drive.

Cost: none. The Drive API is free; a full run is a few dozen requests against
a per-user quota in the thousands per 100 seconds.

    python testkit/gdocs_oracle.py auth
    python testkit/gdocs_oracle.py run testkit/batch --sources testkit/adv
"""
import os, sys, glob, json, time, argparse, io

import _paths  # noqa: F401
import harness

PROJECT = _paths.PROJECT
CREDS = os.path.join(PROJECT, "credentials.json")
TOKEN = os.path.join(PROJECT, "token.json")
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
GDOC_MIME = "application/vnd.google-apps.document"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _service(interactive=True):
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(TOKEN):
        creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not interactive:
                raise RuntimeError("no valid token; run: gdocs_oracle.py auth")
            if not os.path.exists(CREDS):
                raise RuntimeError("missing %s" % CREDS)
            flow = InstalledAppFlow.from_client_secrets_file(CREDS, SCOPES)
            creds = flow.run_local_server(port=0,
                                          authorization_prompt_message=
                                          "Opening a browser for Google consent...",
                                          success_message=
                                          "Authorised. You can close this tab.")
        with open(TOKEN, "w") as f:
            f.write(creds.to_json())
        try:
            os.chmod(TOKEN, 0o600)
        except OSError:
            pass
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def roundtrip(svc, docx_path, out_pdf, keep=False):
    """Upload -> convert to a Google Doc -> export PDF -> delete."""
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(docx_path, mimetype=DOCX_MIME, resumable=False)
    meta = {"name": os.path.basename(docx_path), "mimeType": GDOC_MIME}
    f = svc.files().create(body=meta, media_body=media, fields="id").execute()
    fid = f["id"]
    try:
        data = svc.files().export(fileId=fid, mimeType="application/pdf").execute()
        with open(out_pdf, "wb") as fh:
            fh.write(data)
    finally:
        if not keep:
            try:
                svc.files().delete(fileId=fid).execute()
            except Exception:
                pass
    return out_pdf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["auth", "run"])
    ap.add_argument("docx_dir", nargs="?", help="directory of .docx to test")
    ap.add_argument("--sources", nargs="*", default=[],
                    help="directories holding the matching source PDFs")
    ap.add_argument("--out", default=None)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    if a.cmd == "auth":
        _service(interactive=True)
        print("token written to", TOKEN)
        return 0

    svc = _service(interactive=False)
    out = a.out or os.path.join(a.docx_dir, "gdocs")
    os.makedirs(out, exist_ok=True)

    srcmap = {}
    for d in a.sources:
        for p in glob.glob(os.path.join(d, "*.pdf")):
            srcmap[os.path.splitext(os.path.basename(p))[0]] = p

    docxs = sorted(glob.glob(os.path.join(a.docx_dir, "*.docx")))
    if a.limit:
        docxs = docxs[:a.limit]

    rows = []
    for dx in docxs:
        name = os.path.splitext(os.path.basename(dx))[0]
        src = srcmap.get(name)
        if not src:
            print("  skip %-30s (no source PDF)" % name[:30])
            continue
        pdf = os.path.join(out, name + ".gdocs.pdf")
        try:
            t0 = time.time()
            roundtrip(svc, dx, pdf)
            secs = time.time() - t0
        except Exception as e:
            print("  FAIL %-30s %s" % (name[:30], str(e)[:70]))
            continue
        try:
            r = harness.evaluate(src, dx, out, save_images=True,
                                 img_dir=os.path.join(out, "cmp_" + name),
                                 rendered_pdf=pdf)
            r["roundtrip_s"] = round(secs, 1)
            rows.append(r)
            print("GDOCS " + harness.brief(r))
        except Exception as e:
            print("  EVAL FAIL %-26s %s" % (name[:26], str(e)[:70]))

    with open(os.path.join(out, "gdocs_results.json"), "w") as f:
        json.dump(rows, f, indent=1)
    print("\nwrote", os.path.join(out, "gdocs_results.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
