import os

from maya import cmds
import contextlib

import avalon.maya
import pype.api
import pype.maya.lib as lib


class ExtractModel(pype.api.Extractor):
    """Extract proxy model as Maya Ascii to use as arnold standin


    """

    order = pype.api.Extractor.order + 0.2
    label = "Ass Proxy (Maya ASCII)"
    hosts = ["maya"]
    families = ["ass"]

    def process(self, instance):

        @contextlib.contextmanager
        def unparent(root):
            """Temporarily unparent `root`"""
            parent = cmds.listRelatives(root, parent=True)
            if parent:
                cmds.parent(root, world=True)
                yield
                self.log.info("{} - {}".format(root, parent))
                cmds.parent(root, parent)
            else:
                yield


        # Define extract output file path
        stagingdir = self.staging_dir(instance)
        filename = "{0}.ma".format(instance.name)
        path = os.path.join(stagingdir, filename)

        # Perform extraction
        self.log.info("Performing extraction..")

        # Get only the shape contents we need in such a way that we avoid
        # taking along intermediateObjects
        members = instance.data['proxy']
        members = cmds.ls(members,
                          dag=True,
                          transforms=True,
                          noIntermediate=True)
        self.log.info(members)

        with avalon.maya.maintained_selection():
            with unparent(members[0]):
                cmds.select(members, noExpand=True)
                cmds.file(path,
                          force=True,
                          typ="mayaAscii",
                          exportSelected=True,
                          preserveReferences=False,
                          channels=False,
                          constraints=False,
                          expressions=False,
                          constructionHistory=False)


        if "files" not in instance.data:
            instance.data["files"] = list()

        instance.data["files"].append(filename)

        self.log.info("Extracted instance '%s' to: %s" % (instance.name, path))