# =============================================================================
# HYDRA-UMC-DEV-SERVER - examples/plugins/readme-generator/plugin.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""Example plugin that provides one GENERATOR: a README skeleton.

A generator receives a dict of parameters (at most 4096 bytes of JSON, chosen by
the caller, so treat every value as untrusted text) and returns exactly
`{"filename": <plain file name>, "content": <text>}`. The server hands the text
back to the caller and writes nothing to disk. Copy this directory, change the
generator and approve the new SHA-256 shown by `plugin list`.
"""


def readme_skeleton(params: dict) -> dict:
    name = str(params.get("name", "my-project"))[:80]
    summary = str(params.get("summary", "Describe what this project does."))[:500]
    content = f"# {name}\n\n{summary}\n\n## Usage\n\nTODO\n\n## License\n\nTODO\n"
    return {"filename": "README.md", "content": content}


def register(registry) -> None:
    registry.add_generator("readme-skeleton", readme_skeleton)
