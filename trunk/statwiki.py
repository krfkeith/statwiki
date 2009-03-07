#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-
"""
    StatWiki - Static Wiki based on MoinMoin

    @copyright: 2007 by José Fonseca, 2009 by Arkadiusz Wahlig
    @license: GNU GPL, see COPYING for details.
"""


__version__ = '0.85.0'
__date__ = '7.03.2009'


import sys, os
import codecs
import time
from StringIO import StringIO
from optparse import OptionParser
import pickle

import config
import formatter
import wikiparser
import wikiutil


def read(filename):
    return codecs.open(filename, 'rt', encoding=config.charset).read()


class Pragmas(object):
    '''This class keeps dictionaries of all pragmas of all wiki pages. There are
    two such dictionaries, one contains pragmas saved to a _statwiki.pragmas file
    during previous StatWiki run, the other keeps pragmas for files that were
    changed or added since the last run.
    
    This makes it possible to quicky scan all pages for a particullar pragmas.
    Having the state from the last StatWiki run makes it possible to access removed/
    replaced pragmas and update relevant pages accordingly.
    
    Pragmas are represented by wikiparser.PragmaParser objects.
    
    XXX: This is a simple way to manage relationships between pages but it won't
    scale well!
    '''
    
    def __init__(self, force_update=[]):
        try:
            self.old = pickle.load(open('_statwiki.pragmas', 'rb'))
        except IOError:
            self.old = {}
        self.new = {}
        for filename in os.listdir('.'):
            if filename.endswith('.wiki') and (filename not in self.old or
                    os.path.getmtime(filename) > self.old[filename].mtime or
                    filename in force_update):
                pp = wikiparser.PragmaParser(read(filename))
                pp.mtime = os.path.getmtime(filename)
                self.new[filename] = pp
        
    def __del__(self):
        if self.new:
            pickle.dump(self.full(), open('_statwiki.pragmas', 'wb'), 2)

    def full(self):
        '''Returns a dictionary of current pragmas.'''
        all = self.old.copy()
        all.update(self.new)
        return all

    def items(self):
        '''Returns a list of (filename, PragmaParser-object) tuples representing
        current pragmas.'''
        return self.full().items()
        
    def previous_items(self):
        '''Returns a list of (filename, PragmaParser-object) tuples representing
        previous pragmas.'''
        return self.old.items()

    def __getitem__(self, filename):
        #return self.full()[filename]
        try:
            return self.new[filename]
        except KeyError:
            return self.old[filename]

    def previous(self, filename):
        '''Gives access to pragmas stored during previous run of StatWiki.
        Returns an empty PragmaParser object for newly created pages.'''
        try:
            return self.old[filename]
        except KeyError:
            if filename in self.new:
                return wikiparser.PragmaParser(u'')
                
    def remove(self, filename):
        try:
            del self.new[filename]
        except KeyError:
            del self.old[filename]


def process(wikipages):
    donepages = []

    # Load default template.
    default_template = read(config.template.default)
    
    # Load sidebar template.
    try:
        name = config.template.sidebar
    except AttributeError:
        sidebar_template = default_template
    else:
        sidebar_template = read(name)

    # Load all pragmas.
    all_pragmas = Pragmas(force_update=wikipages)

    # Check for deleted pages.
    for filename, pragmas in all_pragmas.previous_items():
        if not os.path.exists(filename):
            # Process categories so the page is removed from them.
            for category in pragmas.multiple('#category'):
                fname = wikiutil.pageName2inputFile(category)
                if fname not in wikipages:
                    wikipages.append(fname)
            all_pragmas.remove(filename)

    # Process the pages.
    while wikipages:

        filename = wikipages[0]
        del wikipages[0]
        assert os.path.exists(filename), '%s does not exist' % filename
    
        pagename = wikiutil.inputFile2pageName(filename)
        pragmas = all_pragmas[filename]
        prev_pragmas = all_pragmas.previous(filename)

        ftemp = StringIO()
        f = formatter.Formatter(pagename=pagename)
        p = wikiparser.Parser(read(filename), ftemp)

        try:
            sidebar = pragmas.single('#sidebar')
            assert sidebar != ''
        except ValueError:
            sidebar = ''
    
        print filename

        if sidebar:
            # Format the sidebar content
            fname = wikiutil.pageName2inputFile(sidebar)
            wikiutil.assertFileNameCase(fname)
            assert os.path.exists(fname), '%s does not exist' % fname
            fstemp = StringIO()
            sp = wikiparser.Parser(read(fname), fstemp)
            sp.format(f)
            sidebar_content = fstemp.getvalue()
        else:
            # No sideabr
            sidebar_content = ''
    
        # Get the page summary.
        summary = pragmas.single('#summary', '')
    
        # Format the content.
        p.format(f)
        content = ftemp.getvalue()

        # Process links to subpages in this category.
        subpages = []
        for fname, prag in all_pragmas.items():
            if pagename in prag.multiple('#category'):
                subpages.append(wikiutil.inputFile2pageName(fname))
        if subpages:
            lines = ['', '<a name="#category-subpages"></a>',
                '<h1>%s</h1>' % (config.text.subpages % dict(name=pagename)),
                '<div id="category-subpages">', '<table>', '<tr>', '<td>', '<ul>']
            subpages.sort(lambda a, b: -(a.lower() < b.lower()))
            num_of_columns = 3
            m = len(subpages)
            p = m / num_of_columns
            if m % num_of_columns:
                p += 1
            for i in xrange(m):
                if i > 0 and i % p == 0:
                    lines.extend(['</ul>', '</td>', '<td>', '<ul>'])
                lines.append('<li><a href="%s.html">%s</a>' % ((subpages[i],)*2))
            lines.extend(['</ul>', '</td>', '</tr>', '</table>', '</div>'])
            content += '\n'.join(lines)

        # Process categories this page belongs to.
        lines = ['']
        for category in sorted(pragmas.multiple('#category'),
                lambda a, b: -(a.lower() < b.lower())):
            fname = wikiutil.pageName2inputFile(category)
            wikiutil.assertFileNameCase(fname)
            assert os.path.exists(fname), '%s does not exist' % fname
            lines.append('<p class="category-link"><a href="%s.html">%s</a></p>' \
                % (category, (config.text.category % dict(name=category))))
            # Add the category page to processing to update its subpages list.
            if category not in prev_pragmas.multiple('#category'):
                fname = wikiutil.pageName2inputFile(category)
                wikiutil.assertFileNameCase(fname)
                if fname not in donepages and fname not in wikipages:
                    wikipages.append(fname)
        content += '\n'.join(lines)
        
        # Process categories this page was removed from.
        for category in prev_pragmas.multiple('#category'):
            if category not in pragmas.multiple('#category'):
                fname = wikiutil.pageName2inputFile(category)
                wikiutil.assertFileNameCase(fname)
                if fname not in donepages and fname not in wikipages and \
                        os.path.exists(fname):
                    wikipages.append(fname)

        # Choose a template.
        try:
            name = pragmas.single('#template')
        except ValueError:
            if sidebar:
                template = sidebar_template
            else:
                template = default_template
        else:
            template = read(name)
        
        # Create a HTML from the template.
        fout = codecs.open(wikiutil.pageName2outputFile(pagename), 'wt', encoding=config.charset)
        mtime = time.strftime(config.general.timeformat, time.gmtime(os.path.getmtime(filename)))
        ptime = time.strftime(config.general.timeformat, time.gmtime())
        fout.write(template % dict(pagename=pagename.replace(u'_', u' '),
            summary=summary,
            has_sidebar=not not sidebar,
            sidebar=sidebar_content,
            content=content,
            modification_time=mtime.replace(' ', '&nbsp;'),
            processing_time=ptime.replace(' ', '&nbsp;'),
            statwiki_version=__version__.replace(' ', '&nbsp;'),
            statwiki_date=__date__.replace(' ', '&nbsp;')
        ))
        fout.close()

        if filename not in donepages:
            donepages.append(filename)
    
        # Add pages using the current page as a sidebar to processing.
        for filename, pragmas in all_pragmas.items():
            try:
                 sidebar = pragmas.single('#sidebar')
            except ValueError:
                continue
            if sidebar != pagename:
                continue
            if filename not in donepages and filename not in wikipages:
                assert os.path.exists(filename), '%s does not exist' % filename
                wikipages.append(filename)


def warning(message):
    print >>sys.stderr, 'warning: %s' % message


def main():
    usage = 'usage: %prog [options] [pagename ...]'
    version = '%%prog %s (%s)' % (__version__, __date__)

    optparser = OptionParser(usage=usage, version=version)
    optparser.add_option('-m', '--make', action='store_true', help='build modified pages')
    optparser.add_option('-b', '--build', action='store_true', help='build all pages')
    optparser.add_option('-c', '--clean', action='store_true', help='remove html files')
    optparser.add_option('-s', '--synchronize', action='store_true', help='upload modified files to the FTP '
        'server; wiki files are not uploded; subdirectories *ARE* uploaded; requires ftputil library; FTP '
        'has to be configured using the config file; this switch can be combined with any of the above '
        'three')
    optparser.add_option('-f', '--force', action='store_true', help='when used together with --synchronize, '
        'causes the files and directories that does not exist locally to be deleted from the FTP server')
    optparser.add_option('-d', '--directory', dest='dir', help='wiki directory, defaults to current directory',
        default='.')
    optparser.add_option('-g', '--config', help='name of the config file relative to the wiki directory, '
        'defaults to _statwiki.config', default='_statwiki.config')

    options, args = optparser.parse_args()
    a = [name for name, value in options.__dict__.items() if name in ('make', 'build', 'clean') and value]
    if len(a) > 1:
        sys.exit('error: only one of --make, --build and --clean switches can be used at once')
    try:
        mode = a[0]
    except IndexError:
        if options.synchronize:
            # if only --synchronize was specified, do nothing besides syncing
            mode = 'idle'
        else:
            sys.exit('error: one of the --make, --build, --clean or --synchronize switches must '
                'be specified; use --help for more information')

    os.chdir(options.dir)
    config.parse(wikiutil.fixFileNameCase(options.config))

    if args:
        # Add .wiki to the names if needed.
        wikipages = []
        for name in args:
            if not name.endswith('.wiki'):
                name = wikiutil.pageName2inputFile(name)
            wikipages.append(wikiutil.fixFileNameCase(name))
    else:
        wikipages = [x for x in os.listdir('.') if x.endswith('.wiki') and not x.startswith('_')]

    if mode == 'clean':
        print 'Cleaning...'
        for filename in wikipages:
            pagename = wikiutil.inputFile2pageName(filename)
            try:
                os.unlink(wikiutil.pageName2outputFile(pagename))
                print wikiutil.pageName2outputFile(pagename)
            except OSError:
                pass

    elif mode == 'make':
        print 'Making...'
        todo = []
        for filename in wikipages:
            ofilename = wikiutil.inputFile2outputFile(filename)
            if not os.path.exists(ofilename) or \
                    os.path.getmtime(ofilename) < os.path.getmtime(filename):
                todo.append(filename)
        process(todo)

    elif mode == 'build':
        print 'Building...'
        process(wikipages)
    
    if options.synchronize:
        print 'Synchronizing with %s...' % getattr(config.ftp, 'host', '???')
        try:
            host = config.ftp.host
        except AttributeError:
            sys.exit('cannot synchronize, configure the FTP server access first')
        # Import ftpsync only if --synchronize was specified so that ftputil doesn't have to be
        # installed if this option is not used.
        from ftpsync import synchronize
        synchronize(options.force)
    elif options.force:
        sys.exit('error: --force can only be used together with --synchronize')


if __name__ == '__main__':
    main()


# vim:set ts=4 sw=4 et:
