import signal
import os
import sys
import pwd

from logging import (getLevelName, getLogger,
                     FileHandler, StreamHandler, Formatter, info)

from optparse import OptionParser
from ConfigParser import ConfigParser, NoSectionError

import dbus.glib # Side-effects rule!

from twisted.application.service import Application, Service
from twisted.application.app import startApplication

from landscape import VERSION
from landscape.lib.persist import Persist
from landscape.lib.dbus_util import get_bus
from landscape.lib import bpickle_dbus
from landscape.log import rotate_logs
from landscape.reactor import TwistedReactor

from landscape.upgraders import UPGRADE_MANAGERS


def init_logging(configuration, program_name):
    """Given a basic configuration, set up logging."""
    handlers = []
    if not os.path.exists(configuration.log_dir):
        os.makedirs(configuration.log_dir)
    log_filename = os.path.join(configuration.log_dir, program_name+".log")
    handlers.append(FileHandler(log_filename))
    if not configuration.quiet:
        handlers.append(StreamHandler(sys.stdout))
    getLogger().setLevel(getLevelName(configuration.log_level.upper()))
    for handler in handlers:
        getLogger().addHandler(handler)
        format = ("%(asctime)s %(levelname)-8s [%(threadName)-10s] "
                  "%(message)s")
        handler.setFormatter(Formatter(format))


class BaseConfiguration(object):
    """Base class for configuration implementations.

    @cvar required_options: Optionally, a sequence of key names to require when
        reading or writing a configuration.
    @cvar unsaved_options: Optionally, a sequence of key names to never write
        to the configuration file.  This is useful when you want to provide
        command-line options that should never end up in a configuration file.
    @cvar default_config_filenames: A sequence of filenames to check when
        reading or writing a configuration.
    """

    required_options = ()
    unsaved_options = ()
    default_config_filenames = ["/etc/landscape/client.conf"]
    if (os.path.dirname(os.path.abspath(sys.argv[0]))
        == os.path.abspath("scripts")):
        default_config_filenames.insert(0, "landscape-client.conf")
    default_config_filenames = tuple(default_config_filenames)
    config_section = "client"

    def __init__(self):
        """Default configuration.

        Default values for supported options are set as in L{make_parser}.
        """
        self._set_options = {}
        self._command_line_args = []
        self._command_line_options = {}
        self._config_filename = None
        self._config_file_options = {}
        self._parser = self.make_parser()
        self._command_line_defaults = self._parser.defaults.copy()
        # We don't want them mixed with explicitly given options,
        # otherwise we can't define the precedence properly.
        self._parser.defaults.clear()

    def __getattr__(self, name):
        """Find and return the value of the given configuration parameter.

        The following sources will be searched:
          - The attributes that were explicitly set on this object,
          - The parameters specified on the command line,
          - The parameters specified in the configuration file, and
          - The defaults.

        If no values are found and the parameter does exist as a possible
        parameter, C{None} is returned.

        Otherwise C{AttributeError} is raised.
        """
        for options in [self._set_options,
                        self._command_line_options,
                        self._config_file_options,
                        self._command_line_defaults]:
            if name in options:
                value = options[name]
                break
        else:
            if self._parser.has_option("--" + name.replace("_", "-")):
                value = None
            else:
                raise AttributeError(name)
        if isinstance(value, basestring):
            option = self._parser.get_option("--" + name.replace("_", "-"))
            if option is not None:
                value = option.convert_value(None, value)
        return value

    def get(self, name, default=None):
        """Return the value of the C{name} option or C{default}."""
        try:
            return self.__getattr__(name)
        except AttributeError:
            return default

    def __setattr__(self, name, value):
        """Set a configuration parameter.

        If the name begins with C{_}, it will only be set on this object and
        not stored in the configuration file.
        """
        if name.startswith("_"):
            super(BaseConfiguration, self).__setattr__(name, value)
        else:
            self._set_options[name] = value

    def reload(self):
        """Reload options using the configured command line arguments.

        @see: L{load_command_line}
        """
        self.load(self._command_line_args)

    def load(self, args, accept_nonexistent_config=False):
        """
        Load configuration data from command line arguments and a config file.

        @raise: A SystemExit if the arguments are bad.
        """
        self.load_command_line(args)

        # Parse configuration file, if found.
        if self.config:
            if os.path.isfile(self.config):
                self.load_configuration_file(self.config)
            elif not accept_nonexistent_config:
                sys.exit("error: file not found: %s" % self.config)
        else:
            for potential_config_file in self.default_config_filenames:
                if os.access(potential_config_file, os.R_OK):
                    self.load_configuration_file(potential_config_file)
                    break

        self._load_external_options()

        # Check that all needed options were given.
        for option in self.required_options:
            if not getattr(self, option):
                sys.exit("error: must specify --%s "
                         "or the '%s' directive in the config file."
                         % (option.replace('_','-'), option))

        if self.bus not in ("session", "system"):
            sys.exit("error: bus must be one of 'session' or 'system'")

    def _load_external_options(self):
        """Hook for loading options from elsewhere (e.g. for --import)."""

    def load_command_line(self, args):
        """Load configuration data from the given command line."""
        self._command_line_args = args
        values = self._parser.parse_args(args)[0]
        self._command_line_options = vars(values)

    def load_configuration_file(self, filename):
        """Load configuration data from the given file name.

        If any data has already been set on this configuration object,
        then the old data will take precedence.
        """
        self._config_filename = filename
        config_parser = ConfigParser()
        config_parser.read(filename)
        try:
            self._config_file_options = dict(
                config_parser.items(self.config_section))
        except NoSectionError:
            pass

    def write(self):
        """Write back configuration to the configuration file.

        Values which match the default option in the parser won't be saved.

        Options are considered in the following precedence:

          1. Manually set options (C{config.option = value})
          2. Options passed in the command line
          3. Previously existent options in the configuration file

        The filename picked for saving configuration options is the one
        returned by L{get_config_filename}.
        """
        # The filename we'll write to
        filename = self.get_config_filename()

        config_parser = ConfigParser()
        # Make sure we read the old values from the config file so that we
        # don't remove *unrelated* values.
        config_parser.read(filename)
        if not config_parser.has_section(self.config_section):
            config_parser.add_section(self.config_section)
        all_options = self._config_file_options.copy()
        all_options.update(self._command_line_options)
        all_options.update(self._set_options)
        for name, value in all_options.items():
            if (name != "config" and
                name not in self.unsaved_options):
                if value == self._command_line_defaults.get(name):
                    config_parser.remove_option(self.config_section, name)
                else:
                    config_parser.set(self.config_section, name, value)
        config_file = open(filename, "w")
        config_parser.write(config_file)
        config_file.close()

    def make_parser(self):
        """Parser factory for supported options

        @return: An L{OptionParser} preset with options that all
            landscape-related programs accept. These include
              - C{config} (C{None})
              - C{bus} (C{system})
        """
        parser = OptionParser(version=VERSION)
        parser.add_option("-c", "--config", metavar="FILE",
                          help="Use config from this file (any command line "
                               "options override settings from the file) "
                               "(default: '/etc/landscape/client.conf').")
        parser.add_option("--bus", default="system",
                          help="Which DBUS bus to use. One of 'session' "
                               "or 'system' (default: 'system').")
        return parser

    def get_config_filename(self):
        """Pick the proper configuration file.

        The picked filename is:
          1. C{self.config}, if defined
          2. The last loaded configuration file, if any
          3. The first filename in C{self.default_config_filenames}
        """
        if self.config:
            return self.config
        if self._config_filename:
            return self._config_filename
        if self.default_config_filenames:
            for potential_config_file in self.default_config_filenames:
                if os.access(potential_config_file, os.R_OK):
                    return potential_config_file
            return self.default_config_filenames[0]
        return None

    def get_command_line_options(self):
        """Get currently loaded command line options.

        @see: L{load_command_line}
        """
        return self._command_line_options


class Configuration(BaseConfiguration):
    """Configuration data for Landscape client.

    This contains all simple data, some of it calculated.
    """

    @property
    def hashdb_filename(self):
        return os.path.join(self.data_path, "hash.db")

    def make_parser(self):
        """Parser factory for supported options.

        @return: An L{OptionParser} preset for all options
            from L{BaseConfiguration.make_parser} plus:
              - C{data_path} (C{"/var/lib/landscape/client/"})
              - C{quiet} (C{False})
              - C{log_dir} (C{"/var/log/landscape"})
              - C{log_level} (C{"info"})
              - C{ignore_sigint} (C{False})
        """
        parser = super(Configuration, self).make_parser()
        parser.add_option("-d", "--data-path", metavar="PATH",
                          default="/var/lib/landscape/client/",
                          help="The directory to store data files in "
                          "(default: '/var/lib/landscape/client/').")
        parser.add_option("-q", "--quiet", default=False, action="store_true",
                          help="Do not log to the standard output.")
        parser.add_option("-l", "--log-dir", metavar="FILE",
                          help="The directory to write log files to "
                          "(default: '/var/log/landscape').",
                          default="/var/log/landscape")
        parser.add_option("--log-level", default="info",
                          help="One of debug, info, warning, error or "
                               "critical.")
        parser.add_option("--ignore-sigint", action="store_true", default=False,
                          help="Ignore interrupt signals.")
        parser.add_option("--ignore-sigusr1", action="store_true", default=False,
                          help="Ignore SIGUSR1 signal to rotate logs.")

        return parser


def get_versioned_persist(service):
    """Get a L{Persist} database with upgrade rules applied.

    Load a L{Persist} database for the given C{service} and upgrade or
    mark as current, as necessary.
    """
    persist = Persist(filename=service.persist_filename)
    upgrade_manager = UPGRADE_MANAGERS[service.service_name]
    if os.path.exists(service.persist_filename):
        upgrade_manager.apply(persist)
    else:
        upgrade_manager.initialize(persist)
    persist.save(service.persist_filename)
    return persist


class LandscapeService(Service, object):
    """Utility superclass for defining Landscape services.

    This sets up the reactor, bpickle/dbus integration, a Persist object, and
    connects to the bus when started.

    @ivar reactor: a L{TwistedReactor} object.
    @cvar service_name: The lower-case name of the service. This is used to
        generate the bpickle filename.
    """
    reactor_factory = TwistedReactor
    persist_filename = None

    def __init__(self, config):
        self.config = config
        bpickle_dbus.install()
        self.reactor = self.reactor_factory()
        if self.persist_filename:
            self.persist = get_versioned_persist(self)
        if not (self.config is not None and self.config.ignore_sigusr1):
            signal.signal(signal.SIGUSR1, lambda signal, frame: rotate_logs())

    def startService(self):
        """Extend L{twisted.application.service.IService.startService}.

        Create a a new DBus connection (normally using a C{SystemBus}) and
        save it in the public L{self.bus} instance variable.
        """
        Service.startService(self)
        self.bus = get_bus(self.config.bus)
        info("%s started on '%s' bus with config %s" % (
                self.service_name.capitalize(), self.config.bus,
                self.config.get_config_filename()))

    def stopService(self):
        Service.stopService(self)
        info("%s stopped on '%s' bus with config %s" % (
                self.service_name.capitalize(), self.config.bus,
                self.config.get_config_filename()))


def assert_unowned_bus_name(bus, bus_name):
    dbus_object = bus.get_object("org.freedesktop.DBus",
                                 "/org/freedesktop/DBus")
    if dbus_object.NameHasOwner(bus_name,
                                dbus_interface="org.freedesktop.DBus"):
        sys.exit("error: DBus name %s is owned. "
                 "Is the process already running?" % bus_name)


_required_users = {
    "broker": "landscape",
    "monitor": "landscape",
    "manager": "root"}


def run_landscape_service(configuration_class, service_class, args, bus_name):
    """Run a Landscape service.

    The function will instantiate the given L{LandscapeService} subclass
    and attach the resulting service object to a Twisted C{Application}.

    After that it will start the Twisted L{Application} and call the
    L{TwistedReactor.run} method of the L{LandscapeService}'s reactor.

    @param configuration_class: The service-specific subclass of L{Configuration} used
        to parse C{args} and build the C{service_class} object.
    @param service_class: The L{LandscapeService} subclass to create and start.
    @param args: Command line arguments.
    @param bus_name: A bus name used to verify if the service is already
        running.
    """
    from landscape.reactor import install
    install()

    # Let's consider adding this:
#     from twisted.python.log import startLoggingWithObserver, PythonLoggingObserver
#     startLoggingWithObserver(PythonLoggingObserver().emit, setStdout=False)

    configuration = configuration_class()
    configuration.load(args)

    if configuration.bus == "system":
        required_user = _required_users[service_class.service_name]
        if required_user != pwd.getpwuid(os.getuid())[0]:
            sys.exit(
                "When using the system bus, landscape-%s must be run as %s."
                % (service_class.service_name, required_user))

    init_logging(configuration, service_class.service_name)

    assert_unowned_bus_name(get_bus(configuration.bus), bus_name)

    application = Application("landscape-%s" % (service_class.service_name,))
    service = service_class(configuration)
    service.setServiceParent(application)

    startApplication(application, False)

    if configuration.ignore_sigint:
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    service.reactor.run()
