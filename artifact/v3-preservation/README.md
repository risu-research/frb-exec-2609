# Artifact V3 legacy-authority preservation

This directory is a preservation-only carrier for pre-existing scientific authority bytes whose original GitHub Actions retention windows are finite.

Rules:

- No experiment is executed here.
- No result is recomputed or promoted here.
- Original archive bytes are preserved losslessly as Base64 text where included.
- Every preserved archive is checked against its pre-existing SHA-256 authority before admission.
- Human-readable extracted members are convenience mirrors only; the decoded archive hash is the byte-level authority.
- A preservation failure cannot be repaired by rerunning a historical experiment.
- This public carrier intentionally contains no private-manuscript or private-repository metadata.

The branch is descended from the frozen Artifact V2 public carrier and is not an authority replacement.