"""
Requires:
    None
Provides:
    context -> comment (str)
"""

import pyblish.api


class CollectComment(pyblish.api.ContextPlugin):
    """This plug-ins displays the comment dialog box per default"""

    label = "Collect Comment"
    order = pyblish.api.CollectorOrder

    def process(self, context):
        context.data["comment"] = ""
