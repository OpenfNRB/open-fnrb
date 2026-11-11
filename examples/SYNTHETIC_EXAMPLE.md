# Synthetic example

All locations, raster values, parameters, harvest and class counts here are invented. These examples test software operation and do not establish ecological accuracy. They require no downloads or provider account.

`synthetic/agb`, `synthetic/canopy` and `synthetic/classification` contain ready-made input sets. Each contains a four-cell grid (100 m by 100 m cells), stock, uncertainty, land cover, a GeoPackage boundary/zone, CSV tables and nominal/Monte Carlo configurations. The classification example also contains an invented confusion matrix. All paths within these inputs are relative.

Copy the desired folder to a new assessment directory outside the package. From the package folder in QGIS Python:

```text
python run_open_fnrb.py nominal C:/assessments/agb/workflow.json --output C:/assessments/agb-results
python run_open_fnrb.py monte-carlo C:/assessments/agb/workflow.json --sampling C:/assessments/agb/sampling.json --output C:/assessments/agb-mc-results
```

The supplied Monte Carlo configurations start at 10,000 iterations and may extend to 50,000. Inspect completion and precision status. For a short installation check, use tools/check_installation.py instead; it deliberately uses only 32 draws and is not a precision assessment.

To regenerate the examples in new external directories:

```text
python examples/create_nominal_example.py C:/assessments/new-agb
python examples/create_nominal_example.py C:/assessments/new-canopy --stock-mode canopy
python examples/create_nominal_example.py C:/assessments/new-classification --classification-uncertainty
python examples/create_nominal_example.py C:/assessments/new-travel --boundary-mode travel
```

Output directories must be new. See NOMINAL_WORKFLOW.txt for configuration and interpretation details. Never replace real evidence with these demonstration values.
