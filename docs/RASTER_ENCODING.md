# Raster encoding and uncertainty

Physical decoding converts stored values to physical units. Statistical interpretation determines how uncertainty informs Monte Carlo draws. Verify both from the selected product and version; neither can be inferred from filenames or transferred automatically between representations. Mask missing codes before conversion, preserve true zeros, and apply scaling exactly once.

## Explicit local decoding

`tools/prepare_encoded_raster.py` processes a self-contained local, single-band raster in blocks of at most 256 by 256 cells. It preserves the full native grid, uses Float64 output, and applies the declared multiplier and offset directly to raw values exactly once. Missing values are masked before domain validation; true zeros remain zeros. Out-of-domain values cause failure rather than clipping. This utility does not crop, resample, download global rasters, or assign scientific uncertainty distributions.

Supply a JSON configuration with exactly these fields:

| Field | Meaning |
| --- | --- |
| source | Local file path, relative to the configuration file or absolute |
| source_sha256 | Verified SHA-256 of that file |
| source_reference | Product, version, year and source reference |
| encoding_evidence | Evidence supporting the raw-to-physical conversion |
| acknowledged | Explicit true after reviewing the encoding contract |
| expected_data_type | Exact GDAL type, such as Int16 or UInt16 |
| expected_gdal_scale / expected_gdal_offset | Exact stored metadata; JSON null means absent |
| raw_nodata | Explicit extra missing-value codes; use [] when none |
| multiplier / offset | Complete raw-to-physical conversion, without an additional GDAL multiplication |
| output_units | Units expected by the assessment input contract |
| minimum / maximum | Allowed physical domain; maximum may be null |

```text
python tools/prepare_encoded_raster.py C:/assessments/encoding.json --output C:/assessments/decoded_stock
```

The output directory must be new. `decoded.tif` and `preparation_record.json` preserve the conversion, original metadata, runtime, file hashes, counts and errors. Read status before using a file: a failed preparation may leave an incomplete TIFF for diagnosis. Only complete outputs should enter an assessment. The source hash is checked before and after processing. Unpinned sidecars and VRT dependencies are rejected.

For stock and uncertainty, prepare both with their own evidence, then use the normal assessment alignment checks. A known physical-unit raster can use multiplier one; do not apply a provider's raw conversion again to an already decoded export. This utility detects conflicting expectations, but cannot validate an incorrect scientific encoding contract supplied by a user.
