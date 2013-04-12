"""Test helpers for wiring together the various components in the broker stack.

Each test helper sets up a particular component in the stack of the broker
dependencies. The lowest-level component is a L{BrokerConfiguration} instance,
the highest-level ones are a full L{BrokerServer} exposed over AMP and
connected to remote test L{BrokerClient}.
"""
import os

from landscape.lib.fetch import fetch_async
from landscape.lib.persist import Persist
from landscape.watchdog import bootstrap_list
from landscape.reactor import FakeReactor
from landscape.broker.transport import FakeTransport
from landscape.broker.exchange import MessageExchange
from landscape.broker.exchangestore import ExchangeStore
from landscape.broker.store import get_default_message_store
from landscape.broker.registration import Identity, RegistrationHandler
from landscape.broker.ping import Pinger
from landscape.broker.config import BrokerConfiguration
from landscape.broker.server import BrokerServer
from landscape.broker.amp import (
    BrokerServerProtocolFactory, BrokerClientProtocolFactory,
    RemoteBrokerConnector)
from landscape.broker.client import BrokerClient


class BrokerConfigurationHelper(object):
    """Setup a L{BrokerConfiguration} instance with some test config values.

    The following attributes will be set on your test case:

      - C{config}: A sample L{BrokerConfiguration}.

      - C{config_filename}: The name of the configuration file that was used to
        generate the above C{config}.
    """

    def set_up(self, test_case):
        data_path = test_case.makeDir()
        log_dir = test_case.makeDir()
        test_case.config_filename = os.path.join(test_case.makeDir(),
                                                 "client.conf")
        open(test_case.config_filename, "w").write(
            "[client]\n"
            "url = http://localhost:91919\n"
            "computer_title = Some Computer\n"
            "account_name = some_account\n"
            "ping_url = http://localhost:91910\n"
            "data_path = %s\n"
            "log_dir = %s\n" % (data_path, log_dir))

        bootstrap_list.bootstrap(data_path=data_path, log_dir=log_dir)

        test_case.config = BrokerConfiguration()
        test_case.config.load(["-c", test_case.config_filename])

    def tear_down(self, test_case):
        pass


class ExchangeHelper(BrokerConfigurationHelper):
    """Setup a L{MessageExchange} instance along with its dependencies.

    This helper uses the sample broker configuration provided by the
    L{BrokerConfigurationHelper} to create all the components needed by
    a L{MessageExchange}.

    The following attributes will be set on your test case:

      - C{exchanger}: A L{MessageExchange} using a L{FakeReactor} and a
        L{FakeTransport}.

      - C{reactor}: The L{FakeReactor} used by the C{exchager}.

      - C{transport}: The L{FakeTransport} used by the C{exchanger}.

      - C{identity}: The L{Identity} used by the C{exchanger} and based
        on the sample configuration.

      - C{mstore}: The L{MessageStore} used by the C{exchanger} and based
        on the sample configuration.

      - C{persist}: The L{Persist} object used by C{mstore} and C{identity}.

      - C{persit_filename}: Path to the file holding the C{persist} data.
    """

    def set_up(self, test_case):
        super(ExchangeHelper, self).set_up(test_case)
        test_case.persist_filename = test_case.makePersistFile()
        test_case.persist = Persist(filename=test_case.persist_filename)
        test_case.mstore = get_default_message_store(
            test_case.persist, test_case.config.message_store_path)
        test_case.identity = Identity(test_case.config, test_case.persist)
        test_case.transport = FakeTransport(None, test_case.config.url,
                                            test_case.config.ssl_public_key)
        test_case.reactor = FakeReactor()
        test_case.exchange_store = ExchangeStore(
            test_case.config.exchange_store_path)
        test_case.exchanger = MessageExchange(
            test_case.reactor, test_case.mstore, test_case.transport,
            test_case.identity, test_case.exchange_store, test_case.config)


class RegistrationHelper(ExchangeHelper):
    """Setup a L{RegistrationHandler} instance along with its dependencies.

    This helper adds a L{RegistrationHandler} instance to L{ExchangeHelper}. If
    the test case has C{cloud} class attribute, the L{RegistrationHandler}
    will be configured for a cloud registration.

    The following attributes will be set in your test case:

      - C{handler}: A L{RegistrationHandler}.

      - C{fetch_func}: The C{fetch_async} function used by the C{handler}, it
        can be customised by test cases.
    """

    def set_up(self, test_case):
        super(RegistrationHelper, self).set_up(test_case)
        test_case.pinger = Pinger(test_case.reactor, test_case.identity,
                                  test_case.exchanger, test_case.config)

        def fetch_func(*args, **kwargs):
            return test_case.fetch_func(*args, **kwargs)

        test_case.fetch_func = fetch_async
        test_case.config.cloud = getattr(test_case, "cloud", False)
        test_case.handler = RegistrationHandler(
            test_case.config, test_case.identity, test_case.reactor,
            test_case.exchanger, test_case.pinger, test_case.mstore,
            fetch_async=fetch_func)


class BrokerServerHelper(RegistrationHelper):
    """Setup a L{BrokerServer} instance.

    This helper adds a L{BrokerServer} to the L{RegistrationHelper}.

    The following attributes will be set in your test case:

      - C{broker}: A L{BrokerServer}.
    """

    def set_up(self, test_case):
        super(BrokerServerHelper, self).set_up(test_case)
        test_case.broker = BrokerServer(test_case.config, test_case.reactor,
                                        test_case.exchanger, test_case.handler,
                                        test_case.mstore, test_case.pinger)


class RemoteBrokerHelper(BrokerServerHelper):
    """Setup a connected L{RemoteBroker}.

    This helper extends L{BrokerServerHelper}.by adding a L{RemoteBroker} which
    exposes the L{BrokerServer} instance remotely via our AMP-based machinery.

    IMPORTANT: note that the connection is created using a *real* Unix socket,
    calling L{FakeReactor.call_unix} which in turn defers to the *real* Twisted
    reactor. This means that all calls to the L{RemoteBroker} instance will
    be truly asynchronous and tests will need to return deferreds in order to
    let the reactor run. See also::

        http://twistedmatrix.com/documents/current/core/howto/testing.html

    and the "Leave the Reactor as you found it" paragraph to understand how
    to write tests interacting with the reactor.

    The following attributes will be set in your test case:

      - C{remote}: A C{RemoteObject} connected to the broker server.
    """

    def set_up(self, test_case):
        super(RemoteBrokerHelper, self).set_up(test_case)

        factory = BrokerServerProtocolFactory(object=test_case.broker)
        socket = os.path.join(test_case.config.sockets_path,
                              BrokerServer.name + ".sock")
        self._port = test_case.reactor.listen_unix(socket, factory)
        self._connector = RemoteBrokerConnector(test_case.reactor,
                                                test_case.config)

        def set_remote(remote):
            test_case.remote = remote
            return remote

        connected = self._connector.connect()
        return connected.addCallback(set_remote)

    def tear_down(self, test_case):
        self._connector.disconnect()
        self._port.stopListening()
        super(RemoteBrokerHelper, self).tear_down(test_case)


class BrokerClientHelper(RemoteBrokerHelper):
    """Setup a connected L{BrokerClient}.

    This helper adds a L{BrokerClient} connected to a L{BrokerServerHelper} via
    its C{broker} attribute, which is the L{RemoteBroker} instance setup by
    the L{RemoteBrokerHelper}.

    The following attributes will be set in your test case:

      - C{client}: A connected L{BrokerClient}.

      - C{client_reactor}: The L{FakeReactor} used by the client. Note that
        this needs to be different from the C{reactor} attribute, which is
        the L{FakeReactor} used by the L{BrokerServer}, so tests can emulate
        events firing in different processes.
    """

    def set_up(self, test_case):

        def set_client(remote):
            # The client needs its own reactor to avoid infinite loops
            # when the broker broadcasts and event
            test_case.client_reactor = FakeReactor()
            test_case.client = BrokerClient(test_case.client_reactor)
            test_case.client.broker = remote

        connected = super(BrokerClientHelper, self).set_up(test_case)
        return connected.addCallback(set_client)


class RemoteClientHelper(BrokerClientHelper):
    """Setup a connected and registered L{RemoteClient}.

    This helper extends L{BrokerClientHelper} by registering the test
    L{BrokerClient} against the L{BrokerServer} which will then be able to
    talk to it via our AMP-based machinery.
    .
    The following attributes will be set in your test case:

      - C{remote_client}: A C{RemoteClient} connected to a registered client.
    """

    def set_up(self, test_case):

        def set_remote_client(ignored):
            test_case.remote_client = test_case.broker.get_client("client")
            self._client_connector = test_case.broker.get_connector("client")

        def listen(ignored):

            factory = BrokerClientProtocolFactory(object=test_case.client)
            socket = os.path.join(test_case.config.sockets_path,
                                  test_case.client.name + ".sock")
            self._client_port = test_case.client_reactor.listen_unix(socket,
                                                                     factory)
            result = test_case.remote.register_client("client")
            return result.addCallback(set_remote_client)

        connected = super(RemoteClientHelper, self).set_up(test_case)
        return connected.addCallback(listen)

    def tear_down(self, test_case):
        self._client_connector.disconnect()
        self._client_port.stopListening()
        super(RemoteClientHelper, self).tear_down(test_case)
