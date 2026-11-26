#!/usr/bin/env python3
"""Worst Superpower -- make.fun entry (revised entrypoint).

Writes one line inventing the most useless superpower to
$MAKEFUN_OUTPUT_DIR/entry.txt (default /output).

Before anything touches the disk, the entry passes a strict
gate: one line, 1 to 140 characters, more than whitespace, no
leading or trailing whitespace, and no control characters, C1
controls, byte order mark, line or paragraph separators,
invisible format characters, or surrogates. The write is atomic
and deterministic -- identical bytes on every run -- using a
temp file staged inside the output directory, os.replace,
chmod 0644 on both the temp file and the final file, fsync of
the file and of the directory, and a read-back check of the
bytes that landed on disk.

Python 3.13 standard library only.
"""

import os
import tempfile
import unicodedata

ENTRY = (
    "I can make any microwave finish one second early, "
    "but only microwaves in other people's kitchens."
)

DEFAULT_OUTPUT_DIR = "/output"
MAX_ENTRY_CHARS = 140
TMP_PREFIX = ".entry-"
TMP_SUFFIX = ".tmp"


def _reject_blank_shape(text):
    """Reject a non-string, empty, or whitespace-only entry."""
    if not isinstance(text, str):
        raise ValueError("entry must be a string, got %s" % type(text).__name__)
    if not text:
        raise ValueError("entry is empty")
    if not text.strip():
        raise ValueError("entry is only white space")


def _reject_bad_length(text):
    """Reject an entry outside the 1 to 140 character gate."""
    if len(text) > MAX_ENTRY_CHARS:
        raise ValueError(
            "entry is %d characters, over the %d-character limit"
            % (len(text), MAX_ENTRY_CHARS)
        )


def _reject_multiline_or_padded(text):
    """Reject newlines, carriage returns, and surrounding whitespace."""
    if "\n" in text or "\r" in text:
        raise ValueError("entry must be a single line")
    if text != text.strip():
        raise ValueError("entry has leading or trailing white space")


def _forbidden_reason(ch):
    """Return why *ch* may not appear in an entry, or None if allowed."""
    code = ord(ch)
    if code < 0x20 or code == 0x7F:
        return "control character (U+%04X)" % code
    if 0x80 <= code <= 0x9F:
        return "C1 control character (U+%04X)" % code
    if code == 0xFEFF:
        return "byte order mark (U+FEFF)"
    if code in (0x2028, 0x2029):
        return "line separator (U+%04X)" % code
    if 0xD800 <= code <= 0xDFFF:
        return "surrogate (U+%04X)" % code
    if unicodedata.category(ch) in ("Cf", "Cc", "Cs", "Co", "Cn"):
        return "invisible or unassigned character (U+%04X)" % code
    return None


def _reject_forbidden_characters(text):
    """Reject any character the gate forbids, naming the first one."""
    for ch in text:
        reason = _forbidden_reason(ch)
        if reason is not None:
            raise ValueError("entry contains a %s" % reason)


def check_entry(text):
    """Run every gate check on *text*; raise ValueError on failure.

    The checks are split so each rule has its own home: shape,
    length, single-line form, and character set. A bad entry is
    always rejected loudly here, never silently written out.
    """
    _reject_blank_shape(text)
    _reject_bad_length(text)
    _reject_multiline_or_padded(text)
    _reject_forbidden_characters(text)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("entry is not encodable as UTF-8: %s" % exc) from exc


def locate_output_directory():
    """Return the output directory, falling back on a blank env value.

    An unset variable, an empty string, or a value that is only
    whitespace all mean the default. A value naming an existing
    file instead of a directory is rejected loudly rather than
    failing later inside makedirs.
    """
    raw = os.environ.get("MAKEFUN_OUTPUT_DIR")
    if raw is None or not raw.strip():
        return DEFAULT_OUTPUT_DIR
    out_dir = raw.strip()
    if os.path.exists(out_dir) and not os.path.isdir(out_dir):
        raise NotADirectoryError(
            "MAKEFUN_OUTPUT_DIR names a file, not a directory: %r" % out_dir
        )
    return out_dir


def empty_output_directory(path):
    """Remove plain files and symlinks inside path, never path itself.

    Subdirectories are left alone. Clearing the contents first means
    a stale ``entry.txt`` or a stale temporary file can never
    survive a run and be mistaken for this run's output.
    """
    for name in os.listdir(path):
        full = os.path.join(path, name)
        try:
            if os.path.islink(full) or os.path.isfile(full):
                os.unlink(full)
        except FileNotFoundError:
            continue


def sync_directory_entry(out_dir):
    """Flush the directory entry so the rename survives a crash."""
    dir_fd = os.open(out_dir, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _write_and_verify(tmp_path, data):
    """Write *data* to *tmp_path*, fsync, and read it back to check."""
    with open(tmp_path, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    with open(tmp_path, "rb") as handle:
        if handle.read() != data:
            raise ValueError("read-back verification failed")


def publish_entry_atomically(out_dir, data):
    """Publish *data* as entry.txt in *out_dir* via temp file + replace.

    The temp file is chmod 0644 before the bytes are written and
    again before the rename, the bytes are fsynced and read back
    for verification, and the temp file is unlinked on any failure
    so a half-written entry never becomes the visible output.
    """
    target = os.path.join(out_dir, "entry.txt")
    fd, tmp_path = tempfile.mkstemp(
        prefix=TMP_PREFIX, suffix=TMP_SUFFIX, dir=out_dir
    )
    os.close(fd)
    try:
        os.chmod(tmp_path, 0o644)
        _write_and_verify(tmp_path, data)
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, target)
        os.chmod(target, 0o644)
        sync_directory_entry(out_dir)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _encode_entry(text):
    """Validate *text* against the gate and return its UTF-8 bytes.

    Keeping validation and encoding together means no caller can
    accidentally publish bytes that were never checked.
    """
    check_entry(text)
    return text.encode("utf-8")


def run():
    data = _encode_entry(ENTRY)

    out_dir = locate_output_directory()
    os.makedirs(out_dir, exist_ok=True)
    empty_output_directory(out_dir)
    publish_entry_atomically(out_dir, data)


if __name__ == "__main__":
    run()
