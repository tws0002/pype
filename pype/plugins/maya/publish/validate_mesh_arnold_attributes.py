import pymel.core as pc

import pyblish.api
import pype.api
import pype.maya.action
from avalon import maya


class ValidateMeshArnoldAttributes(pyblish.api.InstancePlugin):
    """Validate the mesh has default Arnold attributes.

    It compares all Arnold attributes from a default mesh. This is to ensure
    later published looks can discover non-default Arnold attributes.
    """

    order = pype.api.ValidateMeshOrder
    hosts = ["maya"]
    families = ["model"]
    category = "geometry"
    label = "Mesh Arnold Attributes"
    actions = [
        pype.maya.action.SelectInvalidAction,
        pype.api.RepairAction
    ]
    optional = True

    @classmethod
    def get_invalid_attributes(cls, instance, compute=False):
        invalid = []

        if compute:
            # Get default arnold attributes.
            temp_transform = pc.polyCube()[0]

            for shape in pc.ls(instance, type="mesh"):
                for attr in temp_transform.getShape().listAttr():
                    if not attr.attrName().startswith("ai"):
                        continue

                    target_attr = pc.PyNode(
                        "{}.{}".format(shape.name(), attr.attrName())
                    )
                    if attr.get() != target_attr.get():
                        invalid.append(target_attr)

            pc.delete(temp_transform)

            instance.data["nondefault_arnold_attributes"] = invalid
        else:
            invalid.extend(instance.data["nondefault_arnold_attributes"])

        return invalid

    @classmethod
    def get_invalid(cls, instance):
        invalid = []

        for attr in cls.get_invalid_attributes(instance, compute=False):
            invalid.append(attr.node().name())

        return invalid

    @classmethod
    def repair(cls, instance):
        with maya.maintained_selection():
            with pc.UndoChunk():
                temp_transform = pc.polyCube()[0]

                attributes = cls.get_invalid_attributes(
                    instance, compute=False
                )
                for attr in attributes:
                    source = pc.PyNode(
                        "{}.{}".format(
                            temp_transform.getShape(), attr.attrName()
                        )
                    )
                    attr.set(source.get())

                pc.delete(temp_transform)

    def process(self, instance):

        invalid = self.get_invalid_attributes(instance, compute=True)
        if invalid:
            raise RuntimeError(
                "Non-default Arnold attributes found in instance:"
                " {0}".format(invalid)
            )
