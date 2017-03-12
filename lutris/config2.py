#!/usr/bin/env python3
"""
Lutris Configuration v2

(c) 2017 Taeyeon Mori

The new configuration system uses proper cascading lookups and
removes the separate keyspaces for the levels. This means the config
is a single keyspace with an arbitrary number of levels.
"""

import os
from collections import OrderedDict

import yaml

from .sysoptions import system_options
from .settings import CONFIG_DIR


# ========== Helpers ==========================================================
def rawdict(self):
    try:
        return self.this
    except AttributeError:
        return self


def cascade(dict, parent=None):
    if parent is None:
        return dict
    else:
        return CascadingProxy(dict, parent)


def makedef(options):
    return OrderedDict([(opt["option"], opt) for opt in options])


# ========== Cascading Logic ==================================================
class CascadingProxy(object):
    """ Cascade without copying the data; like collections.ChainMap """
    def __init__(self, this, parent):
        self.parent = parent
        self.this = this

    def __repr__(self):
        return "CascadingProxy(%s, %s)" % (self.this, self.parent)

    def __getitem__(self, key):
        if key in self.this:
            return self.this[key]
        return self.parent[key]

    def __contains__(self, key):
        return key in self.this or key in self.parent

    def __setitem__(self, key, value):
        self.this[key] = value

    def __delitem__(self, key):
        del self.this[key]

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def update(self, other):
        self.this.update(other)
        return self


class CascadingConfig(object):
    """
    Cascading Configuration

    Supports following definitions:
        - options: The option's name
        - default: Define a default value
        - only one of:
            - getter: Use a custom getter [fn(config, key) -> value]
            - cascading: The value is a dictionary and should itself cascade [bool]
            - transform: Run a transformation function on the value before returning it [fn(config, key, value) -> value]
        - validate: Validate a value before setting it [fn(config, key, value) -> bool]. Will raise ValueError on failure

    Note:
        the definition may not be changed while a CascadingConfig object
        that uses it exists, as some definitions are cached across levels.
    """
    def __init__(self, definition, data=None, parent=None):
        self.data = {} if data is None else data
        self.definition = definition
        self.config = cascade(self.data, parent)
        self.parent = parent

        # Caches to speed up some cascaded lookups
        self.defaults = self.build_definition_cache("default")
        self.validate_cache = self.build_definition_cache("validate")
        self.getter_cache = self.build_getter_cache()
        self.cascade_cache = {}

    # ======== Access =========================================================
    def __contains__(self, key):
        return key in self.config

    def __getitem__(self, key):
        if key in self.getter_cache:
            getter = self.getter_cache[key]
            try:
                return getter(self, key)
            except KeyError:
                if key in self.defaults:
                    return self.defaults[key]
                raise
        else:
            try:
                return self.config[key]
            except KeyError:
                if key in self.defaults:
                    return self.defaults[key]
                raise

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def get_nodefaults(self, key):
        if key in self.getter_cache:
            return self.getter_cache[key](self, key)
        else:
            return self.config[key]

    # Special getters
    def cascade_getter(self, key):
        """ Get a sub-dictionary with cascaded items """
        if key not in self.cascade_cache:
            self.data.setdefault(key, {})
            if self.parent:
                cas = CascadingProxy(self.data[key], self.parent.get_cascade(key))
            else:
                cas = self.data[key]
            self.cascade_cache[key] = cas
        return self.cascade_cache[key]

    def transform_getter(self, key):
        """ Get a transformed item. Used when 'transform' definition is set """
        if key in self.config:
            return self.definition[key]["transform"](self, key, self.config[key])
        else:
            return self.defaults.get(key, None)

    # Modification
    def __setitem__(self, key, value):
        if key in self.validate_cache and not self.validate_cache[key](self, key, value):
            raise ValueError("Config value validation failed.")

        self.config[key] = value

    def __delitem__(self, key):
        del self.config[key]

    def update(self, other):
        self.config.update(other)
        return self

    def replace(self, other):
        self.data = other
        if self.parent is not None:
            self.config.this = other

    # ======== Definition =====================================================
    @property
    def cascade_definition(self):
        return cascade(self.definition, self.parent.cascade_definition() if self.parent else None)

    def get_definition(self, key, name=None):
        if key in self.definition:
            if name is not None:
                if name in self.definition[key]:
                    return self.definition[key][name]
            else:
                return self.definition[key]
        elif self.parent:
            return self.parent.get_definition(key, name)

    def build_definition_cache(self, name):
        """ Cache a specific definition for all keys """
        cache = self.parent.build_definition_cache(name) if self.parent else {}
        for key, defn in self.definition.items():
            if name in defn:
                cache[key] = defn[name]
        return cache

    def build_getter_cache(self):
        """ Build a mapping of keys to special getters """
        cache = self.parent.build_getter_cache() if self.parent else {}
        for key, defn in self.definition.items():
            if "getter" in defn:
                cache[key] = defn["getter"]
            elif "cascade" in defn and defn["cascade"]:
                cache[key] = cascade_getter
            elif "transform" in defn:
                cache[key] = transform_getter
        return cache

    # ======== Files ==========================================================
    @staticmethod
    def _load_file(filename):
        with open(filename, "r") as f:
            return yaml.load(f)

    @staticmethod
    def _dump_file(filename, data):
        with open(filename, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

    @classmethod
    def from_file(cls, definition, file, parent=None):
        return cls(definition, cls._load_file(file), parent)

    def update_from_file(self, file):
        self.update(self._load_file(file))

    def dump_to_file(self, file):
        self._dump_file(file, self.data)


class ConfigFile(CascadingConfig):
    def __init__(self, definition, filename, parent=None, data=None):
        self.filename = filename

        # Load data
        if data is None and os.path.exists(filename):
            data = self._load_file(filename)

        # Construct
        super(ConfigFile, self).__init__(definition, data, parent)


    def load(self):
        self.replace(self._load_file(self.filename))

    def save(self):
        self.dump_to_file(self.filename)


# ========= Lutris Config Files ===============================================
class SystemConfig(ConfigFile):
    def __init__(self):
        super(SystemConfig, self).__init__(
            makedef(system_options),
            os.path.join(CONFIG_DIR, "system.yml")
        )

    def __repr__(self):
        return "<Lutris SystemConfig() at %p>" % id(self)


class RunnerConfig(ConfigFile):
    def __init__(self, runner_slug, options, parent=None):
        self.runner_slug = runner_slug

        super(RunnerConfig, self).__init__(
            makedef(options),
            os.path.join(CONFIG_DIR, "runners", "%s.yml" % runner_slug),
            parent
        )

    def __repr__(self):
        return "<Lutris RunnerConfig(%s, ..., %r) at %p>" % (self.runner_slug, self.parent, id(self))


class GameConfig(ConfigFile):
    def __init__(self, game_config_id, options, parent=None, data=None, definition=None):
        self.game_config_id = game_config_id

        super(GameConfig, self).__init__(
            makedef(options) if definition is None else definition,
            os.path.join(CONFIG_DIR, "games/%s.yml" % self.game_config_id),
            parent,
            data
        )

    def __repr__(self):
        return "<Lutris GameConfig(%s, ..., %r) at %p>" % (self.game_config_id, self.parent, id(self))


class TempGameConfig(CascadingConfig):
    def __init__(self, options, parent=None):
        super(TempGameConfig, self).__init__(
            makedef(options),
            None,
            parent
        )

    def __repr__(self):
        return "<Lutris TempGameConfig(..., %r) at %p>" % (self.parent, id(self))

    def assign_id(self, game_config_id):
        return GameConfig(
            game_config_id,
            None,
            self.parent,
            data=self.data,
            definition=self.definition
        )
