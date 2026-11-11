# Input requirements

## Choose the inputs for the selected route

Read this table first. "Required" means required by the current input contract, including nominal preparation; it does not mean that uncertainty is sampled in a nominal run.

| Component | When needed | If unavailable |
|---|---|---|
| Assessment ID, year/scope and provenance | Every assessment; record year/scope in the evidence log and source dates, not invented JSON keys | Establish the assessment and sources before execution |
| Harvesting polygon OR points plus travel settings | Exactly one boundary route | Obtain a justified boundary; do not silently substitute an administrative border |
| AGB plus matching uncertainty OR canopy plus matching uncertainty | Exactly one stock route; uncertainty input is required even for nominal preparation | Obtain evidence or an explicitly justified supported input; never fill missing uncertainty with zero |
| Ecological-zone polygons and growth/capacity table | Both stock routes, nominal and MC | Resolve every zone/parameter gap before running |
| Land-cover raster and eligibility rules | Every assessment | Supply class coverage and explicit decisions; class names do not imply eligibility |
| Exclusion polygons | Where additional restrictions apply; an explicit empty list is required when none apply | Obtain the user's exclusion decision; do not infer none from absent files |
| Harvest table and harvest uncertainty selection | Every assessment; choose one of three harvest routes | Obtain harvest evidence; a blank is not zero |
| Administrative polygons/totals, built-up raster and allocation rules | Only built_up_allocation harvest | Supply the complete allocation inputs or select another evidenced harvest route |
| Household woody biomass use observations, weights and survey-unit IDs | Only household_bootstrap harvest uncertainty | Obtain suitable observations or explicitly select another supported harvest model |
| Validation confusion matrix | Only classification-enabled MC; may also be prepared in a nominal run for audit | Obtain applicable evidence or explicitly leave classification fixed |
| CRS/transform settings and projection acknowledgement | Every workflow; transform settings when required by different CRSs | Resolve alignment and area measurement; do not guess tolerances |
| sampling.json, seed, precision and dependence choices | MC/resume | Explain and agree the supported assumptions before MC |
| Output paths and optional export/recovery settings | All commands as applicable | Choose safe new paths and adequate resources |

## Formats and common intake rules

- Use the supplied [blank workbook](../templates/Open_fNRB_input_template.xlsx) or [CSV templates](../templates/README.txt). CSV headers must match the order below; XLSX sheets must use the corresponding table names and headers. Supply values, not formulas. Do not rename fields or add undocumented columns.
- Numbers must be finite. Means, scales and counts obey the specific rules below. Preserve text identifiers and leading zeros. Each table's first-column identifier is unique; matrix entries are unique by mapped/reference pair. Each ordinary table row requires a nonempty source description.
- The usual local raster interchange is GeoTIFF; the reader uses GDAL-readable local files with a declared band and auditable dependencies. A VRT must retain its original source dependencies. The standalone raw-decoding utility has the stricter self-contained input contract described in [raster encoding](RASTER_ENCODING.md).
- Use local OGR-readable polygon/point datasets such as GeoPackage, GeoJSON or shapefiles, with a defined CRS, the correct geometry type and named attributes. Select the layer explicitly when needed. Keep shapefile sidecars together. Actual geometry, CRS and dependency validation still applies; a filename extension alone is not approval.
- Raster configuration requires path, units, source, version and date, with optional band (default 1). All local paths must exist. Record year, measurement definition and provenance consistently with the source; no year is inferred from the filename.
- Files referenced by a configuration resolve relative to that configuration file. Keep source files unchanged; use separate prepared files and record all conversions. Rejected or incomplete preparation outputs must not enter a run.

## Boundaries, points and travel

| Input | Fields, units and format | Evidence and preparation | Uncertainty / missing-data treatment |
|---|---|---|---|
| Harvesting boundary | Polygon vector; workflow boundary has path and optional layer/transform | Prefer a project-supplied collection-area boundary with documented provenance. The pinned national geoBoundaries sources are suitable only when that national scope is actually intended. Check geometry, CRS, overlaps, extent and resource coverage; the tool unions boundary polygons | Boundary uncertainty is not sampled. Investigate uncertain boundaries through separately documented scenarios, not hidden alterations |
| Household/stove collection points | Point vector with path, id_field and optional layer; unique nonempty text IDs; optional maximum_accuracy_metres for CRS conversion | Use evidenced project/survey coordinates, preserve IDs and coordinate provenance, inspect misplaced/duplicate points and protect private locations | Coordinates are fixed in MC. Missing locations are not generated from row numbers or guessed centroids |
| Travel assumptions | Travel CSV/XLSX: hours per round trip, travelling_share as a fraction, speed in km/hour, edge tolerance in metres | Prefer observed collection-trip evidence. All four values must be positive, travelling_share at most 1. Radius in metres = round_trip_hours × travelling_share × speed_kmh × 500; edge tolerance must be smaller than radius | Straight-line buffers are dissolved; overlaps do not duplicate area. Terrain, road routing, tenure and travel-parameter uncertainty are not modelled automatically |

Exact Travel headers:

```text
assessment_id,round_trip_hours,travelling_share,speed_kmh,edge_tolerance_metres,source
```

Select the assessment's Travel row through inputs.json. The travel boundary object uses kind="travel" and a points object. A polygon boundary uses its vector path instead. See [workflow configuration](../examples/NOMINAL_WORKFLOW.txt). Keep administrative accounting areas distinct from resource collection boundaries.

## Starting stock and its uncertainty

Both stock and uncertainty raster specifications are required by workflow.json, including for nominal-only runs. They must have matching native grids and compatible masks/valid coverage. Select one route:

| Route | Input values and units | Required uncertainty interpretation | Preparation and source choice |
|---|---|---|---|
| agb | Nonnegative dry AGB density, units exactly t_dry_matter/ha | uncertainty_interpretation="standard_deviation"; nonnegative scale in the same physical units | Select a documented stock/uncertainty pair from [recommended global datasets](RECOMMENDED_DATASETS.md) or other suitable evidence. Preserve the provider's original statistic and separately document the justification for using it as the required sampling scale |
| canopy | Continuous cover, units fraction (0–1) or percent (0–100) | uncertainty_interpretation="pre_truncation_normal_scale"; nonnegative scale with the same units as stock | Select continuous canopy cover appropriate to the assessment year, with independently justified uncertainty. AGB uncertainty, a binary tree-extent map or land-cover confusion matrix cannot substitute for cover uncertainty |

The intake converts both canopy values and their scale from percent to fraction when units="percent". Do not convert values to fractions and still declare percent. Raw storage decoding is a separate step; band scale/offset metadata must agree with the physical representation. Do not apply the same conversion twice.

SD, standard error, residual error, confidence limits and validation RMSE are not interchangeable without evidence. No automatic SD conversion from arbitrary intervals or error statistics is offered by this raster interface. If suitable uncertainty is missing, report it; an explicit scientifically justified preparation decision is needed, not a zero-filled layer. See [recommended global datasets](RECOMMENDED_DATASETS.md) for source options.

## Ecological zones, growth and capacity

All assessments require polygon ecological zones and a Parameters table. The zone vector is supplied under zones.vector and the text identifier attribute under zones.zone_field; attribute values must match Parameters.zone_id. Check valid geometry, full required support, overlaps and the crosswalk. Do not assign missing areas to a neighbouring ecological zone silently.

Use documented locally applicable ecological mapping and parameter studies. Global ecological maps can support stratification; they do not provide validated logistic parameters. No reference parameter subset is bundled. Justify every supplied parameter for its vegetation, management and assessment context.

Exact Parameters headers:

```text
zone_id,increment_mean,increment_sd,capacity_mean,capacity_sd,increment_group,capacity_group,source
```

| Field | Meaning and rules | Evidence / uncertainty |
|---|---|---|
| zone_id | Unique text ID matching the vector's ecological-zone field | Document the mapping from ecological evidence to this zone |
| increment_mean, increment_sd | Peak annual growth parameter and its arithmetic SD, tonnes dry matter/ha/year; mean positive, SD nonnegative | Review applicability of growth measurements and the model's peak-growth proxy; do not insert a generic growth percentage |
| capacity_mean, capacity_sd | Capacity/reference-stock parameter and its arithmetic SD, tonnes dry matter/ha; mean positive, SD nonnegative | Required for growth in both routes and for canopy-derived starting stock; mean forest biomass as capacity is an explicit proxy assumption |
| increment_group, capacity_group | Nonempty source-group IDs | Reused source parameters of the same kind must share IDs and identical mean/SD. Groups are statistical sharing units, not new raster bands |
| source | Nonempty provenance text | Retain reference, page/table, units, original statistic, conversions and applicability justification in evidence |

The supported MC adapter uses mean-preserving lognormal draws matching these arithmetic moments, shared within each parameter-kind/source group. Independent growth/capacity group draws require acknowledgement. It does not accept an arbitrary covariance matrix or alternative parameter distribution through these tables. Zero SD must be a documented fixed assumption, not a replacement for unknown SD. Missing/unsupported zones block preparation; do not fill gaps by copying unrelated values.

## Land-cover eligibility and exclusions

Supply a categorical land-cover raster with units="class_code", unchanged codes and legend, identity scale and zero offset. Use a source from [recommended global datasets](RECOMMENDED_DATASETS.md) or a documented compatible alternative. Resource eligibility is a user-supported rule, not inherent in the map legend.

Exact Eligibility headers:

```text
class_code,eligible,source
```

class_code is a unique nonnegative integer. eligible is explicitly TRUE/FALSE. Cover every encountered mapped class and, for classification sampling, every possible reference-class outcome. State the scientific/operational justification in source. Inspect missing and unclassifiable cells; do not label them usable vegetation by default. Keep plantation status, accessible resource and woody cover conceptually separate when deriving rules.

Additional exclusions are polygon vector specifications in workflow.exclusions. Use applicable user-supplied access/tenure restrictions or authoritative restriction/land-use layers where supported by the assessment's rules. A protected-area or ownership label does not by itself define the model's exclusion policy. The user must establish which restrictions apply, their dates and scope. An explicit [] means no supplementary exclusions; missing files do not mean no exclusions.

Exclusions remain fixed in MC and do not remove household woody biomass use. Land-cover uncertainty changes eligibility only through the optional confusion-matrix route below. Restriction-map uncertainty is not automatically sampled.

## Estimated harvest, household woody biomass use and fuel conversions

Every assessment needs one selected Harvest row. The annual total is estimated annual harvested biomass; household routes derive it from household woody biomass use under an explicit sourcing assumption. Document whether fuel is locally collected, purchased, imported, stockpiled or obtained through other channels. Only the justified share sourced from the applicable landscape belongs in the harvest estimate. See [definitions](terminology_definitions.md). Prefer project household/stove surveys, measured consumption/KPT evidence and reconciled administrative/census counts appropriate to the reference year and population. Source selection alone does not establish representativeness; document population, sampling period, fuel basis and scaling to a full year.

Exact Harvest headers:

```text
assessment_id,mode,estimated_annual_harvest_tonnes,households,woody_biomass_use_tonnes_per_household_year,source
```

| mode | Required values | Leave blank | Calculation |
|---|---|---|---|
| annual_total | estimated_annual_harvest_tonnes, finite nonnegative tonnes dry woody biomass/year | households and woody_biomass_use_tonnes_per_household_year | Uses the supplied total |
| household_count | households and woody_biomass_use_tonnes_per_household_year, both finite nonnegative | estimated_annual_harvest_tonnes | Count × annual woody biomass use per household |
| built_up_allocation | woody_biomass_use_tonnes_per_household_year, finite nonnegative | estimated_annual_harvest_tonnes and households | Spatially allocated household count × annual woody biomass use per household |

All modes require assessment_id and source. Keep annual household woody biomass use in tonnes dry woody biomass per household per year. Kilograms, daily measurements, wet fuel, charcoal, volume, energy or per-person consumption require an evidenced upstream conversion to the accepted quantity. The tool has no generic moisture, calorific-value, charcoal-yield, density or household-size conversion field. Preserve measurements and conversions with their evidence; do not invent factors. Report uncertainty omitted by those conversions unless it is validly included in a supported harvest model.

Counts and allocation weights may yield noninteger household totals; do not round them without a justified rule. Zero harvest is allowed but has a flagged reporting convention. Missing harvest is not zero, and excluding land does not remove the associated population's harvest automatically.

## Administrative totals and built-up allocation

These inputs are required only for built_up_allocation. Do not attach them to other harvest routes; the validator rejects unused administrative inputs/allocation settings.

| Component | Format/fields | Suitable evidence and checks | Missing-data / MC treatment |
|---|---|---|---|
| Administrative areas | Polygon vector plus an explicit id_field in household_allocation; optional layer/transform | Use the boundary vintage corresponding to official household totals. IDs must be unique and match AdminHouseholds exactly | Mismatched IDs, missing totals or incompatible boundaries must be resolved |
| AdminHouseholds | CSV/XLSX with administrative_id, households, source | Official census/administrative household totals or justified project counts; households finite nonnegative and IDs text | Totals remain fixed in MC; do not imply that count uncertainty is sampled by the household woody biomass use bootstrap |
| Built-up support | Categorical raster declared class_code, with source/version/date and band | A documented built-up layer or the built-up classes of a suitable land-cover product; check its population-allocation applicability | Requires valid coverage over full administrative units, including areas outside the harvesting boundary |
| Built-up rules | Separate CSV/XLSX Eligibility-format table selected by rules_table | Mark the classes used as household-allocation support; do not reuse resource eligibility merely because the columns match | These rules and support remain fixed during classification MC |

Exact AdminHouseholds headers:

```text
administrative_id,households,source
```

The household_allocation object requires administrative_vector, id_field, built_up and rules_table; built_up_transform is conditional on CRS differences. Allocation uses each unit's eligible built-up area inside the assessment divided by that unit's full eligible built-up area, multiplied by its household total. Preserve and reconcile both areas and allocated counts. Clipping away the outside portion before establishing the denominator changes the allocation. Missing/zero required support must be investigated rather than replaced by equal-area or guessed population allocation.

## Harvest uncertainty and survey observations

inputs.json requires an explicit harvest_uncertainty object even for nominal preparation. The selected model affects MC, not the central nominal harvest. These are the supported choices:

| kind | Required configuration/evidence | Applicability and checks | If evidence is absent |
|---|---|---|---|
| fixed | kind only; record why harvest is held fixed in the decision log | Available for every harvest route; disclose omitted uncertainty | Do not select silently as a claim that harvest is known exactly |
| lognormal | kind, source_id, acknowledged=true, sd | Positive central total harvest; sd is finite nonnegative arithmetic SD of the annual assessment TOTAL in tonnes, not per-household SD or a percentage; tool matches arithmetic moments | Obtain/derive justified total-harvest SD or explicitly select another supported model |
| household_bootstrap | kind, source_id, acknowledged=true, design; Observations table | Household_count or built_up_allocation only; design is independent_units or assumed_iid | Obtain valid survey evidence or select a different documented harvest model |

Exact Observations headers:

```text
observation_id,annual_household_woody_biomass_use_tonnes,weight,unit_id,source
```

Use unique text observation_id, nonnegative annual household woody biomass use in tonnes per household, strictly positive finite weights, explicit text survey-unit IDs and provenance. Select observations relevant to the current assessment. The weighted observation mean must equal Harvest.woody_biomass_use_tonnes_per_household_year; inconsistent central values are rejected, not replaced automatically.

For independent_units, unit_id identifies the independent sampling unit, retaining repeated observations within that unit. assumed_iid requires distinct unit IDs and an explicit independence assumption; do not use it to conceal repeated households or clustered sampling. The tool does not infer survey design from rows, estimate missing weights, or implement every complex survey design. Survey corrections and annualisation need evidence before intake. Observations supplied without the bootstrap selection are rejected. Household totals, built-up allocation and coordinates remain fixed while household woody biomass use is bootstrapped.

## Configuration and numerical inputs

These settings are supplied by the user/assistant as explicit choices. They are not provider datasets. Use the actual supported schema and do not add arbitrary keys. See [the full workflow](../examples/NOMINAL_WORKFLOW.txt) for command examples.

### inputs.json: tabular intake

Required top-level keys: schema_version=2, assessment_id, tables, harvest_uncertainty. tables requires Harvest, Parameters and Eligibility; optional entries are Travel, AdminHouseholds and Observations for the routes above. Each entry is a CSV or XLSX path; multiple table names may point to the same workbook. The selected assessment must have exactly one matching Harvest row and, when supplied, one matching Travel row.

ClassificationMatrix is deliberately not an entry in this tables object. Link it through workflow.json classification_uncertainty.matrix instead, even if it is a sheet in the same workbook.

### workflow.json: GIS and preparation

Required keys: schema_version=1, tabular_config, stock_mode, stock, stock_uncertainty, uncertainty_interpretation, boundary, zones, land_cover, exclusions, projection_suitability_acknowledged. Optional keys: household_allocation, land_cover_transform, maximum_raster_block_cells, classification_uncertainty.

- Each raster specification has path, units, source, version, date and optional band. Vector specifications use path and optional layer/transform; zone and administrative IDs and travel points use their route-specific fields above.
- Supported area handling is geographic WGS84 (EPSG:4326) with geodesic areas or a suitable projected metre CRS with explicit projection-suitability acknowledgement. Metre units alone do not establish adequate area accuracy.
- For polygon transforms, provide max_source_segment in source CRS units, target_tolerance in target CRS units and maximum_accuracy_metres, optionally maximum_refinements. Defaults and valid ranges are checked by the transform implementation; do not confuse degree and metre tolerances. No ballpark or unknown-accuracy operation should be substituted silently.
- A land-cover or built-up CRS different from the stock CRS needs the documented domain_to_source and cells_to_stock transformation objects. These preserve categorical cell identities for intersection; they do not silently resample the classification map. Point conversion uses its separate maximum_accuracy_metres option.
- maximum_raster_block_cells is an optional positive integer (default 65,536). It bounds individual raster reads, not total memory; changing workflow preparation settings requires a new assessment, not resume.
- classification_uncertainty requires matrix, source_id, orientation, dependence, acknowledged and scope exactly as documented in the confusion-matrix section below.

### sampling.json: MC choices

Required top-level keys: schema_version=1, stock, parameters, settings. There is no free-form distribution field: the following implemented models and policies apply.

| Component | Supported settings | Meaning / evidence needed |
|---|---|---|
| stock.dependence | independent or shared | Independent latent draws across native stock cells or a shared latent draw. Repeated fragments of a cell retain the same draw. Neither option estimates an arbitrary spatial correlation model |
| stock.zero_policy, AGB | fixed_zero or censored_normal | Positive stock uses arithmetic-moment-matched lognormal sampling. At zero mapped stock, fixed_zero omits positive uncertainty; censored_normal uses max(0, scale × normal draw), which can raise expected stock. Explain and acknowledge this choice |
| stock.zero_policy, canopy | bounded_cover | Normal cover truncated to [0,1]; map value is the pre-truncation location, not necessarily the resulting mean. The supplied normal scale is not generally the resulting SD |
| stock.acknowledged | true after informed acceptance | Covers stock error interpretation, route, dependence and zero/bounded-cover assumptions |
| parameters | dependence="independent_shared_groups", acknowledged=true after acceptance | Shared draws within parameter-kind/source groups; independent growth/capacity groups. Supply moments in Parameters, not here |
| settings.seed | Nonnegative integer | Reproducible random seed, retained with the assessment |
| settings.initial_iterations | Integer at least 32 | Initial MC batch; not an ecological accuracy threshold |
| settings.extension_iterations | Positive integer | Additional draws per extension |
| settings.maximum_iterations | Integer at least initial_iterations | Computational stopping limit; reaching it without passing precision must be reported |
| settings.precision_target | Finite number strictly between 0 and 1 | Target for the implemented numerical checks; not a total uncertainty confidence level |
| settings.required_passes | Optional positive integer; default 2 | Required passing precision checks |
| settings.checkpoint_interval | Optional positive integer; default 100 | Frequency of preserving restart state |

Harvest uncertainty is selected in inputs.json and classification uncertainty in workflow.json, not sampling.json. Boundary, travel, exclusions, ecological-zone geometry, household totals/allocation and matrix-estimation uncertainty are not separately sampled. Document those omissions and use separate justified scenarios where the supported model cannot represent an uncertainty component. Do not present every possible real-world uncertainty as covered by MC.

### Command-line and output controls

nominal takes workflow configuration and a new --output directory. monte-carlo additionally requires --sampling; resume uses the original compatible configuration, sampling file and output directory. Optional --stop-after is an absolute completed-iteration stopping count. --maximum-scratch-bytes and --cell-block-size are positive integer spatial-export resource controls (defaults 20,000,000,000 bytes and 256 cells); they do not change scientific distributions. --full-iteration-gis requests potentially large per-draw exports and persists on resume.

replay takes an existing assessment, a zero-based completed --iteration, a new external --output and optional --gis. spatial-summary takes an existing finished assessment, a new --output and the spatial resource controls. These operations reuse preserved evidence/checkpoints; they are not new source datasets. Do not edit checkpoints or use altered source files to force recovery. See [audit and interpretation](AUDIT.md).

### Acquisition and conversion controls

Obtain source datasets separately using provider access instructions. Select only the area needed for the assessment and preserve product provenance.

For an explicit raw-to-physical raster conversion, the complete encoding JSON contract is documented in [raster encoding](RASTER_ENCODING.md): source, source_sha256, source_reference, encoding_evidence, acknowledged, expected_data_type, expected_gdal_scale, expected_gdal_offset, raw_nodata, multiplier, offset, output_units, minimum and maximum. Do not omit evidence or assume that a raster's name establishes its multiplier. Keep any provider credentials local and outside assessment records.

## Readiness and provenance checklist

Before running, use this catalogue to record a status for every applicable input: supplied and verified, needs preparation, missing evidence, or not applicable with a reason. Record exact local paths in the private assessment manifest, not this distributable guide. Retain source references and dates, permissions/attribution, checksums, original units and measurement basis, conversion records, spatial coverage, uncertainty interpretations and accepted limitations.

Confirm that all required table fields and geometrical/raster coverage checks pass, optional inputs match the selected routes, and no synthetic example values remain. If classification may add resource land, validate stock/uncertainty/ecological data on that candidate area too. Numerical validation cannot establish scientific applicability: require both before describing inputs as ready. Use AGENTS.md to guide collection and resolve missing decisions before execution.

### Confusion matrix to classification MC

The implemented route accepts CSV or an XLSX workbook containing a `ClassificationMatrix` sheet. Use exactly the columns `mapped_class`, `reference_class`, `count`, with values rather than spreadsheet formulas. Supply every class pair, including explicit zeros. Both axes must use the same nonnegative integer code list; every mapped class must be represented, every row must have positive total weight, and eligibility rules must cover every possible reference class.

The tool normalises each mapped-class row:

`P(reference class j | mapped class i) = count(i,j) / sum_j count(i,j)`

For illustration only, mapped-tree counts of 80 reference-tree and 20 reference-shrub observations become probabilities 0.8 and 0.2. This is not a recommended matrix. Finite nonnegative weighted counts are supported, but the tool does not infer survey-design weights, bias corrections, matrix orientation or legend harmonisation. Document and apply any required corrections before intake. Overall accuracy, producer accuracy or user accuracy alone is not a complete confusion matrix.

Select evidence for the actual product/version, class legend and a defensible geographical and temporal scope. A global matrix is not automatically representative of an individual assessment. Retain the source table, reference, orientation, sampling design, transformations and applicability justification. If only reference-row counts are published, prepare the required mapped-row orientation explicitly and review whether weighting is also needed.

Link the prepared matrix in `workflow.json`:

```json
"classification_uncertainty": {
  "matrix": "classification_matrix.csv",
  "source_id": "Replace with the validation source and version",
  "orientation": "mapped_rows_reference_columns",
  "dependence": "independent_native_cells",
  "acknowledged": true,
  "scope": "resource_eligibility_only"
}
```

This is a configuration fragment, not a complete workflow. Set the acknowledgement only after the user understands and accepts the assumptions. Use the XLSX path instead of the CSV path when appropriate; the supplied input workbook has the required sheet.

Each MC iteration draws a class per native land-cover cell, with all fragments of that cell sharing the draw. Classification changes resource eligibility only; ecological zones, growth-parameter sources, exclusions and household allocation remain fixed. Candidate land that could become eligible also needs valid stock, uncertainty and ecological inputs. The nominal result continues to use mapped classes.

The implementation assumes independent draws between native class cells and fixed matrix probabilities. It does not sample matrix-estimation uncertainty or spatially correlated classification errors. A probability raster is not a drop-in replacement for this matrix interface. If suitable evidence is unavailable, explicitly agree to keep classification fixed and disclose the omitted uncertainty, or pause classification-enabled MC preparation. A land-cover matrix does not supply canopy-cover uncertainty.

See [the operating instructions](../AGENTS.md), [input-table guidance](../templates/README.txt) and [the full configuration workflow](../examples/NOMINAL_WORKFLOW.txt).
