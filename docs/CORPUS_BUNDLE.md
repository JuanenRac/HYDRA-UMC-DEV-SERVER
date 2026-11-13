# The documentation corpus bundle

The assistant that answers technicians (HYDRA-UMC-DOCS-QA) answers from an index of the documentation of the ecosystem. Indexing on the small computer at every start ties the answers to whatever files happen to be on its disk and cannot be reproduced. The index is built once per release instead, in CI, and travels as a signed file.

## The chain

1. **Build in CI, unsigned.** The workflow `Corpus bundle` (started by hand, or as a check on a pull request that touches it) clones the PUBLIC repositories listed in `configs/corpus-repos.json` anonymously, takes each at one commit, and builds the bundle of HYDRA-UMC-DOCS-QA **twice** (two directories, two hash seeds). It stops unless both files are identical byte for byte. It uploads `corpus-<release>.json`, `corpus-<release>.sources.json` (the commit of every repository, the commit of the indexer, `"signed": false`), `SHA256SUMS` and `build-manifest.json` as one artifact with a build-provenance attestation. The workflow holds no key.
2. **Sign on the maintainer's machine.** The release step downloads the artifact, verifies the attestation and the hashes, and signs `corpus-<release>.json` with the release key that signs the images and packages: `corpus-<release>.json.sha256` and `corpus-<release>.json.sig` (the `sha256sum` line and the base64 Ed25519 signature of the exact bytes). The key is never in a repository or in Actions. The same release can be rebuilt from `corpus-<release>.sources.json` with `--pin`.
3. **Deliver with the image.** HYDRA-UMC-OS-REBUILDER verifies the three files against the pinned public key before it puts them in an image, and refuses an altered or unsigned corpus.
4. **Verify before loading.** `hydra-umc-docs-qa serve --bundle FILE --bundle-public-key KEY` checks the same signature over the bytes it loads. Only a signed corpus is loaded by default; if a bundle is refused and `--bundle-fallback-local` was given, the service says so in a warning and indexes local documents instead.

## Building by hand

```
python -m hydra_umc_dev_server.corpus_build --release 0.3.0 --workspace /tmp/repos --out out --docs-qa ../HYDRA-UMC-DOCS-QA
python -m hydra_umc_dev_server.corpus_build --release 0.3.0 --workspace /tmp/repos --out out --docs-qa ../HYDRA-UMC-DOCS-QA --dry-run
```

`--dry-run` lists what would be cloned and does nothing else. `--pin corpus-0.3.0.sources.json` fetches exactly the commits of an earlier build; `--no-clone` uses checkouts that are already in `--workspace`. The result line is `CORPUS_BUILD=PASS` or `CORPUS_BUILD=FAIL reason` (exit status 0 or 1).

## What it does not do

It reads no secret and no private repository, signs nothing, publishes nothing and touches no device. The signature check on the device is in HYDRA-UMC-DOCS-QA; the delivery in the image is in HYDRA-UMC-OS-REBUILDER.
