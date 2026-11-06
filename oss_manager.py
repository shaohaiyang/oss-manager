#!/usr/bin/env python3
from __future__ import annotations

import argparse
import mimetypes
import os
import sys
from dataclasses import dataclass
from typing import Optional

try:
    import alibabacloud_oss_v2 as oss
    from alibabacloud_oss_v2 import exceptions
except ModuleNotFoundError:
    project_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(project_dir, ".venv", "bin", "python"),
        os.path.join(project_dir, ".venv", "Scripts", "python.exe"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            os.execv(candidate, [candidate, *sys.argv])
    raise SystemExit(
        "Missing dependency alibabacloud-oss-v2.\n"
        "Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    )

DEFAULT_ROOT = "oss://your-bucket/shared"
BATCH_SIZE = 1000
SINGLE_OPERATION_LIMIT = 5 * 1024**3
MIN_PART_SIZE = 64 * 1024**2
MAX_PARTS = 10000


class UserError(Exception):
    pass


@dataclass
class Target:
    bucket: str
    key: str
    rel: str


def human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num} B"


class OssManager:
    def __init__(self, client: oss.Client, bucket: str, root: str):
        self.client = client
        self.bucket = bucket
        self.root = root.strip("/")

    def resolve(self, path: str) -> Target:
        raw = (path or "").strip().replace("\\", "/")
        if raw.startswith("oss://"):
            rest = raw[len("oss://"):]
            bucket, _, key = rest.partition("/")
            if not bucket:
                raise UserError("invalid OSS path, bucket is missing")
            key = key.strip("/")
            return Target(bucket, key, self.display_key(key))

        raw = raw.strip("/")
        parts = [p for p in raw.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise UserError("path must not contain '..'")

        root_parts = [p for p in self.root.split("/") if p]
        if parts[: len(root_parts)] == root_parts:
            parts = parts[len(root_parts):]
        rel = "/".join(parts)
        key = "/".join(root_parts + parts)
        return Target(self.bucket, key, rel)

    def display_key(self, key: str) -> str:
        if not self.root:
            return key
        if key == self.root:
            return ""
        if key.startswith(self.root + "/"):
            return key[len(self.root) + 1:]
        return key

    def folder_prefix(self, target: Target) -> str:
        return target.key.rstrip("/") + "/" if target.key else ""

    def with_new_name(self, target: Target, new_name: str) -> Target:
        if not new_name or new_name in (".", "..") or "/" in new_name or "\\" in new_name:
            raise UserError("--new-name must be a simple name without path separators")
        key = target.key.rstrip("/")
        parent, _, _ = key.rpartition("/")
        new_key = f"{parent}/{new_name}" if parent else new_name
        return Target(target.bucket, new_key, self.display_key(new_key))

    def list_keys(self, bucket: str, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.client.list_objects_v2_paginator()
        for page in paginator.iter_page(
            oss.ListObjectsV2Request(bucket=bucket, prefix=prefix)
        ):
            for obj in page.contents or []:
                keys.append(obj.key)
        return keys

    def delete_keys(self, bucket: str, keys: list[str]) -> int:
        unique = list(dict.fromkeys(keys))
        for start in range(0, len(unique), BATCH_SIZE):
            batch = unique[start:start + BATCH_SIZE]
            self.client.delete_multiple_objects(
                oss.DeleteMultipleObjectsRequest(
                    bucket=bucket,
                    objects=[oss.DeleteObject(key=key) for key in batch],
                    quiet=True,
                )
            )
        return len(unique)

    @staticmethod
    def part_size_for(size: int) -> int:
        return max(MIN_PART_SIZE, (size + MAX_PARTS - 1) // MAX_PARTS)

    def copy_object(
        self, source_bucket: str, source_key: str, bucket: str, key: str
    ) -> None:
        meta = self.client.head_object(
            oss.HeadObjectRequest(bucket=source_bucket, key=source_key)
        )
        size = meta.content_length or 0
        if size <= SINGLE_OPERATION_LIMIT:
            self.client.copy_object(
                oss.CopyObjectRequest(
                    bucket=bucket,
                    key=key,
                    source_bucket=source_bucket,
                    source_key=source_key,
                )
            )
            return

        upload = self.client.initiate_multipart_upload(
            oss.InitiateMultipartUploadRequest(bucket=bucket, key=key)
        )
        upload_id = upload.upload_id
        part_size = self.part_size_for(size)
        parts: list[oss.UploadPart] = []
        try:
            part_number = 1
            start = 0
            while start < size:
                end = min(start + part_size, size) - 1
                result = self.client.upload_part_copy(
                    oss.UploadPartCopyRequest(
                        bucket=bucket,
                        key=key,
                        part_number=part_number,
                        upload_id=upload_id,
                        source_bucket=source_bucket,
                        source_key=source_key,
                        source_range=f"bytes={start}-{end}",
                    )
                )
                parts.append(
                    oss.UploadPart(part_number=part_number, etag=result.etag)
                )
                part_number += 1
                start = end + 1
            self.client.complete_multipart_upload(
                oss.CompleteMultipartUploadRequest(
                    bucket=bucket,
                    key=key,
                    upload_id=upload_id,
                    complete_multipart_upload=oss.CompleteMultipartUpload(parts=parts),
                )
            )
        except Exception:
            try:
                self.client.abort_multipart_upload(
                    oss.AbortMultipartUploadRequest(
                        bucket=bucket, key=key, upload_id=upload_id
                    )
                )
            except Exception:
                pass
            raise

    def multipart_upload(
        self,
        bucket: str,
        key: str,
        handle,
        size: int,
        content_type: Optional[str],
    ) -> None:
        upload = self.client.initiate_multipart_upload(
            oss.InitiateMultipartUploadRequest(
                bucket=bucket, key=key, content_type=content_type
            )
        )
        upload_id = upload.upload_id
        part_size = self.part_size_for(size)
        parts: list[oss.UploadPart] = []
        try:
            part_number = 1
            remaining = size
            while remaining > 0:
                data = handle.read(min(part_size, remaining))
                if not data:
                    break
                result = self.client.upload_part(
                    oss.UploadPartRequest(
                        bucket=bucket,
                        key=key,
                        part_number=part_number,
                        upload_id=upload_id,
                        body=data,
                        content_length=len(data),
                    )
                )
                parts.append(
                    oss.UploadPart(part_number=part_number, etag=result.etag)
                )
                part_number += 1
                remaining -= len(data)
            self.client.complete_multipart_upload(
                oss.CompleteMultipartUploadRequest(
                    bucket=bucket,
                    key=key,
                    upload_id=upload_id,
                    complete_multipart_upload=oss.CompleteMultipartUpload(parts=parts),
                )
            )
        except Exception:
            try:
                self.client.abort_multipart_upload(
                    oss.AbortMultipartUploadRequest(
                        bucket=bucket, key=key, upload_id=upload_id
                    )
                )
            except Exception:
                pass
            raise

    def put_from_source(
        self,
        bucket: str,
        key: str,
        content: Optional[str],
        from_file: Optional[str],
    ) -> None:
        if content is not None and from_file is not None:
            raise UserError("--content and --from cannot be used together")

        if from_file == "-":
            data = sys.stdin.buffer.read()
            self.client.put_object(
                oss.PutObjectRequest(bucket=bucket, key=key, body=data)
            )
            return

        if from_file is not None:
            if not os.path.isfile(from_file):
                raise UserError(f"local file not found: {from_file}")
            size = os.path.getsize(from_file)
            content_type, _ = mimetypes.guess_type(from_file)
            with open(from_file, "rb") as handle:
                if size > SINGLE_OPERATION_LIMIT:
                    self.multipart_upload(
                        bucket, key, handle, size, content_type
                    )
                else:
                    self.client.put_object(
                        oss.PutObjectRequest(
                            bucket=bucket,
                            key=key,
                            body=handle,
                            content_length=size,
                            content_type=content_type,
                        )
                    )
            return

        data = (content or "").encode("utf-8")
        self.client.put_object(
            oss.PutObjectRequest(
                bucket=bucket,
                key=key,
                body=data,
                content_type="text/plain; charset=utf-8",
            )
        )

    def create_folder(self, path: str) -> None:
        target = self.resolve(path)
        if not target.rel:
            raise UserError("cannot create the root folder")
        marker = self.folder_prefix(target)
        if self.client.is_object_exist(target.bucket, marker):
            raise UserError(f"folder already exists: {self.display_key(marker)}")
        self.client.put_object(
            oss.PutObjectRequest(bucket=target.bucket, key=marker, body=b"")
        )
        print(f"Created folder: {self.display_key(marker)}")

    def create_file(
        self,
        path: str,
        content: Optional[str],
        from_file: Optional[str],
        overwrite: bool,
    ) -> None:
        target = self.resolve(path)
        if not target.rel:
            raise UserError("cannot create a file at the root path, specify a file name")
        key = target.key.rstrip("/")
        if not overwrite and self.client.is_object_exist(target.bucket, key):
            raise UserError(
                f"file already exists, use --overwrite: {self.display_key(key)}"
            )
        self.put_from_source(target.bucket, key, content, from_file)
        print(f"Created file: {self.display_key(key)}")

    def delete_folder(self, path: str, recursive: bool, force: bool) -> None:
        target = self.resolve(path)
        if not target.rel:
            raise UserError("refusing to delete the root folder")
        prefix = self.folder_prefix(target)
        keys = self.list_keys(target.bucket, prefix)
        if not keys:
            if force:
                print(f"Folder not found, skipped: {self.display_key(prefix)}")
                return
            raise UserError(f"folder not found: {self.display_key(prefix)}")
        children = [key for key in keys if key != prefix]
        if children and not recursive:
            raise UserError(
                f"folder is not empty ({len(children)} objects), use --recursive"
            )
        count = self.delete_keys(target.bucket, keys)
        print(f"Deleted folder: {self.display_key(prefix)} ({count} objects)")

    def delete_file(self, path: str, force: bool) -> None:
        target = self.resolve(path)
        if not target.rel:
            raise UserError("please specify a file path")
        key = target.key.rstrip("/")
        if not self.client.is_object_exist(target.bucket, key):
            if force:
                print(f"File not found, skipped: {self.display_key(key)}")
                return
            raise UserError(f"file not found: {self.display_key(key)}")
        self.client.delete_object(
            oss.DeleteObjectRequest(bucket=target.bucket, key=key)
        )
        print(f"Deleted file: {self.display_key(key)}")

    def modify_folder(
        self,
        path: str,
        new_name: Optional[str],
        to_path: Optional[str],
        overwrite: bool,
    ) -> None:
        target = self.resolve(path)
        if not target.rel:
            raise UserError("cannot rename the root folder")
        if new_name and to_path:
            raise UserError("--new-name and --to cannot be used together")

        if new_name:
            destination = self.with_new_name(target, new_name)
        elif to_path:
            destination = self.resolve(to_path)
        else:
            raise UserError("specify --new-name or --to")

        source_prefix = self.folder_prefix(target)
        dest_prefix = self.folder_prefix(destination)
        if destination.bucket == target.bucket and dest_prefix == source_prefix:
            raise UserError("source and destination are the same")

        source_keys = self.list_keys(target.bucket, source_prefix)
        if not source_keys:
            raise UserError(f"folder not found: {self.display_key(source_prefix)}")

        if not overwrite and self.list_keys(destination.bucket, dest_prefix):
            raise UserError(
                f"destination folder already exists, use --overwrite: "
                f"{self.display_key(dest_prefix)}"
            )

        copied = 0
        for source_key in source_keys:
            suffix = source_key[len(source_prefix):]
            dest_key = dest_prefix + suffix
            if destination.bucket == target.bucket and dest_key == source_key:
                continue
            self.copy_object(
                target.bucket, source_key, destination.bucket, dest_key
            )
            copied += 1

        self.delete_keys(target.bucket, source_keys)
        print(
            f"Modified folder: {self.display_key(source_prefix)} -> "
            f"{self.display_key(dest_prefix)} ({copied} objects moved)"
        )

    def modify_file(
        self,
        path: str,
        new_name: Optional[str],
        to_path: Optional[str],
        content: Optional[str],
        from_file: Optional[str],
        overwrite: bool,
    ) -> None:
        target = self.resolve(path)
        if not target.rel:
            raise UserError("please specify a file path")
        if new_name and to_path:
            raise UserError("--new-name and --to cannot be used together")

        source_key = target.key.rstrip("/")
        if not self.client.is_object_exist(target.bucket, source_key):
            raise UserError(f"file not found: {self.display_key(source_key)}")

        if new_name:
            destination = self.with_new_name(target, new_name)
        elif to_path:
            destination = self.resolve(to_path)
        else:
            destination = target

        dest_key = destination.key.rstrip("/")
        has_new_content = content is not None or from_file is not None
        same_object = (
            destination.bucket == target.bucket and dest_key == source_key
        )

        if same_object:
            if not has_new_content:
                raise UserError("nothing to modify, specify --content/--from or --new-name/--to")
            self.put_from_source(target.bucket, source_key, content, from_file)
            print(f"Modified file content: {self.display_key(source_key)}")
            return

        if not overwrite and self.client.is_object_exist(destination.bucket, dest_key):
            raise UserError(
                f"destination already exists, use --overwrite: {self.display_key(dest_key)}"
            )

        if has_new_content:
            self.put_from_source(destination.bucket, dest_key, content, from_file)
        else:
            self.copy_object(
                target.bucket, source_key, destination.bucket, dest_key
            )
        self.client.delete_object(
            oss.DeleteObjectRequest(bucket=target.bucket, key=source_key)
        )
        print(
            f"Modified file: {self.display_key(source_key)} -> "
            f"{self.display_key(dest_key)}"
        )

    def list_objects(self, path: str, recursive: bool, long_format: bool) -> None:
        target = self.resolve(path)
        prefix = self.folder_prefix(target)

        if target.key and self.client.is_object_exist(target.bucket, target.key):
            obj = self.client.head_object(
                oss.HeadObjectRequest(bucket=target.bucket, key=target.key)
            )
            self._print_rows(
                [("FILE", target.key, obj.content_length, obj.last_modified)],
                long_format,
            )
            return

        rows: list[tuple[str, str, Optional[int], Optional[object]]] = []
        seen: set[str] = set()
        paginator = self.client.list_objects_v2_paginator()
        request = {"bucket": target.bucket, "prefix": prefix}
        if not recursive:
            request["delimiter"] = "/"

        for page in paginator.iter_page(oss.ListObjectsV2Request(**request)):
            for prefix_info in page.common_prefixes or []:
                key = prefix_info.prefix
                if key not in seen:
                    seen.add(key)
                    rows.append(("DIR", key, None, None))
            for obj in page.contents or []:
                key = obj.key
                if key == prefix or key in seen:
                    continue
                seen.add(key)
                if key.endswith("/"):
                    rows.append(("DIR", key, None, None))
                else:
                    rows.append(("FILE", key, obj.size, obj.last_modified))

        if not rows:
            print("(empty)")
            return

        rows.sort(key=lambda row: (0 if row[0] == "DIR" else 1, row[1]))
        self._print_rows(rows, long_format)

    def _print_rows(
        self,
        rows: list[tuple[str, str, Optional[int], Optional[object]]],
        long_format: bool,
    ) -> None:
        if not long_format:
            for _, key, _, _ in rows:
                print(self.display_key(key))
            return

        print(f"{'TYPE':<5} {'SIZE':>10}  {'LAST MODIFIED':<19}  PATH")
        for kind, key, size, modified in rows:
            display = self.display_key(key)
            if kind == "DIR":
                print(f"{kind:<5} {'-':>10}  {'-':<19}  {display}")
            else:
                modified_text = (
                    modified.strftime("%Y-%m-%d %H:%M:%S") if modified else "-"
                )
                print(
                    f"{kind:<5} {human_size(size or 0):>10}  "
                    f"{modified_text:<19}  {display}"
                )


def parse_root(root_arg: str, bucket_override: Optional[str]) -> tuple[str, str]:
    root = (root_arg or "").strip()
    bucket: Optional[str]
    if root.startswith("oss://"):
        rest = root[len("oss://"):]
        bucket, _, prefix = rest.partition("/")
        prefix = prefix.strip("/")
    else:
        bucket = None
        prefix = root.strip("/")
    if bucket_override:
        bucket = bucket_override
    if not bucket:
        raise UserError(
            "bucket is required, set OSS_BUCKET or use --root oss://<bucket>/<prefix>"
        )
    return bucket, prefix


def build_client(args: argparse.Namespace) -> oss.Client:
    credentials_provider = oss.credentials.EnvironmentVariableCredentialsProvider()

    cfg = oss.config.load_default()
    cfg.credentials_provider = credentials_provider

    region = args.region or os.getenv("OSS_REGION")
    if not region:
        raise UserError("region is required, set OSS_REGION or pass --region")
    cfg.region = region

    endpoint = args.endpoint or os.getenv("OSS_ENDPOINT")
    if endpoint:
        cfg.endpoint = endpoint

    return oss.Client(cfg)


def add_common_options(
    parser: argparse.ArgumentParser, suppressed: bool = False
) -> None:
    def default(value=None):
        return argparse.SUPPRESS if suppressed else value

    parser.add_argument(
        "--region", default=default(), help="OSS region, e.g. cn-hangzhou"
    )
    parser.add_argument("--endpoint", default=default(), help="OSS endpoint")
    parser.add_argument(
        "--root",
        default=default(os.getenv("OSS_ROOT", DEFAULT_ROOT)),
        help=f"root OSS path or prefix (default: {DEFAULT_ROOT})",
    )
    parser.add_argument(
        "--bucket", default=default(os.getenv("OSS_BUCKET")), help="bucket name"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oss_manager.py",
        description="Manage folders and files under an OSS prefix (Python SDK v2).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "credentials: OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET\n"
            "region      : OSS_REGION (or --region)\n"
            "endpoint    : OSS_ENDPOINT (optional, or --endpoint)\n"
            "root        : OSS_ROOT (default oss://your-bucket/shared, or --root)\n"
            "bucket      : OSS_BUCKET (optional, overrides bucket in root)\n"
            "\n"
            "examples:\n"
            "  oss_manager.py list\n"
            "  oss_manager.py list docs --recursive --long\n"
            "  oss_manager.py create folder docs/2026\n"
            "  oss_manager.py create file docs/readme.txt --content 'hello'\n"
            "  oss_manager.py create file docs/photo.jpg --from ./photo.jpg\n"
            "  oss_manager.py modify file docs/readme.txt --content 'new text'\n"
            "  oss_manager.py modify file docs/readme.txt --new-name notes.txt\n"
            "  oss_manager.py modify folder docs/2026 --new-name archive\n"
            "  oss_manager.py delete file docs/notes.txt\n"
            "  oss_manager.py delete folder docs/archive --recursive\n"
        ),
    )
    add_common_options(parser)

    commands = parser.add_subparsers(dest="command", required=True)

    create_parser = commands.add_parser("create", help="create a folder or file")
    add_common_options(create_parser, suppressed=True)
    create_kinds = create_parser.add_subparsers(dest="kind", required=True)

    create_folder = create_kinds.add_parser("folder", help="create a folder")
    add_common_options(create_folder, suppressed=True)
    create_folder.add_argument("path", help="folder path relative to root")
    create_folder.set_defaults(handler="create_folder")

    create_file = create_kinds.add_parser("file", help="create a file")
    add_common_options(create_file, suppressed=True)
    create_file.add_argument("path", help="file path relative to root")
    create_file.add_argument("--content", help="file content as text")
    create_file.add_argument("--from", dest="from_file", metavar="LOCAL",
                             help="upload from a local file, use - for stdin")
    create_file.add_argument("--overwrite", action="store_true",
                             help="overwrite if the file already exists")
    create_file.set_defaults(handler="create_file")

    delete_parser = commands.add_parser("delete", help="delete a folder or file")
    add_common_options(delete_parser, suppressed=True)
    delete_kinds = delete_parser.add_subparsers(dest="kind", required=True)

    delete_folder = delete_kinds.add_parser("folder", help="delete a folder")
    add_common_options(delete_folder, suppressed=True)
    delete_folder.add_argument("path", help="folder path relative to root")
    delete_folder.add_argument("--recursive", action="store_true",
                               help="delete all objects under the folder")
    delete_folder.add_argument("--force", action="store_true",
                               help="do not fail when the folder does not exist")
    delete_folder.set_defaults(handler="delete_folder")

    delete_file = delete_kinds.add_parser("file", help="delete a file")
    add_common_options(delete_file, suppressed=True)
    delete_file.add_argument("path", help="file path relative to root")
    delete_file.add_argument("--force", action="store_true",
                             help="do not fail when the file does not exist")
    delete_file.set_defaults(handler="delete_file")

    modify_parser = commands.add_parser("modify", help="rename or update a folder/file")
    add_common_options(modify_parser, suppressed=True)
    modify_kinds = modify_parser.add_subparsers(dest="kind", required=True)

    modify_folder = modify_kinds.add_parser("folder", help="rename/move a folder")
    add_common_options(modify_folder, suppressed=True)
    modify_folder.add_argument("path", help="folder path relative to root")
    modify_folder.add_argument("--new-name", help="new name in the same parent folder")
    modify_folder.add_argument("--to", dest="to_path",
                               help="destination path relative to root")
    modify_folder.add_argument("--overwrite", action="store_true",
                               help="overwrite the destination folder")
    modify_folder.set_defaults(handler="modify_folder")

    modify_file = modify_kinds.add_parser("file", help="update/rename/move a file")
    add_common_options(modify_file, suppressed=True)
    modify_file.add_argument("path", help="file path relative to root")
    modify_file.add_argument("--new-name", help="new name in the same folder")
    modify_file.add_argument("--to", dest="to_path",
                             help="destination path relative to root")
    modify_file.add_argument("--content", help="replace file content as text")
    modify_file.add_argument("--from", dest="from_file", metavar="LOCAL",
                             help="replace content from a local file, use - for stdin")
    modify_file.add_argument("--overwrite", action="store_true",
                             help="overwrite the destination file")
    modify_file.set_defaults(handler="modify_file")

    list_parser = commands.add_parser("list", help="list folders and files")
    add_common_options(list_parser, suppressed=True)
    list_parser.add_argument("path", nargs="?", default="",
                             help="folder path relative to root (default: root)")
    list_parser.add_argument("--recursive", action="store_true",
                             help="list all nested objects")
    list_parser.add_argument("-l", "--long", action="store_true",
                             help="show size and last modified time")
    list_parser.set_defaults(handler="list_objects")

    return parser


def dispatch(manager: OssManager, args: argparse.Namespace) -> None:
    handler = getattr(manager, args.handler)
    if args.handler == "create_folder":
        handler(args.path)
    elif args.handler == "create_file":
        handler(args.path, args.content, args.from_file, args.overwrite)
    elif args.handler == "delete_folder":
        handler(args.path, args.recursive, args.force)
    elif args.handler == "delete_file":
        handler(args.path, args.force)
    elif args.handler == "modify_folder":
        handler(args.path, args.new_name, args.to_path, args.overwrite)
    elif args.handler == "modify_file":
        handler(
            args.path,
            args.new_name,
            args.to_path,
            args.content,
            args.from_file,
            args.overwrite,
        )
    elif args.handler == "list_objects":
        handler(args.path, args.recursive, args.long)
    else:
        raise UserError(f"unknown handler: {args.handler}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        bucket, root = parse_root(args.root, args.bucket)
        client = build_client(args)
        manager = OssManager(client, bucket, root)
        dispatch(manager, args)
        return 0
    except UserError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except exceptions.OperationError as exc:
        detail = exc.unwrap()
        if isinstance(detail, exceptions.ServiceError):
            print(
                f"OSS error [{detail.status_code} {detail.code}]: "
                f"{detail.message} (request id: {detail.request_id})",
                file=sys.stderr,
            )
        else:
            print(f"OSS SDK error: {detail}", file=sys.stderr)
        return 1
    except exceptions.ServiceError as exc:
        print(
            f"OSS error [{exc.status_code} {exc.code}]: {exc.message} "
            f"(request id: {exc.request_id})",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
