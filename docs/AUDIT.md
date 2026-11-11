# Audit records and result interpretation

Inspect `status.json` and logs before using any result. `precision_met` means the configured numerical checks passed. `precision_limit_reached` means the configured draw limit was reached without that acceptance. `interrupted`, `failed` and `export_failed` require attention; the latter preserves completed simulation results while recording incomplete exports.

The assessment retains input/code fingerprints, configuration, runtime information, parameter draws, checkpoints and run attempts. Excel summaries are a convenient view of computed values. CSV/NPZ/JSON records retain detailed values and provenance. Do not edit a checkpoint or omit failed iterations. Resume only through the documented command.

## GIS outputs

Keep TIFFs and every shapefile sidecar together. Shapefile fields use short names with a JSON field dictionary; decimal attributes are rounded while machine records retain full precision. Layer catalogues explain units and support. Categorical TIFFs keep their own native CRS; support polygons use the biomass CRS.

Nominal outputs use mapped eligibility. Classification-enabled runs also export candidate support. With classification sampling, spatial density summaries use fixed candidate area, including zero eligible-resource contribution when a draw classifies a record as ineligible. Those zeros do not imply zero physical landscape biomass. Eligible-fraction and eligible-hectare maps are supplied separately. Every completed draw contributes to the statistics.

Fragments are aggregated within each native stock cell before spatial percentiles are computed. Percentile maps and cell standard deviations cannot be added to obtain assessment-level uncertainty. Use the assessment Monte Carlo summaries for overall uncertainty. No pixel-level fNRB is calculated.

## Recovery and replay

Automatic spatial export and optional full-iteration GIS preserve failed attempts. Compatible resume verifies completed exports and reuses them; altered files are rejected. Replay verifies sampled parameters and metrics against the saved checkpoint before exporting a selected zero-based iteration.

## Standardised and research provenance

Run records include the package version and execution mode. A research workspace has a baseline record and a research marker. Its results are experimental even if the version string matches the downloaded source. Keep research outputs separate, report the baseline and changes, and never relabel them as standardised results.

Source-package checksums detect changes but are not digital signatures, licensing evidence or methodological approval. A clean-looking report does not remove the limitations recorded in its inputs, assumptions and methodology.

## Detailed uncertainty exports

`parameter_draws.jsonl` retains each complete parameter record. `parameter_draws.csv` provides a long-form view with iteration, parameter name and a JSON-encoded value, preserving arrays and nested records without rounding. Spatial draws remain reproducible from source identities and seeds; use replay or optional full-iteration GIS for their explicit maps.

Canopy runs export `canopy_uncertainty.csv` with mapped fractions, input normal standard deviations, and analytical bounded means, standard deviations and mean shifts for each prepared source-cell fragment. These are conditional distribution moments, not Monte Carlo sampling errors. Shared source-cell identifiers preserve the relationship between fragments. Per-draw aggregate expected stock shifts are retained in the parameter records.

The nominal run record lists resolved QGIS, Python and numerical/GIS dependency versions and locations. This is evidence of the runtime used, not permission to substitute versions without verification.
