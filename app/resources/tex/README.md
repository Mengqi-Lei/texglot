The unmodified `aastex.cls` is AASTeX 5.2 from the American Astronomical Society,
distributed under LPPL 1.3c (see `AASTeX-LICENSE`). The complete upstream work is
available at [AASJournals/AASTeX52, commit be4c2a5](https://github.com/AASJournals/AASTeX52/tree/be4c2a59b593d6986f93c81480f182486e1f8b47).

TeXGlot supplies this version only for Tectonic projects requesting `aastex`
without providing their own class. The 2022 Tectonic bundle contains a 1999
release candidate that lacks later AASTeX 5.x table commands. Using the complete
upstream class preserves its table implementation instead of emulating commands.
