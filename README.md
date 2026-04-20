# archivistdnd

Extension of the Archivist AI for 5.5E.

## Step 13 Contract Probes

Step 13 in `DESIGN.md` requires live API contract validation before item-path
implementation proceeds. Use `scripts/probe_contracts.py` to probe:

- `Item.type` wire format for multi-word values.
- Accepted `mechanics` payload shapes for item creation.

### Prerequisites

Set the same environment variables used by the server:

- `ARCHIVIST_API_KEY`
- `ARCHIVIST_CAMPAIGN_ID`
- Optional: `ARCHIVIST_BASE_URL`

### Run the probe

Dry run (no network calls, validates matrix + report generation):

```bash
python scripts/probe_contracts.py --dry-run --print-matrix
```

Live run (writes disposable probe entities and attempts cleanup):

```bash
python scripts/probe_contracts.py --print-matrix
```

Optional output directory override:

```bash
python scripts/probe_contracts.py --output-dir scripts/probe-results
```

### Outputs

Each run writes:

- JSON evidence report (`contract_probe_<timestamp>.json`)
- Markdown summary (`contract_probe_<timestamp>.md`)

Default output location is `scripts/probe-results/`.

### Required closure workflow

Before step 14 starts:

1. Run the live probe and review the generated reports.
2. Copy evidence into `DESIGN.md` -> `Contract probe results` using the template:
   date, tested payloads, upstream responses, accepted wire format/shape,
   validator decision, and commit SHA.
3. Mark Open Questions #2 and #3 as closed with pointers to the recorded
   evidence entry.
4. Keep the generated report artifacts for auditability.

## Tests

Install dev dependencies and run the suite:

```bash
pip install -e ".[dev]"
pytest
```
