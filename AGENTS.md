# AI-assisted operation of OpenfNRB

Guide the user through the complete assessment, explaining choices in plain language. Read README.md, docs/INPUTS.md, docs/METHODOLOGY.md, docs/SCIENTIFIC_LIMITATIONS.md, docs/terminology_definitions.md and docs/AUDIT.md. The tool is country- and provider-agnostic; use the user's assessment inputs and the optional global source list. Do not assume any real datasets are present.

Keep inputs, results and decision logs outside the package. Preserve the supplied source and its manifest. Use synthetic values only for demonstrations, never as ecological defaults or real household evidence. Record source versions, units, coverage and uncertainty assumptions. Never invent missing uncertainty, evidence or informed acknowledgements. Preserve licence and copyright notices. Keep private records and credentials local unless sharing is explicitly authorised.

## Guided end-to-end assessment

### How to guide an inexperienced user

Explain one stage at a time: what it achieves, what information is needed, what the assistant will do, and what the result means. Use familiar language before introducing technical terms. For example, explain Monte Carlo as repeatedly running the calculation with plausible input values to show the consequences of the stated uncertainty assumptions.

Start by inspecting the supplied package, inputs and previous decisions. Reuse information already available; do not ask the user to provide it again. Maintain a short progress checklist and an assessment decision log outside the package. Record evidence, units, accepted assumptions, missing inputs and whether each stage passed. Ask focused questions only for material missing information or choices. Continue independent authorised work while waiting, but do not invent a scientific choice or set an acknowledgement to true on the user's behalf without their informed acceptance. Prior authorisation remains valid.

Before proposing a download, inspect local data and their metadata. Before a large run, explain the expected resource demands and agree its extent and export options. Do not silently launch nationwide preparation when the user needs a small project assessment. For software/environment issues, do routine diagnosis and explain any action requiring a change to the shared runtime.

### 1. Establish the assessment and working folders

Read README.md, docs/INPUTS.md, docs/RECOMMENDED_DATASETS.md, docs/METHODOLOGY.md and docs/AUDIT.md. Check the actual package version and packaged source manifest if present; report absent or mismatched verification honestly. Use the packaged calculation for assessments. Code or methodological changes require a separate copy created with tools/create_research_workspace.py; report those results as modified-model results.

Establish the assessment purpose, reference year, geographical scope and whether the user needs nominal-only results or MC as well. Explain that nominal means one calculation using the chosen central inputs; MC adds only the uncertainty components actually configured. Establish either an explicit harvesting polygon or household/stove points with evidenced travel assumptions. Do not silently use an administrative border as a harvesting boundary.

Create an assessment directory outside the package with separate source inputs, prepared inputs, configuration, evidence and new results folders. Preserve source files. Use new destinations for transformations and runs. Record where everything is stored in a short assessment README so the user can find it again. Keep sensitive locations and household records local.

### 2. Collect and assess the input evidence

Use docs/INPUTS.md as the complete input contract for the supported input routes, not a declaration that all inputs are present. Work through its route-selection table, exact table headers and configuration sections. Mark every component as required, conditional or not applicable for this assessment; check both scientific evidence and the implemented input contract. Build a readiness table with one row per required component, its source/version/year, physical units, geographical coverage, preparation needed, uncertainty evidence and unresolved decisions:

- Boundary or travel points: geometry, CRS, unique IDs and collection/travel assumptions. Explain that straight-line buffers do not model terrain, access rights or tenure.
- Starting stock: choose either AGB with its matching uncertainty layer, or continuous canopy cover with its own uncertainty and reference-capacity parameters. Explain the two routes; never silently substitute one for the other.
- Land cover and eligibility: obtain the class legend and an explicit eligible/ineligible rule for every relevant class. Obtain supplementary exclusions. Explain that excluding resource land does not remove household woody biomass use.
- Ecological zones and parameters: obtain applicable growth and capacity means, standard deviations, units and evidence for every required zone/group. No ecological parameter defaults are supplied; missing zone parameters must be resolved using applicable evidence.
- Harvest: select annual total, household count and consumption, or the documented built-up allocation route. Obtain dry-woody-biomass units and document any upstream moisture/fuel conversions. For allocation, obtain full administrative household totals, matching IDs, built-up data and separate allocation rules.
- Harvest uncertainty: obtain the evidence needed for the selected model, including observations, weights and independent survey-unit IDs when using bootstrap sampling. Do not assume observations are independent or adopt example household woody biomass use values.
- Classification uncertainty, if requested: collect an applicable validation confusion matrix and its sampling-design evidence, following stage 4. A separate probability raster is not required by that route.

Distinguish missing evidence from missing software functionality. Explain what blocks the selected run and what narrower analysis is possible. A fixed-input assumption is a disclosed modelling choice, not proof of no uncertainty. Even a nominal workflow must meet the implemented input contract; do not bypass required uncertainty fields by inserting invented zeros.

For authorised data acquisition, follow the selected provider's access instructions. Keep credentials local. Record source identifiers, versions, terms and checksums. Reuse verified local files and check actual valid coverage; a catalogue footprint alone does not establish usable input coverage.

### 3. Prepare and validate the data

Read templates/README.txt, the workbook Field guide and examples/NOMINAL_WORKFLOW.txt. Copy the blank workbook or CSV headers to the assessment directory. Help the user populate the necessary tables without changing sheet names or headers; supply values rather than formulas. Keep blanks distinct from zeros. Reference example files only for structure; their invented values and acknowledgements are not scientific defaults.

Inspect raster CRS, transform, dimensions, bounds, bands, units, scale/offset, NoData codes and actual valid coverage. Check vector geometry, identifiers and ecological coverage. Keep stock and uncertainty on matching native grids. Preserve source-cell identities. Do not replace missing values with zero, stretch incomplete rasters over the boundary, or infer resolution from a filename.

Use docs/RASTER_ENCODING.md for explicit physical decoding. Where supported, prepare each stock/uncertainty source with tools/prepare_encoded_raster.py and its evidence-backed encoding configuration, then inspect preparation_record.json. Mask raw missing codes before conversion and apply scale once. Distinguish percent from fraction and observation support from stored pixel spacing. Confirm representation-specific encoding from provider evidence.

Prepare categorical inputs using their documented legend, missing codes and the input contract in docs/INPUTS.md. When CRSs differ, use the documented explicit transformation settings in examples/NOMINAL_WORKFLOW.txt; explain tolerances in the actual source/target units. Do not casually resample categorical classes or stock uncertainty. Check complete coverage over the assessment and, when classification is sampled, over all candidate resource land. Household allocation may also require coverage over full administrative units used in its denominators.

Create inputs.json for the tabular intake and workflow.json for GIS sources, boundary, stock route, ecological mapping, eligibility/exclusions and optional allocation/classification settings. Resolve paths relative to their configuration files. Record provenance and assumptions. Show a plain-language readiness summary before using the prepared data: included area, sources and dates, units, missing data, eligibility choices, parameter gaps and remaining uncertainty limitations. Do not present incomplete preparation as ready.

### 4. Prepare confusion-matrix evidence when classification MC is requested

Explain that the matrix records how mapped land-cover classes compared with reference observations. The implemented conversion is **P(reference class | mapped class)**. The tool normalises mapped rows and draws a class for each native land-cover cell; the user need not produce probability rasters.

Read the classification section of docs/INPUTS.md and the classification section of examples/NOMINAL_WORKFLOW.txt. Inspect the actual evidence before converting it:

1. Check product/version/year, class legend, geographical applicability, reference quality and sampling design. Overall accuracy or a list of per-class accuracies is insufficient to reconstruct the full matrix.
2. Establish which axis contains mapped classes. Transpose only when the source evidence establishes that this is necessary. Apply documented design weighting or bias correction upstream when required; simple row normalisation cannot repair inappropriate raw counts. Do not invent missing off-diagonal counts or collapse legends without an explicit justified mapping.
3. Prepare CSV or the workbook's ClassificationMatrix sheet with exactly mapped_class, reference_class, count. Use finite nonnegative counts or justified weighted counts, every pair including zeros, the same nonnegative integer code list on both axes, positive totals for every mapped row, and eligibility rules for every possible sampled class. Reject formulas and unexplained blank cells.
4. Explain one row's resulting probabilities to the user and record evidence for the entire matrix. The loader checks structure and the sampler normalises rows; the assistant must separately assess scientific applicability.
5. Configure classification_uncertainty in workflow.json with matrix, source_id, orientation="mapped_rows_reference_columns", dependence="independent_native_cells", scope="resource_eligibility_only" and the user's acknowledgement. Use the exact configuration fragment in the linked workflow documentation.

Explain the limits before enabling it: all fragments of a native class cell share one draw; different native cells are sampled independently; the probabilities themselves are fixed. Matrix-estimation uncertainty and spatially correlated classification errors are not sampled. Only resource eligibility changes; ecological zones, parameter sources, exclusions and household allocation remain fixed. Nominal eligibility still uses the mapped classes.

If suitable evidence is unavailable, explain the choice between obtaining it and explicitly keeping classification fixed. Omit classification_uncertainty for the latter and disclose the omission in results. Never quietly insert the synthetic example matrix. A classification matrix does not replace canopy-cover uncertainty or biomass uncertainty.

### 5. Initialise and verify the tool environment

Read docs/INSTALLATION.md. Locate the user's actual QGIS Python launcher; do not assume the example installation path exists. Run tools/check_environment.py to a new external report. For a new/unverified installation, run tools/check_installation.py to a new external directory and inspect its synthetic verification reports. Reuse an existing successful installation check only when the package/runtime are still applicable and record that evidence.

The following PowerShell patterns use placeholders: replace every path with the verified local path before execution. Reuse $qgisPython for the later commands.

```powershell
$qgisPython = 'C:\path\to\QGIS\bin\python-qgis.bat'
& $qgisPython 'C:\path\to\open-fnrb\tools\check_environment.py' --output 'C:\assessments\case\evidence\environment.json'
& $qgisPython 'C:\path\to\open-fnrb\tools\check_installation.py' --output 'C:\assessments\case\installation-check'
```

Inspect process exit codes and report contents. Import errors, crashes or incomplete checks are not success. Explain that a synthetic check verifies operation, not ecological validity, and its deliberately short MC run can reach its precision limit. Do not install arbitrary replacements into QGIS. Resolve environment problems before a real assessment.

### 6. Run and review the nominal assessment

Run the validated real inputs into a new output directory:

```powershell
& $qgisPython 'C:\path\to\open-fnrb\run_open_fnrb.py' nominal 'C:\assessments\case\configuration\workflow.json' --output 'C:\assessments\case\nominal-results'
```

Read status.json, failure.json if present, events.jsonl, run_record.json, nominal.json and summary.xlsx. Review eligible area, harvest, starting stock, growth, supplied/unrealised harvest, units and diagnostic flags. Check spatial coverage and the documented mass-balance/consistency diagnostics. Explain implausible inputs or unresolved failures before MC. A nominal run can prepare classification candidate support but does not perform classification draws. Correcting inputs requires a new run directory and preserved prior evidence.

### 7. Configure and run Monte Carlo

Explain the nominal result and list which uncertainties will be sampled and which will stay fixed. Prepare sampling.json using the current workflow documentation and actual supported options. Obtain and record the required distribution/interpretation, stock spatial-dependence, zero-stock policy and shared-parameter acknowledgements. Preserve shared source-group IDs for reused parameters. For canopy, explain that truncating normal cover to [0,1] can shift its expected value; the supplied pre-truncation scale is not generally the resulting SD.

Review harvest sampling, any observation/survey design, and classification settings separately. Explain that sample size controls numerical precision, not evidence quality. Set and record a reproducible seed, initial/extension/maximum iterations, precision target, required passes and checkpoint interval. Use supported settings; do not lower precision requirements merely to label a run successful. Describe remaining omissions and the expected time/disk needs, particularly spatial export. Full-iteration GIS is optional and off by default; offer it when the user needs every draw, explaining its storage cost.

```powershell
& $qgisPython 'C:\path\to\open-fnrb\run_open_fnrb.py' monte-carlo 'C:\assessments\case\configuration\workflow.json' --sampling 'C:\assessments\case\configuration\sampling.json' --output 'C:\assessments\case\mc-results'
```

This command includes nominal preparation under mc-results/nominal; it does not consume the earlier nominal-results folder. Keep configuration and inputs consistent with the reviewed assessment. Monitor status and logs without changing active inputs. Use --stop-after N for a supported graceful stop when requested. For recovery, use the same inputs, sampling configuration and output directory with the resume command. Check compatibility and locks first; never delete an active process's lock or skip failed draws.

```powershell
& $qgisPython 'C:\path\to\open-fnrb\run_open_fnrb.py' resume 'C:\assessments\case\configuration\workflow.json' --sampling 'C:\assessments\case\configuration\sampling.json' --output 'C:\assessments\case\mc-results'
```

Changed scientific inputs, matrices, code or configuration require a new assessment. If exports fail after simulation, inspect export_failed and retry through compatible resume; do not discard the completed checkpoint or resample its draws. Report precision_limit_reached honestly rather than calling it precision_met.

### 8. Inspect and explain the outputs

Do not hand over only a number or an output folder. Read the actual output records and provide links with a short explanation of what the user should open first:

| Output | What to explain to the user |
|---|---|
| summary.xlsx | Convenient results, uncertainty, sources and diagnostic summary. Values are computed outputs; it is not a spreadsheet for changing model inputs. |
| status.json, events.jsonl, failure.json when present | Whether calculation and exports completed, whether precision passed, and any failures or interruptions. |
| run_record.json and manifest.json | Sources, configuration, fingerprints, runtime and assumptions needed to trace the result. Preserve referenced source paths for resume/replay. |
| nominal.json and nominal_cells.csv | Central-input result and detailed calculation records; consult recorded units and spatial support. |
| monte_carlo records and parameter_draws.jsonl / parameter_draws.csv | Iteration results, sampled parameters, mean/median/SD/P10/P90, precision diagnostics and checkpoint evidence. Locate files in the actual run tree. |
| gis layer catalogue, TIFFs, shapefiles and sidecars | Stock, flux and area maps in their recorded CRSs/units; preserve all companion files. There is no pixel-level fNRB map. |
| spatial_exports and optional iteration_exports | Conditional spatial summaries and, only if requested, individual-draw GIS. Verify the successful export attempt and index before linking results. |

Explain fNRB as the model's assessment-level fraction of estimated harvested biomass exceeding modelled annual regeneration under the stated inputs and sourcing assumptions. Report it as both fraction and percent when helpful, using the same underlying value. It is not the percentage of land deforested or a pixel-level forest-loss rate. Report prescribed harvest, realised harvest and annual regeneration with their units. With zero prescribed harvest, zero fNRB is a flagged reporting convention; it is not proof of sustainability. With positive harvest and no eligible resource, the documented result is fNRB=1.

For MC, distinguish the nominal estimate, simulation mean/median and spread. P10 and P90 delimit the central 80% of the simulated outcomes under the configured assumptions; they are not automatically a confidence interval or a measure of all real-world uncertainty. precision_met concerns the implemented numerical checks, not scientific validity or separately guaranteed map-percentile precision. A maximum-iteration stop is a remaining precision limitation.

Explain that density maps and totals have different meanings. Use eligible/candidate area and the layer catalogue to interpret them; do not add cell SDs or percentiles to obtain overall uncertainty. With classification sampling, spatial density summaries use fixed candidate area, and zero eligible-resource contribution does not mean zero physical biomass. Show eligible fraction/area alongside those results. Use assessment-level MC summaries for overall uncertainty.

Offer a selected-iteration replay only if useful for diagnosis or explanation, using the documented replay command and a new directory outside the original assessment. Verify replay results rather than presenting an arbitrary draw as the central estimate.

### 9. Complete the handover

Provide a short plain-language assessment note outside the package containing: purpose/year/boundary, software version and mode, source and preparation summary, accepted assumptions, nominal result, MC components and summaries if run, completion/export/precision status, material limitations and any unresolved work. Explain how each limitation could affect interpretation without claiming an unquantified numerical effect.

Link the summary workbook, decision log, configuration, audit records and useful maps. State where to find preserved source inputs and how compatible resume/replay works. Do not delete scratch-independent evidence, failed attempts, sidecars or checkpoints. Do not describe a nominal-only run as uncertainty-assessed, an incomplete run as completed, or software verification as ecological validation or regulatory acceptance.
