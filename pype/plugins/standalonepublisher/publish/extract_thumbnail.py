import os
import tempfile
import subprocess
import pyblish.api
import pype.api


class ExtractThumbnailSP(pyblish.api.InstancePlugin):
    """Extract jpeg thumbnail from component input from standalone publisher

    Uses jpeg file from component if possible (when single or multiple jpegs
    are loaded to component selected as thumbnail) otherwise extracts from
    input file/s single jpeg to temp.
    """

    label = "Extract Thumbnail SP"
    hosts = ["standalonepublisher"]
    order = pyblish.api.ExtractorOrder

    def process(self, instance):
        repres = instance.data.get('representations')
        if not repres:
            return

        thumbnail_repre = None
        for repre in repres:
            if repre.get("thumbnail"):
                thumbnail_repre = repre
                break

        if not thumbnail_repre:
            return

        files = thumbnail_repre.get("files")
        if not files:
            return

        if isinstance(files, list):
            files_len = len(files)
            file = str(files[0])
        else:
            files_len = 1
            file = files

        is_jpeg = False
        if file.endswith(".jpeg") or file.endswith(".jpg"):
            is_jpeg = True

        if is_jpeg and files_len == 1:
            # skip if already is single jpeg file
            return

        elif is_jpeg:
            # use first frame as thumbnail if is sequence of jpegs
            full_thumbnail_path = file
            self.log.info(
                "For thumbnail is used file: {}".format(full_thumbnail_path)
            )

        else:
            # Convert to jpeg if not yet
            full_input_path = os.path.join(thumbnail_repre["stagingDir"], file)
            self.log.info("input {}".format(full_input_path))

            full_thumbnail_path = tempfile.mkstemp(suffix=".jpg")[1]
            self.log.info("output {}".format(full_thumbnail_path))

            config_data = instance.context.data.get("output_repre_config", {})

            proj_name = os.environ.get("AVALON_PROJECT", "__default__")
            profile = config_data.get(
                proj_name,
                config_data.get("__default__", {})
            )

            ffmpeg_path = os.getenv("FFMPEG_PATH", "")
            if ffmpeg_path:
                ffmpeg_path += "/ffmpeg"
            else:
                ffmpeg_path = "ffmpeg"

            jpeg_items = []
            jpeg_items.append(ffmpeg_path)
            # override file if already exists
            jpeg_items.append("-y")
            # add input filters from peresets
            if profile:
                jpeg_items.extend(profile.get('input', []))
            # input file
            jpeg_items.append("-i {}".format(full_input_path))
            # extract only single file
            jpeg_items.append("-vframes 1")
            # output file
            jpeg_items.append(full_thumbnail_path)

            subprocess_jpeg = " ".join(jpeg_items)

            # run subprocess
            self.log.debug("Executing: {}".format(subprocess_jpeg))
            subprocess.Popen(
                subprocess_jpeg,
                stdout=subprocess.PIPE,
                shell=True
            )

        # remove thumbnail key from origin repre
        thumbnail_repre.pop("thumbnail")

        filename = os.path.basename(full_thumbnail_path)
        staging_dir = os.path.dirname(full_thumbnail_path)

        # create new thumbnail representation
        representation = {
            'name': 'jpg',
            'ext': 'jpg',
            'files': filename,
            "stagingDir": staging_dir,
            "thumbnail": True,
            "tags": []
        }

        # # add Delete tag when temp file was rendered
        # if not is_jpeg:
        #     representation["tags"].append("delete")

        instance.data["representations"].append(representation)
