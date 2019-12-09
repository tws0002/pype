import os

from pyblish import api as pyblish
from avalon import api as avalon
from .lib import filter_pyblish_plugins
from pypeapp import config


import logging
log = logging.getLogger(__name__)

__version__ = "2.3.0"

PACKAGE_DIR = os.path.dirname(__file__)
PLUGINS_DIR = os.path.join(PACKAGE_DIR, "plugins")

# Global plugin paths
PUBLISH_PATH = os.path.join(PLUGINS_DIR, "global", "publish")
LOAD_PATH = os.path.join(PLUGINS_DIR, "global", "load")

# we are monkey patching `avalon.api.discover()` to allow us to load
# plugin presets on plugins being discovered by avalon. Little bit of
# hacking, but it allows us to add out own features without need
# to modify upstream code.

_original_discover = avalon.discover


def patched_discover(superclass):
    """
    Monkey patched version of :func:`avalon.api.discover()`. It allows
    us to load presets on plugins being discovered.
    """
    # run original discover and get plugins
    plugins = _original_discover(superclass)

    # determine host application to use for finding presets
    if avalon.registered_host() is None:
        return plugins
    host = avalon.registered_host().__name__.split(".")[-1]

    # map plugin superclass to preset json. Currenly suppoted is load and
    # create (avalon.api.Loader and avalon.api.Creator)
    plugin_type = "undefined"
    if superclass.__name__.split(".")[-1] == "Loader":
        plugin_type = "load"
    elif superclass.__name__.split(".")[-1] == "Creator":
        plugin_type = "create"

    print(">>> trying to find presets for {}:{} ...".format(host, plugin_type))
    try:
        config_data = config.get_presets()['plugins'][host][plugin_type]
    except KeyError:
        print("*** no presets found.")
    else:
        for plugin in plugins:
            if plugin.__name__ in config_data:
                print(">>> We have preset for {}".format(plugin.__name__))
                for option, value in config_data[plugin.__name__].items():
                    if option == "enabled" and value is False:
                        setattr(plugin, "active", False)
                        print("  - is disabled by preset")
                    else:
                        setattr(plugin, option, value)
                        print("  - setting `{}`: `{}`".format(option, value))
    return plugins


def install():
    log.info("Registering global plug-ins..")
    pyblish.register_plugin_path(PUBLISH_PATH)
    pyblish.register_discovery_filter(filter_pyblish_plugins)
    avalon.register_plugin_path(avalon.Loader, LOAD_PATH)

    # apply monkey patched discover to original one
    avalon.discover = patched_discover


def uninstall():
    log.info("Deregistering global plug-ins..")
    pyblish.deregister_plugin_path(PUBLISH_PATH)
    pyblish.deregister_discovery_filter(filter_pyblish_plugins)
    avalon.deregister_plugin_path(avalon.Loader, LOAD_PATH)
    log.info("Global plug-ins unregistred")

    # restore original discover
    avalon.discover = _original_discover
