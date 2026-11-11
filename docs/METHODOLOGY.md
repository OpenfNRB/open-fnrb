# Single-year calculation

The reporting unit is a user-defined assessment area over one year. Biomass densities use tonnes of dry woody matter per hectare. Estimated annual harvest uses tonnes of dry woody matter per year. Household woody biomass use is treated as a proxy for harvested biomass only under the documented sourcing assumption. See [definitions](terminology_definitions.md). Input records preserve native biomass-cell identities when boundaries, classes and ecological zones split cells.

## Starting stock and growth

Direct AGB supplies starting stock B0. The canopy route uses B0 = tree-cover fraction × reference capacity Kref. In Monte Carlo, canopy stock and growth use the same sampled reference capacity. No canopy threshold determines resource eligibility.

Effective capacity is Keff = max(Kref, B0). Peak increment I remains unchanged when capacity is raised. The logistic coefficient is r = 4I / Keff. Within the year the model solves concurrent growth and prescribed harvesting:

`dB/dt = r B (1 − B / Keff) − h`

The instantaneous biological increment is `G(B) = 4I (B/Keff) (1 − B/Keff)`.
I is the curve's peak, not the growth applied at every stock. Growth equals I
only at half capacity; it is zero at zero stock and at capacity. The stock
position and growth change continuously during the single assessment year.

Kref is a total stock ceiling, not additional headroom above starting AGB.
For B0 = 60 and Kref = 100 t/ha, initial headroom is 40 t/ha. For B0 = 150
and Kref = 100, effective capacity is 150 and initial headroom is zero.
In the latter case, growth starts at zero and can become positive as harvesting
lowers stock. Raising capacity recalculates r while preserving I.

Growth and capacity are user-supplied model parameters. Using published mean forest stock as reference capacity or annual increment as peak logistic increment is a proxy assumption requiring explicit justification. Such values do not establish local equilibrium capacity or peak productivity. The model does not fit parameters to paired stock/growth observations automatically, and no ecological parameter defaults are bundled.

Biomass is constrained to remain nonnegative. Harvesting stops when available stock is exhausted; unrealised harvest is retained. Exactly zero starting stock produces no growth. Missing stock/uncertainty is an input error, not zero. Explicit uncertain-zero sampling can produce positive starting stock only under the acknowledged configured policy.

## Harvest and accounting

Estimated annual harvest is applied as prescribed annual harvest and allocated uniformly per eligible hectare. Unrealised harvest from depleted cells is not transferred to other cells. Travel-based boundaries use the documented straight-line collection radius and dissolved buffers; they do not simulate road networks, terrain or tenure. Eligibility and exclusions are user-supplied.

Let H be estimated annual harvested biomass applied as prescribed annual harvest, and R be annual woody biomass regeneration modelled during concurrent harvesting over the household-accessible resource base. The primary output is:

`NRB = max(0, H - R)` and `fNRB = NRB / H`, for H > 0.

For H = 0 the tool reports zero with a zero-prescribed-harvest flag. The denominator includes unrealised harvest. Stock depletion and realised-harvest ratios are separate diagnostics, not replacements for the annual harvest-regeneration metric. Fire, land-use conversion and other disturbances are not independently simulated in this implementation. There is no multi-year stock carry-forward or marginal intervention counterfactual.

## Uncertainty

Positive growth/capacity parameters use arithmetic-mean-preserving lognormal draws with shared source-group identities. Growth and capacity groups are independent under the supported acknowledged configuration. Positive AGB uses mean-preserving lognormal draws; uncertain mapped zeros require an explicit policy. Canopy uses a normal-error model truncated to [0,1]; its boundary-induced mean shift is recorded. Stock errors use explicit independent-native-cell or shared-error scenarios.

Harvest may remain fixed or use the supported documented distribution/bootstrap specification. Household counts, travel assumptions and boundaries remain fixed within a run; alternatives use separate scenarios. Unsupported distributions are rejected rather than approximated silently.

Optional classification sampling uses user-supplied conditional probabilities of reference class given mapped class. All fragments of a native classification cell share a draw. Sampling changes resource eligibility only; ecological zones, parameter sources, exclusions and household allocation remain fixed. Candidate preparation includes land that could become eligible. Matrix-estimation uncertainty and spatial classification-error correlation are not represented.

Monte Carlo reports mean, median, standard deviation, P10 and P90. Numerical checks assess fNRB mean and percentile stability and may extend runs to the configured limit. They are not guarantees of ecological validity or total uncertainty coverage. Spatial percentiles have no separate precision acceptance test.

## Reproducibility and limits

Inputs, code, runtime, configuration and seeds determine a run. Restart verifies these records; failed draws are not silently removed or replaced. Numerical tests cover conservation, sampling, preparation and workflows. Independent observations and suitable scientific benchmarks are still required to evaluate ecological validity.

Supported area measurement uses suitable projected metre CRSs or regional WGS84 longitude/latitude grids. Antimeridian/global-width domains and other geographic datums require preprocessing. Bounded raster reads reduce input-buffer memory; geometry and export memory still scale with the assessment. See [scientific limitations](SCIENTIFIC_LIMITATIONS.md) for the scope of interpretation.
