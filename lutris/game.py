#!/usr/bin/python
# -*- coding:Utf-8 -*-
#
#  Copyright (C) 2010 Mathieu Comandon <strider@strycore.com>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License version 3 as
#  published by the Free Software Foundation.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import subprocess
import gobject
import logging
import os
import os.path
import time
import gtk

from lutris.gui.common import QuestionDialog, ErrorDialog
from lutris.config import LutrisConfig
from lutris.thread import LutrisThread
from lutris.desktop_control import LutrisDesktopControl, change_resolution
from lutris.constants import *

def show_error_message(message, info=None):
    if "RUNNER_NOT_INSTALLED" == message['error']:
        q = QuestionDialog({
                    'title': 'Error the runner is not installed',
                    'question': '%s is not installed, \
                            do you want to install it now ?' % message['runner']
                })
        if gtk.RESPONSE_YES == q.result:
            # FIXME : This is not right at all!
            # Call the runner's install method
            subprocess.Popen(['software-center', message['runner']])
    elif "NO_BIOS" == message['error']:
        ErrorDialog("A bios file is required to run this game")
    elif "FILE_NOT_FOUND" == message['error']:
        ErrorDialog("The file %s doesn't exists" % message['file'])

def get_list():
    """Get the list of all installed games"""

    game_list = []
    for file in os.listdir(GAME_CONFIG_PATH):
        if file.endswith(CONFIG_EXTENSION):
            game_name = file[:len(file) - len(CONFIG_EXTENSION)]
            Game = LutrisGame(game_name)
            if not Game.load_success:
                message = "Error while loading configuration for %s" % game_name

                #error_dialog = gtk.MessageDialog(parent=None, flags=0,
                #                                 type=gtk.MESSAGE_ERROR,
                #                                 buttons=gtk.BUTTONS_OK,
                #                                 message_format=message)
                #error_dialog.run()
                #error_dialog.destroy()
                print message
            game_list.append({"name": Game.real_name,
                              "runner": Game.runner_name,
                              "id":game_name})
    return game_list

class LutrisGame():
    """"This class takes cares about loading the configuration for a game
    and running it."""
    def __init__(self, name):
        self.name = name
        self.pid = 0
        self.runner = None
        self.subprocess = None
        self.game_thread = None
        self.lutris_desktop_control = LutrisDesktopControl()
        self.load_success = self.load_config()

    def load_config(self):
        #Load the game's configuration
        self.game_config = LutrisConfig(game=self.name)

        if "realname" in self.game_config.config:
            self.real_name = self.game_config["realname"]
        else:
            self.real_name = self.name

        try:
            self.runner_name = self.game_config["runner"]
        except KeyError:
            print "Error in %s config file : No runner" % self.name
            return False

        try:
            runner_module = __import__("lutris.runners.%s" %
                    self.runner_name, globals(), locals(),
                    [self.runner_name], -1 )
            runner_cls = getattr(runner_module, self.runner_name)
            self.machine = runner_cls(self.game_config)
        except AttributeError, msg:
            logging.error("Invalid configuration file (Attribute Error) : %s" % self.name)
            logging.error(msg)
            return False
        except KeyError, msg:
            logging.error("Invalid configuration file (Key Error) : %s" % self.name)
            logging.error(msg)
            return False
        return True

    def play(self):
        if not self.machine.is_installed():
        	print "the required runner is not installed"
        	return False
        config = self.game_config.config
        logging.debug("get ready for %s " % config['realname'])
        self.hide_panels = False
        oss_wrapper = None
        gameplay_info = self.machine.play()

        if type(gameplay_info) == dict:
            if 'error' in gameplay_info:
                show_error_message(gameplay_info)

                return False
            game_run_args = gameplay_info["command"]
        else:
            game_run_args = gameplay_info
            logging.debug("Old method used for returning gameplay infos")

        if "system" in config and config["system"] is not None:
            #Hide Gnome panels
            if "hide_panels" in config["system"]:
                if config["system"]["hide_panels"]:
                    self.lutris_desktop_control.hide_panels()
                    self.hide_panels = True

            #Change resolution before starting game
            if "resolution" in config["system"]:
                success = change_resolution(config["system"]["resolution"])
                if success:
                    logging.debug("Resolution changed to %s"
                                  % config["system"]["resolution"])
                else:
                    logging.debug("Failed to set resolution %s"
                                  % config["system"]["resolution"])

            #Setting OSS Wrapper
            if "oss_wrapper" in config["system"]:
                oss_wrapper = config["system"]["oss_wrapper"]

            #Reset Pulse Audio
            if "reset_pulse" in config["system"] and config["system"]["reset_pulse"]:
                subprocess.Popen("pulseaudio --kill && sleep 1 && pulseaudio --start",
                                 shell=True)
                logging.debug("PulseAudio restarted")

            # Set compiz fullscreen windows
            # TODO : Check that compiz is running
            if "compiz_nodecoration" in config['system']:
                self.lutris_desktop_control.set_compiz_nodecoration(title=config['system']['compiz_nodecoration'])
            if "compiz_fullscreen" in config['system']:
                self.lutris_desktop_control.set_compiz_fullscreen(title=config['system']['compiz_fullscreen'])


            if "killswitch" in config['system']:
                killswitch = config['system']['killswitch']
            else:
                killswitch = None

            # Switch to other WM
            # TODO

        if hasattr(self.machine, 'game_path'):
            path = self.machine.game_path
        else:
        	path = None

        #print game_run_args
        command = " " . join(game_run_args)
        # Set OSS Wrapper
        if oss_wrapper and oss_wrapper != 'none':
            command = oss_wrapper + " " + command
        if game_run_args:
            self.timer_id = gobject.timeout_add(5000, self.poke_process)
            logging.debug(" > Running : " + command)
            self.game_thread = LutrisThread(command, path, killswitch)
            self.game_thread.start()
            if 'joy2key' in gameplay_info:
                self.run_joy2key(gameplay_info['joy2key'])

    def run_joy2key(self, config):
        win = "grep %s" % config['window']
        if 'notwindow' in config:
            win = win + ' | grep -v %s' % config['notwindow']
        wid = "xwininfo -root -tree | %s | awk '{print $1}'" % win
        buttons = config['buttons']
        axis = "Left Right Up Down"
        command = "sleep 5 && joy2key $(%s) -X -rcfile ~/.joy2keyrc -buttons %s -axis %s" % (
                wid, buttons, axis
            )
        self.joy2key_thread = LutrisThread(command, "/tmp")
        self.joy2key_thread.start()

    def write_conf(self, settings):
        self.lutris_config.write_game_config(self.name, settings)

    def poke_process(self):
        if self.game_thread.pid:
            os.system("gnome-screensaver-command --poke")
        else:
            self.quit_game()
            return False
        return True

    def quit_game(self):
        logging.debug("game has quit at %s" % time.strftime("%a, %d %b %Y %H:%M:%S", time.localtime()))
        if self.game_thread is not None and self.game_thread.pid:
            if self.game_thread.cedega:
                for pid in self.game_thread.pid:
                    os.popen("kill -9 %s" % pid)
            else:
                self.game_thread.game_process.terminate()
        if 'reset_desktop' in self.game_config.config['system']:
            if self.game_config.config['system']['reset_desktop']:
                self.lutris_desktop_control.reset_desktop()

        #os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))
