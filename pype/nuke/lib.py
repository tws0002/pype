import os
import re
import sys
import getpass
from collections import OrderedDict

from avalon import api, io, lib
import avalon.nuke
import pype.api as pype

import nuke


from .presets import (
    get_colorspace_preset,
    get_node_dataflow_preset,
    get_node_colorspace_preset
)

from .presets import (
    get_anatomy
)
# TODO: remove get_anatomy and import directly Anatomy() here

from pypeapp import Logger
log = Logger().get_logger(__name__, "nuke")

self = sys.modules[__name__]
self._project = None


def onScriptLoad():
    ''' Callback for ffmpeg support
    '''
    if nuke.env['LINUX']:
        nuke.tcl('load ffmpegReader')
        nuke.tcl('load ffmpegWriter')
    else:
        nuke.tcl('load movReader')
        nuke.tcl('load movWriter')


def checkInventoryVersions():
    """
    Actiual version idetifier of Loaded containers

    Any time this function is run it will check all nodes and filter only
    Loader nodes for its version. It will get all versions from database
    and check if the node is having actual version. If not then it will color
    it to red.
    """
    # TODO: make it for all nodes not just Read (Loader

    # get all Loader nodes by avalon attribute metadata
    for each in nuke.allNodes():
        if each.Class() == 'Read':
            container = avalon.nuke.parse_container(each)

            if container:
                node = container["_node"]
                avalon_knob_data = avalon.nuke.get_avalon_knob_data(
                    node, ['avalon:', 'ak:'])

                # get representation from io
                representation = io.find_one({
                    "type": "representation",
                    "_id": io.ObjectId(avalon_knob_data["representation"])
                })

                # Get start frame from version data
                version = io.find_one({
                    "type": "version",
                    "_id": representation["parent"]
                })

                # get all versions in list
                versions = io.find({
                    "type": "version",
                    "parent": version["parent"]
                }).distinct('name')

                max_version = max(versions)

                # check the available version and do match
                # change color of node if not max verion
                if version.get("name") not in [max_version]:
                    node["tile_color"].setValue(int("0xd84f20ff", 16))
                else:
                    node["tile_color"].setValue(int("0x4ecd25ff", 16))


def writes_version_sync():
    ''' Callback synchronizing version of publishable write nodes
    '''
    # TODO: make it work with new write node group
    try:
        rootVersion = pype.get_version_from_path(nuke.root().name())
        padding = len(rootVersion)
        new_version = "v" + str("{" + ":0>{}".format(padding) + "}").format(
            int(rootVersion)
        )
        log.debug("new_version: {}".format(new_version))
    except Exception:
        return

    for each in nuke.allNodes():
        if each.Class() == 'Write':
            avalon_knob_data = avalon.nuke.get_avalon_knob_data(
                each, ['avalon:', 'ak:'])

            try:
                if avalon_knob_data['families'] not in ["render"]:
                    log.debug(avalon_knob_data['families'])
                    continue

                node_file = each['file'].value()

                node_version = "v" + pype.get_version_from_path(node_file)
                log.debug("node_version: {}".format(node_version))

                node_new_file = node_file.replace(node_version, new_version)
                each['file'].setValue(node_new_file)
                if not os.path.isdir(os.path.dirname(node_new_file)):
                    log.warning("Path does not exist! I am creating it.")
                    os.makedirs(os.path.dirname(node_new_file), 0o766)
            except Exception as e:
                log.warning(
                    "Write node: `{}` has no version in path: {}".format(each.name(), e))


def version_up_script():
    ''' Raising working script's version
    '''
    import nukescripts
    nukescripts.script_and_write_nodes_version_up()


def get_render_path(node):
    ''' Generate Render path from presets regarding avalon knob data
    '''
    data = dict()
    data['avalon'] = avalon.nuke.get_avalon_knob_data(
        node, ['avalon:', 'ak:'])

    data_preset = {
        "class": data['avalon']['family'],
        "preset": data['avalon']['families']
    }

    nuke_dataflow_writes = get_node_dataflow_preset(**data_preset)
    nuke_colorspace_writes = get_node_colorspace_preset(**data_preset)

    application = lib.get_application(os.environ["AVALON_APP_NAME"])
    data.update({
        "application": application,
        "nuke_dataflow_writes": nuke_dataflow_writes,
        "nuke_colorspace_writes": nuke_colorspace_writes
    })

    anatomy_filled = format_anatomy(data)
    return anatomy_filled["render"]["path"].replace("\\", "/")


def format_anatomy(data):
    ''' Helping function for formating of anatomy paths

    Arguments:
        data (dict): dictionary with attributes used for formating

    Return:
        path (str)
    '''
    # TODO: perhaps should be nonPublic

    anatomy = get_anatomy()
    log.debug("__ anatomy.templates: {}".format(anatomy.templates))

    try:
        padding = int(anatomy.templates['render']['padding'])
    except KeyError as e:
        log.error("`padding` key is not in `render` "
                  "Anatomy template. Please, add it there and restart "
                  "the pipeline (padding: \"4\"): `{}`".format(e))

    version = data.get("version", None)
    if not version:
        file = script_name()
        data["version"] = pype.get_version_from_path(file)
    project_document = pype.get_project()
    data.update({
        "root": api.Session["AVALON_PROJECTS"],
        "subset": data["avalon"]["subset"],
        "asset": data["avalon"]["asset"],
        "task": api.Session["AVALON_TASK"].lower(),
        "family": data["avalon"]["family"],
        "project": {"name": project_document["name"],
                    "code": project_document["data"].get("code", '')},
        "representation": data["nuke_dataflow_writes"]["file_type"],
        "app": data["application"]["application_dir"],
        "hierarchy": pype.get_hierarchy(),
        "frame": "#" * padding,
    })
    return anatomy.format(data)


def script_name():
    ''' Returns nuke script path
    '''
    return nuke.root().knob('name').value()


def add_button_write_to_read(node):
    name = "createReadNode"
    label = "Create Read"
    value = "import write_to_read;write_to_read.write_to_read(nuke.thisNode())"
    k = nuke.PyScript_Knob(name, label, value)
    k.setFlag(0x1000)
    node.addKnob(k)


def create_write_node(name, data, input=None, prenodes=None):
    ''' Creating write node which is group node

    Arguments:
        name (str): name of node
        data (dict): data to be imprinted
        input (node): selected node to connect to
        prenodes (list, optional): list of lists, definitions for nodes
                                to be created before write

    Example:
        prenodes = [(
            "NameNode",  # string
            "NodeClass",  # string
            (   # OrderDict: knob and values pairs
                ("knobName", "knobValue"),
                ("knobName", "knobValue")
            ),
            (   # list outputs
                "firstPostNodeName",
                "secondPostNodeName"
            )
        )
        ]

    Return:
        node (obj): group node with avalon data as Knobs
    '''

    nuke_dataflow_writes = get_node_dataflow_preset(**data)
    nuke_colorspace_writes = get_node_colorspace_preset(**data)
    application = lib.get_application(os.environ["AVALON_APP_NAME"])

    try:
        data.update({
            "application": application,
            "nuke_dataflow_writes": nuke_dataflow_writes,
            "nuke_colorspace_writes": nuke_colorspace_writes
        })
        anatomy_filled = format_anatomy(data)

    except Exception as e:
        log.error("problem with resolving anatomy tepmlate: {}".format(e))

    # build file path to workfiles
    fpath = str(anatomy_filled["work"]["folder"]).replace("\\", "/")
    fpath = data["fpath_template"].format(
        work=fpath, version=data["version"], subset=data["subset"],
        frame=data["frame"],
        ext=data["nuke_dataflow_writes"]["file_type"]
    )

    # create directory
    if not os.path.isdir(os.path.dirname(fpath)):
        log.warning("Path does not exist! I am creating it.")
        os.makedirs(os.path.dirname(fpath), 0o766)

    _data = OrderedDict({
        "file": fpath
    })

    # adding dataflow template
    log.debug("nuke_dataflow_writes: `{}`".format(nuke_dataflow_writes))
    {_data.update({k: v})
     for k, v in nuke_dataflow_writes.items()
     if k not in ["_id", "_previous"]}

    # adding colorspace template
    log.debug("nuke_colorspace_writes: `{}`".format(nuke_colorspace_writes))
    {_data.update({k: v})
     for k, v in nuke_colorspace_writes.items()}

    _data = avalon.nuke.lib.fix_data_for_node_create(_data)

    log.debug("_data: `{}`".format(_data))

    if "frame_range" in data.keys():
        _data["frame_range"] = data.get("frame_range", None)
        log.debug("_data[frame_range]: `{}`".format(_data["frame_range"]))

    GN = nuke.createNode("Group", "name {}".format(name))

    prev_node = None
    with GN:
        connections = list()
        if input:
            # if connected input node was defined
            connections.append({
                "node":  input,
                "inputName": input.name()})
            prev_node = nuke.createNode(
                "Input", "name {}".format(input.name()))
        else:
            # generic input node connected to nothing
            prev_node = nuke.createNode(
                "Input", "name {}".format("rgba"))

        # creating pre-write nodes `prenodes`
        if prenodes:
            for name, klass, properties, set_output_to in prenodes:
                # create node
                now_node = nuke.createNode(klass, "name {}".format(name))

                # add data to knob
                for k, v in properties:
                    if k and v:
                        now_node[k].serValue(str(v))

                # connect to previous node
                if set_output_to:
                    if isinstance(set_output_to, (tuple or list)):
                        for i, node_name in enumerate(set_output_to):
                            input_node = nuke.createNode(
                                "Input", "name {}".format(node_name))
                            connections.append({
                                "node":  nuke.toNode(node_name),
                                "inputName": node_name})
                            now_node.setInput(1, input_node)
                    elif isinstance(set_output_to, str):
                        input_node = nuke.createNode(
                            "Input", "name {}".format(node_name))
                        connections.append({
                            "node":  nuke.toNode(set_output_to),
                            "inputName": set_output_to})
                        now_node.setInput(0, input_node)
                else:
                    now_node.setInput(0, prev_node)

                # swith actual node to previous
                prev_node = now_node

        # creating write node
        write_node = now_node = avalon.nuke.lib.add_write_node(
            "inside_{}".format(name),
            **_data
            )

        # connect to previous node
        now_node.setInput(0, prev_node)

        # swith actual node to previous
        prev_node = now_node

        now_node = nuke.createNode("Output", "name Output1")

        # connect to previous node
        now_node.setInput(0, prev_node)

    # imprinting group node
    GN = avalon.nuke.imprint(GN, data["avalon"])

    divider = nuke.Text_Knob('')
    GN.addKnob(divider)

    add_rendering_knobs(GN)

    # adding write to read button
    add_button_write_to_read(GN)

    divider = nuke.Text_Knob('')
    GN.addKnob(divider)

    # set tile color
    tile_color = _data.get("tile_color", "0xff0000ff")
    GN["tile_color"].setValue(tile_color)

    # add render button
    lnk = nuke.Link_Knob("Render")
    lnk.makeLink(write_node.name(), "Render")
    lnk.setName("Render")
    GN.addKnob(lnk)

    # Deadline tab.
    add_deadline_tab(GN)

    return GN


def add_rendering_knobs(node):
    ''' Adds additional rendering knobs to given node

    Arguments:
        node (obj): nuke node object to be fixed

    Return:
        node (obj): with added knobs
    '''
    if "render" not in node.knobs():
        knob = nuke.Boolean_Knob("render", "Render")
        knob.setFlag(0x1000)
        knob.setValue(False)
        node.addKnob(knob)
    if "render_farm" not in node.knobs():
        knob = nuke.Boolean_Knob("render_farm", "Render on Farm")
        knob.setValue(False)
        node.addKnob(knob)
    if "review" not in node.knobs():
        knob = nuke.Boolean_Knob("review", "Review")
        knob.setValue(True)
        node.addKnob(knob)
    return node


def add_deadline_tab(node):
    node.addKnob(nuke.Tab_Knob("Deadline"))

    knob = nuke.Int_Knob("deadlineChunkSize", "Chunk Size")
    knob.setValue(1)
    node.addKnob(knob)

    knob = nuke.Int_Knob("deadlinePriority", "Priority")
    knob.setValue(50)
    node.addKnob(knob)


def get_deadline_knob_names():
    return ["Deadline", "deadlineChunkSize", "deadlinePriority"]


def create_backdrop(label="", color=None, layer=0,
                    nodes=None):
    """
    Create Backdrop node

    Arguments:
        color (str): nuke compatible string with color code
        layer (int): layer of node usually used (self.pos_layer - 1)
        label (str): the message
        nodes (list): list of nodes to be wrapped into backdrop

    """
    assert isinstance(nodes, list), "`nodes` should be a list of nodes"

    # Calculate bounds for the backdrop node.
    bdX = min([node.xpos() for node in nodes])
    bdY = min([node.ypos() for node in nodes])
    bdW = max([node.xpos() + node.screenWidth() for node in nodes]) - bdX
    bdH = max([node.ypos() + node.screenHeight() for node in nodes]) - bdY

    # Expand the bounds to leave a little border. Elements are offsets
    # for left, top, right and bottom edges respectively
    left, top, right, bottom = (-20, -65, 20, 60)
    bdX += left
    bdY += top
    bdW += (right - left)
    bdH += (bottom - top)

    bdn = nuke.createNode("BackdropNode")
    bdn["z_order"].setValue(layer)

    if color:
        bdn["tile_color"].setValue(int(color, 16))

    bdn["xpos"].setValue(bdX)
    bdn["ypos"].setValue(bdY)
    bdn["bdwidth"].setValue(bdW)
    bdn["bdheight"].setValue(bdH)

    if label:
        bdn["label"].setValue(label)

    bdn["note_font_size"].setValue(20)
    return bdn


class WorkfileSettings(object):
    """
    All settings for workfile will be set

    This object is setting all possible root settings to the workfile.
    Including Colorspace, Frame ranges, Resolution format. It can set it
    to Root node or to any given node.

    Arguments:
        root (node): nuke's root node
        nodes (list): list of nuke's nodes
        nodes_filter (list): filtering classes for nodes

    """

    def __init__(self,
                 root_node=None,
                 nodes=None,
                 **kwargs):
        self._project = kwargs.get(
            "project") or io.find_one({"type": "project"})
        self._asset = kwargs.get("asset_name") or api.Session["AVALON_ASSET"]
        self._asset_entity = pype.get_asset(self._asset)
        self._root_node = root_node or nuke.root()
        self._nodes = self.get_nodes(nodes=nodes)

        self.data = kwargs

    def get_nodes(self, nodes=None, nodes_filter=None):
        # filter out only dictionaries for node creation
        #
        # print("\n\n")
        # pprint(self._nodes)
        #

        if not isinstance(nodes, list) and not isinstance(nodes_filter, list):
            return [n for n in nuke.allNodes()]
        elif not isinstance(nodes, list) and isinstance(nodes_filter, list):
            nodes = list()
            for filter in nodes_filter:
                [nodes.append(n) for n in nuke.allNodes(filter=filter)]
            return nodes
        elif isinstance(nodes, list) and not isinstance(nodes_filter, list):
            return [n for n in self._nodes]
        elif isinstance(nodes, list) and isinstance(nodes_filter, list):
            for filter in nodes_filter:
                return [n for n in self._nodes if filter in n.Class()]

    def set_viewers_colorspace(self, viewer_dict):
        ''' Adds correct colorspace to viewer

        Arguments:
            viewer_dict (dict): adjustments from presets

        '''
        assert isinstance(viewer_dict, dict), log.error(
            "set_viewers_colorspace(): argument should be dictionary")

        filter_knobs = [
            "viewerProcess",
            "wipe_position"
        ]

        erased_viewers = []
        for v in [n for n in self._nodes
                  if "Viewer" in n.Class()]:
            v['viewerProcess'].setValue(str(viewer_dict["viewerProcess"]))
            if str(viewer_dict["viewerProcess"]) \
                    not in v['viewerProcess'].value():
                copy_inputs = v.dependencies()
                copy_knobs = {k: v[k].value() for k in v.knobs()
                              if k not in filter_knobs}

                # delete viewer with wrong settings
                erased_viewers.append(v['name'].value())
                nuke.delete(v)

                # create new viewer
                nv = nuke.createNode("Viewer")

                # connect to original inputs
                for i, n in enumerate(copy_inputs):
                    nv.setInput(i, n)

                # set coppied knobs
                for k, v in copy_knobs.items():
                    print(k, v)
                    nv[k].setValue(v)

                # set viewerProcess
                nv['viewerProcess'].setValue(str(viewer_dict["viewerProcess"]))

        if erased_viewers:
            log.warning(
                "Attention! Viewer nodes {} were erased."
                "It had wrong color profile".format(erased_viewers))

    def set_root_colorspace(self, root_dict):
        ''' Adds correct colorspace to root

        Arguments:
            root_dict (dict): adjustmensts from presets

        '''
        assert isinstance(root_dict, dict), log.error(
            "set_root_colorspace(): argument should be dictionary")

        log.debug(">> root_dict: {}".format(root_dict))

        # first set OCIO
        if self._root_node["colorManagement"].value() \
                not in str(root_dict["colorManagement"]):
            self._root_node["colorManagement"].setValue(
                str(root_dict["colorManagement"]))
            log.debug("nuke.root()['{0}'] changed to: {1}".format(
                "colorManagement", root_dict["colorManagement"]))
            root_dict.pop("colorManagement")

        # second set ocio version
        if self._root_node["OCIO_config"].value() \
                not in str(root_dict["OCIO_config"]):
            self._root_node["OCIO_config"].setValue(
                str(root_dict["OCIO_config"]))
            log.debug("nuke.root()['{0}'] changed to: {1}".format(
                "OCIO_config", root_dict["OCIO_config"]))
            root_dict.pop("OCIO_config")

        # third set ocio custom path
        if root_dict.get("customOCIOConfigPath"):
            self._root_node["customOCIOConfigPath"].setValue(
                str(root_dict["customOCIOConfigPath"]).format(**os.environ)
                )
            log.debug("nuke.root()['{}'] changed to: {}".format(
                "customOCIOConfigPath", root_dict["customOCIOConfigPath"]))
            root_dict.pop("customOCIOConfigPath")

        # then set the rest
        for knob, value in root_dict.items():
            if self._root_node[knob].value() not in value:
                self._root_node[knob].setValue(str(value))
                log.debug("nuke.root()['{}'] changed to: {}".format(
                    knob, value))

    def set_writes_colorspace(self, write_dict):
        ''' Adds correct colorspace to write node dict

        Arguments:
            write_dict (dict): nuke write node as dictionary

        '''
        # TODO: complete this function so any write node in
        # scene will have fixed colorspace following presets for the project
        assert isinstance(write_dict, dict), log.error(
            "set_root_colorspace(): argument should be dictionary")

        log.debug("__ set_writes_colorspace(): {}".format(write_dict))

    def set_colorspace(self):
        ''' Setting colorpace following presets
        '''
        nuke_colorspace = get_colorspace_preset().get("nuke", None)

        try:
            self.set_root_colorspace(nuke_colorspace["root"])
        except AttributeError:
            log.error(
                "set_colorspace(): missing `root` settings in template")
        try:
            self.set_viewers_colorspace(nuke_colorspace["viewer"])
        except AttributeError:
            log.error(
                "set_colorspace(): missing `viewer` settings in template")
        try:
            self.set_writes_colorspace(nuke_colorspace["write"])
        except AttributeError:
            log.error(
                "set_colorspace(): missing `write` settings in template")

        try:
            for key in nuke_colorspace:
                log.debug("Preset's colorspace key: {}".format(key))
        except TypeError:
            log.error("Nuke is not in templates! \n\n\n"
                      "contact your supervisor!")

    def reset_frame_range_handles(self):
        """Set frame range to current asset"""

        if "data" not in self._asset_entity:
            msg = "Asset {} don't have set any 'data'".format(self._asset)
            log.warning(msg)
            nuke.message(msg)
            return
        data = self._asset_entity["data"]

        missing_cols = []
        check_cols = ["fps", "frameStart", "frameEnd",
                      "handleStart", "handleEnd"]

        for col in check_cols:
            if col not in data:
                missing_cols.append(col)

        if len(missing_cols) > 0:
            missing = ", ".join(missing_cols)
            msg = "'{}' are not set for asset '{}'!".format(
                missing, self._asset)
            log.warning(msg)
            nuke.message(msg)
            return

        # get handles values
        handle_start = data["handleStart"]
        handle_end = data["handleEnd"]

        fps = data["fps"]
        frame_start = int(data["frameStart"]) - handle_start
        frame_end = int(data["frameEnd"]) + handle_end

        self._root_node["fps"].setValue(fps)
        self._root_node["first_frame"].setValue(frame_start)
        self._root_node["last_frame"].setValue(frame_end)

        # setting active viewers
        try:
            nuke.frame(int(data["frameStart"]))
        except Exception as e:
            log.warning("no viewer in scene: `{}`".format(e))

        range = '{0}-{1}'.format(
            int(data["frameStart"]),
            int(data["frameEnd"]))

        for node in nuke.allNodes(filter="Viewer"):
            node['frame_range'].setValue(range)
            node['frame_range_lock'].setValue(True)
            node['frame_range'].setValue(range)
            node['frame_range_lock'].setValue(True)

        # adding handle_start/end to root avalon knob
        if not avalon.nuke.imprint(self._root_node, {
            "handleStart": int(handle_start),
            "handleEnd": int(handle_end)
        }):
            log.warning("Cannot set Avalon knob to Root node!")

    def reset_resolution(self):
        """Set resolution to project resolution."""
        log.info("Reseting resolution")
        project = io.find_one({"type": "project"})
        asset = api.Session["AVALON_ASSET"]
        asset = io.find_one({"name": asset, "type": "asset"})
        asset_data = asset.get('data', {})

        data = {
            "width": int(asset_data.get(
                'resolutionWidth',
                asset_data.get('resolution_width'))),
            "height": int(asset_data.get(
                'resolutionHeight',
                asset_data.get('resolution_height'))),
            "pixel_aspect": asset_data.get(
                'pixelAspect',
                asset_data.get('pixel_aspect', 1)),
            "name": project["name"]
        }

        if any(x for x in data.values() if x is None):
            log.error(
                "Missing set shot attributes in DB."
                "\nContact your supervisor!."
                "\n\nWidth: `{width}`"
                "\nHeight: `{height}`"
                "\nPixel Asspect: `{pixel_aspect}`".format(**data)
            )

        bbox = self._asset_entity.get('data', {}).get('crop')

        if bbox:
            try:
                x, y, r, t = bbox.split(".")
                data.update(
                    {
                        "x": int(x),
                        "y": int(y),
                        "r": int(r),
                        "t": int(t),
                    }
                )
            except Exception as e:
                bbox = None
                log.error(
                    "{}: {} \nFormat:Crop need to be set with dots, example: "
                    "0.0.1920.1080, /nSetting to default".format(__name__, e)
                )

        existing_format = None
        for format in nuke.formats():
            if data["name"] == format.name():
                existing_format = format
                break

        if existing_format:
            # Enforce existing format to be correct.
            existing_format.setWidth(data["width"])
            existing_format.setHeight(data["height"])
            existing_format.setPixelAspect(data["pixel_aspect"])

            if bbox:
                existing_format.setX(data["x"])
                existing_format.setY(data["y"])
                existing_format.setR(data["r"])
                existing_format.setT(data["t"])
        else:
            format_string = self.make_format_string(**data)
            log.info("Creating new format: {}".format(format_string))
            nuke.addFormat(format_string)

        nuke.root()["format"].setValue(data["name"])
        log.info("Format is set.")

    def make_format_string(self, **kwargs):
        if kwargs.get("r"):
            return (
                "{width} "
                "{height} "
                "{x} "
                "{y} "
                "{r} "
                "{t} "
                "{pixel_aspect:.2f} "
                "{name}".format(**kwargs)
            )
        else:
            return (
                "{width} "
                "{height} "
                "{pixel_aspect:.2f} "
                "{name}".format(**kwargs)
            )

    def set_context_settings(self):
        # replace reset resolution from avalon core to pype's
        self.reset_resolution()
        # replace reset resolution from avalon core to pype's
        self.reset_frame_range_handles()
        # add colorspace menu item
        self.set_colorspace()


def get_hierarchical_attr(entity, attr, default=None):
    attr_parts = attr.split('.')
    value = entity
    for part in attr_parts:
        value = value.get(part)
        if not value:
            break

    if value or entity['type'].lower() == 'project':
        return value

    parent_id = entity['parent']
    if (
        entity['type'].lower() == 'asset'
        and entity.get('data', {}).get('visualParent')
    ):
        parent_id = entity['data']['visualParent']

    parent = io.find_one({'_id': parent_id})

    return get_hierarchical_attr(parent, attr)


def get_write_node_template_attr(node):
    ''' Gets all defined data from presets

    '''
    # get avalon data from node
    data = dict()
    data['avalon'] = avalon.nuke.get_avalon_knob_data(
        node, ['avalon:', 'ak:'])
    data_preset = {
        "class": data['avalon']['family'],
        "families": data['avalon']['families'],
        "preset": data['avalon']['families']  # omit < 2.0.0v
    }

    # get template data
    nuke_dataflow_writes = get_node_dataflow_preset(**data_preset)
    nuke_colorspace_writes = get_node_colorspace_preset(**data_preset)

    # collecting correct data
    correct_data = OrderedDict({
        "file": get_render_path(node)
    })

    # adding dataflow template
    {correct_data.update({k: v})
     for k, v in nuke_dataflow_writes.items()
     if k not in ["_id", "_previous"]}

    # adding colorspace template
    {correct_data.update({k: v})
     for k, v in nuke_colorspace_writes.items()}

    # fix badly encoded data
    return avalon.nuke.lib.fix_data_for_node_create(correct_data)


class BuildWorkfile(WorkfileSettings):
    """
    Building first version of workfile.

    Settings are taken from presets and db. It will add all subsets in last version for defined representaions

    Arguments:
        variable (type): description

    """
    xpos = 0
    ypos = 0
    xpos_size = 80
    ypos_size = 90
    xpos_gap = 50
    ypos_gap = 50
    pos_layer = 10

    def __init__(self,
                 root_path=None,
                 root_node=None,
                 nodes=None,
                 to_script=None,
                 **kwargs):
        """
        A short description.

        A bit longer description.

        Argumetns:
            root_path (str): description
            root_node (nuke.Node): description
            nodes (list): list of nuke.Node
            nodes_effects (dict): dictionary with subsets

        Example:
            nodes_effects = {
                    "plateMain": {
                        "nodes": [
                               [("Class", "Reformat"),
                               ("resize", "distort"),
                               ("flip", True)],

                               [("Class", "Grade"),
                               ("blackpoint", 0.5),
                               ("multiply", 0.4)]
                            ]
                        },
                    }

        """

        WorkfileSettings.__init__(self,
                                  root_node=root_node,
                                  nodes=nodes,
                                  **kwargs)
        self.to_script = to_script
        # collect data for formating
        self.data_tmp = {
            "root": root_path or api.Session["AVALON_PROJECTS"],
            "project": {"name": self._project["name"],
                        "code": self._project["data"].get("code", '')},
            "asset": self._asset or os.environ["AVALON_ASSET"],
            "task": kwargs.get("task") or api.Session["AVALON_TASK"].lower(),
            "hierarchy": kwargs.get("hierarchy") or pype.get_hierarchy(),
            "version": kwargs.get("version", {}).get("name", 1),
            "user": getpass.getuser(),
            "comment": "firstBuild"
        }

        # get presets from anatomy
        anatomy = get_anatomy()
        # format anatomy
        anatomy_filled = anatomy.format(self.data_tmp)

        # get dir and file for workfile
        self.work_dir = anatomy_filled["avalon"]["work"]
        self.work_file = anatomy_filled["avalon"]["workfile"] + ".nk"

    def save_script_as(self, path=None):
        # first clear anything in open window
        nuke.scriptClear()

        if not path:
            dir = self.work_dir
            path = os.path.join(
                self.work_dir,
                self.work_file).replace("\\", "/")
        else:
            dir = os.path.dirname(path)

        # check if folder is created
        if not os.path.exists(dir):
            os.makedirs(dir)

        # save script to path
        nuke.scriptSaveAs(path)

    def process(self,
                regex_filter=None,
                version=None,
                representations=["exr", "dpx", "lutJson", "mov", "preview"]):
        """
        A short description.

        A bit longer description.

        Args:
            regex_filter (raw string): regex pattern to filter out subsets
            version (int): define a particular version, None gets last
            representations (list):

        Returns:
            type: description

        Raises:
            Exception: description

        """

        if not self.to_script:
            # save the script
            self.save_script_as()

        # create viewer and reset frame range
        viewer = self.get_nodes(nodes_filter=["Viewer"])
        if not viewer:
            vn = nuke.createNode("Viewer")
            vn["xpos"].setValue(self.xpos)
            vn["ypos"].setValue(self.ypos)
        else:
            vn = viewer[-1]

        # move position
        self.position_up()

        wn = self.write_create()
        wn["xpos"].setValue(self.xpos)
        wn["ypos"].setValue(self.ypos)
        wn["render"].setValue(True)
        vn.setInput(0, wn)

        bdn = self.create_backdrop(label="Render write \n\n\n\nOUTPUT",
                                   color='0xcc1102ff', layer=-1,
                                   nodes=[wn])

        # move position
        self.position_up(4)

        # set frame range for new viewer
        self.reset_frame_range_handles()

        # get all available representations
        subsets = pype.get_subsets(self._asset,
                                   regex_filter=regex_filter,
                                   version=version,
                                   representations=representations)

        log.info("__ subsets: `{}`".format(subsets))

        nodes_backdrop = list()

        for name, subset in subsets.items():
            if "lut" in name:
                continue
            log.info("Building Loader to: `{}`".format(name))
            version = subset["version"]
            log.info("Version to: `{}`".format(version["name"]))
            representations = subset["representaions"]
            for repr in representations:
                rn = self.read_loader(repr)
                rn["xpos"].setValue(self.xpos)
                rn["ypos"].setValue(self.ypos)
                wn.setInput(0, rn)

                # get editional nodes
                lut_subset = [s for n, s in subsets.items()
                              if "lut{}".format(name.lower()) in n.lower()]
                log.debug(">> lut_subset: `{}`".format(lut_subset))

                if len(lut_subset) > 0:
                    lsub = lut_subset[0]
                    fxn = self.effect_loader(lsub["representaions"][-1])
                    fxn_ypos = fxn["ypos"].value()
                    fxn["ypos"].setValue(fxn_ypos - 100)
                    nodes_backdrop.append(fxn)

                nodes_backdrop.append(rn)
                # move position
                self.position_right()

            bdn = self.create_backdrop(label="Loaded Reads",
                                       color='0x2d7702ff', layer=-1,
                                       nodes=nodes_backdrop)

    def read_loader(self, representation):
        """
        Gets Loader plugin for image sequence or mov

        Arguments:
            representation (dict): avalon db entity

        """
        context = representation["context"]

        loader_name = "LoadSequence"
        if "mov" in context["representation"]:
            loader_name = "LoadMov"

        loader_plugin = None
        for Loader in api.discover(api.Loader):
            if Loader.__name__ != loader_name:
                continue

            loader_plugin = Loader

        return api.load(Loader=loader_plugin,
                        representation=representation["_id"])

    def effect_loader(self, representation):
        """
        Gets Loader plugin for effects

        Arguments:
            representation (dict): avalon db entity

        """
        context = representation["context"]

        loader_name = "LoadLuts"

        loader_plugin = None
        for Loader in api.discover(api.Loader):
            if Loader.__name__ != loader_name:
                continue

            loader_plugin = Loader

        return api.load(Loader=loader_plugin,
                        representation=representation["_id"])

    def write_create(self):
        """
        Create render write

        Arguments:
            representation (dict): avalon db entity

        """
        task = self.data_tmp["task"]
        sanitized_task = re.sub('[^0-9a-zA-Z]+', '', task)
        subset_name = "render{}Main".format(
            sanitized_task.capitalize())

        Create_name = "CreateWriteRender"

        creator_plugin = None
        for Creator in api.discover(api.Creator):
            if Creator.__name__ != Create_name:
                continue

            creator_plugin = Creator

        # return api.create()
        return creator_plugin(subset_name, self._asset).process()

    def create_backdrop(self, label="", color=None, layer=0,
                        nodes=None):
        """
        Create Backdrop node

        Arguments:
            color (str): nuke compatible string with color code
            layer (int): layer of node usually used (self.pos_layer - 1)
            label (str): the message
            nodes (list): list of nodes to be wrapped into backdrop

        """
        assert isinstance(nodes, list), "`nodes` should be a list of nodes"
        layer = self.pos_layer + layer

        create_backdrop(label=label, color=color, layer=layer, nodes=nodes)

    def position_reset(self, xpos=0, ypos=0):
        self.xpos = xpos
        self.ypos = ypos

    def position_right(self, multiply=1):
        self.xpos += (self.xpos_size * multiply) + self.xpos_gap

    def position_left(self, multiply=1):
        self.xpos -= (self.xpos_size * multiply) + self.xpos_gap

    def position_down(self, multiply=1):
        self.ypos -= (self.ypos_size * multiply) + self.ypos_gap

    def position_up(self, multiply=1):
        self.ypos -= (self.ypos_size * multiply) + self.ypos_gap
