import os
import sys
import argparse
import logging
import json

from pype.vendor import ftrack_api
from pype.ftrack import BaseAction


class ThumbToChildren(BaseAction):
    '''Custom action.'''

    # Action identifier
    identifier = 'thumb.to.children'
    # Action label
    label = 'Thumbnail'
    # Action variant
    variant = " to Children"
    # Action icon
    icon = '{}/ftrack/action_icons/Thumbnail.svg'.format(
        os.environ.get('PYPE_STATICS_SERVER', '')
    )

    def discover(self, session, entities, event):
        ''' Validation '''

        if (len(entities) != 1 or entities[0].entity_type in ['Project']):
            return False

        return True

    def launch(self, session, entities, event):
        '''Callback method for action.'''

        userId = event['source']['user']['id']
        user = session.query('User where id is ' + userId).one()

        job = session.create('Job', {
            'user': user,
            'status': 'running',
            'data': json.dumps({
                'description': 'Push thumbnails to Childrens'
            })
        })

        try:
            for entity in entities:
                thumbid = entity['thumbnail_id']
                if thumbid:
                    for child in entity['children']:
                        child['thumbnail_id'] = thumbid

            # inform the user that the job is done
            job['status'] = 'done'
        except Exception:
            # fail the job if something goes wrong
            job['status'] = 'failed'
            raise
        finally:
            session.commit()

        return {
            'success': True,
            'message': 'Created job for updating thumbnails!'
        }


def register(session, plugins_presets={}):
    '''Register action. Called when used as an event plugin.'''

    ThumbToChildren(session, plugins_presets).register()


def main(arguments=None):
    '''Set up logging and register action.'''
    if arguments is None:
        arguments = []

    parser = argparse.ArgumentParser()
    # Allow setting of logging level from arguments.
    loggingLevels = {}
    for level in (
        logging.NOTSET, logging.DEBUG, logging.INFO, logging.WARNING,
        logging.ERROR, logging.CRITICAL
    ):
        loggingLevels[logging.getLevelName(level).lower()] = level

    parser.add_argument(
        '-v', '--verbosity',
        help='Set the logging output verbosity.',
        choices=loggingLevels.keys(),
        default='info'
    )
    namespace = parser.parse_args(arguments)

    # Set up basic logging
    logging.basicConfig(level=loggingLevels[namespace.verbosity])

    session = ftrack_api.Session()
    register(session)

    # Wait for events
    logging.info(
        'Registered actions and listening for events. Use Ctrl-C to abort.'
    )
    session.event_hub.wait()


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
