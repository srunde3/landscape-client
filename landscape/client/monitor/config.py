import os

from landscape.client.deployment import Configuration
from landscape.client.watchdog import ALL_MONITOR_PLUGINS


class MonitorConfiguration(Configuration):
    """Specialized configuration for the Landscape Monitor."""

    def make_parser(self):
        """
        Specialize L{Configuration.make_parser}, adding many
        monitor-specific options.
        """
        parser = super().make_parser()

        parser.add_option(
            "--monitor-plugins",
            metavar="PLUGIN_LIST",
            help="Comma-delimited list of monitor plugins to "
            "use. ALL means use all plugins.",
            default="ALL",
        )
        parser.add_option(
            "--root-monitor-plugins",
            help="Comma-delimited list of monitor plugins to run as root.",
            default=[],
        )
        return parser

    @property
    def plugin_factories(self):
        if is_running_as_root():
            return self.root_plugins_factories
        else:
            return self.landscape_plugin_factories

    @property
    def root_plugins_factories(self):
        if self.root_monitor_plugins:
            return [x.strip() for x in self.root_monitor_plugins.split(",")]
        else:
            return []

    @property
    def landscape_plugin_factories(self):
        if self.monitor_plugins == "ALL":
            plugins = ALL_MONITOR_PLUGINS
        else:
            plugins = [x.strip() for x in self.monitor_plugins.split(",")]

        return [x for x in plugins if x not in self.root_plugins_factories]


def is_running_as_root():
    return os.getuid() == 0
