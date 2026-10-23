# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/identifiers.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The one place that says what a name may look like.

An account name ends up in a `useradd` argv and a systemd unit, a path in a unit file and a
`ReadWritePaths` line, a task or worker id in a directory name and a lock file. Each of them used to
carry its own regular expression, in three modules; the rules are here now, as an allow-list of
characters, and the modules call these functions. A name that fails is refused, never cleaned up.
"""
from __future__ import annotations

import re

# a lowercase Linux account name: letters, digits, '_' and '-', up to 32 characters, not starting with a digit or '-'
_ACCOUNT = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
# text that becomes part of a path: no space, no quote, no '$', no control character, no non-ASCII look-alike
_PATH_TEXT = re.compile(r"[A-Za-z0-9/._-]+")
# a task, worker or lock name: one path segment, up to 128 characters, starting with a letter or digit
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def is_account_name(text: object) -> bool:
    return isinstance(text, str) and _ACCOUNT.fullmatch(text) is not None


def path_text_problem(text: object) -> str | None:
    """Why `text` may not be part of a path, or None. The characters are an allow-list, and a `..` segment is
    refused wherever it stands."""
    if not isinstance(text, str) or not text:
        return "it is empty"
    if not _PATH_TEXT.fullmatch(text):
        return "it may only contain letters, digits, '/', '.', '_' and '-'"
    if ".." in text.split("/"):
        return "it has a '..' segment"
    return None


def is_identifier(text: object) -> bool:
    """A task id, a worker id: one safe path segment, never `..` inside it."""
    return isinstance(text, str) and _IDENTIFIER.fullmatch(text) is not None and ".." not in text
