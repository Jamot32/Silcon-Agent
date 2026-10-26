"""Trusted-runner metadata admission only. Never opens private input contents."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

MAX_ROOTS = 16
MAX_ENTRIES = 100_000
MAX_DEPTH = 64
MAX_PATH_BYTES = 4096
NAMESPACES = ("eval/heldout", "eval/dev", "eval/oracles")
FIELDS = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
          "st_size", "st_mtime_ns", "st_ctime_ns")


class AdmissionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__("Private input metadata admission rejected: " + code)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def absolute(value):
    if (type(value) is not str or not value.startswith("/") or
        any(ord(c) < 32 or ord(c) == 127 for c in value) or
        any(p in (".", "..") for p in value.split("/")) or
        os.path.normpath(value) != value):
        raise AdmissionError("path_shape")
    try:
        if len(os.fsencode(value)) > MAX_PATH_BYTES:
            raise AdmissionError("path_bound")
    except UnicodeError:
        raise AdmissionError("path_shape") from None
    return Path(value)


def roster(value):
    if (type(value) is not dict or set(value) != {"schema_version", "roots"} or
        type(value["schema_version"]) is not int or value["schema_version"] != 1 or
        type(value["roots"]) is not list or not 1 <= len(value["roots"]) <= MAX_ROOTS):
        raise AdmissionError("roster_shape")
    paths = tuple(str(absolute(p)) for p in value["roots"])
    if len(set(paths)) != len(paths):
        raise AdmissionError("duplicate_root")
    return tuple(sorted(paths))


def registry(value):
    fields = {"schema_version", "registered_roots", "explicit_private_roots",
              "git_registry_receipt_sha256"}
    if (type(value) is not dict or set(value) != fields or
        type(value["registered_roots"]) is not list or not value["registered_roots"] or
        type(value["explicit_private_roots"]) is not list):
        raise AdmissionError("collector_shape")
    receipt = value["git_registry_receipt_sha256"]
    if (type(receipt) is not str or len(receipt) != 64 or
        any(c not in "0123456789abcdef" for c in receipt)):
        raise AdmissionError("collector_provenance")
    paths = roster({"schema_version": value["schema_version"],
                    "roots": value["registered_roots"] + value["explicit_private_roots"]})
    return paths, {"registered_roots_count": len(value["registered_roots"]),
                   "explicit_private_roots_count": len(value["explicit_private_roots"]),
                   "git_registry_receipt_sha256": receipt}


def configuration(value):
    fields = {"schema_version", "original_project_root", "roots", "git_object_roots", "retained_private_roots",
              "retained_inventory_complete", "max_entries", "max_depth"}
    if type(value) is not dict or set(value) != fields:
        raise AdmissionError("config_shape")
    roots = roster({"schema_version": value["schema_version"], "roots": value["roots"]})
    if str(absolute(value["original_project_root"])) not in roots:
        raise AdmissionError("original_root_missing")
    if value["retained_inventory_complete"] is not True:
        raise AdmissionError("retained_inventory_unadmitted")
    for key, ceiling in (("max_entries", MAX_ENTRIES), ("max_depth", MAX_DEPTH)):
        if type(value[key]) is not int or not 1 <= value[key] <= ceiling:
            raise AdmissionError("scan_bound")
    if (type(value["git_object_roots"]) is not list or not value["git_object_roots"] or
        type(value["retained_private_roots"]) is not list or
        len(value["git_object_roots"]) + len(value["retained_private_roots"]) > 64):
        raise AdmissionError("extra_scope_shape")
    scopes = [(Path(r) / name, "input", False) for r in roots for name in NAMESPACES]
    extras = [(absolute(p), kind, True) for key, kind in
              (("git_object_roots", "git_objects"), ("retained_private_roots", "retained_private"))
              for p in value[key]]
    if len({str(p) for p, _, _ in extras}) != len(extras):
        raise AdmissionError("duplicate_extra_scope")
    for path, _, _ in extras:
        if not any(path.is_relative_to(Path(r)) for r in roots):
            raise AdmissionError("uncovered_private_scope")
    # Explicitly deny dangerous broad roots; never infer coverage from a snapshot.
    if any(r in ("/", "/Users", "/private", "/private/tmp", "/usr", "/System") for r in roots):
        raise AdmissionError("overbroad_root")
    return roots, scopes + extras


def metadata(info):
    return tuple(getattr(info, key) for key in FIELDS)


def chain(path):
    """Reject aliases in every ancestor; return metadata of existing components."""
    result = []
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            return result, False
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise AdmissionError("directory_alias_or_type")
        # Sibling writes outside the audited tree do not change ancestor identity.
        result.append((str(part), metadata(info)[:5]))
    return result, True


def scan(roots, scopes, max_entries, max_depth):
    rows = {}; totals = []; count = 0
    for root in roots:
        ancestors, exists = chain(Path(root))
        if not exists:
            raise AdmissionError("missing_protected_root")
        if Path(root).lstat().st_uid != os.getuid():
            raise AdmissionError("root_owner")
        rows[(root, "ancestors")] = ancestors
    for base, kind, required in scopes:
        ancestors, exists = chain(base)
        rows[(str(base), "ancestors")] = ancestors
        if not exists:
            if required:
                raise AdmissionError("missing_private_scope")
            totals.append({"scope_sha256": digest(os.fsencode(base)), "kind": kind,
                           "present": False, "files": 0, "directories": 0,
                           "bytes": 0, "owner_only_ancestor_observed": None,
                           "relative_identifiers_sha256": []})
            continue
        stack = [(base, 0)]; identifiers = []; files = directories = size = 0
        while stack:
            path, depth = stack.pop()
            if depth > max_depth:
                raise AdmissionError("depth_bound")
            count += 1
            if count > max_entries:
                raise AdmissionError("entry_bound")
            relative = os.fsencode(path.relative_to(base))
            if len(relative) > MAX_PATH_BYTES:
                raise AdmissionError("path_bound")
            identity = digest(os.fsencode(base) + b"\0" + relative)
            before = path.lstat()
            if before.st_uid != os.getuid():
                raise AdmissionError("entry_owner")
            if stat.S_ISREG(before.st_mode):
                if before.st_nlink != 1:
                    raise AdmissionError("file_hardlink")
                if kind == "git_objects" and relative == b"info/alternates":
                    raise AdmissionError("git_alternates_unassessed")
                files += 1; size += before.st_size
            elif stat.S_ISDIR(before.st_mode):
                directories += 1
                with os.scandir(path) as entries:
                    children = []
                    for entry in entries:
                        if count + len(stack) + len(children) + 1 > max_entries:
                            raise AdmissionError("entry_bound")
                        children.append(Path(entry.path))
                    children.sort(reverse=True)
                # Directory enumeration must not replace or mutate its container.
                if metadata(path.lstat()) != metadata(before):
                    raise AdmissionError("metadata_changed")
                stack.extend((child, depth + 1) for child in children)
            else:
                raise AdmissionError("entry_alias_or_type")
            rows[(str(base), relative)] = metadata(before)
            identifiers.append(identity)
        totals.append({"scope_sha256": digest(os.fsencode(base)), "kind": kind,
                       "present": True, "files": files, "directories": directories,
                       "owner_only_ancestor_observed": any(
                           info[3] == os.getuid() and stat.S_IMODE(info[2]) == 0o700
                           for _, info in ancestors),
                       "bytes": size, "relative_identifiers_sha256": sorted(identifiers)})
    return rows, totals


def admit(config, registry_reader):
    """registry_reader supplies fresh trusted registry METADATA, not input bodies.

    The host must collect the registry itself; this helper performs no Git calls.
    Two supplied identical stale snapshots cannot prove a current live registry.
    """
    try:
        roots, scopes = configuration(config)
        before, provenance_before = registry(registry_reader())
        if before != roots:
            raise AdmissionError("roster_drift")
        first, totals = scan(roots, scopes, config["max_entries"], config["max_depth"])
        second, _ = scan(roots, scopes, config["max_entries"], config["max_depth"])
        if first != second:
            raise AdmissionError("metadata_changed")
        after, provenance_after = registry(registry_reader())
        if after != before:
            raise AdmissionError("roster_drift")
        return {"kind": "private_input_metadata_point_admission", "passed": True,
                "protected_roots_count": len(roots), "roster_sha256": digest(encode(before)),
                "collector_before": provenance_before, "collector_after": provenance_after,
                "config_sha256": digest(encode(config)), "scopes": totals,
                "input_content_reads": 0, "continuous_isolation_proved": False,
                "arbitrary_copied_content_absence_proved": False,
                "host_registry_collection_and_completeness_trusted": True}
    except AdmissionError:
        raise
    except (OSError, RuntimeError, TypeError, ValueError, UnicodeError):
        raise AdmissionError("metadata_io_or_shape") from None


def read_metadata_json(path):
    # Only caller-owned CONFIG/REGISTRY JSON metadata is opened, never scan targets.
    with Path(path).open("rb") as stream:
        raw = stream.read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        raise AdmissionError("config_bound")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AdmissionError("duplicate_json_key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--registry-before", required=True)
    parser.add_argument("--registry-after", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--release-received", action="store_true")
    args = parser.parse_args()
    if not (args.execute and args.release_received):
        parser.error("Actual metadata traversal requires explicit root release.")
    try:
        inputs = iter([args.registry_before, args.registry_after])
        report = admit(read_metadata_json(args.config), lambda: read_metadata_json(next(inputs)))
        status = 0
    except AdmissionError as error:
        report = {"kind": "private_input_metadata_point_admission", "passed": False,
                  "code": error.code, "input_content_reads": 0}
        status = 1
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(report, stream, indent=2, sort_keys=True); stream.write("\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
