from landscape.client.deployment import Configuration


ALL_PLUGINS = [
    "ActiveProcessInfo",
    "ComputerInfo",
    "LoadAverage",
    "MemoryInfo",
    "MountInfo",
    "ProcessorInfo",
    "Temperature",
    "PackageMonitor",
    "UserMonitor",
    "RebootRequired",
    "AptPreferences",
    "NetworkActivity",
    "NetworkDevice",
    "UpdateManager",
    "CPUUsage",
    "SwiftUsage",
    "CephUsage",
    "ComputerTags",
    "UbuntuProInfo",
    "LivePatch",
    "UbuntuProRebootRequired",
    "SnapMonitor",
]


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
    def root_plugin_factories(self):
        if self.root_monitor_plugins:
            return [x.strip() for x in self.root_monitor_plugins.split(",")]
        else:
            return []

    @property
    def landscape_plugin_factories(self):
        if self.monitor_plugins == "ALL":
            plugins = ALL_PLUGINS
        else:
            plugins = [x.strip() for x in self.monitor_plugins.split(",")]

        return [x for x in plugins if x not in self.root_plugin_factories]
