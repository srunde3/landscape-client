from unittest import mock

from landscape.client.manager.ubuntuproinfo import get_ubuntu_pro_info
from landscape.client.manager.ubuntuproinfo import UbuntuProInfo
from landscape.client.tests.helpers import LandscapeTest
from landscape.client.tests.helpers import MonitorHelper


class UbuntuProInfoTest(LandscapeTest):
    """Ubuntu Pro info plugin tests."""

    helpers = [MonitorHelper]

    def setUp(self):
        super().setUp()
        self.mstore.set_accepted_types(["ubuntu-pro-info"])

    def test_ubuntu_pro_info(self):
        """Tests calling `ua status`."""
        plugin = UbuntuProInfo()

        with mock.patch("subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(
                stdout='"This is a test"',
            )
            self.monitor.add(plugin)
            plugin.run()

        run_mock.assert_called()
        messages = self.mstore.get_pending_messages()
        self.assertTrue(len(messages) > 0)
        self.assertTrue("ubuntu-pro-info" in messages[0])
        self.assertEqual(messages[0]["ubuntu-pro-info"], '"This is a test"')

    def test_ubuntu_pro_info_no_pro(self):
        """Tests calling `pro status` when it is not installed."""
        plugin = UbuntuProInfo()
        self.monitor.add(plugin)

        with mock.patch("subprocess.run") as run_mock:
            run_mock.side_effect = FileNotFoundError()
            plugin.run()

        messages = self.mstore.get_pending_messages()
        run_mock.assert_called_once()
        self.assertTrue(len(messages) > 0)
        self.assertTrue("ubuntu-pro-info" in messages[0])
        self.assertIn("errors", messages[0]["ubuntu-pro-info"])

    def test_get_ubuntu_pro_info_core(self):
        """In Ubuntu Core, there is no pro info, so return a reasonable erro
        message.
        """
        with mock.patch(
            "landscape.client.manager.ubuntuproinfo.IS_CORE",
            new="1",
        ):
            result = get_ubuntu_pro_info()

        self.assertIn("errors", result)
        self.assertIn("not available", result["errors"][0]["message"])
        self.assertEqual(result["result"], "failure")

    def test_persistence_unchanged_data(self):
        """If data hasn't changed, a new message is not sent"""
        plugin = UbuntuProInfo()
        self.monitor.add(plugin)
        data = '"Initial data!"'

        with mock.patch("subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(
                stdout=data,
            )
            plugin.run()

        messages = self.mstore.get_pending_messages()
        run_mock.assert_called_once()
        self.assertEqual(1, len(messages))
        self.assertTrue("ubuntu-pro-info" in messages[0])
        self.assertEqual(messages[0]["ubuntu-pro-info"], data)

        with mock.patch("subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(
                stdout=data,
            )
            plugin.run()

        run_mock.assert_called_once()
        messages = self.mstore.get_pending_messages()
        self.assertEqual(1, len(messages))

    def test_persistence_changed_data(self):
        """New data will be sent in a new message in the queue"""
        plugin = UbuntuProInfo()
        self.monitor.add(plugin)

        with mock.patch("subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(
                stdout='"Initial data!"',
            )
            plugin.run()

        messages = self.mstore.get_pending_messages()
        run_mock.assert_called_once()
        self.assertEqual(1, len(messages))
        self.assertTrue("ubuntu-pro-info" in messages[0])
        self.assertEqual(messages[0]["ubuntu-pro-info"], '"Initial data!"')

        with mock.patch("subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(
                stdout='"New data!"',
            )
            plugin.run()

        run_mock.assert_called_once()
        messages = self.mstore.get_pending_messages()
        self.assertEqual(2, len(messages))
        self.assertEqual(messages[1]["ubuntu-pro-info"], '"New data!"')

    def test_persistence_reset(self):
        """Resetting the plugin will allow a message with identical data to
        be sent"""
        plugin = UbuntuProInfo()
        self.monitor.add(plugin)
        data = '"Initial data!"'

        with mock.patch("subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(
                stdout=data,
            )
            plugin.run()

        messages = self.mstore.get_pending_messages()
        run_mock.assert_called_once()
        self.assertEqual(1, len(messages))
        self.assertTrue("ubuntu-pro-info" in messages[0])
        self.assertEqual(messages[0]["ubuntu-pro-info"], data)

        plugin._reset()

        with mock.patch("subprocess.run") as run_mock:
            run_mock.return_value = mock.Mock(
                stdout=data,
            )
            plugin.run()

        run_mock.assert_called_once()
        messages = self.mstore.get_pending_messages()
        self.assertEqual(2, len(messages))
        self.assertTrue("ubuntu-pro-info" in messages[1])
        self.assertEqual(messages[1]["ubuntu-pro-info"], data)
