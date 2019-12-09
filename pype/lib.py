import os
import re
import logging
import importlib
import itertools
import contextlib
import subprocess
import inspect

from .vendor import pather
from .vendor.pather.error import ParseError

import avalon.io as io
import avalon.api
import avalon

log = logging.getLogger(__name__)


# Special naming case for subprocess since its a built-in method.
def _subprocess(args):
    """Convenience method for getting output errors for subprocess."""

    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
        env=os.environ
    )

    output = proc.communicate()[0]

    if proc.returncode != 0:
        log.error(output)
        raise ValueError("\"{}\" was not successful: {}".format(args, output))
    return output


def get_hierarchy(asset_name=None):
    """
    Obtain asset hierarchy path string from mongo db

    Returns:
        string: asset hierarchy path

    """
    if not asset_name:
        asset_name = io.Session.get("AVALON_ASSET", os.environ["AVALON_ASSET"])

    asset_entity = io.find_one({
        "type": 'asset',
        "name": asset_name
    })

    not_set = "PARENTS_NOT_SET"
    entity_parents = asset_entity.get("data", {}).get("parents", not_set)

    # If entity already have parents then just return joined
    if entity_parents != not_set:
        return "/".join(entity_parents)

    # Else query parents through visualParents and store result to entity
    hierarchy_items = []
    entity = asset_entity
    while True:
        parent_id = entity.get("data", {}).get("visualParent")
        if not parent_id:
            break
        entity = io.find_one({"_id": parent_id})
        hierarchy_items.append(entity["name"])

    # Add parents to entity data for next query
    entity_data = asset_entity.get("data", {})
    entity_data["parents"] = hierarchy_items
    io.update_many(
        {"_id": asset_entity["_id"]},
        {"$set": {"data": entity_data}}
    )

    return "/".join(hierarchy_items)


def add_tool_to_environment(tools):
    """
    It is adding dynamic environment to os environment.

    Args:
        tool (list, tuple): list of tools, name should corespond to json/toml

    Returns:
        os.environ[KEY]: adding to os.environ
    """

    import acre
    tools_env = acre.get_tools(tools)
    env = acre.compute(tools_env)
    env = acre.merge(env, current_env=dict(os.environ))
    os.environ.update(env)


@contextlib.contextmanager
def modified_environ(*remove, **update):
    """
    Temporarily updates the ``os.environ`` dictionary in-place.

    The ``os.environ`` dictionary is updated in-place so that the modification
    is sure to work in all situations.

    :param remove: Environment variables to remove.
    :param update: Dictionary of environment variables and values to add/update.
    """
    env = os.environ
    update = update or {}
    remove = remove or []

    # List of environment variables being updated or removed.
    stomped = (set(update.keys()) | set(remove)) & set(env.keys())
    # Environment variables and values to restore on exit.
    update_after = {k: env[k] for k in stomped}
    # Environment variables and values to remove on exit.
    remove_after = frozenset(k for k in update if k not in env)

    try:
        env.update(update)
        [env.pop(k, None) for k in remove]
        yield
    finally:
        env.update(update_after)
        [env.pop(k) for k in remove_after]


def pairwise(iterable):
    """s -> (s0,s1), (s2,s3), (s4, s5), ..."""
    a = iter(iterable)
    return itertools.izip(a, a)


def grouper(iterable, n, fillvalue=None):
    """Collect data into fixed-length chunks or blocks

    Examples:
        grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx

    """

    args = [iter(iterable)] * n
    return itertools.izip_longest(fillvalue=fillvalue, *args)


def is_latest(representation):
    """Return whether the representation is from latest version

    Args:
        representation (dict): The representation document from the database.

    Returns:
        bool: Whether the representation is of latest version.

    """

    version = io.find_one({"_id": representation['parent']})

    # Get highest version under the parent
    highest_version = io.find_one({
        "type": "version",
        "parent": version["parent"]
    }, sort=[("name", -1)], projection={"name": True})

    if version['name'] == highest_version['name']:
        return True
    else:
        return False


def any_outdated():
    """Return whether the current scene has any outdated content"""

    checked = set()
    host = avalon.api.registered_host()
    for container in host.ls():
        representation = container['representation']
        if representation in checked:
            continue

        representation_doc = io.find_one({"_id": io.ObjectId(representation),
                                          "type": "representation"},
                                         projection={"parent": True})
        if representation_doc and not is_latest(representation_doc):
            return True
        elif not representation_doc:
            log.debug("Container '{objectName}' has an invalid "
                      "representation, it is missing in the "
                      "database".format(**container))

        checked.add(representation)
    return False


def _rreplace(s, a, b, n=1):
    """Replace a with b in string s from right side n times"""
    return b.join(s.rsplit(a, n))


def version_up(filepath):
    """Version up filepath to a new non-existing version.

    Parses for a version identifier like `_v001` or `.v001`
    When no version present _v001 is appended as suffix.

    Returns:
        str: filepath with increased version number

    """

    dirname = os.path.dirname(filepath)
    basename, ext = os.path.splitext(os.path.basename(filepath))

    regex = r"[._]v\d+"
    matches = re.findall(regex, str(basename), re.IGNORECASE)
    if not matches:
        log.info("Creating version...")
        new_label = "_v{version:03d}".format(version=1)
        new_basename = "{}{}".format(basename, new_label)
    else:
        label = matches[-1]
        version = re.search(r"\d+", label).group()
        padding = len(version)

        new_version = int(version) + 1
        new_version = '{version:0{padding}d}'.format(version=new_version,
                                                     padding=padding)
        new_label = label.replace(version, new_version, 1)
        new_basename = _rreplace(basename, label, new_label)

    if not new_basename.endswith(new_label):
        index = (new_basename.find(new_label))
        index += len(new_label)
        new_basename = new_basename[:index]

    new_filename = "{}{}".format(new_basename, ext)
    new_filename = os.path.join(dirname, new_filename)
    new_filename = os.path.normpath(new_filename)

    if new_filename == filepath:
        raise RuntimeError("Created path is the same as current file,"
                           "this is a bug")

    for file in os.listdir(dirname):
        if file.endswith(ext) and file.startswith(new_basename):
            log.info("Skipping existing version %s" % new_label)
            return version_up(new_filename)

    log.info("New version %s" % new_label)
    return new_filename


def switch_item(container,
                asset_name=None,
                subset_name=None,
                representation_name=None):
    """Switch container asset, subset or representation of a container by name.

    It'll always switch to the latest version - of course a different
    approach could be implemented.

    Args:
        container (dict): data of the item to switch with
        asset_name (str): name of the asset
        subset_name (str): name of the subset
        representation_name (str): name of the representation

    Returns:
        dict

    """

    if all(not x for x in [asset_name, subset_name, representation_name]):
        raise ValueError("Must have at least one change provided to switch.")

    # Collect any of current asset, subset and representation if not provided
    # so we can use the original name from those.
    if any(not x for x in [asset_name, subset_name, representation_name]):
        _id = io.ObjectId(container["representation"])
        representation = io.find_one({"type": "representation", "_id": _id})
        version, subset, asset, project = io.parenthood(representation)

        if asset_name is None:
            asset_name = asset["name"]

        if subset_name is None:
            subset_name = subset["name"]

        if representation_name is None:
            representation_name = representation["name"]

    # Find the new one
    asset = io.find_one({"name": asset_name, "type": "asset"})
    assert asset, ("Could not find asset in the database with the name "
                   "'%s'" % asset_name)

    subset = io.find_one({"name": subset_name,
                          "type": "subset",
                          "parent": asset["_id"]})
    assert subset, ("Could not find subset in the database with the name "
                    "'%s'" % subset_name)

    version = io.find_one({"type": "version",
                           "parent": subset["_id"]},
                          sort=[('name', -1)])

    assert version, "Could not find a version for {}.{}".format(
        asset_name, subset_name
    )

    representation = io.find_one({"name": representation_name,
                                  "type": "representation",
                                  "parent": version["_id"]})

    assert representation, ("Could not find representation in the database with"
                            " the name '%s'" % representation_name)

    avalon.api.switch(container, representation)

    return representation


def _get_host_name():

    _host = avalon.api.registered_host()
    # This covers nested module name like avalon.maya
    return _host.__name__.rsplit(".", 1)[-1]


def get_asset(asset_name=None):
    entity_data_keys_from_project_when_miss = [
        "frameStart", "frameEnd", "handleStart", "handleEnd", "fps",
        "resolutionWidth", "resolutionHeight"
    ]

    entity_keys_from_project_when_miss = []

    alternatives = {
        "handleStart": "handles",
        "handleEnd": "handles"
    }

    defaults = {
        "handleStart": 0,
        "handleEnd": 0
    }

    if not asset_name:
        asset_name = avalon.api.Session["AVALON_ASSET"]

    asset_document = io.find_one({"name": asset_name, "type": "asset"})
    if not asset_document:
        raise TypeError("Entity \"{}\" was not found in DB".format(asset_name))

    project_document = io.find_one({"type": "project"})

    for key in entity_data_keys_from_project_when_miss:
        if asset_document["data"].get(key):
            continue

        value = project_document["data"].get(key)
        if value is not None or key not in alternatives:
            asset_document["data"][key] = value
            continue

        alt_key = alternatives[key]
        value = asset_document["data"].get(alt_key)
        if value is not None:
            asset_document["data"][key] = value
            continue

        value = project_document["data"].get(alt_key)
        if value:
            asset_document["data"][key] = value
            continue

        if key in defaults:
            asset_document["data"][key] = defaults[key]

    for key in entity_keys_from_project_when_miss:
        if asset_document.get(key):
            continue

        value = project_document.get(key)
        if value is not None or key not in alternatives:
            asset_document[key] = value
            continue

        alt_key = alternatives[key]
        value = asset_document.get(alt_key)
        if value:
            asset_document[key] = value
            continue

        value = project_document.get(alt_key)
        if value:
            asset_document[key] = value
            continue

        if key in defaults:
            asset_document[key] = defaults[key]

    return asset_document


def get_project():
    io.install()
    return io.find_one({"type": "project"})


def get_version_from_path(file):
    """
    Finds version number in file path string

    Args:
        file (string): file path

    Returns:
        v: version number in string ('001')

    """
    pattern = re.compile(r"[\._]v([0-9]+)")
    try:
        return pattern.findall(file)[0]
    except IndexError:
        log.error(
            "templates:get_version_from_workfile:"
            "`{}` missing version string."
            "Example `v004`".format(file)
        )


def get_avalon_database():
    if io._database is None:
        set_io_database()
    return io._database


def set_io_database():
    required_keys = ["AVALON_PROJECT", "AVALON_ASSET", "AVALON_SILO"]
    for key in required_keys:
        os.environ[key] = os.environ.get(key, "")
    io.install()


def get_all_avalon_projects():
    db = get_avalon_database()
    projects = []
    for name in db.collection_names():
        projects.append(db[name].find_one({'type': 'project'}))
    return projects


def filter_pyblish_plugins(plugins):
    """
    This servers as plugin filter / modifier for pyblish. It will load plugin
    definitions from presets and filter those needed to be excluded.

    :param plugins: Dictionary of plugins produced by :mod:`pyblish-base`
                    `discover()` method.
    :type plugins: Dict
    """
    from pypeapp import config
    from pyblish import api

    host = api.current_host()

    presets = config.get_presets().get('plugins', {})

    # iterate over plugins
    for plugin in plugins[:]:
        # skip if there are no presets to process
        if not presets:
            continue

        file = os.path.normpath(inspect.getsourcefile(plugin))
        file = os.path.normpath(file)

        # host determined from path
        host_from_file = file.split(os.path.sep)[-3:-2][0]
        plugin_kind = file.split(os.path.sep)[-2:-1][0]

        try:
            config_data = presets[host]["publish"][plugin.__name__]
        except KeyError:
            try:
                config_data = presets[host_from_file][plugin_kind][plugin.__name__]  # noqa: E501
            except KeyError:
                continue

        for option, value in config_data.items():
            if option == "enabled" and value is False:
                log.info('removing plugin {}'.format(plugin.__name__))
                plugins.remove(plugin)
            else:
                log.info('setting {}:{} on plugin {}'.format(
                    option, value, plugin.__name__))

                setattr(plugin, option, value)


def get_subsets(asset_name,
                regex_filter=None,
                version=None,
                representations=["exr", "dpx"]):
    """
    Query subsets with filter on name.

    The method will return all found subsets and its defined version and subsets. Version could be specified with number. Representation can be filtered.

    Arguments:
        asset_name (str): asset (shot) name
        regex_filter (raw): raw string with filter pattern
        version (str or int): `last` or number of version
        representations (list): list for all representations

    Returns:
        dict: subsets with version and representaions in keys
    """
    from avalon import io

    # query asset from db
    asset_io = io.find_one({"type": "asset",
                            "name": asset_name})

    # check if anything returned
    assert asset_io, "Asset not existing. \
                      Check correct name: `{}`".format(asset_name)

    # create subsets query filter
    filter_query = {"type": "subset", "parent": asset_io["_id"]}

    # add reggex filter string into query filter
    if regex_filter:
        filter_query.update({"name": {"$regex": r"{}".format(regex_filter)}})
    else:
        filter_query.update({"name": {"$regex": r'.*'}})

    # query all assets
    subsets = [s for s in io.find(filter_query)]

    assert subsets, "No subsets found. Check correct filter. Try this for start `r'.*'`: asset: `{}`".format(asset_name)

    output_dict = {}
    # Process subsets
    for subset in subsets:
        if not version:
            version_sel = io.find_one({"type": "version",
                                       "parent": subset["_id"]},
                                      sort=[("name", -1)])
        else:
            assert isinstance(version, int), "version needs to be `int` type"
            version_sel = io.find_one({"type": "version",
                                       "parent": subset["_id"],
                                       "name": int(version)})

        find_dict = {"type": "representation",
                     "parent": version_sel["_id"]}

        filter_repr = {"$or": [{"name": repr} for repr in representations]}

        find_dict.update(filter_repr)
        repres_out = [i for i in io.find(find_dict)]

        if len(repres_out) > 0:
            output_dict[subset["name"]] = {"version": version_sel,
                                           "representaions": repres_out}

    return output_dict
