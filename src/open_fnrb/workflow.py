# SPDX-License-Identifier: GPL-3.0-or-later
"""File-driven nominal assessments with persistent validation and failure evidence."""
from datetime import datetime, timezone
from pathlib import Path
import csv
import json
import platform
import traceback
import numpy as np
from osgeo import gdal

from .input_config import load_tabular_config,fields,unique_object
from .gis_inputs import RasterSpec,RasterSource,read_polygons,prepare_raster_pair,fingerprint,require_area_crs,spatial_reference
from .spatial_inputs import categorical_support,households_from_raster,TransformSettings
from .preparation import union_boundaries
from .area import PlanarArea,WGS84Area
from .annual import assess_year,stock_from_canopy
from .tables import read_table
from .gis_exports import export_nominal_gis
from .point_inputs import read_points
from .travel import collection_boundary
from .excel_report import export_excel,TEMPLATE
from .runtime import runtime_record


def write_json(path,value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def run_nominal(config_path,output):
    """Run polygon or travel-point boundary workflows into a new output directory.

    CSV/JSON, lossless prepared records, GeoTIFFs and shapefiles are exported.
    The Excel summary and Monte Carlo workflow are separate components.
    """
    output = Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    def event(step,**details):
        with (output/'events.jsonl').open('a',encoding='utf-8') as handle:
            handle.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),step=step,**details),allow_nan=False)+'\n')
    event('started')
    write_json(output/'status.json',dict(status='running',phase='validation'))
    try:
        from .provenance import execution_identity
        package_identity=execution_identity()
        path = Path(config_path).resolve(strict=True)
        config = json.loads(path.read_text(encoding='utf-8-sig'),object_pairs_hook=unique_object,
                            parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f'Invalid JSON number {x}.')))
        required={'schema_version','tabular_config','stock_mode','stock','stock_uncertainty',
                  'uncertainty_interpretation','boundary','zones','land_cover','exclusions',
                  'projection_suitability_acknowledged'}
        fields(config,required,{'household_allocation','land_cover_transform','maximum_raster_block_cells','classification_uncertainty'})
        maximum_block_cells=config.get('maximum_raster_block_cells',65536)
        if type(maximum_block_cells) is not int or maximum_block_cells<=0:
            raise ValueError('Positive integer maximum_raster_block_cells required.')
        if type(config['schema_version']) is not int or config['schema_version'] != 1:
            raise ValueError('Unsupported workflow schema version.')
        if type(config['projection_suitability_acknowledged']) is not bool:
            raise ValueError('Projection suitability acknowledgement must be explicit boolean.')
        def local(reference):
            if not isinstance(reference,str) or not reference:
                raise ValueError('Nonempty local file path required.')
            return (path.parent/reference).resolve(strict=True)
        def raster(value):
            fields(value,{'path','units','source','version','date'},{'band'})
            return RasterSpec(**dict(value,path=str(local(value['path']))))
        def categorical_transform(value):
            if value is None:return None
            fields(value,{'domain_to_source','cells_to_stock'})
            for settings in value.values():
                fields(settings,{'max_source_segment','target_tolerance','maximum_accuracy_metres'},{'maximum_refinements'})
            return {key:TransformSettings(**settings) for key,settings in value.items()}
        intake = load_tabular_config(local(config['tabular_config']))
        stock,uncertainty = raster(config['stock']),raster(config['stock_uncertainty'])
        with RasterSource(stock) as source:
            crs = source.crs.Clone()
        if crs.IsGeographic():
            if not crs.IsSame(spatial_reference('EPSG:4326')):
                raise ValueError('Geographic workflow currently requires WGS84.')
            measure = WGS84Area()
        else:
            require_area_crs(crs,distortion_acknowledged=config['projection_suitability_acknowledged'])
            measure = PlanarArea()
        vector_audit=[]
        def vectors(value,field=None):
            fields(value,{'path'}, {'layer','transform'})
            target=local(value['path'])
            settings=None
            if 'transform' in value:
                fields(value['transform'],{'max_source_segment','target_tolerance','maximum_accuracy_metres'}, {'maximum_refinements'})
                settings=TransformSettings(**value['transform'])
            records=read_polygons(target,expected_crs=crs,layer_name=value.get('layer'),
                     required_fields=() if field is None else (field,),transformation_settings=settings)
            dataset=gdal.OpenEx(str(target),gdal.OF_VECTOR|gdal.OF_READONLY)
            filelist=dataset.GetFileList() if dataset is not None else None
            dataset=None
            if not filelist:
                raise ValueError('Cannot enumerate vector dependencies for audit.')
            vector_audit.append(dict(files=[fingerprint(f) for f in sorted(set(filelist))],
                layer=value.get('layer'),transformations=[r['transformation'] for r in records]))
            return records
        travel,points,point_audit=None,None,None
        boundary_config=config['boundary']
        if not isinstance(boundary_config,dict):
            raise ValueError('Explicit boundary configuration required.')
        if boundary_config.get('kind')=='travel':
            fields(boundary_config,{'kind','points'})
            point_config=boundary_config['points']
            fields(point_config,{'path','id_field'},{'layer','maximum_accuracy_metres'})
            if 'Travel' not in intake.tables:
                raise ValueError('Travel boundary requires a Travel table for the selected assessment.')
            points,point_audit=read_points(local(point_config['path']),expected_crs=crs,
                id_field=point_config['id_field'],layer_name=point_config.get('layer'),
                maximum_accuracy_metres=point_config.get('maximum_accuracy_metres'))
            settings=intake.selected('Travel')
            travel=collection_boundary(points=points,crs=crs.ExportToWkt(),
                **{k:settings[k] for k in ('round_trip_hours','travelling_share','speed_kmh','edge_tolerance_metres')},
                distortion_acknowledged=config['projection_suitability_acknowledged'])
            boundary=travel.geometry
        else:
            boundary=union_boundaries([r['geometry'] for r in vectors(boundary_config)])
        fields(config['zones'],{'vector','zone_field'})
        if not isinstance(config['zones']['zone_field'],str) or not config['zones']['zone_field']:
            raise ValueError('Explicit ecological zone identifier field required.')
        parameters=intake.parameters()
        mapping={p.name:i for i,p in enumerate(parameters)}
        zones=[]
        for row in vectors(config['zones']['vector'],config['zones']['zone_field']):
            identity=row['fields'][config['zones']['zone_field']]
            if identity not in mapping:
                raise ValueError(f'No parameter record for ecological zone {identity}.')
            zones.append((mapping[identity],row['geometry']))
        if not isinstance(config['exclusions'],list):
            raise ValueError('Supply exclusion layers explicitly, or an empty list for none.')
        exclusions=[r['geometry'] for item in config['exclusions'] for r in vectors(item)]
        classes=categorical_support(spec=raster(config['land_cover']),domain=boundary,expected_crs=crs,
                    rules=intake.eligibility(),area_measure=measure,
                    transformation_settings=categorical_transform(config.get('land_cover_transform')),maximum_block_cells=maximum_block_cells)
        allocations=None
        allocation_audit=None
        built_up=None
        administrative=None
        harvest_input_mode=intake.selected('Harvest')['mode']
        if harvest_input_mode == 'built_up_allocation':
            if 'household_allocation' not in config:
                raise ValueError('Built-up harvest requires household_allocation GIS settings.')
            allocation=config['household_allocation']
            fields(allocation,{'administrative_vector','id_field','built_up','rules_table'},{'built_up_transform'})
            totals={r['administrative_id']:r['households'] for r in intake.tables['AdminHouseholds']}
            rows=vectors(allocation['administrative_vector'],allocation['id_field'])
            ids=[r['fields'][allocation['id_field']] for r in rows]
            if len(set(ids)) != len(ids) or set(ids) != set(totals):
                raise ValueError('Administrative geometries and household-total identifiers must match exactly.')
            rule_path=local(allocation['rules_table'])
            rules={r['class_code']:r['eligible'] for r in read_table(rule_path,'Eligibility')}
            allocations,built_up=households_from_raster(spec=raster(allocation['built_up']),
                administrative_areas=[(identity,totals[identity],row['geometry']) for identity,row in zip(ids,rows)],
                boundary=boundary,expected_crs=crs,rules=rules,area_measure=measure,
                transformation_settings=categorical_transform(allocation.get('built_up_transform')),maximum_block_cells=maximum_block_cells)
            allocation_audit=dict(support=built_up.audit,rules_file=fingerprint(rule_path))
            administrative=dict(geometries=[r['geometry'] for r in rows],columns={
                'record_id':np.arange(len(rows)),
                **{k:np.array([a[k] for a in allocations]) for k in
                   ('households_total','households_allocated','full_support_m2','inside_support_m2')}})
        elif 'household_allocation' in config:
            raise ValueError('Household-allocation GIS supplied for a different harvest mode.')
        harvest_inputs=intake.resolve_harvest(allocations=allocations)
        event('inputs_validated',assessment_id=intake.assessment_id)
        prepared=prepare_raster_pair(stock_spec=stock,uncertainty_spec=uncertainty,
            stock_mode=config['stock_mode'],boundary=boundary,zones=zones,
            eligibility=classes.selected,exclusions=exclusions,
            distortion_acknowledged=config['projection_suitability_acknowledged'],
            uncertainty_interpretation=config['uncertainty_interpretation'],maximum_block_cells=maximum_block_cells)
        event('prepared',records=len(prepared.area_ha))
        classification_model=None
        if 'classification_uncertainty' in config:
            from .classification import load_classification_matrix,prepare_classification_support
            from .gis_exports import write_polygons,write_raster
            settings=config['classification_uncertainty']
            fields(settings,{'matrix','source_id','orientation','dependence','acknowledged','scope'})
            if settings['scope']!='resource_eligibility_only':
                raise ValueError('Classification sampling currently supports resource_eligibility_only; ecological zones and household allocation remain fixed.')
            model=load_classification_matrix(local(settings['matrix']),**{k:settings[k] for k in
                ('source_id','orientation','dependence','acknowledged')})
            candidate=prepare_classification_support(classes=classes,model=model,rules=intake.eligibility(),area_measure=measure,
                stock_spec=stock,uncertainty_spec=uncertainty,stock_mode=config['stock_mode'],boundary=boundary,zones=zones,
                exclusions=exclusions,distortion_acknowledged=config['projection_suitability_acknowledged'],
                uncertainty_interpretation=config['uncertainty_interpretation'],maximum_block_cells=maximum_block_cells)
            support=candidate.prepared
            candidate_arrays=dict(area_ha=support.area_ha,source_cell_id=support.source_cell_ids,zone_index=support.zone_index,
                mapped_stock=support.mapped_stock,stock_uncertainty=support.stock_scale,
                class_cell_id=candidate.class_cell_ids,mapped_class=candidate.mapped_classes,nominal_eligible=candidate.nominal_eligible)
            np.savez_compressed(output/'classification_candidates.npz',**candidate_arrays)
            with (output/'classification_candidates.csv').open('w',newline='',encoding='utf-8') as handle:
                writer=csv.writer(handle);writer.writerow(['record_id',*candidate_arrays,'geometry_wkt'])
                for i,g in enumerate(support.geometries):writer.writerow([i,*[v[i] for v in candidate_arrays.values()],g.wkt])
            classification_model=dict(codes=list(model.codes),counts=[list(r) for r in model.counts],source_id=model.source_id,
                evidence=model.evidence,rules={str(k):v for k,v in intake.eligibility().items()},preparation=support.audit)
        capacity=np.array([p.capacity_mean for p in parameters])[prepared.zone_index]
        increment=np.array([p.increment_mean for p in parameters])[prepared.zone_index]
        start=prepared.mapped_stock if config['stock_mode']=='agb' else stock_from_canopy(prepared.mapped_stock,capacity)
        result=assess_year(prepared.area_ha,start,capacity,increment,harvest_inputs['prescribed_annual_harvest_tonnes'])
        gis=export_nominal_gis(output/'gis',prepared=prepared,result=result,crs=crs,measure=measure,
            boundary=boundary,zones=zones,exclusions=exclusions,classes=classes,
            stock_spec=stock,uncertainty_spec=uncertainty,built_up=built_up,administrative=administrative,
            travel=travel,points=points)
        if classification_model is not None:
            gis['layers'].append(write_polygons(output/'gis'/'classification_candidates.shp',support.geometries,
                dict(record_id=np.arange(len(support.area_ha)),**candidate_arrays),crs,units={'area_ha':'ha'}))
            metadata=support.audit;shape=tuple(metadata['shape']);r0,c0=metadata['source_origin'];width=metadata['source_shape'][1]
            area=np.zeros(shape);np.add.at(area,(support.source_cell_ids//width-r0,support.source_cell_ids%width-c0),support.area_ha)
            gis['layers'].append(write_raster(output/'gis'/'candidate_area.tif',np.where(area>0,area,np.nan),metadata['transform'],crs,
                units='ha',support='Potential resource area across mapped and possible sampled eligibility; not nominal eligible area'))
            write_json(output/'gis'/'layers.json',gis)
        event('gis_exported',layers=len(gis['layers']))
        write_json(output/'nominal.json',result.summary)
        arrays=dict(source_cell_id=prepared.source_cell_ids,zone_index=prepared.zone_index,
                    mapped_stock=prepared.mapped_stock,stock_uncertainty=prepared.stock_scale,**result.cells)
        np.savez_compressed(output/'prepared_nominal.npz',**arrays)
        with (output/'nominal_cells.csv').open('w',newline='',encoding='utf-8') as handle:
            writer=csv.writer(handle);writer.writerow(['record_id',*arrays,'geometry_wkt'])
            for i,g in enumerate(prepared.geometries):
                writer.writerow([i,*[v[i] for v in arrays.values()],g.wkt])
        with (output/'classification_cells.csv').open('w',newline='',encoding='utf-8') as handle:
            writer=csv.writer(handle);writer.writerow(['source_cell_id','class_code','selected','area_m2','geometry_wkt'])
            for r in classes.cells:
                writer.writerow([r['source_cell_id'],r['class_code'],r['selected'],r['area_m2'],r['geometry'].wkt])
        write_json(output/'run_record.json',dict(configuration=fingerprint(path),resolved_config=config,
            package_identity=package_identity,
            tabular=intake.audit,harvest=harvest_inputs,preparation=prepared.audit,classification=classes.audit,
            classification_model=classification_model,
            household_allocation=allocation_audit,vectors=vector_audit,crs_wkt=crs.ExportToWkt(),
            point_input=point_audit,travel=travel.audit if travel is not None else None,
            runtime=runtime_record(),
            code=[fingerprint(p) for p in sorted(Path(__file__).parent.glob('*.py'))],
            output_scope='nominal_tables_gis_and_excel',pending_exports=[],gis=gis,report_template=fingerprint(TEMPLATE),
            boundary_wkt=boundary.wkt,exclusions_wkt=[g.wkt for g in exclusions]))
        export_excel(output/'summary.xlsx',result.summary,json.loads((output/'run_record.json').read_text(encoding='utf-8')))
        event('nominal_complete',fnrb=result.summary['fnrb'])
        write_json(output/'status.json',dict(status='nominal_complete',output_scope='nominal_tables_gis_and_excel',pending_exports=[]))
        write_json(output/'manifest.json',dict(files=[fingerprint(p) for p in sorted(output.rglob('*')) if p.is_file()]))
        return result.summary
    except BaseException as error:
        event('failed',error_type=type(error).__name__,message=str(error))
        write_json(output/'failure.json',dict(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc()))
        write_json(output/'status.json',dict(status='failed'))
        raise
