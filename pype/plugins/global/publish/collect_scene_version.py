import os
import pyblish.api
import pype.api as pype


class CollectSceneVersion(pyblish.api.ContextPlugin):
    """Finds version in the filename or passes the one found in the context
        Arguments:
        version (int, optional): version number of the publish
    """

    order = pyblish.api.CollectorOrder
    label = 'Collect Version'

    def process(self, context):
        if "standalonepublisher" in context.data.get("host", []):
            return

        filename = os.path.basename(context.data.get('currentFile'))

        if '<shell>' in filename:
            return

        rootVersion = pype.get_version_from_path(filename)
        context.data['version'] = rootVersion

        self.log.info('Scene Version: %s' % context.data('version'))
