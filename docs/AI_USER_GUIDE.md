# Using Open fNRB with an AI assistant

Give the assistant the package folder and ask it to read AGENTS.md. Describe the assessment you want to run. Keep your inputs and outputs outside the package.

[AGENTS.md](../AGENTS.md) contains the full guided process: scope and folders, data collection, preparation, confusion-matrix intake, environment verification, nominal run, Monte Carlo, recovery, output interpretation and handover. You do not need to know the commands in advance. The assistant should inspect available inputs, explain choices in plain language, perform authorised work and ask only for missing evidence or material decisions.

Use [input requirements](INPUTS.md) and the [global dataset list](RECOMMENDED_DATASETS.md) to identify suitable sources and missing evidence. For classification MC, the tool can convert suitable confusion-matrix counts into sampling probabilities; a separate probability raster is not required. The assistant must help establish matrix orientation, applicability and any necessary sampling-design corrections before enabling this option.

## Run an assessment

Example request:

> Run Open fNRB in standardised-use mode. Help me prepare my inputs from the supplied Excel template, explain the required scientific assumptions, check the QGIS environment, and run the documented workflow. Keep the downloaded package unchanged. Ask me for missing harvest, eligibility and uncertainty choices. Preserve the complete audit outputs and explain their limitations.

Provide a harvesting boundary or household/stove points and travel assumptions; annual harvest or household counts and mean annual woody biomass use; AGB or tree cover with the relevant uncertainty layers; land cover; ecological parameters; and explicit eligibility/exclusion rules. The assistant must not invent household woody biomass use or scientific evidence. A nominal-only run can check the workflow before Monte Carlo.

Obtain real inputs separately using provider access instructions. Keep any access credentials local. No downloads are needed for the supplied synthetic examples.

Ask the assistant to report the software version, unchanged-package check, input sources, assumptions, completion and precision status, nominal estimate and Monte Carlo summaries. Request links to the Excel summary, CSVs, run record, logs and GIS outputs. A zero-prescribed-harvest flag and unresolved uncertainty limits must remain visible.

## Errors and recovery

Ask the assistant to inspect failure records, preserve incomplete outputs and explain the cause. Resume only with compatible configuration, inputs, source and runtime. Never omit failed Monte Carlo draws, overwrite checkpoints or alter the method just to obtain a result.
