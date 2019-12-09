"""
Wrapper around interactions with the database

Copy of io module in avalon-core.
 - In this case not working as singleton with api.Session!
"""

import os
import time
import errno
import shutil
import logging
import tempfile
import functools
import contextlib
import atexit

import requests

# Third-party dependencies
import pymongo
from pymongo.client_session import ClientSession

class NotActiveTable(Exception):
    pass

def auto_reconnect(func):
    """Handling auto reconnect in 3 retry times"""
    @functools.wraps(func)
    def decorated(*args, **kwargs):
        object = args[0]
        for retry in range(3):
            try:
                return func(*args, **kwargs)
            except pymongo.errors.AutoReconnect:
                object.log.error("Reconnecting..")
                time.sleep(0.1)
        else:
            raise

    return decorated


def check_active_table(func):
    """Handling auto reconnect in 3 retry times"""
    @functools.wraps(func)
    def decorated(obj, *args, **kwargs):
        if not obj.active_table:
            raise NotActiveTable("Active table is not set. (This is bug)")
        return func(obj, *args, **kwargs)

    return decorated


class DbConnector:

    log = logging.getLogger(__name__)
    timeout = 1000

    def __init__(self, mongo_url, database_name, table_name=None):
        self._mongo_client = None
        self._sentry_client = None
        self._sentry_logging_handler = None
        self._database = None
        self._is_installed = False
        self._mongo_url = mongo_url
        self._database_name = database_name

        self.active_table = table_name

    def __getattribute__(self, attr):
        try:
            return super().__getattribute__(attr)
        except AttributeError:
            return self._database[self.active_table].__getattribute__(attr)

    def install(self):
        """Establish a persistent connection to the database"""
        if self._is_installed:
            return
        atexit.register(self.uninstall)
        logging.basicConfig()

        self._mongo_client = pymongo.MongoClient(
            self._mongo_url,
            serverSelectionTimeoutMS=self.timeout
        )

        for retry in range(3):
            try:
                t1 = time.time()
                self._mongo_client.server_info()
            except Exception:
                self.log.error("Retrying..")
                time.sleep(1)
            else:
                break

        else:
            raise IOError(
                "ERROR: Couldn't connect to %s in "
                "less than %.3f ms" % (self._mongo_url, timeout)
            )

        self.log.info("Connected to %s, delay %.3f s" % (
            self._mongo_url, time.time() - t1
        ))

        self._database = self._mongo_client[self._database_name]
        self._is_installed = True

    def uninstall(self):
        """Close any connection to the database"""

        try:
            self._mongo_client.close()
        except AttributeError:
            pass

        self._mongo_client = None
        self._database = None
        self._is_installed = False
        atexit.unregister(self.uninstall)

    def create_table(self, name, **options):
        if self.exist_table(name):
            return

        return self._database.create_collection(name, **options)

    def exist_table(self, table_name):
        return table_name in self.tables()

    def tables(self):
        """List available tables
        Returns:
            list of table names
        """
        collection_names = self.collections()
        for table_name in collection_names:
            if table_name in ("system.indexes",):
                continue
            yield table_name

    @auto_reconnect
    def collections(self):
        return self._database.collection_names()

    @check_active_table
    @auto_reconnect
    def insert_one(self, item, **options):
        assert isinstance(item, dict), "item must be of type <dict>"
        return self._database[self.active_table].insert_one(item, **options)

    @check_active_table
    @auto_reconnect
    def insert_many(self, items, ordered=True, **options):
        # check if all items are valid
        assert isinstance(items, list), "`items` must be of type <list>"
        for item in items:
            assert isinstance(item, dict), "`item` must be of type <dict>"

        options["ordered"] = ordered
        return self._database[self.active_table].insert_many(items, **options)

    @check_active_table
    @auto_reconnect
    def find(self, filter, projection=None, sort=None, **options):
        options["projection"] = projection
        options["sort"] = sort
        return self._database[self.active_table].find(filter, **options)

    @check_active_table
    @auto_reconnect
    def find_one(self, filter, projection=None, sort=None, **options):
        assert isinstance(filter, dict), "filter must be <dict>"

        options["projection"] = projection
        options["sort"] = sort
        return self._database[self.active_table].find_one(filter, **options)

    @check_active_table
    @auto_reconnect
    def replace_one(self, filter, replacement, **options):
        return self._database[self.active_table].replace_one(
            filter, replacement, **options
        )

    @check_active_table
    @auto_reconnect
    def update_one(self, filter, update, **options):
        return self._database[self.active_table].update_one(
            filter, update, **options
        )

    @check_active_table
    @auto_reconnect
    def update_many(self, filter, update, **options):
        return self._database[self.active_table].update_many(
            filter, update, **options
        )

    @check_active_table
    @auto_reconnect
    def distinct(self, *args, **kwargs):
        return self._database[self.active_table].distinct(*args, **kwargs)

    @check_active_table
    @auto_reconnect
    def drop_collection(self, name_or_collection, **options):
        return self._database[self.active_table].drop(
            name_or_collection, **options
        )

    @check_active_table
    @auto_reconnect
    def delete_one(self, filter, collation=None, **options):
        options["collation"] = collation
        return self._database[self.active_table].delete_one(filter, **options)

    @check_active_table
    @auto_reconnect
    def delete_many(self, filter, collation=None, **options):
        options["collation"] = collation
        return self._database[self.active_table].delete_many(filter, **options)
