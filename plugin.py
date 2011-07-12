# -*- Encoding: utf-8 -*-
###
# Copyright (c) 2006-2007 Dennis Kaarsemaker
# Copyright (c) 2008-2010 Terence Simpson
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of version 2 of the GNU General Public License as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
###

from supybot.commands import *
import supybot.ircmsgs as ircmsgs
import supybot.callbacks as callbacks
import sqlite, datetime, time, pytz
import supybot.registry as registry
import supybot.ircdb as ircdb
import supybot.conf as conf
import supybot.utils as utils
import supybot.ircutils as ircutils
import sys, os, re, hashlib, random, time

if sys.version_info >= (2, 5, 0):
  import re
else:
  import sre as re

def checkIgnored(hostmask, recipient='', users=ircdb.users, channels=ircdb.channels):
    if ircdb.ignores.checkIgnored(hostmask):
        return True
    try:
        id = ircdb.users.getUserId(hostmask)
        user = users.getUser(id)
    except KeyError:
        # If there's no user...
        if ircutils.isChannel(recipient):
            channel = channels.getChannel(recipient)
            if channel.checkIgnored(hostmask):
                return True
            else:
                return False
        else:
            return False
    if user._checkCapability('owner'):
        # Owners shouldn't ever be ignored.
        return False
    elif user.ignore:
        return True
    elif recipient:
        if ircutils.isChannel(recipient):
            channel = ircdb.channels.getChannel(recipient)
            if channel.checkIgnored(hostmask):
                return True
            else:
                return False
        else:
            return False
    else:
        return False

# Simple wrapper class for factoids
class Factoid:
    def __init__(self, name, value, author, added, popularity):
        self.name = name;     self.value = value
        self.author = author; self.added = added
        self.popularity = popularity

class FactoidSet:
    def __init__(self):
        self.global_primary = self.global_secondary = \
        self.channel_primary = self.channel_secondary = None

# Repeat filtering message queue
msgcache = {}
def queue(irc, to, msg):
    now = time.time()
    for m in msgcache.keys():
        if msgcache[m] < now - 30:
            msgcache.pop(m)
    for m in msgcache:
        if m[0] == irc and m[1] == to:
            oldmsg = m[2]
            if msg == oldmsg or oldmsg.endswith(msg):
                break
            if msg.endswith(oldmsg) and ':' in msg:
                msg = msg[:-len(oldmsg)] + 'please see above'
    else:
        msgcache[(irc, to, msg)] = now
        irc.queueMsg(ircmsgs.privmsg(to, msg))

def capab(prefix, capability):
    # too bad people don't use supybot's own methods, 
    # it would save me the trouble of hacking this up.
    if capability == "editfactoids":
        #if capab(user.name, "addeditors"):
        return True
    import supybot.world as world
    if world.testing:
        # we're running a testcase, return always True.
        return True
    capability = capability.lower()
    if prefix.find('!') > 0:
        user = prefix[:prefix.find('!')]
    else:
        user = prefix
    try:
        user = ircdb.users.getUser(prefix)
        capabilities = list(user.capabilities)
    except:
        return False
    # Capability hierarchy #
    if capability == "addeditors":
        if capab(user.name, "admin"):
            return True
    if capability == "admin":
        if capab(user.name, "owner"):
            return True
    # End #
    if capability in capabilities:
        return True
    else:
        return False

def safeQuote(s):
    if isinstance(s, list):
        res = []
        for i in s:
            res.append(safeQuote(i))
        return res
    return s.replace('%', '%%')

# This regexp should match most urls in the format protocol://(domain|ip adress)
# and the special case when there's no protocol but domain starts with www.
#
# We do this so we can filter obvious requests with spam in them
octet = r'(?:2(?:[0-4]\d|5[0-5])|1\d\d|\d{1,2})' # 0 - 255
ip_address = r'%s(?:\.%s){3}' % (octet, octet)   # 0.0.0.0 - 255.255.255.255
# Base domain regex off RFC 1034 and 1738
label = r'[0-9a-z][-0-9a-z]*[0-9a-z]?'
domain = r'%s(?:\.%s)*\.[a-z][-0-9a-z]*[a-z]?' % (label, label) # like www.ubuntu.com
# complete regexp
urlRe = re.compile(r'(?:\w+://(?:%s|%s)|www\.%s)' % (domain, ip_address, domain), re.I)

def checkUrl(s):
    """Check if string contains something like an url."""
    return bool(urlRe.search(s))


class Encyclopedia(callbacks.Plugin):
    """!factoid: show factoid"""

    def __init__(self, irc):
        callbacks.Plugin.__init__(self, irc)
        self.databases = {}
        self.times = {}
        self.edits = {}
        self.alert = False

    def addeditor(self, irc, msg, args, name):
        """<name>

        Adds the user with the name <name> to the list of editors.
        """
        if not capab(msg.prefix, 'addeditors'):
            return
        try:
            u = ircdb.users.getUser(name)
            u.addCapability('editfactoids')
            irc.replySuccess()
        except:
            irc.error('User %s is not registered' % name)
    addeditor = wrap(addeditor, ['text'])

    def removeeditor(self, irc, msg, args, name):
        """<name>

        Removes the user with the name <name> from the list of editors.
        """
        if not capab(msg.prefix, 'addeditors'):
            return
        try:
            u = ircdb.users.getUser(name)
            u.removeCapability('editfactoids')
            irc.replySuccess()
        except:
            irc.error('User %s is not registered or not an editor' % name)
    removeeditor = wrap(removeeditor, ['text'])

    def editors(self, irc, msg, args):
        """Takes no arguments

        Lists all the users who are in the list of editors.
        """
        irc.reply(', '.join([u.name for u in ircdb.users.users.values() if capab(u.name, 'editfactoids')]), private=True)
    editors = wrap(editors)

    def moderators(self, irc, msg, args):
        """Takes no arguments

        Lists all the users who can add users to the list of editors.
        """
        irc.reply(', '.join([u.name for u in ircdb.users.users.values() if capab(u.name, 'addeditors')]), private=True)
    moderators = wrap(moderators)

    def get_target(self, nick, text, orig_target):
        target = orig_target
        retmsg = ''
        rettext = text[:]
        hasPipe = False
        hasRedir = False
        
        if text.startswith('tell '):
            text = ' ' + text

        if '|' in text and not text.strip().endswith('|'):
            hasPipe = True
            retmsg = text[text.find('|')+1:].strip() + ': '
            rettext = text[:text.find('|')].strip()

        if ' tell ' in text and ' about ' in text:
            target = text[text.find(' tell ')+6:].strip().split(None,1)[0]
            rettext = text[text.find(' about ')+7:].strip()
            retmsg = "<%s> wants you to know: " % nick
            
        if '>' in text:
            if hasPipe:
                if text.index('|') > text.index('>'):
                    target = text[text.rfind('>')+1:].strip().split()[0]
                    rettext = text[:text.rfind('>')].strip()
                    retmsg = "<%s> wants you to know: " % nick
            else:
                target = text[text.rfind('>')+1:].strip().split()[0]
                rettext = text[:text.rfind('>')].strip()
                retmsg = "<%s> wants you to know: " % nick


        if target == 'me':
            target = nick
        if target.lower() != orig_target.lower() and target.startswith('#'):
            target = orig_target
            retmsg = ''

        if (target.lower() == nick.lower() or retmsg[:-2].lower() == nick.lower()) and nick.lower() != orig_target.lower():
            target = nick
            retmsg = '(In the future, please use a private message to investigate) '

        return (rettext, target, retmsg)

    def get_db(self, channel):
        db = self.registryValue('database',channel)
        if channel in self.databases:
            if self.databases[channel].time < time.time() - 3600 or self.databases[channel].name != db:
                self.databases[channel].close()
                self.databases.pop(channel)
        if channel not in self.databases:
            self.databases[channel] = sqlite.connect(os.path.join(self.registryValue('datadir'), '%s.db' % db))
            self.databases[channel].name = db
            self.databases[channel].time = time.time()
        return self.databases[channel]

    def get_log_db(self, channel=None):
        db = "%s-log" % self.registryValue('database',channel)
        db_path = os.path.join(self.registryValue('datadir'), "%s.db" % db)
        if not os.access(db_path, os.R_OK | os.W_OK):
            self.log.warning("Encyclopedia: Could not access log database at '%s.db'" % db_path)
            return None
        channel = "%s-log" % channel
        if channel in self.databases:
            if self.databases[channel].time < time.time() - 3600 or self.databases[channel].name != db:
                self.databases[channel].close()
                self.databases.pop(channel)
        if channel not in self.databases:
            self.databases[channel] = sqlite.connect(db_path)
            self.databases[channel].name = db
            self.databases[channel].time = time.time()
        return self.databases[channel]

    def addressed(self, recipients, text, irc, msg):
        nlen = len(irc.nick)
        if recipients[0] == '#':
            text = text.strip()
            if text.lower() == self.registryValue('prefixchar', channel=recipients) + irc.nick.lower():
                return irc.nick.lower()
            if len(text) and text[0] == self.registryValue('prefixchar',channel=recipients):
                text = text[1:]
                if text.lower().startswith(irc.nick.lower()) and (len(text) < nlen or not text[nlen].isalnum()):
                    t2 = text[nlen+1:].strip()
                    if t2 and t2.find('>') != -1 and t2.find('|') != -1:
                        text = text[nlen+1:].strip()
                return text
            if text.lower().startswith(irc.nick.lower()) and (len(text) > nlen and not text[nlen].isalnum()):
                return text[nlen+1:]
            return False
        else: # Private
            if text.strip()[0] in str(conf.supybot.reply.whenAddressedBy.chars.get(msg.args[0])):
                return False
            if not text.split()[0] == 'search':
                for c in irc.callbacks:
                    comm = text.split()[0]
                    if c.isCommandMethod(comm) and not c.isDisabled(comm):
                        return False
            if text[0] == self.registryValue('prefixchar',channel=recipients):
                return text[1:]
            return text
            
    def get_factoids(self, name, channel, resolve = True, info = False, raw = False):
        factoids = FactoidSet()
        factoids.global_primary    = self.get_single_factoid(channel, name, deleted=raw)
        factoids.global_secondary  = self.get_single_factoid(channel, name + '-also', deleted=raw)
        factoids.channel_primary   = self.get_single_factoid(channel, name + '-' + channel.lower(), deleted=raw)
        factoids.channel_secondary = self.get_single_factoid(channel, name + '-' + channel.lower() + '-also', deleted=raw)
        if resolve and not raw:
            factoids.global_primary    = self.resolve_alias(channel, factoids.global_primary)
            factoids.global_secondary  = self.resolve_alias(channel, factoids.global_secondary)
            factoids.channel_primary   = self.resolve_alias(channel, factoids.channel_primary)
            factoids.channel_secondary = self.resolve_alias(channel, factoids.channel_secondary)
        if info:
        # Get aliases for factoids
            factoids.global_primary    = self.factoid_info(channel, factoids.global_primary)
            factoids.global_secondary  = self.factoid_info(channel, factoids.global_secondary)
            factoids.channel_primary   = self.factoid_info(channel, factoids.channel_primary)
            factoids.channel_secondary = self.factoid_info(channel, factoids.channel_secondary)
        return factoids
        
    def get_single_factoid(self, channel, name, deleted=False):
        db = self.get_db(channel)
        cur = db.cursor()
        if deleted:
            cur.execute("SELECT name, value, author, added, popularity FROM facts WHERE name = %s", name)
        else:
            cur.execute("SELECT name, value, author, added, popularity FROM facts WHERE name = %s AND value NOT like '<deleted>%%'", name)
        factoids = cur.fetchall()
        if len(factoids):
            f = factoids[0]
            return Factoid(f[0],f[1],f[2],f[3],f[4])

    def resolve_alias(self, channel, factoid, loop=0):
        if factoid and factoid.name in self.registryValue('alert', channel):
            self.alert = True
        if loop >= 10:
            return Factoid('','<reply> Error: infinite <alias> loop detected','','',0)
        if factoid and factoid.value.lower().startswith('<alias>'):
            new_factoids = self.get_factoids(factoid.value[7:].lower().strip(), channel, False)
            for x in ['channel_primary', 'global_primary']:
                if getattr(new_factoids, x):
                    return self.resolve_alias(channel, getattr(new_factoids, x), loop+1)
            return Factoid('','<reply> Error: unresolvable <alias> to %s' % factoid.value[7:].lower().strip(),'','',0)
        else:
            return factoid

    def factoid_info(self, channel, factoid):
        if not factoid:
            return
        if not factoid.value.startswith('<alias>'):
            # Try and find aliases
            db = self.get_db(channel)
            cur = db.cursor()
            cur.execute("SELECT name FROM facts WHERE value = %s", '<alias> ' + factoid.name)
            data = cur.fetchall()
            if data:
                factoid.value = "<reply> %s aliases: %s" % (factoid.name, ', '.join([x[0] for x in data]))
            else:
                factoid.value = "<reply> %s has no aliases" % (factoid.name)
        # Author info
        db = self.get_db(channel)
        cur = db.cursor()
        cur.execute("SELECT author, added FROM log WHERE name = %s", factoid.name)
        data = cur.fetchall()
        factoid.value += " - added by %s on %s" % (factoid.author[:factoid.author.find('!')], factoid.added[:factoid.added.find('.')])
        if data:
            last_edit = data[len(data)-1]
            who = last_edit[0][:last_edit[0].find('!')]
            when = last_edit[1][:last_edit[1].find('.')]
            factoid.value += " - last edited by %s on %s" % (who, when)
        return factoid

    def check_aliases(self, channel, factoid):
        now = time.time()
        for e in self.edits.keys():
            if self.edits[e] + 10 < now:
                self.edits.pop(e)
        if not factoid.value.startswith('<alias>'):
            return
        # Was the old value an alias?
        oldf = self.get_single_factoid(channel, factoid.name)
        if oldf and oldf.value.startswith('<alias>'):
            if factoid.name not in self.edits:
                self.edits[factoid.name] = now
                return "You are editing an alias. Please repeat the edit command within the next 10 seconds to confirm"
        # Do some alias resolving
        if factoid.value.startswith('<alias>'):
            aliasname = factoid.value[7:].strip()
            alias = self.get_single_factoid(channel, aliasname)
            if not alias:
                return "Factoid '%s' does not exist" % aliasname
            alias = self.resolve_alias(channel, factoid)
            if alias.value.lower().startswith('error'):
                return alias.value.lower
            factoid.value = '<alias> ' + alias.name

    def callPrecedence(self, irc):
        before = []
        for cb in irc.callbacks:
            if cb.name() == 'IRCLogin':
                before.append(cb)
        return (before, [])

    def inFilter(self, irc, msg):
        orig_msg = msg
        if msg.command == "PRIVMSG" and msg.args[0].lower() == irc.nick.lower():
            recipient, text = msg.args
            new_text = self.addressed(recipient, text, irc, msg)
            if new_text:
                irc = callbacks.ReplyIrcProxy(irc, msg)
                if(irc.nick.lower() == msg.args[0]):
                    self.doPrivmsg(irc, msg)
        return orig_msg

    def doPrivmsg(self, irc, msg):
        def beginswith(text, strings):
            for string in strings:
                if text.startswith(string):
                    return True
            return False

        # Filter CTCP
        if chr(1) in msg.args[1]:
            return

        if checkIgnored(msg.prefix,msg.args[0]):
            return
        # Are we being queried?
        recipient, text = msg.args
        text = self.addressed(recipient, text, irc, msg)
        if not text:
            return
        doChanMsg = True
        display_info = False
        display_raw = False
        target = msg.args[0]
        if target[0] != '#':
            target = msg.nick
        channel = msg.args[0]

        # Strip leading nonalnums
        while text and not text[0].isalnum():
            if text[0] == '-':
                if not display_raw:
                    display_info = True
            if text[0] == '+':
                if not display_info:
                    display_raw = True
            text = text[1:]
        if not text:
            return
            
        # Now switch between actions
        orig_text = text
        lower_text = text.lower()
        if "please see" in lower_text:
            if "from %s" % irc.nick.lower() in lower_text or "from the bot" in lower_text:
                doChanMsg = False
        ret = ''
        retmsg = ''
        term = self.get_target(msg.nick, orig_text, target)
        if term[0] == "search": # Usage info for the !search command
            ret = "Search factoids for term: !search <term>"
            retmsg = term[2]
        elif beginswith(lower_text, self.registryValue('ignores', channel)): # Make sure ignores can ignore these built-in "facts"
            return
        elif term[0] in ("what", "whats", "what's") or term[0].startswith("what ") or term[0].startswith("what ") or term[0].startswith("whats ") or term[0].startswith("what's "): # Try and catch people saying "ubottu: what is ...?"
            ret = "I suck balls"
            retmsg = term[2]
        else:
            # Lookup, search or edit?
            if lower_text.startswith('search '):
                ret = self.search_factoid(lower_text[7:].strip(), channel)
            elif (' is ' in lower_text and lower_text[:3] in ('no ', 'no,')) or '<sed>' in lower_text or '=~' in lower_text \
                or '~=' in lower_text or '<alias>' in lower_text or lower_text.startswith('forget') or lower_text.startswith('unforget'):
                if not (capab(msg.prefix, 'editfactoids') \
                        or channel in self.registryValue('editchannel') \
                        and capab(msg.prefix, 'restricted-editor')):
                    irc.reply("Your edit request has been forwarded to %s.  Thank you for your attention to detail" %
                              self.registryValue('relaychannel',channel),private=True)
                    irc.queueMsg(ircmsgs.privmsg(self.registryValue('relaychannel',channel), "In %s, %s said: %s" %
                                                 (msg.args[0], msg.nick, msg.args[1])))
                    self.logRequest(msg.args[0], msg.nick, text)
                    return
                ret = self.factoid_edit(text, channel, msg.prefix)
            elif (' is ' in lower_text and '|' in lower_text and lower_text.index('|') > lower_text.index(' is ')) or (' is ' in lower_text and '|' not in lower_text):
                if not (capab(msg.prefix, 'editfactoids') \
                        or channel in self.registryValue('editchannel') \
                        and capab(msg.prefix, 'restricted-editor')):
                    if len(text[:text.find('is')]) > 15:
                        irc.error("I suck balls")
                    else:
                        irc.reply("Your edit request has been forwarded to %s.  Thank you for your attention to detail" %
                                  self.registryValue('relaychannel',channel),private=True)
                        irc.queueMsg(ircmsgs.privmsg(self.registryValue('relaychannel',channel), "In %s, %s said: %s" %
                                                     (msg.args[0], msg.nick, msg.args[1])))
                        self.logRequest(msg.args[0], msg.nick, text)
                    return
                ret = self.factoid_add(text, channel, msg.prefix)
            else:
                text, target, retmsg = self.get_target(msg.nick, orig_text, target)
                if text.startswith('bug ') and text != ('bug 1'):
                    return
                ret = self.factoid_lookup(text, channel, display_info, display_raw)

        if not ret:
            if len(text) > 15:
                irc.error("I suck balls")
                return
            retmsg = ''
            ret = self.registryValue('notfoundmsg')
            if ret.count('%') == ret.count('%s') == 1:
                ret = ret % repr(text)
            if channel.lower() == irc.nick.lower():
                queue(irc, msg.nick, ret)
            elif self.registryValue('privateNotFound', channel):
                queue(irc, msg.nick, ret)
            else:
                queue(irc, channel, ret)
            return
        # check if retmsg has urls (possible spam)
        if checkUrl(retmsg):
            if self.alert and (target[0] == '#' and not target.endswith('bots')):
                # !ops factoid called with an url, most likely spam.
                # we filter the msg, but we still warn in -ops.
                queue(irc, self.registryValue('relayChannel', channel), '%s called the ops in %s (%s)' % (msg.nick, msg.args[0], retmsg[:-2]))
                self.alert = False
            # do nothing
            return
        if doChanMsg and channel.lower() != irc.nick.lower() and target[0] != '#': # not /msg
            if target in irc.state.channels[channel].users:
                queue(irc, channel, "%s, please see my private message" % target)
        if type(ret) != list:
            queue(irc, target, retmsg + ret)
        else:
            queue(irc, target, retmsg + ret[0])
            if self.alert:
                if target.startswith('#') and not target.endswith('bots'):
                    queue(irc, self.registryValue('relayChannel', channel), '%s called the ops in %s (%s)' % (msg.nick, msg.args[0], retmsg[:-2]))
                self.alert = False
            for r in ret[1:]:
                queue(irc, target, r)

    def doPart(self, irc, msg):
        if len(msg.args) < 2 or not msg.args[1].startswith('requested by'):
            return

        #self.log.debug('msg: %s', msg.args)
        channel, reason = msg.args
        reason = reason[reason.find('(')+1:-1] # get the text between ()
        self._forcedFactoid(irc, channel, msg.nick, reason)

    def doKick(self, irc, msg):
        #self.log.debug('msg: %s', msg.args)
        channel, nick, reason = msg.args
        self._forcedFactoid(irc, channel, nick, reason)

    def _forcedFactoid(self, irc, channel, nick, reason):
        if not self.registryValue('forcedFactoid', channel):
            return

        prefix = self.registryValue('prefixchar', channel)
        factoidRe = re.compile(r'%s\w+\b' %prefix)
        factoids = factoidRe.findall(reason)
        #self.log.debug('factoids in reason: %s', factoids)
        if not factoids:
            # no factoid in reason
            return

        L = []
        for factoid in factoids:
            result = self.factoid_lookup(factoid.strip(prefix), channel, False)
            L.extend(result)
            
        if not L:
            return
        
        for s in L:
            msg = ircmsgs.privmsg(nick, s)
            irc.queueMsg(msg)

    def factoid_edit(self, text, channel, editor):
        db = self.get_db(channel)
        cs = db.cursor()
        factoid = retmsg = None

        def log_change(factoid):
            cs.execute('''insert into log (author, name, added, oldvalue) values (%s, %s, %s, %s)''',
                     (editor, factoid.name, str(datetime.datetime.now(pytz.timezone("UTC"))), factoid.value))
            db.commit()

        if '<alias>' in text.lower() and not text.lower().startswith('no'):
            return self.factoid_add(text,channel,editor)

        if text.lower().startswith('forget '):
            factoid = self.get_single_factoid(channel, text[7:])
            if not factoid:
                return "I know nothing about %s yet, %s" % (text[7:], editor[:editor.find('!')])
            else:
                log_change(factoid)
                factoid.value = '<deleted>' + factoid.value
                retmsg = "I'll forget that, %s" % editor[:editor.find('!')]
                
        if text.lower().startswith('unforget '):
            factoid = self.get_single_factoid(channel, text[9:], deleted=True)
            if not factoid:
                return "I knew nothing about %s at all, %s" % (text[9:], editor[:editor.find('!')])
            else:
                if not factoid.value.startswith('<deleted>'):
                    return "Factoid %s wasn't deleted yet, %s" % (factoid.name, editor[:editor.find('!')])
                log_change(factoid)
                factoid.value = factoid.value[9:]
                retmsg = "I suddenly remember %s again, %s" % (factoid.name, editor[:editor.find('!')])

        if text.lower()[:3] in ('no ', 'no,'):
            text = text[3:].strip()
            p = text.lower().find(' is ')
            name, value = text[:p].strip(), text[p+4:].strip()
            if not name or not value:
                return
            name = name.lower()
            factoid = self.get_single_factoid(channel, name)
            if not factoid:
                return "I know nothing about %s yet, %s" % (name, editor[:editor.find('!')])
            log_change(factoid)
            factoid.value = value
            retmsg = "I'll remember that %s" % editor[:editor.find('!')]
        
        if not retmsg:
            if ' is<sed>' in text:
                text = text.replace('is<sed>','=~',1)
            if ' is <sed>' in text:
                text = text.replace('is <sed>','=~',1)
            if '~=' in text:
                text = text.replace('~=','=~',1)
            # Split into name and regex
            name = text[:text.find('=~')].strip()
            regex = text[text.find('=~')+2:].strip()
            # Edit factoid
            factoid = self.get_single_factoid(channel, name)
            if not factoid:
                return "I know nothing about %s yet, %s" % (name, editor[:editor.find('!')])
            # Grab the regex
            if regex.startswith('s'):
                regex = regex[1:]
            if regex[-1] != regex[0]:
                return "Missing end delimiter"
            if regex.count(regex[0]) != 3:
                return "Too many (or not enough) delimiters"
            regex, replace = regex[1:-1].split(regex[0])
            try:
                regex = re.compile(regex)
            except:
                return "Malformed regex"
            newval = regex.sub(replace, factoid.value, 1)
            if newval == factoid.value:
                return "Nothing changed there"
            log_change(factoid)
            factoid.value = newval
            retmsg = "I'll remember that %s" % editor[:editor.find('!')]

        ret = self.check_aliases(channel, factoid)
        if ret:
            return ret
        cs.execute("UPDATE facts SET value=%s where name=%s", (factoid.value,factoid.name))
        db.commit()
        return retmsg

    def factoid_add(self, text, channel, editor):
        db = self.get_db(channel)
        cs = db.cursor()

        p = text.lower().find(' is ')
        name, value = text[:p].strip(), text[p+4:].strip()
        if not name or not value:
            return
        name = name.lower()
        if value.startswith('also ') or value.startswith('also:'):
            name += '-also'
            value = value[5:].strip()
            if not value:
                return
        if self.get_single_factoid(channel, name, deleted=True):
            return "But %s already means something else!" % name
        factoid = Factoid(name,value,None,None,None)
        ret = self.check_aliases(channel, factoid)
        if ret:
            return ret
        cs.execute("INSERT INTO facts (name, value, author, added) VALUES (%s, %s, %s, %s)",
                    (name, value, editor, str(datetime.datetime.now(pytz.timezone("UTC")))))
        db.commit()
        return "I'll remember that, %s" % editor[:editor.find('!')]

    def factoid_lookup(self, text, channel, display_info, display_raw=False):
        def subvars(val):
            curStable = self.registryValue('curStable')
            curStableLong = self.registryValue('curStableLong')
            curStableNum = self.registryValue('curStableNum')
            curLTS = self.registryValue('curLTS')
            curLTSLong = self.registryValue('curLTSLong')
            curLTSNum = self.registryValue('curLTSNum')
            curDevel = self.registryValue('curDevel')
            curDevelLong = self.registryValue('curDevelLong')
            curDevelNum = self.registryValue('curDevelNum')
            val = val.replace('$chan',channel)
            val = val.replace('$curStableLong',curStableLong)
            val = val.replace('$curStableNum',curStableNum)
            val = val.replace('$curStableLower',curStable.lower())
            val = val.replace('$curStable',curStable)
            val = val.replace('$curLTSLong',curLTSLong)
            val = val.replace('$curLTSNum',curLTSNum)
            val = val.replace('$curLTSLower',curLTS.lower())
            val = val.replace('$curLTS',curLTS)
            val = val.replace('$curDevelLong',curDevelLong)
            val = val.replace('$curDevelNum',curDevelNum)
            val = val.replace('$curDevelLower',curDevel.lower())
            val = val.replace('$curDevel',curDevel)
            return val
        db = self.get_db(channel)
        factoids = self.get_factoids(text.lower(), channel, resolve = (not display_info and not display_raw), info = display_info, raw = display_raw)
        ret = []
        for order in ('primary', 'secondary'):
            for loc in ('channel', 'global'):
                key = '%s_%s' % (loc, order)
                if getattr(factoids, key):
                    factoid = getattr(factoids,key)
                    if (not display_info and not display_raw):
                        cur = db.cursor()
                        cur.execute("UPDATE FACTS SET popularity = %d WHERE name = %s", factoid.popularity+1, factoid.name)
                        db.commit()
                    if display_raw:
                        ret.append(factoid.value)
                    elif factoid.value.startswith('<reply>'):
                        ret.append(subvars(factoid.value[7:].strip()))
                    elif order == 'secondary':
                        ret.append(subvars(factoid.value.strip()))
                    else:
                        n = factoid.name
                        if '-#' in n:
                            n = n[:n.find('-#')]
                        ret.append('%s is %s' % (n, subvars(factoid.value)))
                    if not display_info:
                        break
        return ret

    def sanatizeRequest(self, channel, msg):
        def normalize(s):
            while s.count("  "):
                s = s.replace("  ", '')
            return s.strip()

        msg = normalize(msg)
        if msg[0] == self.registryValue('prefixchar', channel):
            msg = msg[1:]
        if msg.startswith("no "):
            msg = msg[3:]
        if " is " in msg:
            msg = msg.replace(" is ", " ", 1)
        (name, msg) = msg.split(None, 1)
        factoid = self.get_single_factoid(channel, name)
        oldval = ''
        if factoid:
            oldval = factoid.value
        return (name, msg, oldval)

    def logRequest(self, channel, nick, msg):
        (name, msg, oldval) = self.sanatizeRequest(channel, msg)
        if msg.strip() == oldval.strip():
            return
        if oldval:
            self.doLogRequest(0, channel, nick, name, msg, oldval)
        else:
            self.doLogRequest(1, channel, nick, name, msg)

    def doLogRequest(self, tp, channel, nick, name, msg, oldval = ''):
        db = self.get_log_db(channel)
        if not db:
            return
        cur = db.cursor()
        now = str(datetime.datetime.now(pytz.timezone("UTC")))
        cur.execute("SELECT value FROM requests WHERE name = %s", name)
        items = cur.fetchall()
        if len(items):
            for item in items:
                if item[0] == msg:
                    return
        cur.execute("INSERT INTO requests (type, name, value, oldval, who, date, rank) VALUES (%i, %s, %s, %s, %s, %s, 0)",
            (int(bool(tp)), name, msg, oldval, nick, now))
        db.commit()

    def search_factoid(self, factoid, channel):
        keys = factoid.split()[:5]
        db = self.get_db(channel)
        cur = db.cursor()
        ret = {}
        for k in keys:
            k = k.replace("'","\'")
            cur.execute("SELECT name,value FROM facts WHERE name LIKE '%%%s%%' OR VAlUE LIKE '%%%s%%'" % (k, k))
            res = cur.fetchall()
            for r in res:
                val = r[1]
                d = r[1].startswith('<deleted>')
                a = r[1].startswith('<alias>')
                r = r[0]
                if d:
                    r += '*'
                if a:
                    r += '@' + val[7:].strip()
                try:
                    ret[r] += 1
                except:
                    ret[r] = 1
        if not ret:
            return "None found"
        return 'Found: %s' % ', '.join(sorted(ret.keys(), lambda x, y: cmp(ret[x], ret[y]))[:10])

    def sync(self, irc, msg, args, channel):
        """[<channel>]

        Downloads a copy of the database from the remote server.
        Set the server with the channel variable supybot.plugins.Encyclopedia.remotedb.
        If <channel> is not set it will default to the channel the command is given in or the global value.
        """
        if not capab(msg.prefix, "owner"):
            irc.error("Sorry, you can't do that")
            return
        if channel:
            if not ircutils.isChannel(channel):
                irc.error("'%s' is not a valid channel" % safeQuote(channel))
                return
        remotedb = self.registryValue('remotedb', channel)
        if not remotedb:
            return
        def download_database(location, dpath):
            """Download the database located at location to path dpath"""
            import urllib2
            tmp_db = "%s%stmp" % (dpath, os.extsep)
            fd = urllib2.urlopen(location)
            fd2 = open(tmp_db, 'w')
            fd2.write(fd.read()) # Download to a temparary file
            fd.close()
            fd2.close()
            # Do some checking to make sure we have an SQLite database
            fd2 = open(tmp_db, 'rb')
            data = fd2.read(47)
            if data == '** This file contains an SQLite 2.1 database **': # OK, rename to dpath
                os.rename(tmp_db, dpath)
                try:
                    self.databases[channel].close()
                except:
                    pass
                try:
                    self.databases.pop(channel)
                except:
                    pass
            else: # Remove the tmpparary file and raise an error
                os.remove(tmp_db)
                raise RuntimeError, "Downloaded file was not a SQLite 2.1 database"

        db = self.registryValue('database', channel)
        if not db:
            if channel:
                irc.error("I don't have a database set for %s" % channel)
                return
            irc.error("There is no global database set, use 'config supybot.plugins.Encyclopedia.database <database>' to set it")
            return
        if not remotedb:
            if channel:
                irc.error("I don't have a remote database set for %s" % channel)
                return
            irc.error("There is no global remote database set, use 'config supybot.plugins.Encyclopedia.remotedb <url>' to set it")
            return
        dbpath = os.path.join(self.registryValue('datadir'), '%s.db' % db)
        # We're moving files and downloading, lots can go wrong so use lots of try blocks.
        try:
            os.rename(dbpath, "%s.backup" % dbpath)
        except OSError:
            # file doesn't exist yet, so nothing to backup
            pass
        except Exception, e:
            self.log.error("Encyclopedia: Could not rename %s to %s.backup" % (dbpath, dbpath))
            self.log.error('Encyclopedia: ' + utils.exnToString(e))
            irc.error("Internal error, see log")
            return

        try:
            # Downloading can take some time, let the user know we're doing something
            irc.reply("Attemting to download database", prefixNick=False)
            download_database(remotedb, dbpath)
            irc.replySuccess()
        except Exception, e:
            self.log.error("Encyclopedia: Could not download %s to %s" % (remotedb, dbpath))
            self.log.error('Encyclopedia: ' + utils.exnToString(e))
            irc.error("Internal error, see log")
            os.rename("%s.backup" % dbpath, dbpath)
            return

    sync = wrap(sync, [optional("somethingWithoutSpaces")])

    def lookup(self, irc, msg, args, author):
        """--Future Command-- [<author>]

        Looks up factoids created or edited by <author>,
        <author> defaults to you.
        """
        if not capab(msg.prefix, "editfactoids"):
            irc.error("Sorry, you can't do that")
            return
        channel = self.registryValue('database')
        if not channel:
            irc.reply("Umm, I don't know")
            return
        if not author:
            author = msg.prefix
        def isLastEdit(name, id):
            cur.execute("SELECT MAX(id) FROM log WHERE name=%s", (name,))
            return int(cur.fetchall()[0][0]) == id
        author = author.split('!', 1)[0]
        db = self.get_db(channel)
        cur = db.cursor()
        ret = {}
        log_ret = {}
        cur.execute("SELECT name,value FROM facts WHERE author LIKE '%s%%'" % (author,))
        res = cur.fetchall()
        cur.execute("SELECT id, name, oldvalue FROM log WHERE author LIKE '%s%%'" % (author,))
        log_res = cur.fetchall()
        for r in res:
            val = r[1]
            d = r[1].startswith('<deleted>')
            a = r[1].startswith('<alias>')
            r = r[0]
            if d:
                r += '*'
            if a:
                r += '@' + val[7:].strip()
            try:
                ret[r] += 1
            except:
                ret[r] = 1

        for r in log_res:
            if isLastEdit(r[1], r[0]):
                val = r[2]
                d = r[2].startswith('<deleted>')
                a = r[2].startswith('<alias>')
                r = r[1]
                if d:
                    r += '*'
                if a:
                    r += '@' + val[7:].strip()
                try:
                    log_ret[r] += 1
                except:
                    log_ret[r] = 1

        if not ret:
            rmsg = "Authored: None found"
        else:
            rmsg = 'Authored Found: %s' % ', '.join(sorted(ret.keys(), lambda x, y: cmp(ret[x], ret[y]))[:10])
        if not log_ret:
            log_rmsg = "Edited: None found"
        else:
            log_rmsg = 'Edited Found: %s' % ', '.join(sorted(log_ret.keys(), lambda x, y: cmp(log_ret[x], log_ret[y]))[:10])
        irc.reply(rmsg)
        irc.reply(log_rmsg)
    lookup = wrap(lookup, [optional('otherUser')])

    def ftlogin(self, irc, msg, args):
        """--Future Command-- Takes no arguments

        Login to the Factoid Edit System
        """
        user = None
        if not msg.tagged('identified'):
            irc.error("Not identified")
            return
        try:
            user = ircdb.users.getUser(msg.prefix)
        except:
            irc.error(conf.supybot.replies.incorrectAuthentication())
            return

        if not capab(msg.prefix, "editfactoids"):
            irc.error(conf.supybot.replies.noCapability() % "editfactoids")
            return

        if not user:
            return

        db = self.get_log_db()
        if not db:
            irc.error("Could not open database, contact stdin")
            return
        cur = db.cursor()

        sessid = hashlib.md5('%s%s%d' % (msg.prefix, time.time(), random.randint(1,100000))).hexdigest()
        cur.execute("INSERT INTO sessions (session_id, user, time) VALUES (%s, %s, %d)",
            (sessid, msg.nick, int(time.mktime(time.gmtime())) ))
        db.commit()
        irc.reply("Login at http://jussi01.com/stdin/test/facts.cgi?sessid=%s" % sessid, private=True)

    ftlogin = wrap(ftlogin)

    def ignore(self, irc, msg, args, banmask, expires, channel):
        """<hostmask|nick> [<expires>] [<channel>]

        Ignores commands/requests from <hostmask> or <nick>. If <expires> is
        given the ignore will expire after that ammount of seconds. If
        <channel> is given, the ignore will only apply in that channel.
        """
        if not capab(msg.prefix, "editfactoids"):
            irc.errorNoCapability("editfactoids")
            return
        if channel:
            c = ircdb.channels.getChannel(channel)
            c.addIgnore(banmask, expires)
            ircdb.channels.setChannel(channel, c)
            irc.replySuccess()
        else:
            ircdb.ignores.add(banmask, expires)
            irc.replySuccess()

    ignore = wrap(ignore, ['hostmask', optional("expiry", 0), optional("channel", None)])

    def unignore(self, irc, msg, args, banmask, channel):
        """<hostmask|nick> [<channel>]

        Remove an ignore previously set by @ignore. If <channel> was given
        in the origional @ignore command it must be given here.
        """
        if not capab(msg.prefix, "editfactoids"):
            irc.errorNoCapability("editfactoids")
            return
        if channel:
            c = ircdb.channels.getChannel(channel)
            try:
                c.removeIgnore(banmask)
                ircdb.channels.setChannel(channel, c)
                irc.replySuccess()
            except KeyError:
                irc.error('There are no ignores for that hostmask in %s.' % channel)
        else:
            try:
                ircdb.ignores.remove(banmask)
                irc.replySuccess()
            except KeyError:
                irc.error("%s wasn't in the ignores database." % banmask)

    unignore = wrap(unignore, ['hostmask', optional("channel", None)])

    def ignorelist(self, irc, msg, args, channel):
        """<hostmask|nick> [<channel>]

        Lists all ignores set by @ignore. If <channel> is given this will
        only list ignores set in that channel.
        """
        if not capab(msg.prefix, "editfactoids"):
            irc.errorNoCapability("editfactoids")
            return
        if channel:
            c = ircdb.channels.getChannel(channel)
            if len(c.ignores) == 0:
                irc.reply("I'm not currently ignoring any hostmasks in '%s'" % channel)
            else:
                L = sorted(c.ignores)
                irc.reply(utils.str.commaAndify(map(repr, L)))
        else:
            if ircdb.ignores.hostmasks:
                irc.reply(format('%L', (map(repr,ircdb.ignores.hostmasks))))
            else:
                irc.reply("I'm not currently globally ignoring anyone.")

    ignorelist = wrap(ignorelist, [optional("channel", None)])

Class = Encyclopedia
