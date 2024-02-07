from landscape.client.monitor.config import ALL_PLUGINS
from landscape.client.monitor.config import MonitorConfiguration
from landscape.client.tests.helpers import LandscapeTest
from landscape.client.watchdog import DEFAULT_ROOT_MONITOR_PLUGINS


class MonitorConfigurationTest(LandscapeTest):
    def setUp(self):
        super().setUp()
        self.config = MonitorConfiguration()

    def test_plugin_factories(self):
        """
        By default all plugins are enabled and DEFAULT_ROOT_MONITOR_PLUGINS
        only exist in root_plugin_factories
        """
        expected = set(ALL_PLUGINS) - set(DEFAULT_ROOT_MONITOR_PLUGINS)
        self.assertSetEqual(
            set(self.config.landscape_plugin_factories),
            expected,
        )
        self.assertEqual(
            self.config.root_plugin_factories,
            DEFAULT_ROOT_MONITOR_PLUGINS,
        )

    def test_plugin_factories_with_monitor_plugins(self):
        """
        The C{--monitor-plugins} command line option can be used to specify
        which plugins should be active.
        """
        self.config.load(["--monitor-plugins", "  ComputerInfo, LoadAverage "])
        self.assertEqual(
            self.config.landscape_plugin_factories,
            ["ComputerInfo", "LoadAverage"],
        )

    def test_flush_interval(self):
        """
        The C{--flush-interval} command line option can be used to specify the
        flush interval.
        """
        self.config.load(["--flush-interval", "123"])
        self.assertEqual(self.config.flush_interval, 123)

    def test_root_plugins_take_priority(self):
        """
        Specifying an overlapping root and regular plugin will prefer the root
        """
        self.config.load(
            [
                "--monitor-plugins",
                "ComputerInfo, LoadAverage, UbuntuProInfo",
                "--root-monitor-plugins",
                "UbuntuProInfo",
            ],
        )
        self.assertEqual(
            self.config.landscape_plugin_factories,
            ["ComputerInfo", "LoadAverage"],
        )
        self.assertEqual(
            self.config.root_plugin_factories,
            ["UbuntuProInfo"],
        )
