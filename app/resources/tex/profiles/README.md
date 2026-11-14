# Pinned TeX runtime profiles

These are unmodified upstream TeX packages for diagnostic-driven compatibility recovery in bundled Tectonic. `manifest.json` records each distributed file, SHA-256 digest, original URL and pinned archive digest where applicable. Every file is verified before installation into a prepared task copy.

- `minted3`: minted 3.7.0, fvextra 1.12.0, latex2pydata 0.6.0.
- `minted3-modern`: minted 3.8.0, fvextra 1.14.0, latex2pydata 0.7.0; a second, bounded attempt for newer frozen-cache keys.
- `pstricks`: PSTricks and dependencies from TeX Live 2022 final. Package loading is supported; actual PostScript drawing remains unsupported by the restricted compiler.
- `biblatex`: biblatex 3.20 from TeX Live 2024 final, paired with separately downloaded, checksum-pinned Biber 2.20 (BCF 3.11 / BBL 3.3).

LPPL is retained in `LICENSE.txt`; individual files keep their notices. Minted-family `.dtx` and `.ins` companions are under each profile's `source/`. Biber's Artistic License 2.0 is in `BIBER-LICENSE.txt`. Upstream locations are also listed in the root `THIRD_PARTY.md`.

Project-provided packages take precedence. Profiles do not authorize shell escape, source-supplied executable commands, cache guessing, or dropping code and figures. Runtime libraries are excluded from prose extraction and remain in exported source projects with their provenance.
