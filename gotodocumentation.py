#!/usr/bin/python

import functools
import os
import re
import subprocess
import threading

import sublime
import sublime_plugin


def open_url(url):
    sublime.active_window().run_command('open_url', {"url": url})


def main_thread(callback, *args, **kwargs):
    # sublime.set_timeout gets used to send things onto the main thread
    # most sublime.[something] calls need to be on the main thread
    sublime.set_timeout(functools.partial(callback, *args, **kwargs), 0)


def _make_text_safeish(text, fallback_encoding):
    # The unicode decode here is because sublime converts to unicode inside
    # insert in such a way that unknown characters will cause errors, which is
    # distinctly non-ideal... and there's no way to tell what's coming out of
    # git in output. So...
    try:
        unitext = text.decode('utf-8')
    except UnicodeDecodeError:
        unitext = text.decode(fallback_encoding)
    return unitext


class CommandThread(threading.Thread):
    def __init__(self, command, on_done, working_dir="", fallback_encoding=""):
        threading.Thread.__init__(self)
        self.command = command
        self.on_done = on_done
        self.working_dir = working_dir
        self.fallback_encoding = fallback_encoding

    def run(self):
        try:
            # Per http://bugs.python.org/issue8557 shell=True is required to
            # get $PATH on Windows. Yay portable code.
            shell = os.name == 'nt'
            if self.working_dir != "":
                os.chdir(self.working_dir)

            proc = subprocess.Popen(self.command,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                shell=shell, universal_newlines=True)
            output = proc.communicate()[0]
            # if sublime's python gets bumped to 2.7 we can just do:
            # output = subprocess.check_output(self.command)
            main_thread(self.on_done,
                _make_text_safeish(output, self.fallback_encoding))
        except subprocess.CalledProcessError, e:
            main_thread(self.on_done, e.returncode)


class GotoDocumentationCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        for region in self.view.sel():
            word = self.view.word(region)
            if not word.empty():
                # scope: "text.html.basic source.php.embedded.block.html keyword.other.new.php"
                scope = self.view.scope_name(word.begin()).strip()
                extracted_scope = scope.rpartition('.')[2]
                keyword = self.view.substr(word)
                if ('%s_doc' % extracted_scope != 'js_doc'):
                    getattr(self, '%s_doc' % extracted_scope, self.unsupported)(keyword, scope)
                else:
                    # If the scope is JS we inspect for common used
                    # libraries such as JQuery and Dojo
                    js_lib = self.detect_js_library(region, 32)
                    if not (js_lib):
                        self.js_doc(keyword, scope)
                    else:
                        getattr(self, '%s_doc' % js_lib, \
                            self.unsupported)(keyword)

    def unsupported(self, keyword, scope):
        sublime.status_message("This scope is not supported: %s" % scope.rpartition('.')[2])

    def php_doc(self, keyword, scope):
        open_url("http://php.net/%s" % keyword)

    def rails_doc(self, keyword, scope):
        open_url("http://api.rubyonrails.org/?q=%s" % keyword)

    def controller_doc(self, keyword, scope):
        open_url("http://api.rubyonrails.org/?q=%s" % keyword)

    def ruby_doc(self, keyword, scope):
        open_url("http://api.rubyonrails.org/?q=%s" % keyword)

    def js_doc(self, keyword, scope):
        open_url("https://developer.mozilla.org/en-US/search?q=%s" % keyword)

    coffee_doc = js_doc

    def python_doc(self, keyword, scope):
        """Not trying to be full on intellisense here, but want to make opening a
        browser to a docs.python.org search a last resort
        """
        if not re.match(r'\s', keyword):
            self.run_command(["pydoc", keyword])
            return

        open_url("http://docs.python.org/search.html?q=%s" % keyword)

    def clojure_doc(self, keyword, scope):
        open_url("http://clojuredocs.org/search?x=0&y=0&q=%s" % keyword)

    def go_doc(self, keyword, scope):
        open_url("http://golang.org/search?q=%s" % keyword)

    def smarty_doc(self, keyword, scope):
        open_url('http://www.smarty.net/%s' % keyword)

    def jquery_doc(self, keyword):
        open_url('http://api.jquery.com/%s' % keyword)

    def dojo_doc(self, keyword):
        open_url('http://dojotoolkit.org/api/dojo.%s' % keyword)

    def run_command(self, command, callback=None, **kwargs):
        if not callback:
            callback = self.display_output
        thread = CommandThread(command, callback, **kwargs)
        thread.start()

    def display_output(self, output):
        if not hasattr(self, 'output_view'):
            self.output_view = sublime.active_window().get_output_panel("gotodocumentation")
        self.output_view.set_read_only(False)
        edit = self.output_view.begin_edit()
        region = sublime.Region(0, self.output_view.size())
        self.output_view.erase(edit, region)
        self.output_view.insert(edit, 0, output)
        self.output_view.end_edit(edit)
        self.output_view.set_read_only(True)
        sublime.active_window().run_command("show_panel", {"panel": "output.gotodocumentation"})

    def detect_js_library(self, region, max_backreference):
        """Returns a string with the name of the JS library detected

        param view refers to the current view of the editor, we need
        this for context (not just the keyword)
        param max_backreference refers to the max characters will go
        back to look for a reference to a library. This should be
        deprecated soon and replaced with scope detection
        """
        lib = None
        sel_word = self.view.word(region)
        pre_sel_word = sublime.Region(sel_word.a - 2, sel_word.a - 1)
        pre_string = self.view.substr(pre_sel_word)
        if(pre_string == '$'):
            # Found jquery
            lib = 'jquery'
        if(pre_string == 'o'):
            # It's probably dojo, lets check it out!
            region = sublime.Region(pre_sel_word.a - 3, pre_sel_word.b)
            if(self.view.substr(region) == 'dojo'):
                lib = 'dojo'
        if(pre_string == ')'):
            # Probably a Jquery selector, lets make sure
            for i in range(1, max_backreference):
                region = sublime.Region(pre_sel_word.a - i, \
                    pre_sel_word.a - (i + 1))
                if(self.view.substr(region) == '('):
                    # Found the beggining of the selector
                    region = sublime.Region(region.a - 1, \
                        region.b - 1)
                    if(self.view.substr(region) == '$'):
                        lib = 'jquery'
                    break
        if(lib != None):
            return lib
        else:
            return False
