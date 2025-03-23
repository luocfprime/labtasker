"""
Python emulated MongoDB
Adapted from https://github.com/mongomock/mongomock/blob/develop/mongomock/store.py
"""

import collections
import datetime
import functools
import threading
from pathlib import Path

import jsonpickle
import mongomock
from mongomock.thread import RWLock


class ServerStore:
    """Object holding the data for a whole server (many databases)."""

    def __init__(self, persistence_path=None):
        self._databases = {}
        self._persistence_path = persistence_path

        self.load_from_disk()

    def __getitem__(self, db_name):
        try:
            return self._databases[db_name]
        except KeyError:
            db = self._databases[db_name] = DatabaseStore(server_store=self)
            return db

    def __contains__(self, db_name):
        return self[db_name].is_created

    def list_created_database_names(self):
        return [name for name, db in self._databases.items() if db.is_created]

    def save_to_disk(self, path=None):
        """Save the current state of the database to disk using jsonpickle."""
        save_path = path or self._persistence_path
        if not save_path:
            raise ValueError("No persistence path specified")

        # Ensure directory exists
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        # Serialize and save
        with open(save_path, "w") as f:
            f.write(jsonpickle.encode(self._databases))

    def load_from_disk(self, path=None):
        """Load the database state from disk using jsonpickle."""
        load_path = path or self._persistence_path
        if not load_path:
            raise ValueError("No persistence path specified")

        load_path = Path(load_path)
        if load_path.exists():
            with open(load_path, "r") as f:
                self._databases = jsonpickle.decode(f.read())
        else:
            self._databases = {}


class DatabaseStore:
    """Object holding the data for a database (many collections)."""

    def __init__(self, server_store=None):
        self._collections = {}
        self._server_store = server_store

    def __getitem__(self, col_name):
        try:
            return self._collections[col_name]
        except KeyError:
            col = self._collections[col_name] = CollectionStore(
                col_name, database_store=self
            )
            return col

    def __contains__(self, col_name):
        return self[col_name].is_created

    def list_created_collection_names(self):
        return [name for name, col in self._collections.items() if col.is_created]

    def create_collection(self, name):
        col = self[name]
        col.create()
        return col

    def rename(self, name, new_name):
        col = self._collections.pop(name, CollectionStore(new_name))
        col.name = new_name
        self._collections[new_name] = col

    @property
    def is_created(self):
        return any(col.is_created for col in self._collections.values())


class CollectionStore:
    """Object holding the data for a collection."""

    def __init__(self, name, database_store=None):
        self._documents = collections.OrderedDict()
        self.indexes = {}
        self._is_force_created = False
        self.name = name
        self._ttl_indexes = {}
        self._database_store = database_store

        # 694 - Lock for safely iterating and mutating OrderedDicts
        self._rwlock = RWLock()

    def create(self):
        self._is_force_created = True

    @property
    def is_created(self):
        return self._documents or self.indexes or self._is_force_created

    def drop(self):
        self._documents = collections.OrderedDict()
        self.indexes = {}
        self._ttl_indexes = {}
        self._is_force_created = False
        self._trigger_save()

    def create_index(self, index_name, index_dict):
        self.indexes[index_name] = index_dict
        if index_dict.get("expireAfterSeconds") is not None:
            self._ttl_indexes[index_name] = index_dict
        self._trigger_save()

    def drop_index(self, index_name):
        self._remove_expired_documents()

        # The main index object should raise a KeyError, but the
        # TTL indexes have no meaning to the outside.
        del self.indexes[index_name]
        self._ttl_indexes.pop(index_name, None)
        self._trigger_save()

    def _trigger_save(self):
        """Trigger a save operation if we have a reference to the server store."""
        if self._database_store and hasattr(self._database_store, "_server_store"):
            server_store = self._database_store._server_store
            if server_store and hasattr(server_store, "save_to_disk"):
                server_store.save_to_disk()

    @property
    def is_empty(self):
        self._remove_expired_documents()
        return not self._documents

    def __contains__(self, key):
        self._remove_expired_documents()
        with self._rwlock.reader():
            return key in self._documents

    def __getitem__(self, key):
        self._remove_expired_documents()
        with self._rwlock.reader():
            return self._documents[key]

    def __setitem__(self, key, val):
        with self._rwlock.writer():
            self._documents[key] = val
        self._trigger_save()

    def __delitem__(self, key):
        with self._rwlock.writer():
            del self._documents[key]
        self._trigger_save()

    def __len__(self):
        self._remove_expired_documents()
        with self._rwlock.reader():
            return len(self._documents)

    @property
    def documents(self):
        self._remove_expired_documents()
        with self._rwlock.reader():
            yield from self._documents.values()

    def _remove_expired_documents(self):
        for index in self._ttl_indexes.values():
            self._expire_documents(index)

    def _expire_documents(self, index):
        # TODO(juannyg): use a caching mechanism to avoid re-expiring the documents if
        # we just did and no document was added / updated

        # Ignore non-integer values
        try:
            expiry = int(index["expireAfterSeconds"])
        except ValueError:
            return

        # Ignore commpound keys
        if len(index["key"]) > 1:
            return

        # "key" structure = list of (field name, direction) tuples
        ttl_field_name = next(iter(index["key"]))[0]
        ttl_now = mongomock.utcnow()

        with self._rwlock.reader():
            expired_ids = [
                doc["_id"]
                for doc in self._documents.values()
                if self._value_meets_expiry(doc.get(ttl_field_name), expiry, ttl_now)
            ]

        for exp_id in expired_ids:
            del self[exp_id]

    def _value_meets_expiry(self, val, expiry, ttl_now):
        val_to_compare = _get_min_datetime_from_value(val)
        try:
            return (ttl_now - val_to_compare).total_seconds() >= expiry
        except TypeError:
            return False

    # Add a method to handle jsonpickle serialization of RWLock
    def __getstate__(self):
        """Custom serialization that excludes the lock."""
        state = self.__dict__.copy()
        # Remove the lock as it's not serializable
        state.pop("_rwlock", None)
        return state

    def __setstate__(self, state):
        """Custom deserialization that recreates the lock."""
        self.__dict__.update(state)
        # Recreate the lock
        self._rwlock = RWLock()


def _get_min_datetime_from_value(val):
    if not val:
        return datetime.datetime.max
    if isinstance(val, list):
        return functools.reduce(_min_dt, [datetime.datetime.max, *val])
    return val


def _min_dt(dt1, dt2):
    try:
        return dt1 if dt1 < dt2 else dt2
    except TypeError:
        return dt1


# We need to patch the transactions of MongoMock
# as it is not supported

MONGO_METHODS_TO_PATCH = [
    "find_one",
    "insert_one",
    "insert_many",
    "update_one",
    "delete_one",
    "delete_many",
    "find",
    "update_many",
    "find_one_and_update",
    "find_one_and_delete",
    "find_one_and_replace",
    "count_documents",
    "aggregate",
    "bulk_write",
]

# Global transaction lock
_transaction_lock = threading.RLock()


class MockSession:
    def __init__(self):
        self._transaction_active = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._transaction_active:
            self._transaction_active = False
            _transaction_lock.release()

    def start_transaction(self):
        _transaction_lock.acquire()
        self._transaction_active = True
        return self

    def commit_transaction(self):
        if self._transaction_active:
            self._transaction_active = False
            _transaction_lock.release()

    def abort_transaction(self):
        if self._transaction_active:
            self._transaction_active = False
            _transaction_lock.release()


def ignore_session(original_method):
    """Decorator to make methods ignore the session parameter."""

    def wrapper(*args, session=None, **kwargs):
        # Remove session parameter
        return original_method(*args, **kwargs)

    # Mark this method as already patched
    wrapper._patched_for_session = True
    return wrapper


class MongoClient(mongomock.MongoClient):
    """A wrapper around mongomock.MongoClient to ignore session and transactions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._patch_methods()

    def _patch_methods(self):
        """Patch all collection methods to ignore session parameter."""
        # Patch existing collections
        self._patch_existing_collections()

        # Patch collection creation methods to ensure new collections are patched
        self._patch_collection_creation_methods()

        # Patch database creation methods
        self._patch_database_creation_methods()

    def _patch_existing_collections(self):
        """Patch all existing collections in all databases."""
        for db_name in self.list_database_names():
            db = self[db_name]
            for col_name in db.list_collection_names():
                collection = db[col_name]
                self._patch_collection(collection)

    def _patch_collection_creation_methods(self):
        """Patch methods that create or return collections."""
        for db_name in self.list_database_names():
            db = self[db_name]

            # Patch create_collection
            original_create_collection = db.create_collection

            def patched_create_collection(name, *args, **kwargs):
                collection = original_create_collection(name, *args, **kwargs)
                self._patch_collection(collection)
                return collection

            db.create_collection = patched_create_collection

            # Patch get_collection
            original_get_collection = db.get_collection

            def patched_get_collection(name, *args, **kwargs):
                collection = original_get_collection(name, *args, **kwargs)
                self._patch_collection(collection)
                return collection

            db.get_collection = patched_get_collection

    def _patch_collection(self, collection):
        """Patch a single collection's methods to ignore session parameter."""
        for method_name in MONGO_METHODS_TO_PATCH:
            if hasattr(collection, method_name):
                method = getattr(collection, method_name)
                # Only patch if not already patched
                if not hasattr(method, "_patched_for_session"):
                    setattr(collection, method_name, ignore_session(method))

    def _patch_database_creation_methods(self):
        """Patch methods that create or return databases."""
        # Patch get_database method
        original_get_database = self.get_database

        def patched_get_database(name, *args, **kwargs):
            database = original_get_database(name, *args, **kwargs)
            # Patch this database's collection creation methods
            self._patch_collection_creation_methods_for_db(database)
            return database

        self.get_database = patched_get_database

    def _patch_collection_creation_methods_for_db(self, db):
        """Patch collection creation methods for a specific database."""
        # Patch create_collection
        if hasattr(db, "create_collection"):
            original_create_collection = db.create_collection

            def patched_create_collection(name, *args, **kwargs):
                collection = original_create_collection(name, *args, **kwargs)
                self._patch_collection(collection)
                return collection

            db.create_collection = patched_create_collection

        # Patch get_collection
        if hasattr(db, "get_collection"):
            original_get_collection = db.get_collection

            def patched_get_collection(name, *args, **kwargs):
                collection = original_get_collection(name, *args, **kwargs)
                self._patch_collection(collection)
                return collection

            db.get_collection = patched_get_collection

    def start_session(self, *args, **kwargs):
        """Return a mock session that does nothing."""
        return MockSession()
