from twisted.python.failure import Failure
from twisted.internet.error import ProcessTerminated
from twisted.internet.defer import succeed, fail

from landscape.manager.manager import ManagerPluginRegistry, SUCCEEDED, FAILED
from landscape.manager.shutdownmanager import ShutdownManager
from landscape.tests.helpers import LandscapeIsolatedTest, RemoteBrokerHelper


class ShutdownManagerTest(LandscapeIsolatedTest):

    helpers = [RemoteBrokerHelper]

    def setUp(self):
        super(ShutdownManagerTest, self).setUp()
        self.broker_service.message_store.set_accepted_types(
            ["shutdown", "operation-result"])
        self.manager = ManagerPluginRegistry(
            self.broker_service.reactor, self.remote,
            self.broker_service.config, self.broker_service.bus)
        self.manager.add(ShutdownManager())

    def test_restart(self):
        """
        When a C{shutdown} message is received with a C{shutdown} directive set
        to C{False}, the C{shutdown} command should be called to restart the
        system 5 minutes from now.
        """
        run = self.mocker.replace("twisted.internet.utils.getProcessOutput")
        args = ["-r", "+5", "'Landscape is restarting down the system'"]
        getProcessOutput = self.expect(run("shutdown", args=args, path=None,
                                           errortoo=1))
        getProcessOutput.result(succeed("Shutdown called!"))
        self.mocker.replay()

        def got_result(result):
            self.assertTrue(self.broker_service.exchanger.is_urgent())
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "status": SUCCEEDED,
                  "result-text": "Shutdown called!",
                  "operation-id": 100}])

        dispatched = self.manager.dispatch_message({"type": "shutdown",
                                                    "operation-id": 100,
                                                    "reboot": True})
        dispatched.addCallback(got_result)
        return dispatched

    def test_shutdown(self):
        """
        When a C{shutdown} message is received with a C{shutdown} directive set
        to C{True}, the C{shutdown} command should be called to shutdown the
        system 5 minutes from now.
        """
        run = self.mocker.replace("twisted.internet.utils.getProcessOutput")
        args = ["-h", "+5", "'Landscape is shutting down the system'"]
        getProcessOutput = self.expect(run("shutdown", args=args, path=None,
                                           errortoo=1))
        getProcessOutput.result(succeed("Shutdown called!"))
        self.mocker.replay()

        def got_result(result):
            self.assertTrue(self.broker_service.exchanger.is_urgent())
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "status": SUCCEEDED,
                  "result-text": "Shutdown called!",
                  "operation-id": 100}])

        dispatched = self.manager.dispatch_message({"type": "shutdown",
                                                    "operation-id": 100,
                                                    "reboot": False})
        dispatched.addCallback(got_result)
        return dispatched

    def test_call_to_shutdown_fails(self):
        """
        If the C{shutdown} command fails we should return a failed
        C{operation-result} message.
        """
        run = self.mocker.replace("twisted.internet.utils.getProcessOutput")
        args = ["-r", "+5", "'Landscape is restarting down the system'"]
        getProcessOutput = self.expect(run("shutdown", args=args, path=None,
                                           errortoo=1))
        getProcessOutput.result(fail(Failure(ProcessTerminated(exitCode=1))))
        self.mocker.replay()

        def got_result(result):
            self.assertTrue(self.broker_service.exchanger.is_urgent())
            message = ("A process has ended with a probable error condition: "
                       "process ended with exit code 1.")
            self.assertMessages(
                self.broker_service.message_store.get_pending_messages(),
                [{"type": "operation-result",
                  "status": FAILED,
                  "result-text": message,
                  "operation-id": 100}])

        dispatched = self.manager.dispatch_message({"type": "shutdown",
                                                    "operation-id": 100,
                                                    "reboot": True})
        dispatched.addCallback(got_result)
        return dispatched

