# OpenfNRB

OpenfNRB 1.0.1 calculates the single-year fraction of non-renewable woody biomass for a user-defined assessment area. It accepts user-supplied data from any country through documented input formats. It supports direct aboveground biomass (AGB) or canopy-derived starting stock, concurrent logistic growth and harvesting, and optional Monte Carlo uncertainty analysis.

This is the **OpenfNRB 1.0.1 beta release**.

## Start here

1. Follow [installation](docs/INSTALLATION.md) using Windows and QGIS Python.
2. Run the [included synthetic example](examples/SYNTHETIC_EXAMPLE.md). Ready-made inputs are supplied; no data download is needed.
3. Review [input requirements](docs/INPUTS.md) and [recommended global datasets](docs/RECOMMENDED_DATASETS.md) for your own assessment.
4. Follow the [command and configuration guide](examples/NOMINAL_WORKFLOW.txt), or use the [AI user guide](docs/AI_USER_GUIDE.md).
5. Read the [definitions](docs/terminology_definitions.md), [methodology](docs/METHODOLOGY.md), [scientific limitations](docs/SCIENTIFIC_LIMITATIONS.md) and [output interpretation](docs/AUDIT.md).

Keep assessment inputs, decisions and results outside the package. Examples are invented and are not scientific defaults. No country datasets, growth/capacity defaults or automatic eligibility rules are supplied. Choose and justify these inputs for the assessment.

## Contents

- `src/open_fnrb`: calculation, GIS preparation, uncertainty and audit implementation.
- `examples`: ready-made synthetic GIS inputs, synthetic tables and a reproducible generator.
- `templates`: blank Excel and CSV input templates.
- `docs`: installation, input, method and interpretation guides.
- `docs/diagrams`: level 1 and level 2 system and business-process diagrams in Mermaid format.
- `tools`: environment/installation checks, explicit raster decoding and source packaging utilities.
- `tests`: numerical and workflow checks using synthetic inputs.

Outputs include Excel summaries, CSV/JSON audit records, GeoTIFFs and shapefiles. Monte Carlo runs retain draws, checkpoints and spatial uncertainty summaries. Full-iteration GIS is optional.

See [repository setup](docs/REPOSITORY.md) for source upload, byte preservation and local verification.

Software licence: GPL-3.0-or-later. See [copyright](COPYRIGHT.md), [licence](LICENSE) and [external materials](docs/EXTERNAL_MATERIALS.md).
