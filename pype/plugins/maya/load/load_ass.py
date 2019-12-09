from avalon import api
import pype.maya.plugin
import os
from pypeapp import config


class AssProxyLoader(pype.maya.plugin.ReferenceLoader):
    """Load the Proxy"""

    families = ["ass"]
    representations = ["ass"]

    label = "Reference .ASS standin with Proxy"
    order = -10
    icon = "code-fork"
    color = "orange"

    def process_reference(self, context, name, namespace, data):

        import maya.cmds as cmds
        from avalon import maya
        import pymel.core as pm

        try:
            family = context["representation"]["context"]["family"]
        except ValueError:
            family = "ass"

        with maya.maintained_selection():

            groupName = "{}:{}".format(namespace, name)
            path = self.fname
            proxyPath = os.path.splitext(path)[0] + ".ma"

            nodes = cmds.file(proxyPath,
                              namespace=namespace,
                              reference=True,
                              returnNewNodes=True,
                              groupReference=True,
                              groupName=groupName)

            cmds.makeIdentity(groupName, apply=False, rotate=True,
                              translate=True, scale=True)

            # Set attributes
            proxyShape = pm.ls(nodes, type="mesh")[0]

            proxyShape.aiTranslator.set('procedural')
            proxyShape.dso.set(path)
            proxyShape.aiOverrideShaders.set(0)

            presets = config.get_presets(project=os.environ['AVALON_PROJECT'])
            colors = presets['plugins']['maya']['load']['colors']

            c = colors.get(family)
            if c is not None:
                cmds.setAttr(groupName + ".useOutlinerColor", 1)
                cmds.setAttr(groupName + ".outlinerColor",
                             c[0], c[1], c[2])

        self[:] = nodes

        return nodes

    def switch(self, container, representation):
        self.update(container, representation)

    def update(self, container, representation):

        import os
        from maya import cmds
        import pymel.core as pm

        node = container["objectName"]

        path = api.get_representation_path(representation)
        # path = self.fname
        proxyPath = os.path.splitext(path)[0] + ".ma"

        # Get reference node from container members
        members = cmds.sets(node, query=True, nodesOnly=True)
        reference_node = self._get_reference_node(members)

        assert os.path.exists(path), "%s does not exist." % proxyPath

        try:
            content = cmds.file(proxyPath,
                                loadReference=reference_node,
                                type="mayaAscii",
                                returnNewNodes=True)

            # Set attributes
            proxyShape = pm.ls(content, type="mesh")[0]

            proxyShape.aiTranslator.set('procedural')
            proxyShape.dso.set(path)
            proxyShape.aiOverrideShaders.set(0)

        except RuntimeError as exc:
            # When changing a reference to a file that has load errors the
            # command will raise an error even if the file is still loaded
            # correctly (e.g. when raising errors on Arnold attributes)
            # When the file is loaded and has content, we consider it's fine.
            if not cmds.referenceQuery(reference_node, isLoaded=True):
                raise

            content = cmds.referenceQuery(reference_node,
                                          nodes=True,
                                          dagPath=True)
            if not content:
                raise

            self.log.warning("Ignoring file read error:\n%s", exc)

        # Add new nodes of the reference to the container
        cmds.sets(content, forceElement=node)

        # Remove any placeHolderList attribute entries from the set that
        # are remaining from nodes being removed from the referenced file.
        members = cmds.sets(node, query=True)
        invalid = [x for x in members if ".placeHolderList" in x]
        if invalid:
            cmds.sets(invalid, remove=node)

        # Update metadata
        cmds.setAttr("{}.representation".format(node),
                     str(representation["_id"]),
                     type="string")


class AssStandinLoader(api.Loader):
    """Load .ASS file as standin"""

    families = ["ass"]
    representations = ["ass"]

    label = "Load .ASS file as standin"
    order = -5
    icon = "code-fork"
    color = "orange"

    def load(self, context, name, namespace, data):

        import maya.cmds as cmds
        import avalon.maya.lib as lib
        from avalon.maya.pipeline import containerise
        import mtoa.ui.arnoldmenu
        import pymel.core as pm

        asset = context['asset']['name']
        namespace = namespace or lib.unique_namespace(
            asset + "_",
            prefix="_" if asset[0].isdigit() else "",
            suffix="_",
        )

        # cmds.loadPlugin("gpuCache", quiet=True)

        # Root group
        label = "{}:{}".format(namespace, name)
        root = pm.group(name=label, empty=True)

        presets = config.get_presets(project=os.environ['AVALON_PROJECT'])
        colors = presets['plugins']['maya']['load']['colors']

        c = colors.get('ass')
        if c is not None:
            cmds.setAttr(root + ".useOutlinerColor", 1)
            cmds.setAttr(root + ".outlinerColor",
                         c[0], c[1], c[2])

        # Create transform with shape
        transform_name = label + "_ASS"
        # transform = pm.createNode("transform", name=transform_name,
        #                             parent=root)

        standinShape = pm.PyNode(mtoa.ui.arnoldmenu.createStandIn())
        standin = standinShape.getParent()
        standin.rename(transform_name)

        pm.parent(standin, root)

        # Set the standin filepath
        standinShape.dso.set(self.fname)

        nodes = [root, standin]
        self[:] = nodes

        return containerise(
            name=name,
            namespace=namespace,
            nodes=nodes,
            context=context,
            loader=self.__class__.__name__)

    def update(self, container, representation):

        import pymel.core as pm

        path = api.get_representation_path(representation)

        # Update the standin
        members = pm.sets(container['objectName'], query=True)
        standins = pm.ls(members, type="AiStandIn", long=True)

        assert len(caches) == 1, "This is a bug"

        for standin in standins:
            standin.cacheFileName.set(path)

        container = pm.PyNode(container["objectName"])
        container.representation.set(str(representation["_id"]))

    def switch(self, container, representation):
        self.update(container, representation)

    def remove(self, container):
        import maya.cmds as cmds
        members = cmds.sets(container['objectName'], query=True)
        cmds.lockNode(members, lock=False)
        cmds.delete([container['objectName']] + members)

        # Clean up the namespace
        try:
            cmds.namespace(removeNamespace=container['namespace'],
                           deleteNamespaceContent=True)
        except RuntimeError:
            pass
