import pyblish.api
import nuke
import os
import pype
import clique


class NukeRenderLocal(pype.api.Extractor):
    # TODO: rewrite docstring to nuke
    """Render the current Fusion composition locally.

    Extract the result of savers by starting a comp render
    This will run the local render of Fusion.

    """

    order = pyblish.api.ExtractorOrder
    label = "Render Local"
    hosts = ["nuke"]
    families = ["render.local"]

    def process(self, instance):
        node = None
        for x in instance:
            if x.Class() == "Write":
                node = x

        self.log.debug("instance collected: {}".format(instance.data))

        first_frame = instance.data.get("frameStart", None)
        last_frame = instance.data.get("frameEnd", None)
        node_subset_name = instance.data.get("name", None)

        self.log.info("Starting render")
        self.log.info("Start frame: {}".format(first_frame))
        self.log.info("End frame: {}".format(last_frame))

        # Ensure output directory exists.
        directory = os.path.dirname(node["file"].value())
        if not os.path.exists(directory):
            os.makedirs(directory)

        # Render frames
        nuke.execute(
            node_subset_name,
            int(first_frame),
            int(last_frame)
        )

        path = node['file'].value()
        out_dir = os.path.dirname(path)
        ext = node["file_type"].value()

        if "representations" not in instance.data:
            instance.data["representations"] = []

        collected_frames = os.listdir(out_dir)
        repre = {
            'name': ext,
            'ext': ext,
            'frameStart': "%0{}d".format(len(str(last_frame))) % first_frame,
            'files': collected_frames,
            "stagingDir": out_dir,
            "anatomy_template": "render"
        }
        instance.data["representations"].append(repre)

        self.log.info("Extracted instance '{0}' to: {1}".format(
            instance.name,
            out_dir
        ))

        instance.data['family'] = 'render'
        instance.data['families'].append('render')

        collections, remainder = clique.assemble(collected_frames)
        self.log.info('collections: {}'.format(str(collections)))

        if collections:
            collection = collections[0]
            instance.data['collection'] = collection

        self.log.info('Finished render')
        return
