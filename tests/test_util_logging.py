# -*- coding: utf-8 -*-
"""
    test_util_logging
    ~~~~~~~~~~~~~~~~~

    Test logging util.

    :copyright: Copyright 2007-2016 by the Sphinx team, see AUTHORS.
    :license: BSD, see LICENSE for details.
"""
from __future__ import print_function

import codecs
from docutils import nodes

from sphinx.errors import SphinxWarning
from sphinx.util import logging
from sphinx.util.console import colorize
from sphinx.util.logging import is_suppressed_warning
from sphinx.util.parallel import ParallelTasks

from util import with_app, raises, strip_escseq


@with_app()
def test_info_and_warning(app, status, warning):
    app.verbosity = 3
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    logger.debug('message1')
    logger.info('message2')
    logger.warning('message3')
    logger.critical('message4')
    logger.error('message5')

    assert 'message1' in status.getvalue()
    assert 'message2' in status.getvalue()
    assert 'message3' not in status.getvalue()
    assert 'message4' not in status.getvalue()
    assert 'message5' not in status.getvalue()

    assert 'message1' not in warning.getvalue()
    assert 'message2' not in warning.getvalue()
    assert 'message3' in warning.getvalue()
    assert 'message4' in warning.getvalue()
    assert 'message5' in warning.getvalue()


@with_app()
def test_verbosity_filter(app, status, warning):
    # verbosity = 0: INFO
    app.verbosity = 0
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    logger.info('message1')
    logger.verbose('message2')
    logger.debug('message3')
    logger.debug2('message4')

    assert 'message1' in status.getvalue()
    assert 'message2' not in status.getvalue()
    assert 'message3' not in status.getvalue()
    assert 'message4' not in status.getvalue()

    # verbosity = 1: VERBOSE
    app.verbosity = 1
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    logger.info('message1')
    logger.verbose('message2')
    logger.debug('message3')
    logger.debug2('message4')

    assert 'message1' in status.getvalue()
    assert 'message2' in status.getvalue()
    assert 'message3' not in status.getvalue()
    assert 'message4' not in status.getvalue()

    # verbosity = 2: DEBUG
    app.verbosity = 2
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    logger.info('message1')
    logger.verbose('message2')
    logger.debug('message3')
    logger.debug2('message4')

    assert 'message1' in status.getvalue()
    assert 'message2' in status.getvalue()
    assert 'message3' in status.getvalue()
    assert 'message4' not in status.getvalue()

    # verbosity = 3: DEBUG2
    app.verbosity = 3
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    logger.info('message1')
    logger.verbose('message2')
    logger.debug('message3')
    logger.debug2('message4')

    assert 'message1' in status.getvalue()
    assert 'message2' in status.getvalue()
    assert 'message3' in status.getvalue()
    assert 'message4' in status.getvalue()


@with_app()
def test_nonl_info_log(app, status, warning):
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    logger.info('message1', nonl=True)
    logger.info('message2')
    logger.info('message3')

    assert 'message1message2\nmessage3' in status.getvalue()


def test_is_suppressed_warning():
    suppress_warnings = ["ref", "files.*", "rest.duplicated_labels"]

    assert is_suppressed_warning(None, None, suppress_warnings) is False
    assert is_suppressed_warning("ref", None, suppress_warnings) is True
    assert is_suppressed_warning("ref", "numref", suppress_warnings) is True
    assert is_suppressed_warning("ref", "option", suppress_warnings) is True
    assert is_suppressed_warning("files", "image", suppress_warnings) is True
    assert is_suppressed_warning("files", "stylesheet", suppress_warnings) is True
    assert is_suppressed_warning("rest", "syntax", suppress_warnings) is False
    assert is_suppressed_warning("rest", "duplicated_labels", suppress_warnings) is True


@with_app()
def test_suppress_warnings(app, status, warning):
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    app._warncount = 0  # force reset

    app.config.suppress_warnings = []
    warning.truncate(0)
    logger.warning('message1', type='test', subtype='logging')
    logger.warning('message2', type='test', subtype='crash')
    logger.warning('message3', type='actual', subtype='logging')
    assert 'message1' in warning.getvalue()
    assert 'message2' in warning.getvalue()
    assert 'message3' in warning.getvalue()
    assert app._warncount == 3

    app.config.suppress_warnings = ['test']
    warning.truncate(0)
    logger.warning('message1', type='test', subtype='logging')
    logger.warning('message2', type='test', subtype='crash')
    logger.warning('message3', type='actual', subtype='logging')
    assert 'message1' not in warning.getvalue()
    assert 'message2' not in warning.getvalue()
    assert 'message3' in warning.getvalue()
    assert app._warncount == 4

    app.config.suppress_warnings = ['test.logging']
    warning.truncate(0)
    logger.warning('message1', type='test', subtype='logging')
    logger.warning('message2', type='test', subtype='crash')
    logger.warning('message3', type='actual', subtype='logging')
    assert 'message1' not in warning.getvalue()
    assert 'message2' in warning.getvalue()
    assert 'message3' in warning.getvalue()
    assert app._warncount == 6


@with_app()
def test_warningiserror(app, status, warning):
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    # if False, warning is not error
    app.warningiserror = False
    logger.warning('message')

    # if True, warning raises SphinxWarning exception
    app.warningiserror = True
    raises(SphinxWarning, logger.warning, 'message')


@with_app()
def test_warning_location(app, status, warning):
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    logger.warning('message1', location='index')
    assert 'index.txt: WARNING: message1' in warning.getvalue()

    logger.warning('message2', location=('index', 10))
    assert 'index.txt:10: WARNING: message2' in warning.getvalue()

    logger.warning('message3', location=None)
    assert '\x1b[31mWARNING: message3' in warning.getvalue()  # \x1b[31m = darkred


@with_app()
def test_warn_node(app, status, warning):
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    node = nodes.Node()
    node.source, node.line = ('index.txt', 10)
    logger.warn_node('message1', node)
    assert 'index.txt:10: WARNING: message1' in warning.getvalue()

    node.source, node.line = ('index.txt', None)
    logger.warn_node('message2', node)
    assert 'index.txt:: WARNING: message2' in warning.getvalue()

    node.source, node.line = (None, 10)
    logger.warn_node('message3', node)
    assert '<unknown>:10: WARNING: message3' in warning.getvalue()

    node.source, node.line = (None, None)
    logger.warn_node('message4', node)
    assert '\x1b[31mWARNING: message4' in warning.getvalue()  # \x1b[31m = darkred


@with_app()
def test_pending_warnings(app, status, warning):
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    logger.warning('message1')
    with logging.pending_warnings():
        # not logged yet (bufferred) in here
        logger.warning('message2')
        logger.warning('message3')
        assert 'WARNING: message1' in warning.getvalue()
        assert 'WARNING: message2' not in warning.getvalue()
        assert 'WARNING: message3' not in warning.getvalue()

    # actually logged as ordered
    assert 'WARNING: message2\nWARNING: message3' in strip_escseq(warning.getvalue())


@with_app()
def test_colored_logs(app, status, warning):
    app.verbosity = 3
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    # default colors
    logger.debug2('message1')
    logger.debug('message2')
    logger.verbose('message3')
    logger.info('message4')
    logger.warning('message5')
    logger.critical('message6')
    logger.error('message7')

    assert colorize('lightgray', 'message1') in status.getvalue()
    assert colorize('darkgray', 'message2') in status.getvalue()
    assert 'message3\n' in status.getvalue()  # not colored
    assert 'message4\n' in status.getvalue()  # not colored
    assert colorize('darkred', 'WARNING: message5') in warning.getvalue()
    assert 'WARNING: message6\n' in warning.getvalue()  # not colored
    assert 'WARNING: message7\n' in warning.getvalue()  # not colored

    # color specification
    logger.debug('message8', color='white')
    logger.info('message9', color='red')
    assert colorize('white', 'message8') in status.getvalue()
    assert colorize('red', 'message9') in status.getvalue()


@with_app()
def test_logging_in_ParallelTasks(app, status, warning):
    logging.setup(app, status, warning)
    logger = logging.getLogger(__name__)

    def child_process():
        logger.info('message1')
        logger.warning('message2', location='index')

    tasks = ParallelTasks(1)
    tasks.add_task(child_process)
    tasks.join()
    assert 'message1' in status.getvalue()
    assert 'index.txt: WARNING: message2' in warning.getvalue()


@with_app()
def test_output_with_unencodable_char(app, status, warning):
    class StreamWriter(codecs.StreamWriter):
        def write(self, object):
            self.stream.write(object.encode('cp1252').decode('cp1252'))

    logging.setup(app, StreamWriter(status), warning)
    logger = logging.getLogger(__name__)

    # info with UnicodeEncodeError
    status.truncate(0)
    status.seek(0)
    logger.info(u"unicode \u206d...")
    assert status.getvalue() == "unicode ?...\n"
