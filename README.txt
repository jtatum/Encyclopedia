Copyright (c) 2011, James Tatum
Copyright (c) 2006-2007, Dennis Kaarsemaker

This program is free software; you can redistribute it and/or modify
it under the terms of version 2 of the GNU General Public License as
published by the Free Software Foundation.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

This is a fork of the Ubuntu bots Encyclopedia plugin. Visit their awesome
project at https://launchpad.net/ubuntu-bots and http://ubottu.com/

Changes from Ubuntu Encyclopedia:

* Anyone can edit
  Authentication for updating factoids is disabled.

This plugin used to have package lookup, this was mooved to the PackageInfo
plugin.

Pick a name for your database. A lowercase-only name without spaces is probably
best, this example wil use myfactoids as name. Then create a directory to store
your databases in (somewere in $botdir/data would be best). In the new directory
create an sqlite database with the following command:

sqlite myfactoids.db

CREATE TABLE facts (
        id INTEGER PRIMARY KEY,
        author VARCHAR(100) NOT NULL,
        name VARCHAR(20) NOT NULL,
        added DATETIME,
        value VARCHAR(200) NOT NULL,    
        popularity INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE log (
        id INTEGER PRIMARY KEY,
        author VARCHAR(100) NOT NULL,
        name VARCHAR(20) NOT NULL,
        added DATETIME,
        oldvalue VARCHAR(200) NOT NULL
);

If you want to create more databases, repeat these last two steps.

When the databases exist, you need to configure the bots to actually use them.
To do that, set the global value supybot.plugins.encyclopedia.datadir to the new
dirand the channel value supybot.plugins.encyclopedia.database to the name of
the database (without the .db suffix).

Documentation on adding/editing factoids can be found on
https://wiki.ubuntu.com/UbuntuBots To give people edit access, let them register
with your bot and use: %addeditor nickname_here (replace % with your prefix
char). Similarly you can use removeeditor :).

The web interface is a simple cgi script with some templates, css and the
commoncgi.py file from the bzr tree. Make sure you set the variables datadir and
database in factoids.cgi to the correct values. Also set default_db to the one
you want to show by default.
