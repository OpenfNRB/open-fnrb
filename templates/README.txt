Open fNRB input tables

Use the blank Excel workbook or the matching CSV headers. The workbook's Field
guide explains units and required fields. Keep worksheet names and column headers
unchanged. Supply values rather than formulas. Blank inputs are not zero.

Each harvest row represents one assessment. Choose annual_total, household_count
or built_up_allocation and leave the other route's fields blank. Built-up allocation
uses full administrative totals in AdminHouseholds and spatial built-up support.
Harvest values use dry woody biomass.
Record the source and any upstream moisture/unit conversions.

All supplied parameter means and standard deviations are arithmetic moments.
Use shared source-group IDs where parameters share a source. The workbook does
not prefill ecological defaults. Supply justified parameters and uncertainty for
every zone; see docs/INPUTS.md and docs/SCIENTIFIC_LIMITATIONS.md.

Eligibility requires an explicit TRUE/FALSE rule for every mapped land-cover
class in the assessment. Resource exclusions do not remove household woody biomass use.

Travel settings apply to the separately supplied household/stove point layer.
Points retain unique IDs. Buffers are dissolved so overlaps do not duplicate area.
Their radius assumes straight-line travel and does not model terrain or tenure.

Synthetic CSV examples are in examples/tables. Their values are invented and
must not be treated as scientific defaults or client observations.

The ClassificationMatrix sheet supplies optional land-cover validation counts.
Keep mapped_class,reference_class,count headers; enter every pair including zeros.
Mapped classes are rows and reference classes are columns of the corresponding
matrix. Each mapped row must have positive total count. Select this workbook
through classification_uncertainty.matrix in workflow.json, not the tabular
intake tables. The workflow requires source evidence, orientation, scope and
dependence acknowledgements. These counts affect resource eligibility only.
An invented XLSX example is in examples/tables/classification_matrix.xlsx.

The Observations sheet records annual household woody biomass use, positive weights and explicit
survey-unit IDs. Bootstrap design is selected in configuration. The weighted
observation mean must match the central household woody biomass use supplied in Harvest.
The tool does not infer survey design or silently replace the central estimate.

The examples/tables/inputs.json file demonstrates tabular configuration. File paths
are resolved relative to that JSON file. Each input file is fingerprinted for the
audit record. Unused observation or administrative inputs produce an error.

These tables cover harvest, parameters, eligibility, travel, administrative totals
and household woody biomass use observations. GIS files, stock distribution/dependence choices and
run/export settings still require the complete workflow configuration. The full
command-line workflow is documented in examples/NOMINAL_WORKFLOW.txt.
