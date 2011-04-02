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

import supybot.conf as conf
import supybot.registry as registry

def configure(advanced):
    from supybot.questions import yn, something, output
    from supybot.utils.str import format
    import os
    import sqlite
    import re

    def anything(prompt, default=None):
        """Because supybot is pure fail"""
        from supybot.questions import expect
        return expect(prompt, [], default=default)

    Encyclopedia = conf.registerPlugin('Encyclopedia', True)

    enabled = yn("Enable Encyclopedia for all channels?", default=Encyclopedia.enabled._default)
    if advanced:
        datadir = something("Which directory should the factoids database be in?", default=Encyclopedia.datadir._default)
        database = something("What should be the name of the default database (without the .db extension)?", default=Encyclopedia.database._default)
        prefixchar = something("What prefix character should the bot respond to factoid requests with?", default=Encyclopedia.prefixchar._default)
        ignores = set([])
        output("This plugin can be configured to always ignore certain factoid requests, this is useful when you want another plugin to handle them")
        output("For instance, the PackageInfo plugin responds to !info and !find, so those should be ignored in Encyclopedia to allow this to work")
        ignores_i = anything("Which factoid requets should the bot always ignore?", default=', '.join(Encyclopedia.ignores._default))
        for name in re.split(r',?\s', ignores_i):
            ignores.add(name.lower())

        curStable = something("What is short name of the current stable release?", default=Encyclopedia.curStable._default)
        curStableLong = something("What is long name of the current stable release?", default=Encyclopedia.curStableLong._default)
        curStableNum = something("What is version number of the current stable release?", default=Encyclopedia.curStableNum._default)

        curDevel = something("What is short name of the current development release?", default=Encyclopedia.curDevel._default)
        curDevelLong = something("What is long name of the current development release?", default=Encyclopedia.curDevelLong._default)
        curDevelNum = something("What is version number of the current development release?", default=Encyclopedia.curDevelNum._default)

        curLTS = something("What is short name of the current LTS release?", default=Encyclopedia.curLTS._default)
        curLTSLong = something("What is long name of the current LTS release?", default=Encyclopedia.curLTSLong._default)
        curLTSNum = something("What is version number of the current LTS release?", default=Encyclopedia.curLTSNum._default)
    else:
        datadir = Encyclopedia.datadir._default
        database = Encyclopedia.database._default
        prefixchar = Encyclopedia.prefixchar._default
        ignores = Encyclopedia.ignores._default
        curStable = Encyclopedia.curStable._default
        curStableLong = Encyclopedia.curStableLong._default
        curStableNum = Encyclopedia.curStableNum._default
        curDevel = Encyclopedia.curDevel._default
        curDevelLong = Encyclopedia.curDevelLong._default
        curDevelNum = Encyclopedia.curDevelNum._default
        curLTS = Encyclopedia.curLTS._default
        curLTSLong = Encyclopedia.curLTSLong._default
        curLTSNum = Encyclopedia.curLTSNum._default

    relaychannel = anything("What channel/nick should the bot forward alter messages to?", default=Encyclopedia.relaychannel._default)
    output("What message should the bot reply with when a factoid can not be found?")
    notfoundmsg = something("If you include a '%s' in the message, it will be replaced with the requested factoid", default=Encyclopedia.notfoundmsg._default)
    output("When certain factoids are called an alert can be forwarded to a channel/nick")
    output("Which factoids should the bot forward alert calls for?")
    alert = set([])
    alert_i = anything("Separate types by spaces or commas:", default=', '.join(Encyclopedia.alert._default))
    for name in re.split(r',?\s+', alert_i):
        alert.add(name.lower())
    remotedb = anything("Location of a remote database to sync with (used with @sync)", default=Encyclopedia.remotedb._default)
    privateNotFound = yn("Should the bot reply in private when a factoid is not found, as opposed to in the channel?", default=Encyclopedia.privateNotFound._default)

    Encyclopedia.enabled.setValue(enabled)
    Encyclopedia.datadir.setValue(datadir)
    Encyclopedia.database.setValue(database)
    Encyclopedia.prefixchar.setValue(prefixchar)
    Encyclopedia.ignores.setValue(ignores)
    Encyclopedia.curStable.setValue(curStable)
    Encyclopedia.curStableLong.setValue(curStableLong)
    Encyclopedia.curStableNum.setValue(curStableNum)
    Encyclopedia.curDevel.setValue(curDevel)
    Encyclopedia.curDevelLong.setValue(curDevelLong)
    Encyclopedia.curDevelNum.setValue(curDevelNum)
    Encyclopedia.curLTS.setValue(curLTS)
    Encyclopedia.curLTSLong.setValue(curLTSLong)
    Encyclopedia.curLTSNum.setValue(curLTSNum)
    Encyclopedia.relaychannel.setValue(relaychannel)
    Encyclopedia.notfoundmsg.setValue(notfoundmsg)
    Encyclopedia.alert.setValue(alert)
    Encyclopedia.privateNotFound.setValue(privateNotFound)

    # Create the initial database
    db_dir = Encyclopedia.datadir()
    db_file = Encyclopedia.database()

    if not db_dir:
        db_dir = conf.supybot.directories.data()
        output("supybot.plugins.Encyclopedia.datadir will be set to %r" % db_dir)
        Encyclopedia.datadir.setValue(db_dir)

    if not db_file:
        db_file = 'ubuntu'
        output("supybot.plugins.Encyclopedia.database will be set to %r" % db_file)
        Encyclopedia.database.setValue(db_dir)

    if os.path.exists(os.path.join(db_dir, db_file + '.db')):
        return

    con = sqlite.connect(os.path.join(db_dir, db_file + '.db'))
    cur = con.cursor()

    try:
        cur.execute("""CREATE TABLE facts (
    id INTEGER PRIMARY KEY,
    author VARCHAR(100) NOT NULL,
    name VARCHAR(20) NOT NULL,
    added DATETIME,
    value VARCHAR(200) NOT NULL,
    popularity INTEGER NOT NULL DEFAULT 0
)""")
#"""
        cur.execute("""CREATE TABLE log (
    id INTEGER PRIMARY KEY,
    author VARCHAR(100) NOT NULL,
    name VARCHAR(20) NOT NULL,
    added DATETIME,
    oldvalue VARCHAR(200) NOT NULL
)""")

    except:
        con.rollback()
        raise
    else:
        con.commit()
    finally:
        cur.close()
        con.close()

Encyclopedia = conf.registerPlugin('Encyclopedia')

conf.registerChannelValue(Encyclopedia, 'enabled',
    registry.Boolean(True, "Enable Encyclopedia"))

conf.registerChannelValue(Encyclopedia, 'database',
    registry.String('ubuntu', 'Name of database to use'))

conf.registerChannelValue(Encyclopedia, 'relaychannel',
    registry.String('#ubuntu-ops', 'Relay channel for unauthorized edits'))

conf.registerGlobalValue(Encyclopedia, 'editchannel',
        registry.SpaceSeparatedListOfStrings(['#ubuntu-ops'], 
            'Channels where unauthorised edits are allowed.'))

conf.registerGlobalValue(Encyclopedia, 'notfoundmsg',
    registry.String('Factoid %s not found', 'Reply when factoid isn\'t found'))

conf.registerChannelValue(Encyclopedia,'prefixchar',
    registry.String('!','Prefix character for factoid display/editing'))

conf.registerGlobalValue(Encyclopedia, 'datadir',
    conf.Directory(conf.supybot.directories.data(), 'Path to dir containing factoid databases', private=True))

conf.registerChannelValue(Encyclopedia, 'alert',
    registry.SpaceSeparatedListOfStrings(['ops', 'op', 'kops', 'calltheops'], 'factoid name(s) used for alerts', private=True))

conf.registerChannelValue(Encyclopedia, 'remotedb',
    registry.String('http://ubottu.com/ubuntu.db', 'Remote location of the master database', private=True))

conf.registerChannelValue(Encyclopedia, 'ignores',
    registry.SpaceSeparatedListOfStrings(['find', 'info'], 'factoid name(s) to ignore', private=True))

conf.registerChannelValue(Encyclopedia, 'privateNotFound',
    registry.Boolean(False, "If set to True, send notfoundmsg in private rather than in the channel"))

conf.registerChannelValue(Encyclopedia, 'forcedFactoid',
    registry.Boolean(False, "If True, factoids in kick's reason will be sent to the user in private"))


conf.registerGlobalValue(Encyclopedia, 'curStable',
    registry.String('Lucid', "Current stable release"))
conf.registerGlobalValue(Encyclopedia, 'curStableLong',
    registry.String('Lucid Lynx', "Current stable release"))
conf.registerGlobalValue(Encyclopedia, 'curStableNum',
    registry.String('10.04', "Current stable release"))

conf.registerGlobalValue(Encyclopedia, 'curDevel',
    registry.String('Maverick', "Current development release"))
conf.registerGlobalValue(Encyclopedia, 'curDevelLong',
    registry.String('Maverick Meerkat', "Current development release"))
conf.registerGlobalValue(Encyclopedia, 'curDevelNum',
    registry.String('10.10', "Current development release"))

conf.registerGlobalValue(Encyclopedia, 'curLTS',
    registry.String('Lucid', "Current LTS release"))
conf.registerGlobalValue(Encyclopedia, 'curLTSLong',
    registry.String('Lucid Lynx', "Current LTS release"))
conf.registerGlobalValue(Encyclopedia, 'curLTSNum',
    registry.String('10.04', "Current LTS release"))
