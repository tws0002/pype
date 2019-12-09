import pyblish.api
from avalon import io
from pype import lib


@pyblish.api.log
class ValidateScript(pyblish.api.InstancePlugin):
    """ Validates file output. """

    order = pyblish.api.ValidatorOrder + 0.1
    families = ["workfile"]
    label = "Check script settings"
    hosts = ["nuke"]

    def process(self, instance):
        ctx_data = instance.context.data
        asset_name = ctx_data["asset"]

        # asset = io.find_one({
        #     "type": "asset",
        #     "name": asset_name
        # })

        asset = lib.get_asset(asset_name)
        asset_data = asset["data"]

        # These attributes will be checked
        attributes = [
            "fps",
            "frameStart",
            "frameEnd",
            "resolutionWidth",
            "resolutionHeight",
            "handleStart",
            "handleEnd"
        ]

        # Value of these attributes can be found on parents
        hierarchical_attributes = [
            "fps",
            "resolutionWidth",
            "resolutionHeight",
            "pixelAspect",
            "handleStart",
            "handleEnd"
        ]

        missing_attributes = []
        asset_attributes = {}
        for attr in attributes:
            if attr in asset_data:
                asset_attributes[attr] = asset_data[attr]

            elif attr in hierarchical_attributes:
                # Try to find fps on parent
                parent = asset['parent']
                if asset_data['visualParent'] is not None:
                    parent = asset_data['visualParent']

                value = self.check_parent_hierarchical(parent, attr)
                if value is None:
                    missing_attributes.append(attr)
                else:
                    asset_attributes[attr] = value
            else:
                missing_attributes.append(attr)

        # Raise error if attributes weren't found on asset in database
        if len(missing_attributes) > 0:
            atr = ", ".join(missing_attributes)
            msg = 'Missing attributes "{}" in asset "{}"'
            message = msg.format(atr, asset_name)
            raise ValueError(message)

        # Get handles from database, Default is 0 (if not found)
        handle_start = 0
        handle_end = 0
        if "handleStart" in asset_attributes:
            handle_start = asset_attributes["handleStart"]
        if "handleEnd" in asset_attributes:
            handle_end = asset_attributes["handleEnd"]

        # Set frame range with handles
        # asset_attributes["frameStart"] -= handle_start
        # asset_attributes["frameEnd"] += handle_end
        if len(str(asset_attributes["fps"])) > 4:
            asset_attributes["fps"] = float("{0:.8f}".format(asset_attributes["fps"]))

        # Get values from nukescript
        script_attributes = {
            "handleStart": ctx_data["handleStart"],
            "handleEnd": ctx_data["handleEnd"],
            "fps": ctx_data["fps"],
            "frameStart": ctx_data["frameStart"],
            "frameEnd": ctx_data["frameEnd"],
            "resolutionWidth": ctx_data["resolutionWidth"],
            "resolutionHeight": ctx_data["resolutionHeight"],
            "pixelAspect": ctx_data["pixelAspect"]
        }

        # Compare asset's values Nukescript X Database
        not_matching = []
        for attr in attributes:
            self.log.debug("asset vs script attribute \"{}\": {}, {}".format(
                attr, asset_attributes[attr], script_attributes[attr])
            )
            if asset_attributes[attr] != script_attributes[attr]:
                not_matching.append(attr)

        # Raise error if not matching
        if len(not_matching) > 0:
            msg = "Attributes '{}' are not set correctly"
            # Alert user that handles are set if Frame start/end not match
            if (
                (("frameStart" in not_matching) or ("frameEnd" in not_matching)) and
                ((handle_start > 0) or (handle_end > 0))
            ):
                msg += " (`handle_start` are set to {})".format(handle_start)
                msg += " (`handle_end` are set to {})".format(handle_end)
            message = msg.format(", ".join(not_matching))
            raise ValueError(message)

    def check_parent_hierarchical(self, entityId, attr):
        if entityId is None:
            return None
        entity = io.find_one({"_id": entityId})
        if attr in entity['data']:
            self.log.info(attr)
            return entity['data'][attr]
        else:
            return self.check_parent_hierarchical(entity['parent'], attr)
