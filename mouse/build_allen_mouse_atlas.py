import sys
import urllib.request
from collections import namedtuple
import csv
import io
import json
import re

FormatVersion = '0.9'
AllenDownloadBaseURL = 'http://download.alleninstitute.org/informatics-archive/current-release/mouse_ccf/'
MouseCCFAverageTemplateBaseURL = AllenDownloadBaseURL + 'average_template/'
MouseCCFAraNisslURL = AllenDownloadBaseURL + 'ara_nissl/'

MouseCCFDownloadBaseURL = AllenDownloadBaseURL + 'annotation/ccf_2017/'
MouseCCFMeshBaseURL = MouseCCFDownloadBaseURL + 'structure_meshes/'
MouseCCFMaskBaseURL = MouseCCFDownloadBaseURL + 'structure_masks/'

OntologyQueryURL = ('http://api.brain-map.org/api/v2/data/query.csv?' + 
            'criteria=model::Structure,' +
            'rma::criteria,[ontology_id$eq1],' + 
            'rma::options[order$eq%27structures.graph_order%27][num_rows$eqall]')

resolutions = [10, 25, 50, 100]

def possibly_int(x):
    try:
        return int(x)
    except ValueError:
        return x

def get_allen_mouse_ontology():
    """Retrieve the V2 Allen ontology as CSV, then unpack it into data records."""
    query = OntologyQueryURL
    fp = io.TextIOWrapper(urllib.request.urlopen(query))
    results = {}
    reader = csv.reader(fp)
    Data = namedtuple("Data", next(reader))  # get names from column headers
    for data in map(Data._make, reader):
        results[int(data.id)] = {k: possibly_int(v) for k, v in data._asdict().items()}
    return results


def get_mesh_names():
    """ Get the mesh OBJ filenames from the download directory.
        This is the only way I could find to identify the structures of a particular atlas.
        I'm sure there's another way.
    """
    url = MouseCCFMeshBaseURL
    fp = io.TextIOWrapper(urllib.request.urlopen(url))
    meshes = set()
    for line in fp:
        if not '.obj' in line:
            continue
        m = re.search(r'(\d+\.obj)', line)
        if not m:
            continue
        meshes.add(m.group(1))

    return list(meshes)

def get_mesh_ids():
    mesh_names = get_mesh_names()
    mesh_ids = [int(m.replace('.obj', '')) for m in mesh_names]
    return mesh_ids

def find_children(ontology):
    """Set up links from parents to children in the Allen ontology."""
    for entry in ontology.values():
        parent_id = entry['parent_structure_id']
        if parent_id == '':
            continue
        parent = ontology[parent_id]
        try:
            child_id_list = parent['child_structure_ids']
        except:
            child_id_list = parent['child_structure_ids'] = []
        child_id_list.append(entry['id'])


# create different kinds of nodes
def Header(id_, roots, backgroundImages=None, annotation=None):
    ret = {
        '@id': id_,
        "@type": 'Header',
        'root': [r['@id'] for r in roots],
        'formatVersion': FormatVersion,
    }

    if backgroundImages:
        ret['backgroundImage'] = [i['@id'] for i in backgroundImages]

    if annotation:
        ret['annotation'] = annotation

    return ret

def BaseURL(id_, url):
    return {
        "@id": id_,
        "@type": "BaseURL",
        "url": url
    }

def DataSource(id_, baseURL, mimeType, source, annotation=None, extra_types=None):

    type_ = 'DataSource' if not extra_types else ['DataSource', *extra_types]
    ret = {
        "@id": id_,
        "@type": type_,
        "baseURL": baseURL['@id'],
        "mimeType": mimeType,
        "source": source,
    }
    if annotation:
        ret['annotation'] = annotation
    return ret


def Structure(id_, structure_id, color, mesh_ds, label_ds, is_group=False, annotation=None):
    shape =  {
        "@type": "Shape",
        'dataSource': [mesh_ds['@id']]
    }
    for ds in label_ds:
        shape['dataSource'].append(ds['@id'])

    ret = {
        "@id": id_,
        "@type": ["Structure", "Group"] if is_group else "Structure",
        "style": { 
            "color": color 
        },
        "shape": shape
    }
    if annotation:
        ret["annotation"] = annotation

    return ret

def add_members_to_group(s, m):
    if 'members' in s:
        v = set(s['members'])
        v.add(m['@id'])
        s['members'] = list(v)
    else:
        s['members'] = [m['@id']]

    if '@type' not in s:
        s['@type'] = 'Group'
        return s

    s_type = s['@type']

    if s_type == 'Group':
        return s

    if isinstance(s_type, str):
        s['@type'] = [s_type, 'Group']
        return s

    s_type = set(s_type)
    if 'Group' in s_type:
        return s

    s_type.add('Group')
    s['@type'] = list(s_type)
    return s


def Group(id_, children, color, annotation):
    return {
        '@id': id_,
        '@type': 'Group',
        'annotation': annotation,
        'style': 
        { 
            'color': color 
        },
        'members': [s['@id'] for s in children]
    }


def build_atlas(ontology, mesh_ids):
    result_nodes = []
    mesh_base = BaseURL("#mesh_base_url", MouseCCFMeshBaseURL)
    mask_base = BaseURL("#mask_base_url", MouseCCFMaskBaseURL)
    download_base = BaseURL("#mesh_download_url", MouseCCFDownloadBaseURL)
    average_template_base = BaseURL('#average_template_base_url', MouseCCFAverageTemplateBaseURL)
    ara_nissl_base = BaseURL('#ara_nissl_base_url', MouseCCFAraNisslURL)

    result_nodes.extend([mesh_base, mask_base, download_base, average_template_base, ara_nissl_base])

    # meshes
    mesh_data_sources = {}
    for mid in mesh_ids:
        mesh_data_sources[mid] = DataSource("#mesh_ds_{}".format(mid), 
                                    mesh_base, 'text/plain', "{}.obj".format(mid), 
                                    extra_types=["GeometryDataSource", "TriangleMeshDataSource"])
    result_nodes.extend(mesh_data_sources.values())

    # voxel masks
    label_data_sources = {}
    for mid in mesh_ids:
        label_data_sources[mid] = {}
        for r in resolutions:
            label_data_sources[mid][r] = DataSource('#mask_ds_{}_{}'.format(r, mid),
                                        download_base, 'application/octet-stream',
                                        'structure_masks_{}/structure_{}.nrrd'.format(r, mid), 
                                        { 
                                            'spatialResolutionMicrons': r
                                        },
                                        extra_types=['ImageDataSource', 'VoxelMaskDataSource'])

    result_nodes.extend([n for x in label_data_sources.values() for n in x.values()])

    # structures
    structures = {}
    for mid in mesh_ids:
        ontology_entry = ontology[mid]
        color = '#{}'.format(ontology_entry['color_hex_triplet'])
        structures[mid] = Structure("#structure_{}".format(mid), mid, color,
                            mesh_data_sources[mid], 
                            label_data_sources[mid].values(), 
                            is_group=False, 
                            annotation = {
                                'name': ontology_entry['safe_name'],
                                'acronym': ontology_entry['acronym'],
                                'allenAtlasId': ontology_entry['id']
                            }
                        )
    result_nodes.extend(structures.values())

    # add groups that aren't structures if we need them (currently, we don't)
    if False:
        groups = {}
        for k, s in structures.items():
            parent_id = ontology[k]['parent_structure_id']
            if parent_id == '':
                pass
            elif parent_id in structures:
                add_members_to_group(structures[parent_id], s)
            elif parent_id in groups:
                add_members_to_group(structures[parent_id], s)
            else: # make a new group
                ontology_entry = ontology[parent_id]
                color = '#{}'.format(ontology_entry['color_hex_triplet'])
                groups[parent_id] = Group('#group_{}'.format(parent_id), [s], color, 
                        annotation = {
                        'name': ontology_entry['safe_name'],
                        'acronym': ontology_entry['acronym'],
                        'allenAtlasId': ontology_entry['id']
                    }
                )

    # average templates
    average_templates = {}
    for r in resolutions:
        average_templates[r] = DataSource('#average_template_ds_{}'.format(r), 
                            average_template_base,
                            'application/octet-stream', 
                            'average_template_{}.nrrd'.format(r), 
                            { 'spatialResolutionMicrons': r },
                            extra_types=['ImageDataSource', 'AverageTemplateDataSource'])
    
    result_nodes.extend(average_templates.values())

    # average templates
    ara_nissl = {}
    for r in resolutions:
        ara_nissl[r] = DataSource('#ara_nissl_ds_{}'.format(r), 
                            ara_nissl_base,
                            'application/octet-stream', 
                            'ara_nissl_{}.nrrd'.format(r), 
                            { 
                                'spatialResolutionMicrons': r
                            },
                            extra_types=['ImageDataSource', 'AraNisslDataSource'])

    
    result_nodes.extend(ara_nissl.values())

    header = Header('#__header__', [structures[997]], 
                average_templates.values(), 
                {
                    'name': "Allen Mouse CCF Atlas",
                    'about': [
                        'http://help.brain-map.org/display/mousebrain/',
                        'http://help.brain-map.org/display/mousebrain/API',
                        "http://portal.brain-map.org/"
                    ]
                })
    result_nodes.insert(0, header)

    return result_nodes


if __name__ == '__main__':
    ontology = get_allen_mouse_ontology()
    find_children(ontology)
    
    mesh_ids = get_mesh_ids()

    a = build_atlas(ontology, mesh_ids)
    print(json.dumps(a, indent=2))
