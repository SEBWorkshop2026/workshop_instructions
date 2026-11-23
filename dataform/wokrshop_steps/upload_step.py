#!/usr/bin/env python3
"""Upload a public workshop snapshot to a Dataform development workspace."""

import argparse
import base64
import io
import json
from pathlib import PurePosixPath
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zipfile import BadZipFile, ZipFile


ARCHIVE_URL = "https://codeload.github.com/SEBWorkshop2026/workshop_instructions/zip/refs/heads/main"
SNAPSHOTS = ("01-sources", "02-external", "03-bronze", "04-silver", "05-gold")
LAYERS = ("sources", "external", "bronze", "silver", "gold")
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024


def load_snapshot(step):
    with urlopen(ARCHIVE_URL, timeout=60) as response:
        archive = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError("Workshop archive is too large.")

    prefix = f"workshop_instructions-main/dataform/wokrshop_steps/{SNAPSHOTS[step - 1]}/"
    files = {}
    with ZipFile(io.BytesIO(archive)) as zipped:
        for entry in zipped.infolist():
            if not entry.filename.startswith(prefix) or entry.is_dir():
                continue
            relative = entry.filename[len(prefix):]
            path = PurePosixPath(relative)
            if (
                not relative
                or path.is_absolute()
                or ".." in path.parts
                or str(path) != relative
                or entry.file_size > MAX_FILE_BYTES
                or relative in files
            ):
                raise ValueError(f"Invalid snapshot file: {relative}")
            if relative == "workflow_settings.yaml" or (
                len(path.parts) == 2 and path.parts[0] == "includes" and path.suffix == ".js"
            ) or (
                len(path.parts) == 3 and path.parts[0] == "definitions"
                and path.parts[1] in LAYERS[:step] and path.suffix == ".sqlx"
            ):
                files[relative] = zipped.read(entry)
            else:
                raise ValueError(f"Unexpected snapshot file: {relative}")

    required = {"workflow_settings.yaml", "includes/csvBucket.js", "includes/reportingDate.js"}
    if not required.issubset(files) or any(
        not any(path.startswith(f"definitions/{layer}/") for path in files)
        for layer in LAYERS[:step]
    ):
        raise ValueError("Snapshot is missing required settings, includes, or definitions.")
    return files


class Workspace:
    def __init__(self, project, location, repository, workspace, token):
        resource = "/".join(
            part
            for label, value in (
                ("projects", project),
                ("locations", location),
                ("repositories", repository),
                ("workspaces", workspace),
            )
            for part in (label, quote(value, safe=""))
        )
        self.url = f"https://dataform.googleapis.com/v1/{resource}"
        self.token = token

    def request(self, action, *, params=None, body=None):
        url = f"{self.url}:{action}"
        if params:
            url += "?" + urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            with urlopen(Request(url, data=data, headers=headers), timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Dataform {action} failed (HTTP {error.code}): {detail}") from error

    def list_files(self):
        files = set()
        directories = {""}
        pending = [""]
        while pending:
            directory = pending.pop()
            page_token = None
            while True:
                params = {}
                if directory:
                    params["path"] = directory
                if page_token:
                    params["pageToken"] = page_token
                result = self.request("queryDirectoryContents", params=params)
                for entry in result.get("directoryEntries", []):
                    if "file" in entry:
                        files.add(entry["file"])
                    elif "directory" in entry:
                        directories.add(entry["directory"])
                        if directory or entry["directory"] in ("definitions", "includes"):
                            pending.append(entry["directory"])
                    else:
                        raise ValueError(f"Unexpected workspace directory entry: {entry}")
                page_token = result.get("nextPageToken")
                if not page_token:
                    break
        return files, directories

    def read_file(self, path):
        result = self.request("readFile", params={"path": path})
        return base64.b64decode(result["fileContents"], validate=True)

    def make_directory(self, path):
        self.request("makeDirectory", body={"path": path})

    def write_file(self, path, contents):
        self.request("writeFile", body={
            "path": path,
            "contents": base64.b64encode(contents).decode("ascii"),
        })


def upload_snapshot(workspace, snapshot):
    remote_files, remote_dirs = workspace.list_files()
    directories = set()
    for path in snapshot:
        parent = PurePosixPath(path).parent
        while str(parent) != ".":
            directories.add(str(parent))
            parent = parent.parent
    for directory in sorted(directories):
        if directory in remote_files:
            raise ValueError(f"Workspace file blocks snapshot directory: {directory}")
    for path in snapshot:
        if path in remote_dirs:
            raise ValueError(f"Workspace directory blocks snapshot file: {path}")

    changed = {
        path: contents for path, contents in snapshot.items()
        if path not in remote_files or workspace.read_file(path) != contents
    }
    extras = sorted(
        path for path in remote_files - snapshot.keys()
        if path.startswith(("definitions/", "includes/")) and path.endswith((".sqlx", ".js"))
    )
    if extras:
        print("These workspace code files are not in the snapshot and will remain:")
        for path in extras:
            print(f"  {path}")

    for directory in sorted(directories - remote_dirs, key=lambda path: (path.count("/"), path)):
        workspace.make_directory(directory)
        print(f"Created directory {directory}")
    for path, contents in sorted(changed.items()):
        workspace.write_file(path, contents)
        print(f"Uploaded {path}")
    print(f"Done: {len(changed)} file(s) uploaded. Changes are uncommitted; no workflow was run.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--participant", required=True, type=int, help="Your participant number")
    parser.add_argument("--workspace", required=True, help="Your existing development workspace ID")
    parser.add_argument("--step", required=True, type=int, choices=range(1, 6), help="Snapshot number (1-5)")
    parser.add_argument("--project", default="ws2026-02", help="Google Cloud project ID")
    parser.add_argument("--location", default="europe-west1", help="Dataform repository location")
    args = parser.parse_args()
    if args.participant < 1:
        parser.error("--participant must be a positive number")

    snapshot = load_snapshot(args.step)
    token = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout.strip()
    if not token:
        raise ValueError("gcloud returned an empty access token.")
    workspace = Workspace(
        args.project, args.location, f"participant-{args.participant}", args.workspace, token
    )
    upload_snapshot(workspace, snapshot)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, BadZipFile, subprocess.CalledProcessError, URLError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
