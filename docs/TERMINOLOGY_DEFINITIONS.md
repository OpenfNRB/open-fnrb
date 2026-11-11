# Terminology definitions

This glossary defines the quantities, spatial scope, input fields and calculation terms used by OpenfNRB. The harvested-biomass and fNRB definitions follow [A6.4-AMT-009 version 01.0, section 2.2](https://unfccc.int/sites/default/files/resource/A6.4-AMT-009-v01.0.pdf). Simulation terms describe the implemented model and its accounting conventions; they do not imply methodological approval.

## Units and assessment period

The assessment period is one year. Biomass masses are tonnes of dry woody biomass; stock densities are tonnes per hectare. Annual household-use means are tonnes per household per year. A prescribed removal rate is tonnes per hectare per year; integrated annual cell quantities are tonnes per hectare over the assessment year. Fractions are dimensionless.

## Household use and harvested biomass

**Annual household woody biomass use** is the annual quantity used by households represented in the assessment, estimated from household fuel-use evidence and household counts. **Mean annual woody biomass use per household** is the corresponding per-household mean. The input field is `woody_biomass_use_tonnes_per_household_year`; individual observation values use `annual_household_woody_biomass_use_tonnes`.

**Harvested biomass** is aboveground woody biomass collected or cut from living trees for fuelwood or conversion to charcoal for fuel. **Estimated annual harvested biomass** is the estimated quantity harvested from the applicable sourcing landscape during the assessment year. The annual-total input is `estimated_annual_harvest_tonnes`.

Household woody biomass use is a proxy for harvested biomass only under an explicit sourcing assumption. Explain whether fuel is locally collected, purchased, imported, stockpiled or supplied through other channels. Use only the justified quantity attributable to the assessed landscape. Apply evidence-backed upstream conversions for wet fuel, charcoal, energy, volume or other measurement bases. The tool does not independently infer fuel provenance, sourcing shares or conversion factors. **Fuel consumption** describes measured fuel use captured by KPT and other household surveys.

## Prescribed and realised harvesting

| Term | Code or output name | Definition |
|---|---|---|
| Prescribed annual harvest | `prescribed_annual_harvest_tonnes` | Annual quantity the simulation attempts to remove, derived from estimated annual harvested biomass. |
| Prescribed harvest rate | `prescribed_harvest_rate` | Constant removal rate per hectare applied while biomass remains available. The annual model applies the same rate per eligible hectare. |
| Prescribed annual harvest per hectare | `prescribed_harvest_t_ha` | Prescribed removal per hectare over the full assessment year. |
| Modelled realised harvest | `realised_harvest_tonnes`, `realised_harvest_t_ha` | Quantity actually removed in the simulation, subject to local stock availability. Harvesting stops when a cell is exhausted. |
| Unrealised harvest | `unrealised_harvest_tonnes`, `unrealised_harvest_t_ha` | Prescribed harvest minus modelled realised harvest. It is not transferred to other cells. It does not establish where replacement fuel was obtained. |
| Harvest realisation fraction | `harvest_realisation_fraction` | Realised harvest divided by prescribed annual harvest; undefined when prescribed harvest is zero. |
| Zero prescribed harvest flag | `zero_prescribed_harvest` | True when prescribed annual harvest is zero. Reported zero fNRB is then a convention because the ratio has a zero denominator. |

## Regeneration and non-renewability

**Annual woody biomass regeneration** is the biomass regenerated during the assessment year within the household-accessible woody biomass resource base, as estimated by the model under concurrent harvesting. Aggregate output: `annual_woody_biomass_regeneration_tonnes`. Cell output: `annual_regeneration_t_ha`. It is the integrated biological increment, not a separately established sustainable yield or a management certification.

**Non-renewable biomass (NRB)** is the portion of estimated annual harvested biomass exceeding estimated annual regeneration within the same landscape and period, bounded below by zero. Output: `non_renewable_biomass_tonnes`.

**Fraction of non-renewable biomass (fNRB)** is the proportion of harvested biomass that exceeds the natural rate of regeneration of the landscape during a given period. Output: `fnrb`; metric identifier: `annual_harvest_regeneration_fnrb`.

The implementation calculates:

```text
H = estimated annual harvested biomass applied as prescribed annual harvest
R = modelled annual woody biomass regeneration
NRB = max(0, H - R)
fNRB = NRB / H, for H > 0
```

H includes unrealised harvest. The denominator is not modelled realised harvest. This distinction is material when the simulation cannot fulfil the prescribed extraction. Positive H with no eligible resource produces fNRB = 1; zero H produces the flagged zero convention. fNRB is not a deforestation rate, pixel-level forest-loss fraction or marginal intervention emissions estimate.

**Modelled stock depletion** (`stock_depletion_tonnes`) is the area-weighted sum of positive reductions in stock between the start and end of the year. Increases in other cells do not cancel local depletion in this diagnostic. It is distinct from NRB. `stock_depletion_ratio_diagnostic` divides that quantity by realised harvest where realised harvest is positive.

**Stock and regeneration shortfall** (`stock_and_regeneration_shortfall_tonnes`) is `max(0, H - starting stock - R)` using assessment totals. This aggregate diagnostic does not account for spatial distribution and may differ from unrealised harvest.

## Spatial scope

| Term | Definition |
|---|---|
| Household biomass sourcing landscape | Broader geographical catchment within which the assessment represents households as sourcing woody biomass. |
| Household-accessible harvesting area | Portion of that landscape included for harvesting after eligibility rules, exclusions and accessibility constraints. Code uses `eligible_area_ha` and prepared area records. |
| Household-accessible woody biomass resource base | Woody biomass resources represented within the household-accessible harvesting area. |
| Candidate resource area | Fixed support containing land that can become eligible under the configured classification sampling. It is not necessarily all eligible in an individual draw. |

Eligibility is an explicit assessment assumption. A mapped eligible class does not independently establish access rights or actual collection behaviour. Source-cell fragments retain their shared native-cell identity.

## Stock and growth parameters

| Term | Code or output name | Definition |
|---|---|---|
| Starting woody biomass stock | `start_woody_stock_tonnes`, `starting_stock_t_ha` | Modelled biomass stock at the start of the year. |
| Closing woody biomass stock | `end_woody_stock_tonnes`, `closing_stock_t_ha` | Modelled biomass stock at the end of the year after regeneration and realised harvesting. |
| Reference carrying capacity | `reference_capacity_t_ha` | User-supplied reference stock ceiling used in the logistic model and canopy-to-stock conversion. |
| Effective carrying capacity | `effective_capacity_t_ha` | Maximum of reference capacity and starting stock. |
| Peak annual increment | `peak_increment_t_ha_year` | Maximum of the logistic growth curve, occurring at half effective capacity. It is not the actual annual regeneration at every stock level or automatically mean annual increment. |

Biological growth functions describe the instantaneous stock response. Annual regeneration is the biological increment integrated over the assessment year.

## Input resolution and uncertainty names

| Name | Meaning |
|---|---|
| `Harvest`, `harvest.csv` | Input table/worksheet and its CSV representation. Contains either an annual harvest estimate or household-use evidence used to derive it. |
| `harvest_input_mode` | Route selected using `annual_total`, `household_count` or `built_up_allocation`. |
| `harvest_uncertainty` | Tabular configuration specifying fixed, lognormal or household-bootstrap uncertainty. |
| `harvest_model` | Resolved fixed or stochastic annual-harvest specification passed to the simulation. |
| `harvest_input_record` | Selected source record and its provenance. |
| `harvest` | Saved-record container for resolved harvest values, uncertainty settings and audit evidence. |
| `harvest_inputs` | Local variable holding that resolved container. |
| `prescribed_annual_harvest` | Internal numerical annual-harvest variable. |
| `estimate_annual_harvest()` | Household count multiplied by mean annual woody biomass use per household, under the sourcing assumption. |
| `resolve_harvest()` | Resolves the selected route, central harvest quantity, uncertainty adapter and audit evidence. |
| `_validate_harvest()` | Validates the annual-harvest quantity and sampling specification. |
| `_sample_harvest()` | Produces an annual-harvest draw under the configured model. |
| `bootstrap_household_woody_biomass_use()` | Resamples household-use observations under the specified survey-unit and weighting rules. |
| `AnnualFlux.regeneration` | Integrated biological increment per hectare returned by the annual solver. |
| `AnnualFlux.realised_harvest` | Actual removal per hectare returned by the annual solver. |
| `AnnualFlux.unrealised_harvest` | Unfulfilled prescribed removal per hectare returned by the annual solver. |

Household-use bootstrap uncertainty does not sample household totals, allocation, sourcing boundaries or arbitrary market flows. Fixed inputs are disclosed assumptions, not evidence that uncertainty is absent. See [methodology](METHODOLOGY.md), [scientific limitations](SCIENTIFIC_LIMITATIONS.md) and [input requirements](INPUTS.md).
