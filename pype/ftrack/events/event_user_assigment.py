from pype.vendor import ftrack_api
from pype.ftrack import BaseEvent, lib
from pype.ftrack.lib.io_nonsingleton import DbConnector
from bson.objectid import ObjectId
from pypeapp import config
from pypeapp import Anatomy
import subprocess
import os
import re


class UserAssigmentEvent(BaseEvent):
    """
    This script will intercept user assigment / de-assigment event and
    run shell script, providing as much context as possible.

    It expects configuration file ``presets/ftrack/user_assigment_event.json``.
    In it, you define paths to scripts to be run for user assigment event and
    for user-deassigment::
        {
            "add": [
                "/path/to/script1",
                "/path/to/script2"
            ],
            "remove": [
                "/path/to/script3",
                "/path/to/script4"
            ]
        }

    Those scripts are executed in shell. Three arguments will be passed to
    to them:
        1) user name of user (de)assigned
        2) path to workfiles of task user was (de)assigned to
        3) path to publish files of task user was (de)assigned to
    """

    db_con = DbConnector()
    ca_mongoid = lib.get_ca_mongoid()

    def error(self, *err):
        for e in err:
            self.log.error(e)

    def _run_script(self, script, args):
        """
        Run shell script with arguments as subprocess

        :param script: script path
        :type script: str
        :param args: list of arguments passed to script
        :type args: list
        :returns: return code
        :rtype: int
        """
        p = subprocess.call([script, args], shell=True)
        return p

    def _get_task_and_user(self, session, action, changes):
        """
        Get Task and User entities from Ftrack session

        :param session: ftrack session
        :type session: ftrack_api.session
        :param action: event action
        :type action: str
        :param changes: what was changed by event
        :type changes: dict
        :returns: User and Task entities
        :rtype: tuple
        """
        if not changes:
            return None, None

        if action == 'add':
            task_id = changes.get('context_id', {}).get('new')
            user_id = changes.get('resource_id', {}).get('new')

        elif action == 'remove':
            task_id = changes.get('context_id', {}).get('old')
            user_id = changes.get('resource_id', {}).get('old')

        if not task_id:
            return None, None

        if not user_id:
            return None, None

        task = session.query('Task where id is "{}"'.format(task_id)).one()
        user = session.query('User where id is "{}"'.format(user_id)).one()

        return task, user

    def _get_asset(self, task):
        """
        Get asset from task entity

        :param task: Task entity
        :type task: dict
        :returns: Asset entity
        :rtype: dict
        """
        parent = task['parent']
        self.db_con.install()
        self.db_con.Session['AVALON_PROJECT'] = task['project']['full_name']

        avalon_entity = None
        parent_id = parent['custom_attributes'].get(self.ca_mongoid)
        if parent_id:
            parent_id = ObjectId(parent_id)
            avalon_entity = self.db_con.find_one({
                '_id': parent_id,
                'type': 'asset'
            })

        if not avalon_entity:
            avalon_entity = self.db_con.find_one({
                'type': 'asset',
                'name': parent['name']
            })

        if not avalon_entity:
            self.db_con.uninstall()
            msg = 'Entity "{}" not found in avalon database'.format(
                parent['name']
            )
            self.error(msg)
            return {
                'success': False,
                'message': msg
            }
        self.db_con.uninstall()
        return avalon_entity

    def _get_hierarchy(self, asset):
        """
        Get hierarchy from Asset entity

        :param asset: Asset entity
        :type asset: dict
        :returns: hierarchy string
        :rtype: str
        """
        return asset['data']['hierarchy']

    def _get_template_data(self, task):
        """
        Get data to fill template from task

        .. seealso:: :mod:`pypeapp.Anatomy`

        :param task: Task entity
        :type task: dict
        :returns: data for anatomy template
        :rtype: dict
        """
        project_name = task['project']['full_name']
        project_code = task['project']['name']
        try:
            root = os.environ['PYPE_STUDIO_PROJECTS_PATH']
        except KeyError:
            msg = 'Project ({}) root not set'.format(project_name)
            self.log.error(msg)
            return {
                'success': False,
                'message': msg
            }

        # fill in template data
        asset = self._get_asset(task)
        t_data = {
            'root': root,
            'project': {
                'name': project_name,
                'code': project_code
            },
            'asset': asset['name'],
            'task': task['name'],
            'hierarchy': self._get_hierarchy(asset)
        }

        return t_data

    def launch(self, session, event):
        # load shell scripts presets
        presets = config.get_presets()['ftrack'].get("user_assigment_event")
        if not presets:
            return
        for entity in event.get('data', {}).get('entities', []):
            if entity.get('entity_type') != 'Appointment':
                continue

            task, user = self._get_task_and_user(session,
                                                 entity.get('action'),
                                                 entity.get('changes'))

            if not task or not user:
                self.log.error(
                    'Task or User was not found.')
                continue

            data = self._get_template_data(task)
            # format directories to pass to shell script
            anatomy = Anatomy(data["project"]["name"])
            # formatting work dir is easiest part as we can use whole path
            work_dir = anatomy.format(data)['avalon']['work']
            # we also need publish but not whole
            publish = anatomy.format_all(data)['partial']['avalon']['publish']
            # now find path to {asset}
            m = re.search("(^.+?{})".format(data['asset']),
                          publish)

            if not m:
                msg = 'Cannot get part of publish path {}'.format(publish)
                self.log.error(msg)
                return {
                    'success': False,
                    'message': msg
                }
            publish_dir = m.group(1)

            for script in presets.get(entity.get('action')):
                self.log.info(
                    '[{}] : running script for user {}'.format(
                        entity.get('action'), user["username"]))
                self._run_script(script, [user["username"],
                                          work_dir, publish_dir])

        return True


def register(session, plugins_presets):
    """
    Register plugin. Called when used as an plugin.
    """

    UserAssigmentEvent(session, plugins_presets).register()
