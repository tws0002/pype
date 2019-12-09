import os

from pyblish import api

import nuke


class CollectClips(api.ContextPlugin):
    """Collect all Track items selection."""

    order = api.CollectorOrder + 0.01
    label = "Collect Clips"
    hosts = ["nukestudio"]

    def process(self, context):
        # create asset_names conversion table
        if not context.data.get("assetsShared"):
            self.log.debug("Created `assetsShared` in context")
            context.data["assetsShared"] = dict()

        projectdata = context.data["projectData"]
        version = context.data.get("version", "001")
        sequence = context.data.get("activeSequence")
        selection = context.data.get("selection")

        track_effects = dict()

        # collect all trackItems as instances
        for track_index, video_track in enumerate(sequence.videoTracks()):
            items = video_track.items()
            sub_items = video_track.subTrackItems()

            for item in items:
                # compare with selection or if disabled
                if item not in selection or not item.isEnabled():
                    continue

                # Skip audio track items
                # Try/Except is to handle items types, like EffectTrackItem
                try:
                    media_type = "core.Hiero.Python.TrackItem.MediaType.kVideo"
                    if str(item.mediaType()) != media_type:
                        continue
                except Exception:
                    continue

                asset = item.name()
                track = item.parent()
                source = item.source().mediaSource()
                source_path = source.firstpath()
                effects = [f for f in item.linkedItems() if f.isEnabled()]

                # If source is *.nk its a comp effect and we need to fetch the
                # write node output. This should be improved by parsing the script
                # rather than opening it.
                if source_path.endswith(".nk"):
                    nuke.scriptOpen(source_path)
                    # There should noly be one.
                    write_node = nuke.allNodes(filter="Write")[0]
                    path = nuke.filename(write_node)

                    if "%" in path:
                        # Get start frame from Nuke script and use the item source
                        # in/out, because you can have multiple shots covered with
                        # one nuke script.
                        start_frame = int(nuke.root()["first_frame"].getValue())
                        if write_node["use_limit"].getValue():
                            start_frame = int(write_node["first"].getValue())

                        path = path % (start_frame + item.sourceIn())

                    source_path = path
                    self.log.debug(
                        "Fetched source path \"{}\" from \"{}\" in "
                        "\"{}\".".format(
                            source_path, write_node.name(), source.firstpath()
                        )
                    )

                try:
                    head, padding, ext = os.path.basename(source_path).split(".")
                    source_first_frame = int(padding)
                except Exception:
                    source_first_frame = 0

                data = {"name": "{0}_{1}".format(track.name(), item.name()),
                        "item": item,
                        "source": source,
                        "sourcePath": source_path,
                        "track": track.name(),
                        "trackIndex": track_index,
                        "sourceFirst": source_first_frame,
                        "effects": effects,
                        "sourceIn": int(item.sourceIn()),
                        "sourceOut": int(item.sourceOut()),
                        "clipIn": int(item.timelineIn()),
                        "clipOut": int(item.timelineOut()),
                        "asset": asset,
                        "family": "clip",
                        "families": [],
                        "handles": 0,
                        "handleStart": projectdata.get("handles", 0),
                        "handleEnd": projectdata.get("handles", 0),
                        "version": int(version)}

                instance = context.create_instance(**data)

                self.log.info("Created instance: {}".format(instance))
                self.log.debug(">> effects: {}".format(instance.data["effects"]))

                context.data["assetsShared"][asset] = dict()

            # from now we are collecting only subtrackitems on
            # track with no video items
            if len(items) > 0:
                continue

            # create list in track key
            # get all subTrackItems and add it to context
            track_effects[track_index] = list()

            # collect all subtrack items
            for sitem in sub_items:
                # unwrap from tuple >> it is always tuple with one item
                sitem = sitem[0]
                # checking if not enabled
                if not sitem.isEnabled():
                    continue

                track_effects[track_index].append(sitem)

        context.data["trackEffects"] = track_effects
        self.log.debug(">> sub_track_items: `{}`".format(track_effects))
