"""Handle the game, runner and global system configurations."""

import os
import sys
import time
import yaml
from os.path import join

from lutris import pga, settings, sysoptions
from lutris.runners import import_runner, InvalidRunner
from lutris.util.log import logger

from .config2 import SystemConfig, RunnerConfig, GameConfig, TempGameConfig


# Temporary config name for games that haven't been created yet
TEMP_CONFIG = 'TEMP_CONFIG'


def register_handler():
    """Register the lutris: protocol to open with the application."""
    logger.debug("registering protocol")
    executable = os.path.abspath(sys.argv[0])
    base_key = "desktop.gnome.url-handlers.lutris"
    schema_directory = "/usr/share/glib-2.0/schemas/"
    schema_source = Gio.SettingsSchemaSource.new_from_directory(
        schema_directory, None, True
    )
    schema = schema_source.lookup(base_key, True)
    if schema:
        settings = Gio.Settings.new(base_key)
        settings.set_string('command', executable)
    else:
        logger.warning("Schema not installed, cannot register url-handler")


def check_config(force_wipe=False):
    """Check if initial configuration is correct."""
    directories = [settings.CONFIG_DIR,
                   join(settings.CONFIG_DIR, "runners"),
                   join(settings.CONFIG_DIR, "games"),
                   settings.DATA_DIR,
                   join(settings.DATA_DIR, "covers"),
                   settings.ICON_PATH,
                   join(settings.DATA_DIR, "banners"),
                   join(settings.DATA_DIR, "runners"),
                   join(settings.DATA_DIR, "lib"),
                   settings.RUNTIME_DIR,
                   settings.CACHE_DIR,
                   join(settings.CACHE_DIR, "installer"),
                   join(settings.CACHE_DIR, "tmp")]
    for directory in directories:
        if not os.path.exists(directory):
            logger.debug("creating directory %s" % directory)
            os.makedirs(directory)

    if force_wipe:
        os.remove(settings.PGA_DB)
    pga.syncdb()
    pga.set_config_paths()


def make_game_config_id(game_slug):
    """Return an unique config id to avoid clashes between multiple games"""
    return "{}-{}".format(game_slug, int(time.time()))



class LutrisConfig(object):
    """
    Compatibility wrapper for legacy config API
    """
    def __init__(self, runner_slug=None, game_config_id=None, level=None):
        self._game_config_id = game_config_id
        if runner_slug:
            self.runner_slug = str(runner_slug)
        else:
            self.runner_slug = runner_slug

        # Set config level
        self.level = level
        if not level:
            if game_config_id:
                self.level = 'game'
            elif runner_slug:
                self.level = 'runner'
            else:
                self.level = 'system'

        # Grab runner definitions
        if runner_slug:
            self.runner_cls = import_runner(runner_slug)
            runner_options = self.runner_cls.runner_options
            game_options = self.runner_cls.game_options
        elif self.level != "system":
            logger.warn("game and runner levels should have runner_slug passed!")
            runner_options = game_options = []

        # Initialize config levels
        # system is loaded in all levels
        self.config = self.system_level = SystemConfig()
        if self.level != "system": # game and runner
            self.config = self.runner_level = RunnerConfig(
                self.runner_slug,
                runner_options,
                self.system_level
            )
        if self.level == "game": # game only
            if game_config_id == TEMP_CONFIG:
                self.game_level = TempGameConfig(
                    game_options,
                    self.runner_level
                )
            else:
                self.game_level = GameConfig(
                    game_config_id,
                    game_options,
                    self.runner_level
                )
            self.config = self.game_level

    def __repr__(self):
        return "<Legacy LutrisConfig(level=%s, game_config_id=%s, runner=%s) at %p>" % (
            self.level, self.game_config_id, self.runner_slug, id(self)
        )

    # Catch game_config_id changes
    @property
    def game_config_id(self):
        return self._game_config_id

    @game_config_id.setter
    def game_config_id(self, value):
        if self._game_config_id == TEMP_CONFIG:
            self.game_level = self.config = self.game_level.assign_id(value)
            self._game_config_id = value
        else:
            raise Exception("Cannot change game_config_id later")

    # Paths
    @property
    def system_config_path(self):
        return self.system_level.filename

    @property
    def runner_config_path(self):
        if not self.runner_slug:
            return
        return self.runner_level.filename

    @property
    def game_config_path(self):
        if not self.game_config_id or self.game_config_id == TEMP_CONFIG:
            return
        return self.game_level.filename

    # Legacy config sections
    @property
    def system_config(self):
        return self.config

    runner_config = game_config = system_config

    @property
    def raw_system_config(self):
        return self.config.data

    @raw_system_config.setter
    def raw_system_config(self, value):
        self.config.replace(value)

    raw_runner_config = raw_game_config = raw_system_config

    # Legacy manual updates, now no-ops
    def update_cascaded_config(self):
        pass

    def update_raw_config(self):
        pass

    # Legacy misc
    def remove(self, game=None):
        """Delete the configuration file from disk."""
        if not self.game_config_path:
            return
        if os.path.exists(self.game_config_path):
            os.remove(self.game_config_path)
            logger.debug("Removed config %s", self.game_config_path)
        else:
            logger.debug("No config file at %s", self.game_config_path)

    def save(self):
        """Save configuration file according to its type"""
        self.config.save()

    def get_level(self, level):
        return getattr(self, "%s_level" % level)

    def get_defaults(self, options_type):
        """Return a dict of options' default value."""
        return self.get_level(options_type).defaults

    def options_as_dict(self, options_type):
        """Convert the option list to a dict with option name as keys"""
        return self.get_level(options_type).definition

