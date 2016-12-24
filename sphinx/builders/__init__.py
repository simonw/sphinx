# -*- coding: utf-8 -*-
"""
    sphinx.builders
    ~~~~~~~~~~~~~~~

    Builder superclass for all builders.

    :copyright: Copyright 2007-2016 by the Sphinx team, see AUTHORS.
    :license: BSD, see LICENSE for details.
"""

import os
from os import path

try:
    import multiprocessing
except ImportError:
    multiprocessing = None

from docutils import nodes

from sphinx.util import i18n, path_stabilize, logging
from sphinx.util.osutil import SEP, relative_uri
from sphinx.util.i18n import find_catalog
from sphinx.util.console import bold, darkgreen  # type: ignore
from sphinx.util.parallel import ParallelTasks, SerialTasks, make_chunks, \
    parallel_available

# side effect: registers roles and directives
from sphinx import roles       # noqa
from sphinx import directives  # noqa

if False:
    # For type annotation
    from typing import Any, Callable, Iterable, Sequence, Tuple, Union  # NOQA
    from sphinx.application import Sphinx  # NOQA
    from sphinx.config import Config  # NOQA
    from sphinx.environment import BuildEnvironment  # NOQA
    from sphinx.util.i18n import CatalogInfo  # NOQA
    from sphinx.util.tags import Tags  # NOQA


logger = logging.getLogger(__name__)


class Builder(object):
    """
    Builds target formats from the reST sources.
    """

    # builder's name, for the -b command line options
    name = ''
    # builder's output format, or '' if no document output is produced
    format = ''
    # doctree versioning method
    versioning_method = 'none'
    versioning_compare = False
    # allow parallel write_doc() calls
    allow_parallel = False

    def __init__(self, app):
        # type: (Sphinx) -> None
        self.env = app.env          # type: BuildEnvironment
        self.env.set_versioning_method(self.versioning_method,
                                       self.versioning_compare)
        self.srcdir = app.srcdir
        self.confdir = app.confdir
        self.outdir = app.outdir
        self.doctreedir = app.doctreedir
        if not path.isdir(self.doctreedir):
            os.makedirs(self.doctreedir)

        self.app = app              # type: Sphinx
        self.warn = app.warn        # type: Callable
        self.info = app.info        # type: Callable
        self.config = app.config    # type: Config
        self.tags = app.tags        # type: Tags
        self.tags.add(self.format)
        self.tags.add(self.name)
        self.tags.add("format_%s" % self.format)
        self.tags.add("builder_%s" % self.name)
        # compatibility aliases
        self.status_iterator = app.status_iterator
        self.old_status_iterator = app.old_status_iterator

        # images that need to be copied over (source -> dest)
        self.images = {}  # type: Dict[unicode, unicode]
        # basename of images directory
        self.imagedir = ""
        # relative path to image directory from current docname (used at writing docs)
        self.imgpath = ""

        # these get set later
        self.parallel_ok = False
        self.finish_tasks = None  # type: Any

        # load default translator class
        self.translator_class = app._translators.get(self.name)

        self.init()

    # helper methods
    def init(self):
        # type: () -> None
        """Load necessary templates and perform initialization.  The default
        implementation does nothing.
        """
        pass

    def create_template_bridge(self):
        # type: () -> None
        """Return the template bridge configured."""
        if self.config.template_bridge:
            self.templates = self.app.import_object(
                self.config.template_bridge, 'template_bridge setting')()
        else:
            from sphinx.jinja2glue import BuiltinTemplateLoader
            self.templates = BuiltinTemplateLoader()

    def get_target_uri(self, docname, typ=None):
        # type: (unicode, unicode) -> unicode
        """Return the target URI for a document name.

        *typ* can be used to qualify the link characteristic for individual
        builders.
        """
        raise NotImplementedError

    def get_relative_uri(self, from_, to, typ=None):
        # type: (unicode, unicode, unicode) -> unicode
        """Return a relative URI between two source filenames.

        May raise environment.NoUri if there's no way to return a sensible URI.
        """
        return relative_uri(self.get_target_uri(from_),
                            self.get_target_uri(to, typ))

    def get_outdated_docs(self):
        # type: () -> Union[unicode, Iterable[unicode]]
        """Return an iterable of output files that are outdated, or a string
        describing what an update build will build.

        If the builder does not output individual files corresponding to
        source files, return a string here.  If it does, return an iterable
        of those files that need to be written.
        """
        raise NotImplementedError

    supported_image_types = []  # type: List[unicode]

    def post_process_images(self, doctree):
        # type: (nodes.Node) -> None
        """Pick the best candidate for all image URIs."""
        for node in doctree.traverse(nodes.image):
            if '?' in node['candidates']:
                # don't rewrite nonlocal image URIs
                continue
            if '*' not in node['candidates']:
                for imgtype in self.supported_image_types:
                    candidate = node['candidates'].get(imgtype, None)
                    if candidate:
                        break
                else:
                    logger.warn_node('no matching candidate for image URI %r' % node['uri'],
                                     node)
                    continue
                node['uri'] = candidate
            else:
                candidate = node['uri']
            if candidate not in self.env.images:
                # non-existing URI; let it alone
                continue
            self.images[candidate] = self.env.images[candidate][1]

    # compile po methods

    def compile_catalogs(self, catalogs, message):
        # type: (Set[CatalogInfo], unicode) -> None
        if not self.config.gettext_auto_build:
            return

        def cat2relpath(cat):
            return path.relpath(cat.mo_path, self.env.srcdir).replace(path.sep, SEP)

        logger.info(bold('building [mo]: ') + message)
        for catalog in self.app.status_iterator(
                catalogs, 'writing output... ', darkgreen, len(catalogs),
                cat2relpath):
            catalog.write_mo(self.config.language)

    def compile_all_catalogs(self):
        # type: () -> None
        catalogs = i18n.find_catalog_source_files(
            [path.join(self.srcdir, x) for x in self.config.locale_dirs],
            self.config.language,
            charset=self.config.source_encoding,
            gettext_compact=self.config.gettext_compact,
            force_all=True)
        message = 'all of %d po files' % len(catalogs)
        self.compile_catalogs(catalogs, message)

    def compile_specific_catalogs(self, specified_files):
        # type: (List[unicode]) -> None
        def to_domain(fpath):
            docname, _ = path.splitext(path_stabilize(fpath))
            dom = find_catalog(docname, self.config.gettext_compact)
            return dom

        specified_domains = set(map(to_domain, specified_files))
        catalogs = i18n.find_catalog_source_files(
            [path.join(self.srcdir, x) for x in self.config.locale_dirs],
            self.config.language,
            domains=list(specified_domains),
            charset=self.config.source_encoding,
            gettext_compact=self.config.gettext_compact)
        message = 'targets for %d po files that are specified' % len(catalogs)
        self.compile_catalogs(catalogs, message)

    def compile_update_catalogs(self):
        # type: () -> None
        catalogs = i18n.find_catalog_source_files(
            [path.join(self.srcdir, x) for x in self.config.locale_dirs],
            self.config.language,
            charset=self.config.source_encoding,
            gettext_compact=self.config.gettext_compact)
        message = 'targets for %d po files that are out of date' % len(catalogs)
        self.compile_catalogs(catalogs, message)

    # build methods

    def build_all(self):
        # type: () -> None
        """Build all source files."""
        self.build(None, summary='all source files', method='all')

    def build_specific(self, filenames):
        # type: (List[unicode]) -> None
        """Only rebuild as much as needed for changes in the *filenames*."""
        # bring the filenames to the canonical format, that is,
        # relative to the source directory and without source_suffix.
        dirlen = len(self.srcdir) + 1
        to_write = []
        suffixes = None  # type: Tuple[unicode]
        suffixes = tuple(self.config.source_suffix)  # type: ignore
        for filename in filenames:
            filename = path.normpath(path.abspath(filename))
            if not filename.startswith(self.srcdir):
                logger.warning('file %r given on command line is not under the '
                               'source directory, ignoring', filename)
                continue
            if not (path.isfile(filename) or
                    any(path.isfile(filename + suffix) for suffix in suffixes)):
                logger.warning('file %r given on command line does not exist, '
                               'ignoring', filename)
                continue
            filename = filename[dirlen:]
            for suffix in suffixes:
                if filename.endswith(suffix):
                    filename = filename[:-len(suffix)]
                    break
            filename = filename.replace(path.sep, SEP)
            to_write.append(filename)
        self.build(to_write, method='specific',
                   summary='%d source files given on command '
                   'line' % len(to_write))

    def build_update(self):
        # type: () -> None
        """Only rebuild what was changed or added since last build."""
        to_build = self.get_outdated_docs()
        if isinstance(to_build, str):
            self.build(['__all__'], to_build)
        else:
            to_build = list(to_build)
            self.build(to_build,
                       summary='targets for %d source files that are '
                       'out of date' % len(to_build))

    def build(self, docnames, summary=None, method='update'):
        # type: (Iterable[unicode], unicode, unicode) -> None
        """Main build method.

        First updates the environment, and then calls :meth:`write`.
        """
        if summary:
            logger.info(bold('building [%s]' % self.name) + ': ' + summary)

        # while reading, collect all warnings from docutils
        with logging.pending_warnings():
            updated_docnames = set(self.env.update(self.config, self.srcdir,
                                                   self.doctreedir, self.app))

        doccount = len(updated_docnames)
        logger.info(bold('looking for now-outdated files... '), nonl=1)
        for docname in self.env.check_dependents(updated_docnames):
            updated_docnames.add(docname)
        outdated = len(updated_docnames) - doccount
        if outdated:
            logger.info('%d found', outdated)
        else:
            logger.info('none found')

        if updated_docnames:
            # save the environment
            from sphinx.application import ENV_PICKLE_FILENAME
            logger.info(bold('pickling environment... '), nonl=True)
            self.env.topickle(path.join(self.doctreedir, ENV_PICKLE_FILENAME))
            logger.info('done')

            # global actions
            logger.info(bold('checking consistency... '), nonl=True)
            self.env.check_consistency()
            logger.info('done')
        else:
            if method == 'update' and not docnames:
                logger.info(bold('no targets are out of date.'))
                return

        # filter "docnames" (list of outdated files) by the updated
        # found_docs of the environment; this will remove docs that
        # have since been removed
        if docnames and docnames != ['__all__']:
            docnames = set(docnames) & self.env.found_docs

        # determine if we can write in parallel
        self.parallel_ok = False
        if parallel_available and self.app.parallel > 1 and self.allow_parallel:
            self.parallel_ok = True
            for extname, md in self.app._extension_metadata.items():
                par_ok = md.get('parallel_write_safe', True)
                if not par_ok:
                    logger.warning('the %s extension is not safe for parallel '
                                   'writing, doing serial write', extname)
                    self.parallel_ok = False
                    break

        #  create a task executor to use for misc. "finish-up" tasks
        # if self.parallel_ok:
        #     self.finish_tasks = ParallelTasks(self.app.parallel)
        # else:
        # for now, just execute them serially
        self.finish_tasks = SerialTasks()

        # write all "normal" documents (or everything for some builders)
        self.write(docnames, list(updated_docnames), method)

        # finish (write static files etc.)
        self.finish()

        # wait for all tasks
        self.finish_tasks.join()

    def write(self, build_docnames, updated_docnames, method='update'):
        # type: (Iterable[unicode], Sequence[unicode], unicode) -> None
        if build_docnames is None or build_docnames == ['__all__']:
            # build_all
            build_docnames = self.env.found_docs
        if method == 'update':
            # build updated ones as well
            docnames = set(build_docnames) | set(updated_docnames)
        else:
            docnames = set(build_docnames)
        logger.debug('docnames to write: %s', ', '.join(sorted(docnames)))

        # add all toctree-containing files that may have changed
        for docname in list(docnames):
            for tocdocname in self.env.files_to_rebuild.get(docname, []):
                if tocdocname in self.env.found_docs:
                    docnames.add(tocdocname)
        docnames.add(self.config.master_doc)

        logger.info(bold('preparing documents... '), nonl=True)
        self.prepare_writing(docnames)
        logger.info('done')

        if self.parallel_ok:
            # number of subprocesses is parallel-1 because the main process
            # is busy loading doctrees and doing write_doc_serialized()
            self._write_parallel(sorted(docnames),
                                 nproc=self.app.parallel - 1)
        else:
            self._write_serial(sorted(docnames))

    def _write_serial(self, docnames):
        # type: (Sequence[unicode]) -> None
        with logging.pending_warnings():
            for docname in self.app.status_iterator(
                    docnames, 'writing output... ', darkgreen, len(docnames)):
                doctree = self.env.get_and_resolve_doctree(docname, self)
                self.write_doc_serialized(docname, doctree)
                self.write_doc(docname, doctree)

    def _write_parallel(self, docnames, nproc):
        # type: (Iterable[unicode], int) -> None
        def write_process(docs):
            # type: (List[Tuple[unicode, nodes.Node]]) -> None
            for docname, doctree in docs:
                self.write_doc(docname, doctree)

        # warm up caches/compile templates using the first document
        firstname, docnames = docnames[0], docnames[1:]  # type: ignore
        doctree = self.env.get_and_resolve_doctree(firstname, self)
        self.write_doc_serialized(firstname, doctree)
        self.write_doc(firstname, doctree)

        tasks = ParallelTasks(nproc)
        chunks = make_chunks(docnames, nproc)

        for chunk in self.app.status_iterator(
                chunks, 'writing output... ', darkgreen, len(chunks)):
            arg = []
            for i, docname in enumerate(chunk):
                doctree = self.env.get_and_resolve_doctree(docname, self)
                self.write_doc_serialized(docname, doctree)
                arg.append((docname, doctree))
            tasks.add_task(write_process, arg)

        # make sure all threads have finished
        logger.info(bold('waiting for workers...'))
        tasks.join()

    def prepare_writing(self, docnames):
        # type: (Set[unicode]) -> None
        """A place where you can add logic before :meth:`write_doc` is run"""
        raise NotImplementedError

    def write_doc(self, docname, doctree):
        # type: (unicode, nodes.Node) -> None
        """Where you actually write something to the filesystem."""
        raise NotImplementedError

    def write_doc_serialized(self, docname, doctree):
        # type: (unicode, nodes.Node) -> None
        """Handle parts of write_doc that must be called in the main process
        if parallel build is active.
        """
        pass

    def finish(self):
        # type: () -> None
        """Finish the building process.

        The default implementation does nothing.
        """
        pass

    def cleanup(self):
        # type: () -> None
        """Cleanup any resources.

        The default implementation does nothing.
        """
        pass

    def get_builder_config(self, option, default):
        # type: (unicode, unicode) -> Any
        """Return a builder specific option.

        This method allows customization of common builder settings by
        inserting the name of the current builder in the option key.
        If the key does not exist, use default as builder name.
        """
        # At the moment, only XXX_use_index is looked up this way.
        # Every new builder variant must be registered in Config.config_values.
        try:
            optname = '%s_%s' % (self.name, option)
            return getattr(self.config, optname)
        except AttributeError:
            optname = '%s_%s' % (default, option)
            return getattr(self.config, optname)
