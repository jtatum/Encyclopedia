# -*- Encoding: utf-8 -*-
###
# Copyright (c) 2006 Dennis Kaarsemaker
# Copyright (c) 2010 Elián Hanisch
#
# This program is free software: you can redistribute it and/or modify 
# it under the terms of the GNU General Public License as published by 
# the Free Software Foundation, either version 3 of the License, or    
# (at your option) any later version.                                  
#                                                                      
# This program is distributed in the hope that it will be useful,      
# but WITHOUT ANY WARRANTY; without even the implied warranty of       
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the        
# GNU General Public License for more details.                         
#                                                                      
# You should have received a copy of the GNU General Public License    
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
###

from supybot.test import *
import supybot.conf as conf

Econf = conf.supybot.plugins.Encyclopedia
Econf.prefixchar.set('@')

# we use PluginTestCase instead of ChannelPluginTestCase, Encyclopedia does some weird parsing stuff
# that upset testcases.
class EncyclopediaTestCase(PluginTestCase):
    plugins = ('Encyclopedia',)

    def setUp(self):
        super(EncyclopediaTestCase, self).setUp()
        conf.supybot.reply.whenNotCommand.setValue(False)

    def createDB(self):
        import sqlite, os
        dbfile = os.path.join(Econf.datadir(), '%s.db' %Econf.database())
        try:
            os.remove(dbfile)
        except:
            pass
        db = sqlite.connect(dbfile)
        cursor = db.cursor()
        cursor.execute('CREATE TABLE facts ('\
                        'id INTEGER PRIMARY KEY,'\
                        'author VARCHAR(100) NOT NULL,'\
                        'name VARCHAR(20) NOT NULL,'\
                        'added DATETIME,'\
                        'value VARCHAR(200) NOT NULL,'\
                        'popularity INTEGER NOT NULL DEFAULT 0);')
        cursor.execute('CREATE TABLE log ('\
                        'id INTEGER PRIMARY KEY,'\
                        'author VARCHAR(100) NOT NULL,'\
                        'name VARCHAR(20) NOT NULL,'\
                        'added DATETIME,'\
                        'oldvalue VARCHAR(200) NOT NULL);')
        db.commit()
        cursor.close()
        db.close()
        self.getCallback().databases = {}

    def getCallback(self):
        for cb in self.irc.callbacks:
            if cb.name() == 'Encyclopedia':
                break
        return cb

    def testSimpleTest(self):
        self.createDB()
        self.assertNotError('test is test')
        self.assertResponse('test', 'test is test')
        self.assertNotError('no, test is test1')
        self.assertResponse('test', 'test is test1')
        self.assertNoResponse('hello is <reply> Hi, welcome to $chan!') # no reply? why?
        self.assertResponse('hello', 'Hi, welcome to test!')


# vim:set shiftwidth=4 softtabstop=4 tabstop=4 expandtab textwidth=100:
